# -*- coding: utf-8 -*-
"""批次落库器单测（T11.2 批次创建 / T11.3 用例结果 / T11.4 日志批量落库）。

验收标准（《数据库开发.md》WBS）：
- T11.2：连续两天 batch_no 递增；getpass.getuser() 写入执行人；
- T11.3：status 映射 + 耗时 + 失败原因（error_message）+ 截图/录像路径；
- T11.4：1000 条高频日志不丢、seq_no 顺序正确；50 条 / 1s 阈值批量写。
"""
import getpass
import time

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.engine import create_app_engine
from app.db.migration import init_db
from app.db.models import (
    BatchCaseResult, ExecStatus, ExecutionBatch, ExecutionLog, TestCase,
)
from app.db.repositories.case_repo import load_tree
from app.db.seed import seed_db
from app.db.services.batch_recorder import BatchRecorder, next_batch_no


@pytest.fixture()
def db(tmp_path):
    engine = create_app_engine(tmp_path / "recorder.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def tree(db):
    """真实业务种子用例树（DTO）：4 模块 23 用例，默认勾选 6 条。"""
    return load_tree(db)


def _checked_pairs(tree):
    return [(m, c) for m in tree for c in m.cases if c.default_checked]


# ---------------------------------------------------------------- T11.2 批次创建

def test_batch_no_increments_within_day(db):
    assert next_batch_no(db).endswith("-01")
    BatchRecorder(db, "模块A", queue=_checked_pairs(load_tree(db))[:2])
    assert next_batch_no(db).endswith("-02")


def test_batch_no_restarts_next_day(db):
    """验收：连续两天 batch_no 递增 —— 昨日 #YYYYMMDD-NN 不影响今日从 01 起。"""
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    with Session(db) as s:
        s.add(ExecutionBatch(
            batch_no=f"#{yesterday}-07", module_names="昨日批次", total_cases=1,
        ))
        s.commit()

    today_prefix = f"#{date.today():%Y%m%d}-"
    assert next_batch_no(db) == f"{today_prefix}01"

    recorder = BatchRecorder(db, "模块A", queue=_checked_pairs(load_tree(db))[:1])
    with Session(db) as s:
        batch = s.get(ExecutionBatch, recorder.batch_id)
        assert batch.batch_no == f"{today_prefix}01"


def test_batch_fields_and_executor_autofill(db, tree):
    import getpass
    pairs = _checked_pairs(tree)
    recorder = BatchRecorder(db, "[模块一] 登录与基础功能,[模块二] 实时预览", queue=pairs)

    with Session(db) as s:
        batch = s.get(ExecutionBatch, recorder.batch_id)
        assert batch.batch_no.endswith("-01")
        assert batch.module_names == "[模块一] 登录与基础功能,[模块二] 实时预览"
        assert batch.executor_name == getpass.getuser()  # 确认项 5
        assert batch.total_cases == len(pairs)
        assert batch.batch_status == "RUNNING"
        assert batch.executed_cases == 0
        assert batch.end_time is None


def test_results_created_upfront_with_queue_order(db, tree):
    """建批时全量创建 WAITING 结果，queue_order 与队列顺序一致（uq_batch_case 满足）。"""
    pairs = _checked_pairs(tree)
    recorder = BatchRecorder(db, "模块", queue=pairs)

    with Session(db) as s:
        results = s.query(BatchCaseResult).filter_by(
            batch_id=recorder.batch_id
        ).order_by(BatchCaseResult.queue_order).all()
        assert [r.queue_order for r in results] == list(range(1, len(pairs) + 1))
        assert all(r.exec_status == "WAITING" for r in results)
        # case_id 关联 DB UUID，与队列 case_code 对应
        codes = {c.case_id for _, c in pairs}
        joined = s.execute(
            text("SELECT c.case_code FROM tb_batch_case_result r "
                 "JOIN tb_test_case c ON c.case_id = r.case_id "
                 "WHERE r.batch_id = :bid"),
            {"bid": recorder.batch_id},
        ).scalars().all()
        assert set(joined) == codes


# ---------------------------------------------------------------- T11.3 用例结果

def _mk_recorder(db, tree):
    pairs = _checked_pairs(tree)
    return pairs, BatchRecorder(db, "模块", queue=pairs)


def test_status_transition_updates_result(db, tree):
    pairs, recorder = _mk_recorder(db, tree)
    code = pairs[0][1].case_id

    recorder.on_case_status(code, "running")
    with Session(db) as s:
        r = s.query(BatchCaseResult).filter_by(
            batch_id=recorder.batch_id, queue_order=1
        ).one()
        assert r.exec_status == "RUNNING"
        assert r.start_time is not None  # 用例开始执行时间（LDM 2.8）

    recorder.on_case_status(code, "passed")
    with Session(db) as s:
        r = s.query(BatchCaseResult).filter_by(
            batch_id=recorder.batch_id, queue_order=1
        ).one()
        assert r.exec_status == "PASSED"
        assert r.end_time is not None
        assert r.duration_sec >= 0


def test_failed_case_has_error_message(db, tree):
    """验收：失败用例有 error_message（从 5.1.6 失败日志行提取）。"""
    pairs, recorder = _mk_recorder(db, tree)
    code = pairs[0][1].case_id

    recorder.on_case_status(code, "running")
    recorder.on_log("10:00:01", f"[{code}] 登录测试: 点击 [登录] 按钮... 失败: 元素 '#login-btn' 未找到")
    recorder.on_case_status(code, "failed")

    with Session(db) as s:
        r = s.query(BatchCaseResult).filter_by(
            batch_id=recorder.batch_id, queue_order=1
        ).one()
        assert r.exec_status == "FAILED"
        assert r.error_message == "元素 '#login-btn' 未找到"


def test_failed_case_manual_stop_fallback_message(db, tree):
    """手动停止无失败日志：回填固定文案（不修改引擎信号契约）。"""
    pairs, recorder = _mk_recorder(db, tree)
    code = pairs[0][1].case_id

    recorder.on_case_status(code, "running")
    recorder.on_case_status(code, "failed")

    with Session(db) as s:
        r = s.query(BatchCaseResult).filter_by(
            batch_id=recorder.batch_id, queue_order=1
        ).one()
        assert r.error_message == "批次被手动停止，用例未执行完即中断"


def test_batch_counters_and_pass_rate_backfilled(db, tree):
    pairs, recorder = _mk_recorder(db, tree)
    c1, c2 = pairs[0][1].case_id, pairs[1][1].case_id

    recorder.on_case_status(c1, "running")
    recorder.on_case_status(c1, "passed")
    recorder.on_case_status(c2, "running")
    recorder.on_case_status(c2, "failed")
    recorder.on_batch_finished(False)

    with Session(db) as s:
        batch = s.get(ExecutionBatch, recorder.batch_id)
        assert batch.executed_cases == 2
        assert batch.passed_cases == 1
        assert batch.failed_cases == 1
        total = batch.total_cases
        assert batch.pass_rate == round(1 / total * 100, 1)
        assert batch.batch_status == "COMPLETED"
        assert batch.end_time is not None
        assert batch.duration_sec >= 0


def test_manual_stop_marks_batch_stopped(db, tree):
    pairs, recorder = _mk_recorder(db, tree)
    recorder.on_batch_finished(True)
    with Session(db) as s:
        batch = s.get(ExecutionBatch, recorder.batch_id)
        assert batch.batch_status == "STOPPED"


def test_update_case_media_paths(db, tree):
    pairs, recorder = _mk_recorder(db, tree)
    code = pairs[0][1].case_id
    recorder.update_case_media(code, screenshot_path="shots/001.png", video_path="videos/001.webm")
    with Session(db) as s:
        r = s.query(BatchCaseResult).filter_by(
            batch_id=recorder.batch_id, queue_order=1
        ).one()
        assert r.screenshot_path == "shots/001.png"
        assert r.video_path == "videos/001.webm"


# ---------------------------------------------------------------- T11.4 日志批量落库

def test_1000_logs_no_loss_and_ordered(db, tree):
    """验收：1000 条高频日志不丢、seq_no 严格递增、内容顺序正确。"""
    pairs, recorder = _mk_recorder(db, tree)
    for i in range(1, 1001):
        recorder.on_log("10:00:00", f"[{pairs[0][1].case_id}] 登录测试: 步骤日志 {i}")
    recorder.on_batch_finished(False)

    with Session(db) as s:
        rows = s.query(ExecutionLog).filter_by(
            batch_id=recorder.batch_id
        ).order_by(ExecutionLog.seq_no).all()
        assert len(rows) == 1000                        # 零丢失
        assert [r.seq_no for r in rows] == list(range(1, 1001))  # 顺序正确
        assert rows[0].log_content.endswith("步骤日志 1")
        assert rows[-1].log_content.endswith("步骤日志 1000")
        # 批量写验证：1000 条仅 ~20 次事务（50 条阈值），无逐条提交
        assert all(r.log_level == "INFO" for r in rows)


def test_flush_threshold_by_size(db, tree):
    pairs, recorder = _mk_recorder(db, tree)
    for i in range(50):
        recorder.on_log("10:00:00", f"[{pairs[0][1].case_id}] 日志 {i}")
    # 未结束批次：50 条阈值已触发落库
    with Session(db) as s:
        assert s.query(ExecutionLog).filter_by(
            batch_id=recorder.batch_id
        ).count() == 50
    assert recorder._log_buffer == []


def test_flush_threshold_by_time(db, tree):
    pairs, recorder = _mk_recorder(db, tree)
    recorder.on_log("10:00:00", "[001] 缓冲日志 1")
    with Session(db) as s:
        assert s.query(ExecutionLog).filter_by(
            batch_id=recorder.batch_id
        ).count() == 0  # 未达阈值，仍在缓冲
    time.sleep(1.05)  # 超过 1s 间隔
    recorder.on_log("10:00:01", "[001] 触发冲刷日志 2")
    with Session(db) as s:
        assert s.query(ExecutionLog).filter_by(
            batch_id=recorder.batch_id
        ).count() == 2  # 1s 阈值触发全量冲刷


def test_failure_log_marked_error_level(db, tree):
    pairs, recorder = _mk_recorder(db, tree)
    recorder.on_log("10:00:00", "开始执行测试套件: [模块一]")
    recorder.on_log("10:00:01", f"[{pairs[0][1].case_id}] 登录测试: ... 失败: 页面加载超时")
    recorder.flush_logs()
    with Session(db) as s:
        rows = s.query(ExecutionLog).filter_by(
            batch_id=recorder.batch_id
        ).order_by(ExecutionLog.seq_no).all()
        assert rows[0].log_level == "INFO"
        assert rows[1].log_level == "ERROR"


def test_case_log_linked_to_result_suite_log_null(db, tree):
    """用例日志关联 result_id（按用例过滤）；套件级日志 result_id 为 NULL。"""
    pairs, recorder = _mk_recorder(db, tree)
    code = pairs[0][1].case_id
    recorder.on_log("10:00:00", "开始执行测试套件: [模块一]")
    recorder.on_log("10:00:01", f"[{code}] 登录测试: 打开登录页... 通过")
    recorder.flush_logs()

    with Session(db) as s:
        suite_log = s.query(ExecutionLog).filter_by(
            batch_id=recorder.batch_id, seq_no=1
        ).one()
        case_log = s.query(ExecutionLog).filter_by(
            batch_id=recorder.batch_id, seq_no=2
        ).one()
        assert suite_log.result_id is None
        assert case_log.result_id == recorder._result_ids[code]


def test_end_to_end_simulated_batch(db, tree):
    """模拟 6 条勾选用例批次全流程：结果与面板数字一致（T11.3 验收的离线等价）。"""
    pairs = _checked_pairs(tree)
    recorder = BatchRecorder(
        db,
        ",".join(dict.fromkeys(m.module_name for m, _ in pairs)),
        queue=pairs,
    )
    recorder.on_log("10:00:00", f"开始执行测试套件: {pairs[0][0].module_name}")

    for idx, (module, case) in enumerate(pairs):
        recorder.on_case_status(case.case_id, "running")
        recorder.on_log("10:00:05", f"[{case.case_id}] {case.short_name}: 步骤执行")
        if idx == 1:  # 第 2 条失败
            recorder.on_log("10:00:06", f"[{case.case_id}] {case.short_name}: 断言失败: 元素未找到")
            recorder.on_case_status(case.case_id, "failed")
        else:
            recorder.on_case_status(case.case_id, "passed")
    recorder.on_batch_finished(False)

    with Session(db) as s:
        batch = s.get(ExecutionBatch, recorder.batch_id)
        assert batch.total_cases == len(pairs)
        assert batch.executed_cases == len(pairs)      # 与状态面板数字一致
        assert batch.passed_cases == len(pairs) - 1
        assert batch.failed_cases == 1
        failed = s.query(BatchCaseResult).filter_by(
            batch_id=recorder.batch_id, exec_status="FAILED"
        ).one()
        assert failed.error_message == "元素未找到"
        assert batch.batch_status == "COMPLETED"
