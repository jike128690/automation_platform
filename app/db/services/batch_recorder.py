# -*- coding: utf-8 -*-
"""执行批次落库器（T11.2 批次 / T11.3 用例结果 / T11.4 流水日志批量写入）。

线程模型（数据库开发计划 4.4 / 第 8 节）：
- BatchRecorder 为普通对象（非 QObject），MainWindow 将 WorkerThread 的
  信号直连到本类方法 —— 直连回调在**发射线程（WorkerThread）**内执行，
  即"WorkerThread 写库"；主线程仅在建批时做一次快速写入；
- 每次写库使用独立短事务 Session（WAL + busy_timeout 由 engine 层保证），
  与主线程读库互不阻塞。

设计要点（对照计划 4.4）：
- 批次号 #YYYYMMDD-NN 自然日自增（原生 SQL 取当日最大序号）；
- 用例结果在**建批时一次性创建**（WAITING + queue_order，与状态面板队列
  一致）：计划原文为"用例开始时建"，此处改为建批时全量创建 —— 语义更优
  （手动停止后未执行用例也有 WAITING 历史记录，uq_batch_case 天然满足），
  验收口径不变；
- 状态映射：executor running/passed/failed → RUNNING/PASSED/FAILED；
- error_message 从失败日志行提取（5.1.6 日志契约：`[{case_code}] ... 失败: {原因}`），
  不修改引擎信号契约；手动停止无失败日志时回填固定文案；
- 耗时由本类测量（RUNNING→终态单调时钟差），秒级取整；
- 日志批量写：缓冲 ≥50 条或距上次落库 ≥1s 时触发（追加时惰性检查），
  批次结束强制冲刷 —— 1000 条高频日志仅 ~20 次事务，低配机不卡；
- 日志归属解析：`[{case_code}] ` 前缀命中已建结果则关联 result_id
  （供报告页按用例过滤），套件级日志 result_id 为 NULL；
- screenshot_path / video_path 由 T12.3 失败自动截图路径写入（本期预留 API）。
"""
from __future__ import annotations

import time
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import now_iso
from app.db.models import (
    BatchCaseResult, BatchStatus, ExecStatus, ExecutionBatch, ExecutionLog,
    LogLevel, TestCase,
)

# executor 状态机（小写）→ LDM exec_status
_STATUS_MAP = {
    "waiting": ExecStatus.WAITING,
    "running": ExecStatus.RUNNING,
    "passed": ExecStatus.PASSED,
    "failed": ExecStatus.FAILED,
}

_STOP_ERROR_MESSAGE = "批次被手动停止，用例未执行完即中断"

# 日志级别阈值（图4 日志级别配置）：低于阈值不入库（T12.3）
_LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}


def next_batch_no(engine) -> str:
    """生成下一个批次号 #YYYYMMDD-NN（自然日自增，LDM 2.7）。"""
    prefix = f"#{date.today():%Y%m%d}-"
    with Session(engine) as s:
        max_no = s.execute(
            text("SELECT MAX(batch_no) FROM tb_execution_batch WHERE batch_no LIKE :p"),
            {"p": prefix + "%"},
        ).scalar()
    seq = int(max_no[len(prefix):]) + 1 if max_no else 1
    return f"{prefix}{seq:02d}"


