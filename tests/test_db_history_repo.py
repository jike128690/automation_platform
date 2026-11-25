# -*- coding: utf-8 -*-
"""历史查询仓储单测（T11.5）：报表页预留接口 + 确认项 2 验证。

验收标准（《数据库开发.md》WBS T11.5 / LDM 确认项 2）：
- 报表页预留接口可用（批次列表 / 批次结果 / 批次日志 / 用例历史）；
- JOIN 用例名实时同步：改名后历史结果 JOIN 出新名称；
- 软删除用例后历史仍可查（Core 表选择绕过 Session 全局过滤）。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.engine import create_app_engine
from app.db.migration import init_db
from app.db.models import ExecutionBatch
from app.db.repositories.case_repo import load_tree, soft_delete_case
from app.db.repositories.history_repo import (
    get_batch_logs, get_batch_results, list_batches, list_case_history,
)
from app.db.seed import seed_db
from app.db.services.batch_recorder import BatchRecorder


@pytest.fixture()
def db(tmp_path):
    engine = create_app_engine(tmp_path / "history.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def tree(db):
    return load_tree(db)


def _checked_pairs(tree):
    return [(m, c) for m in tree for c in m.cases if c.default_checked]


def _case_pk(db, code: str) -> str:
    """按 case_code 查 DB 主键 UUID（recorder._result_ids 存的是 result_id，勿混用）。"""
    with Session(db) as s:
        return s.execute(
            text("SELECT case_id FROM tb_test_case WHERE case_code = :code"),
            {"code": code},
        ).scalar_one()


def _run_batch(db, tree, manual=False):
    """用真实种子跑一个模拟批次（6 条勾选用例，全过）。"""
    pairs = _checked_pairs(tree)
    recorder = BatchRecorder(
        db,
        ",".join(dict.fromkeys(m.module_name for m, _ in pairs)),
        queue=pairs,
    )
    recorder.on_log("10:00:00", f"开始执行测试套件: {pairs[0][0].module_name}")
    for module, case in pairs:
        recorder.on_case_status(case.case_id, "running")
        recorder.on_log("10:00:05", f"[{case.case_id}] {case.short_name}: 步骤执行")
        recorder.on_case_status(case.case_id, "passed")
    recorder.on_batch_finished(manual)
    return recorder, pairs


# ---------------------------------------------------------------- 批次列表

def test_list_batches_empty(db):
    assert list_batches(db) == []


def test_list_batches_desc_order_and_fields(db, tree):
    _run_batch(db, tree)
    _run_batch(db, tree)  # 第二个批次

    batches = list_batches(db)
    assert len(batches) == 2
    # 倒序：最新的在前，批次号自然日自增
    assert batches[0].batch_no.endswith("-02")
    assert batches[1].batch_no.endswith("-01")
    top = batches[0]
    assert top.batch_status == "COMPLETED"
    assert top.total_cases == 6
    assert top.executed_cases == 6
    assert top.passed_cases == 6
    assert top.failed_cases == 0
    assert top.pass_rate == 100.0
    assert top.executor_name  # getpass.getuser()
    assert top.end_time is not None
    assert top.duration_sec >= 0


def test_list_batches_limit(db, tree):
    _run_batch(db, tree)
    _run_batch(db, tree)
    assert len(list_batches(db, limit=1)) == 1


# ---------------------------------------------------------------- 批次结果（确认项 2）

def test_get_batch_results_joins_live_case_name(db, tree):
    """确认项 2：改名后历史结果 JOIN 出最新用例名（无快照冗余）。"""
    recorder, pairs = _run_batch(db, tree)
    code = pairs[0][1].case_id
    case_pk = _case_pk(db, code)

    # 模拟用例编辑器改名（直接 UPDATE tb_test_case）
    with Session(db) as s:
        s.execute(
            text("UPDATE tb_test_case SET case_name = '改名后的登录用例' "
                 "WHERE case_id = :pk"),
            {"pk": case_pk},
        )
        s.commit()

    results = get_batch_results(db, recorder.batch_id)
    assert len(results) == 6
    first = results[0]
    assert first.case_name == "改名后的登录用例"  # 实时同步 ✓
    assert first.case_code == code
    assert first.case_pk == case_pk
    assert first.exec_status == "PASSED"
    assert first.queue_order == 1
    assert first.case_is_deleted == 0


def test_soft_deleted_case_still_in_history(db, tree):
    """确认项 2：软删除用例后历史仍可查（绕过 Session 全局过滤）。"""
    recorder, pairs = _run_batch(db, tree)
    case_pk = _case_pk(db, pairs[0][1].case_id)

    with Session(db) as s:
        assert soft_delete_case(s, case_pk) is True
        s.commit()

    # ORM 实体查询已被全局过滤（树不显示），但历史结果行照常返回
    results = get_batch_results(db, recorder.batch_id)
    deleted_row = next(r for r in results if r.case_pk == case_pk)
    assert deleted_row.case_is_deleted == 1
    assert deleted_row.exec_status == "PASSED"          # 历史状态保留
    assert deleted_row.case_name == "账号密码登录功能测试"  # 名称仍可 JOIN


def test_get_batch_results_failed_row_keeps_error(db, tree):
    recorder, pairs = _run_batch(db, tree)
    code = pairs[1][1].case_id
    recorder.on_case_status(code, "running")
    recorder.on_log("10:00:06", f"[{code}] {pairs[1][1].short_name}: 断言失败: 元素未找到")
    recorder.on_case_status(code, "failed")
    recorder.on_batch_finished(False)

    results = get_batch_results(db, recorder.batch_id)
    failed = next(r for r in results if r.queue_order == 2)
    assert failed.exec_status == "FAILED"
    assert failed.error_message == "元素未找到"


# ---------------------------------------------------------------- 批次日志

def test_get_batch_logs_ordered_and_suite_null(db, tree):
    recorder, pairs = _run_batch(db, tree)
    logs = get_batch_logs(db, recorder.batch_id)
    assert len(logs) == 1 + len(pairs)  # 套件级 1 条 + 每用例 1 条
    assert [log.seq_no for log in logs] == list(range(1, len(logs) + 1))
    assert logs[0].result_id is None               # 套件级日志
    assert logs[0].log_content.startswith("开始执行测试套件")
    assert all(log.result_id for log in logs[1:])  # 用例日志已关联


def test_get_batch_logs_filter_by_result(db, tree):
    """图1 [报错日志]：按用例 result_id 过滤。"""
    recorder, pairs = _run_batch(db, tree)
    code = pairs[2][1].case_id
    result_id = recorder._result_ids[code]

    logs = get_batch_logs(db, recorder.batch_id, result_id=result_id)
    assert len(logs) == 1
    assert logs[0].result_id == result_id
    assert f"[{code}]" in logs[0].log_content


# ---------------------------------------------------------------- 用例历史

def test_list_case_history_across_batches(db, tree):
    """按用例查历史：两条批次各含该用例，倒序返回。"""
    recorder1, pairs = _run_batch(db, tree)
    recorder2, _ = _run_batch(db, tree)
    case_pk = _case_pk(db, pairs[0][1].case_id)

    history = list_case_history(db, case_pk)
    assert len(history) == 2
    assert history[0].batch_no.endswith("-02")  # 最新批次在前
    assert history[1].batch_no.endswith("-01")
    assert all(h.exec_status == "PASSED" for h in history)
    assert history[0].batch_status == "COMPLETED"


def test_list_case_history_empty(db):
    with Session(db) as s:
        from app.db.models import TestCase
        case = s.query(TestCase).first()
        case_pk = case.case_id
    assert list_case_history(db, case_pk) == []


# ---------------------------------------------------------------- 批次状态覆盖

def test_manual_stop_batch_visible_in_history(db, tree):
    recorder, pairs = _run_batch(db, tree, manual=True)
    batches = list_batches(db)
    assert batches[0].batch_status == "STOPPED"
    results = get_batch_results(db, recorder.batch_id)
    waiting = [r for r in results if r.exec_status == "WAITING"]
    assert len(waiting) + len([r for r in results if r.exec_status != "WAITING"]) == 6
