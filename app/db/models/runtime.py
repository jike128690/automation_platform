# -*- coding: utf-8 -*-
"""动态执行域 ORM 模型（LDM 2.7–2.9 节，表结构唯一权威来源）。

3 张表：tb_execution_batch / tb_batch_case_result / tb_execution_log。

落地要点（LDM 第 3 节约束 + 《数据库开发.md》4.4/4.6）：
- 动态域物理删除：无 is_deleted 软删除列；批次删除经外键
  ON DELETE CASCADE 级联清结果与日志（报告页删除历史批次，LDM 第 5 节）；
- 历史报表不冗余用例名快照：tb_batch_case_result.case_id 外键
  ON DELETE RESTRICT 指向 tb_test_case，JOIN 实时取最新名称（确认项 2）；
- tb_execution_batch 无 updated_at（LDM 2.7 仅 created_at）；
  tb_batch_case_result 无审计时间列（仅有 start_time/end_time 执行区间）；
- CHECK 枚举：batch_status / exec_status / log_level 与应用层 Python Enum
  双层校验（计划 4.6）；
- is_media_cleaned 状态位支撑本地媒体过期清理跟踪（确认项 4，T13.1 消费）。
"""
import enum
import getpass

from sqlalchemy import (
    CheckConstraint, Float, ForeignKey, Index, Integer, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_uuid, now_iso

__all__ = [
    "ExecutionBatch", "BatchCaseResult", "ExecutionLog",
    "BatchStatus", "ExecStatus", "LogLevel",
]


# ---------------------------------------------------------------- 应用层枚举


class BatchStatus(str, enum.Enum):
    """批次运行状态（LDM 2.7 batch_status）。"""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"


class ExecStatus(str, enum.Enum):
    """用例执行状态（LDM 2.8 exec_status，对应图5右侧队列）。"""

    WAITING = "WAITING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class LogLevel(str, enum.Enum):
    """日志级别（LDM 2.9 log_level）。"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


# ---------------------------------------------------------------- 2.7 tb_execution_batch


class ExecutionBatch(Base):
    """测试执行批次表：每次【运行测试】的批次实例与汇总统计。"""

    __test__ = False  # 防止 pytest 按 Test* 前缀误收集 ORM 类
    __tablename__ = "tb_execution_batch"

    batch_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    batch_no: Mapped[str] = mapped_column(Text(32), nullable=False)
    module_names: Mapped[str] = mapped_column(
        Text(1000), nullable=False,
    )  # 确认项 3：英文逗号分隔的模块名称串
    batch_status: Mapped[str] = mapped_column(
        Text(20), nullable=False, default=BatchStatus.RUNNING.value,
    )
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
    )  # 保留 1 位小数（0.0 ~ 100.0），由落库服务计算
    executor_name: Mapped[str] = mapped_column(
        Text(100), nullable=False, default=getpass.getuser,
    )  # 确认项 5：OS 当前登录用户名
    start_time: Mapped[str] = mapped_column(
        Text(23), nullable=False, default=now_iso,
    )
    end_time: Mapped[str | None] = mapped_column(Text(23), nullable=True)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(
        Text(23), nullable=False, default=now_iso,
    )  # LDM 2.7：仅 created_at，无 updated_at

    __table_args__ = (
        CheckConstraint(
            "batch_status IN ('RUNNING', 'COMPLETED', 'STOPPED')",
            name="ck_batch_status",
        ),
        # ck_batch_counts（LDM 第 3 节原文）
        CheckConstraint(
            "total_cases >= 0 AND passed_cases >= 0 AND failed_cases >= 0 "
            "AND (passed_cases + failed_cases) <= total_cases "
            "AND pass_rate BETWEEN 0.0 AND 100.0",
            name="ck_batch_counts",
        ),
        CheckConstraint("duration_sec >= 0", name="ck_batch_duration"),
        # uq_batch_no：批次展示号全局唯一（#YYYYMMDD-NN）
        Index("uq_batch_no", "batch_no", unique=True),
    )

    results: Mapped[list["BatchCaseResult"]] = relationship(
        back_populates="batch",
        order_by="BatchCaseResult.queue_order",
    )
    logs: Mapped[list["ExecutionLog"]] = relationship(
        back_populates="batch",
        order_by="ExecutionLog.seq_no",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExecutionBatch {self.batch_no} {self.batch_status}>"


# ---------------------------------------------------------------- 2.8 tb_batch_case_result


class BatchCaseResult(Base):
    """批次用例执行结果表：批次 × 用例 的多对多关联实体（LDM 第 4 节）。

    不冗余用例名称：查询历史报告时 JOIN tb_test_case 取最新
    case_code / case_name（确认项 2）。
    """

    __test__ = False  # 防止 pytest 按 Test* 前缀误收集 ORM 类
    __tablename__ = "tb_batch_case_result"

    result_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    batch_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_execution_batch.batch_id", ondelete="CASCADE", name="fk_res_batch"),
        nullable=False,
    )  # 批次物理删除时级联清理（报告页删除历史）
    case_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_test_case.case_id", ondelete="RESTRICT", name="fk_res_case"),
        nullable=False,
    )  # 禁止物理删除已被历史引用的用例，仅允许软删除（确认项 2）
    queue_order: Mapped[int] = mapped_column(Integer, nullable=False)
    exec_status: Mapped[str] = mapped_column(
        Text(20), nullable=False, default=ExecStatus.WAITING.value,
    )
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text(1000), nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(Text(500), nullable=True)
    video_path: Mapped[str | None] = mapped_column(Text(500), nullable=True)
    is_media_cleaned: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )  # 确认项 4：媒体文件过期清理状态位（T13.1 扫描任务置 1）
    start_time: Mapped[str | None] = mapped_column(Text(23), nullable=True)
    end_time: Mapped[str | None] = mapped_column(Text(23), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "exec_status IN ('WAITING', 'RUNNING', 'PASSED', 'FAILED')",
            name="ck_res_status",
        ),
        CheckConstraint("queue_order >= 1", name="ck_res_queue"),
        CheckConstraint("is_media_cleaned IN (0, 1)", name="ck_res_media"),
        CheckConstraint("duration_sec >= 0 AND retry_count >= 0", name="ck_res_counters"),
        # uq_batch_case（LDM 第 3 节）：单批次内同用例唯一；
        # 前导列 batch_id 同时覆盖"按批次查结果"查询路径（计划 4.6）
        Index("uq_batch_case", "batch_id", "case_id", unique=True),
        # 按用例查历史（T11.5 报表页预留）+ fk_res_case RESTRICT 校验路径
        Index("idx_result_case", "case_id"),
    )

    batch: Mapped["ExecutionBatch"] = relationship(back_populates="results")
    logs: Mapped[list["ExecutionLog"]] = relationship(back_populates="result")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BatchCaseResult #{self.queue_order} {self.exec_status}>"


# ---------------------------------------------------------------- 2.9 tb_execution_log


class ExecutionLog(Base):
    """执行流水日志表：带时间戳的步骤明细与异常堆栈。"""

    __test__ = False  # 防止 pytest 按 Test* 前缀误收集 ORM 类
    __tablename__ = "tb_execution_log"

    log_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    batch_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_execution_batch.batch_id", ondelete="CASCADE", name="fk_log_batch"),
        nullable=False,
    )
    result_id: Mapped[str | None] = mapped_column(
        Text(36),
        ForeignKey(
            "tb_batch_case_result.result_id", ondelete="CASCADE", name="fk_log_result",
        ),
        nullable=True,
    )  # 套件级启停日志为 NULL；用例步骤日志关联 result_id 供按用例过滤
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    log_level: Mapped[str] = mapped_column(
        Text(10), nullable=False, default=LogLevel.INFO.value,
    )
    log_time: Mapped[str] = mapped_column(
        Text(8), nullable=False,
    )  # 展示时间戳 HH:mm:ss（图5右下角）
    log_content: Mapped[str] = mapped_column(Text(2000), nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text(23), nullable=False, default=now_iso,
    )  # 精确到毫秒的完整时间戳

    __table_args__ = (
        CheckConstraint(
            "log_level IN ('DEBUG', 'INFO', 'WARN', 'ERROR')",
            name="ck_log_level",
        ),
        CheckConstraint("seq_no >= 1", name="ck_log_seq"),
        # 批次日志流查询路径（计划 4.6：tb_execution_log(batch_id, result_id)）
        Index("idx_log_batch_result", "batch_id", "result_id"),
    )

    batch: Mapped["ExecutionBatch"] = relationship(back_populates="logs")
    result: Mapped["BatchCaseResult | None"] = relationship(back_populates="logs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExecutionLog #{self.seq_no} {self.log_level}>"
