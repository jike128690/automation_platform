# -*- coding: utf-8 -*-
"""历史批次/结果/日志查询仓储（T11.5，报表页/历史页预留）。

查询约定：
- list_batches / get_batch_logs：纯动态域表查询，走 ORM 实体选择；
- get_batch_results / list_case_history：**必须 JOIN tb_test_case 取最新
  用例名**（LDM 确认项 2：不冗余快照、改名实时同步、软删除用例历史仍可查）
  —— T10.4 的 Session 全局过滤会隐藏软删除实体，故这两类查询使用
  **Core 表选择**（soft_delete.py 约定的绕行通道），结果行透出用例
  is_deleted 状态供报表标注"已删除用例"。
- 所有函数接受 engine 参数、内部短事务（与 case_repo.load_tree 风格一致），
  报表页可直接异步调用，不持有长会话。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    BatchCaseResult, ExecutionBatch, ExecutionLog, TestCase,
)

# Core 表（绕过 ORM 实体软删除过滤的查询通道，见模块 docstring）
_RES_T = BatchCaseResult.__table__
_CASE_T = TestCase.__table__


# ---------------------------------------------------------------- 数据行


@dataclass(frozen=True)
class BatchSummary:
    """历史批次摘要（图1 历史列表行）。"""

    batch_id: str
    batch_no: str
    module_names: str
    batch_status: str
    total_cases: int
    executed_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    executor_name: str
    start_time: str
    end_time: str | None
    duration_sec: int


@dataclass(frozen=True)
class CaseResultRow:
    """单批次内用例结果行（用例名经 JOIN 实时同步，确认项 2）。"""

    result_id: str
    batch_id: str
    case_pk: str            # tb_test_case 主键 UUID
    case_code: str          # JOIN 最新值
    case_name: str          # JOIN 最新值（确认项 2）
    short_name: str | None  # JOIN 最新值
    case_is_deleted: int    # 用例软删除状态（报表标注"已删除用例"）
    queue_order: int
    exec_status: str
    duration_sec: int
    retry_count: int
    error_message: str | None
    screenshot_path: str | None
    video_path: str | None
    is_media_cleaned: int
    start_time: str | None
    end_time: str | None


@dataclass(frozen=True)
class LogRow:
    """执行流水日志行（seq_no 严格有序）。"""

    seq_no: int
    log_level: str
    log_time: str
    log_content: str
    result_id: str | None   # 套件级日志为 NULL；[报错日志] 按用例过滤键
    created_at: str


@dataclass(frozen=True)
class CaseHistoryRow:
    """单条用例的历史执行记录（跨批次倒序）。"""

    batch_no: str
    batch_status: str
    batch_start_time: str
    exec_status: str
    duration_sec: int
    retry_count: int
    error_message: str | None
    queue_order: int
    result_start_time: str | None
    result_end_time: str | None


# ---------------------------------------------------------------- 批次查询


def list_batches(engine, limit: int | None = None) -> list[BatchSummary]:
    """历史批次列表（按创建时间倒序，limit 可选）。"""
    stmt = select(ExecutionBatch).order_by(
        ExecutionBatch.created_at.desc(), ExecutionBatch.batch_no.desc(),
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    with Session(engine) as s:
        batches = s.scalars(stmt).all()
    return [
        BatchSummary(
            batch_id=b.batch_id,
            batch_no=b.batch_no,
            module_names=b.module_names,
            batch_status=b.batch_status,
            total_cases=b.total_cases,
            executed_cases=b.executed_cases,
            passed_cases=b.passed_cases,
            failed_cases=b.failed_cases,
            pass_rate=b.pass_rate,
            executor_name=b.executor_name,
            start_time=b.start_time,
            end_time=b.end_time,
            duration_sec=b.duration_sec,
        )
        for b in batches
    ]


def get_batch_results(engine, batch_id: str) -> list[CaseResultRow]:
    """按批次查全部用例结果（queue_order 序，用例名/编号 JOIN 实时同步）。

    Core 表选择：不加载 TestCase 实体，软删除用例的历史行照常返回
    （确认项 2），其 is_deleted 状态随行透出。
    """
    stmt = (
        select(
            _RES_T.c.result_id, _RES_T.c.batch_id, _RES_T.c.case_id,
            _CASE_T.c.case_code, _CASE_T.c.case_name, _CASE_T.c.short_name,
            _CASE_T.c.is_deleted.label("case_is_deleted"),
            _RES_T.c.queue_order, _RES_T.c.exec_status,
            _RES_T.c.duration_sec, _RES_T.c.retry_count,
            _RES_T.c.error_message, _RES_T.c.screenshot_path,
            _RES_T.c.video_path, _RES_T.c.is_media_cleaned,
            _RES_T.c.start_time, _RES_T.c.end_time,
        )
        .join(_CASE_T, _RES_T.c.case_id == _CASE_T.c.case_id)
        .where(_RES_T.c.batch_id == batch_id)
        .order_by(_RES_T.c.queue_order)
    )
    with Session(engine) as s:
        rows = s.execute(stmt).all()
    return [
        CaseResultRow(
            result_id=r.result_id,
            batch_id=r.batch_id,
            case_pk=r.case_id,
            case_code=r.case_code,
            case_name=r.case_name,
            short_name=r.short_name,
            case_is_deleted=r.case_is_deleted,
            queue_order=r.queue_order,
            exec_status=r.exec_status,
            duration_sec=r.duration_sec,
            retry_count=r.retry_count,
            error_message=r.error_message,
            screenshot_path=r.screenshot_path,
            video_path=r.video_path,
            is_media_cleaned=r.is_media_cleaned,
            start_time=r.start_time,
            end_time=r.end_time,
        )
        for r in rows
    ]


# ---------------------------------------------------------------- 日志查询


def get_batch_logs(engine, batch_id: str,
                   result_id: str | None = None) -> list[LogRow]:
    """按批次查流水日志（seq_no 严格有序；result_id 可选按用例过滤）。

    对应图1 [报错日志]：点击某用例后仅展示该用例步骤日志
    （result_id 非空的行）；套件级启停日志 result_id 为 NULL。
    """
    stmt = (
        select(ExecutionLog)
        .where(ExecutionLog.batch_id == batch_id)
        .order_by(ExecutionLog.seq_no)
    )
    if result_id is not None:
        stmt = stmt.where(ExecutionLog.result_id == result_id)
    with Session(engine) as s:
        logs = s.scalars(stmt).all()
    return [
        LogRow(
            seq_no=log.seq_no,
            log_level=log.log_level,
            log_time=log.log_time,
            log_content=log.log_content,
            result_id=log.result_id,
            created_at=log.created_at,
        )
        for log in logs
    ]


# ---------------------------------------------------------------- 用例历史


def list_case_history(engine, case_pk: str) -> list[CaseHistoryRow]:
    """按用例查历史执行记录（跨批次，按批次创建时间倒序）。

    与 get_batch_results 同理走 Core 表选择：软删除用例的历史仍可查。
    """
    stmt = (
        select(
            _RES_T.c.exec_status, _RES_T.c.duration_sec, _RES_T.c.retry_count,
            _RES_T.c.error_message, _RES_T.c.queue_order,
            _RES_T.c.start_time.label("result_start_time"),
            _RES_T.c.end_time.label("result_end_time"),
            ExecutionBatch.batch_no, ExecutionBatch.batch_status,
            ExecutionBatch.start_time.label("batch_start_time"),
            ExecutionBatch.created_at.label("batch_created_at"),
        )
        .join(ExecutionBatch, _RES_T.c.batch_id == ExecutionBatch.batch_id)
        .where(_RES_T.c.case_id == case_pk)
        .order_by(ExecutionBatch.created_at.desc(), _RES_T.c.queue_order)
    )
    with Session(engine) as s:
        rows = s.execute(stmt).all()
    return [
        CaseHistoryRow(
            batch_no=r.batch_no,
            batch_status=r.batch_status,
            batch_start_time=r.batch_start_time,
            exec_status=r.exec_status,
            duration_sec=r.duration_sec,
            retry_count=r.retry_count,
            error_message=r.error_message,
            queue_order=r.queue_order,
            result_start_time=r.result_start_time,
            result_end_time=r.result_end_time,
        )
        for r in rows
    ]