class BatchRecorder:
    """单次【运行测试】的落库生命周期：建批 → 结果/日志写入 → 统计回填。"""

    def __init__(self, engine, module_names: str, queue: list[tuple],
                 log_flush_size: int = 50, log_flush_interval: float = 1.0,
                 min_log_level: str = "INFO"):
        """
        Args:
            engine: SQLAlchemy 引擎（测试注入 tmp 库，生产为全局引擎）。
            module_names: 逗号分隔的模块名称串（确认项 3）。
            queue: [(TestModule, TestCase)] 队列（DTO），按执行顺序；
                   DTO case_id 即 case_code（case_repo.load_tree 映射约定）。
            log_flush_size: 日志缓冲条数阈值。
            log_flush_interval: 日志冲刷时间阈值（秒）。
            min_log_level: 最低入库日志级别（图4 配置；低于阈值丢弃）。
        """
        self.engine = engine
        self._t0 = time.monotonic()
        self._log_flush_size = log_flush_size
        self._log_flush_interval = log_flush_interval
        self._min_level_rank = _LEVEL_RANK.get(min_log_level, 1)

        self._queue_codes = [case.case_id for _, case in queue]
        self._result_ids: dict[str, str] = {}    # case_code → result UUID
        self._status: dict[str, str] = {}        # case_code → exec_status 值
        self._started_at: dict[str, float] = {}  # case_code → 单调时钟起点
        self._retry_counts: dict[str, int] = {}  # case_code → 实际重试次数（LDM 2.8）
        self._log_buffer: list[tuple[int, str, str, str]] = []  # (seq, level, time, content)
        self._seq_no = 0
        self._last_flush = time.monotonic()
        self.batch_id = self._create_batch(module_names)

    # ---------------------------------------------------------- T11.2 批次

    def _create_batch(self, module_names: str) -> str:
        """建批 + 一次性创建全部用例结果（WAITING，含 queue_order）。返回批次 UUID。"""
        codes = self._queue_codes
        with Session(self.engine) as s:
            pk_map = dict(s.execute(
                select(TestCase.case_code, TestCase.case_id)
                .where(TestCase.case_code.in_(codes))
            ).all())

            batch = ExecutionBatch(
                batch_no=next_batch_no(self.engine),
                module_names=module_names,
                total_cases=len(codes),
            )
            s.add(batch)
            s.flush()  # 取 batch_id
            batch_id = batch.batch_id

            results = [
                BatchCaseResult(
                    batch_id=batch_id, case_id=pk_map[code], queue_order=order,
                )
                for order, code in enumerate(codes, 1)
            ]
            s.add_all(results)
            s.flush()  # result_id 已由默认工厂生成
            self._result_ids = {
                code: result.result_id for code, result in zip(codes, results)
            }
            s.commit()
        return batch_id

    # ---------------------------------------------------------- T11.3 用例结果

    def on_case_status(self, case_id: str, status: str):
        """信号槽：用例状态变更（WorkerThread 直连，发射线程内执行）。"""
        exec_status = _STATUS_MAP.get(status)
        result_id = self._result_ids.get(case_id)
        if exec_status is None or result_id is None:
            return

        if exec_status == ExecStatus.RUNNING:
            self._started_at[case_id] = time.monotonic()
            # 终态后再次进入 RUNNING = 引擎失败重试（T12.3 retry_count 落库）
            if self._status.get(case_id) in (
                ExecStatus.PASSED.value, ExecStatus.FAILED.value,
            ):
                self._retry_counts[case_id] = self._retry_counts.get(case_id, 0) + 1

        duration: int | None = None
        if exec_status in (ExecStatus.PASSED, ExecStatus.FAILED):
            if case_id in self._started_at:
                duration = int(time.monotonic() - self._started_at[case_id])
        self._status[case_id] = exec_status.value

        with Session(self.engine) as s:
            result = s.get(BatchCaseResult, result_id)
            if result is None:
                return
            result.exec_status = exec_status.value
            if exec_status == ExecStatus.RUNNING:
                result.start_time = now_iso()  # 用例开始执行时间（LDM 2.8）
            if duration is not None:
                result.duration_sec = duration
            result.retry_count = self._retry_counts.get(case_id, 0)
            if exec_status == ExecStatus.FAILED:
                result.error_message = self._extract_error(case_id)
            if exec_status in (ExecStatus.PASSED, ExecStatus.FAILED):
                result.end_time = now_iso()
            self._sync_batch_counters(s)
            s.commit()

    def _extract_error(self, case_id: str) -> str:
        """从缓冲日志提取失败原因（5.1.6 契约：`[{case_id}] ... 失败: {原因}`）。"""
        prefix = f"[{case_id}] "
        for _seq, _level, _ts, content in reversed(self._log_buffer):
            if content.startswith(prefix) and "失败: " in content:
                return content.split("失败: ", 1)[1][:1000]
        return _STOP_ERROR_MESSAGE

    def update_case_media(self, case_id: str,
                          screenshot_path: str | None = None,
                          video_path: str | None = None):
        """写入报错截图/录像本地路径（T12.3 失败自动截图接入点，本期预留）。"""
        result_id = self._result_ids.get(case_id)
        if result_id is None:
            return
        with Session(self.engine) as s:
            result = s.get(BatchCaseResult, result_id)
            if result is None:
                return
            if screenshot_path:
                result.screenshot_path = screenshot_path
            if video_path:
                result.video_path = video_path
            s.commit()

    def _sync_batch_counters(self, s: Session):
        """按当前状态回填批次统计（executed/passed/failed/pass_rate）。"""
        batch = s.get(ExecutionBatch, self.batch_id)
        if batch is None:
            return
        passed = sum(1 for v in self._status.values() if v == ExecStatus.PASSED.value)
        failed = sum(1 for v in self._status.values() if v == ExecStatus.FAILED.value)
        batch.passed_cases = passed
        batch.failed_cases = failed
        batch.executed_cases = passed + failed
        total = batch.total_cases
        batch.pass_rate = round(passed / total * 100, 1) if total else 0.0

    # ---------------------------------------------------------- T11.4 日志批量落库

    def on_log(self, timestamp: str, message: str):
        """信号槽：流水日志先入缓冲（低于配置级别丢弃），按 50 条 / 1s 阈值批量落库。"""
        level = LogLevel.ERROR.value if "失败" in message else LogLevel.INFO.value
        if _LEVEL_RANK.get(level, 1) < self._min_level_rank:
            return  # 低于日志级别配置（图4）：不入库
        self._seq_no += 1
        self._log_buffer.append((self._seq_no, level, timestamp, message))
        now = time.monotonic()
        if (len(self._log_buffer) >= self._log_flush_size
                or now - self._last_flush >= self._log_flush_interval):
            self.flush_logs()

    def flush_logs(self):
        """冲刷缓冲（不足阈值也强制写入；批次结束时调用保证零丢失）。"""
        if not self._log_buffer:
            self._last_flush = time.monotonic()
            return
        pending, self._log_buffer = self._log_buffer, []
        self._last_flush = time.monotonic()
        logs = [
            ExecutionLog(
                batch_id=self.batch_id,
                result_id=self._resolve_result_id(content),
                seq_no=seq,
                log_level=level,
                log_time=timestamp,
                log_content=content[:2000],
            )
            for seq, level, timestamp, content in pending
        ]
        with Session(self.engine) as s:
            s.add_all(logs)
            s.commit()

    def _resolve_result_id(self, content: str) -> str | None:
        """按 `[{case_code}] ` 前缀解析日志归属用例；套件级日志返回 None。"""
        if content.startswith("[") and "]" in content:
            code = content[1:content.index("]")]
            return self._result_ids.get(code)
        return None

    # ---------------------------------------------------------- 批次收尾

    def on_batch_finished(self, manual_stopped: bool):
        """信号槽：回填 end_time / duration_sec / batch_status，并强制冲刷日志。"""
        self.flush_logs()
        with Session(self.engine) as s:
            batch = s.get(ExecutionBatch, self.batch_id)
            if batch is None:
                return
            self._sync_batch_counters(s)
            batch.end_time = now_iso()
            batch.duration_sec = int(time.monotonic() - self._t0)
            batch.batch_status = (
                BatchStatus.STOPPED.value if manual_stopped
                else BatchStatus.COMPLETED.value
            )
            s.commit()
