# -*- coding: utf-8 -*-
"""动态执行域 schema 与约束单测（T11.1 完成标准：级联/唯一/检查约束与 LDM 一致）。

覆盖验收点：
- 3 表建表成功（v001+v002 迁移链）；
- 级联：result/log → batch CASCADE；result → case RESTRICT；log → result CASCADE；
- 唯一：uq_batch_no、uq_batch_case(batch_id, case_id)；
- 检查：ck_batch_status / ck_batch_counts（LDM 第 3 节原文）/
  ck_res_status / ck_log_level 等枚举与数值域；
- 默认值与 ORM 行为（确认项 5 executor_name、确认项 4 is_media_cleaned）。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.engine import create_app_engine
from app.db.migration import current_version, init_db
from app.db.models import (
    BatchCaseResult, ExecutionBatch, ExecutionLog, TestCase,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_app_engine(tmp_path / "runtime.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()


def seed_db(engine):
    from app.db.seed import seed_db as _seed
    _seed(engine)


def _mk_case(db) -> TestCase:
    with Session(db) as s:
        case = s.query(TestCase).order_by(TestCase.case_code).first()
        s.expunge(case)
        return case


# ---------------------------------------------------------------- 建表

def test_runtime_tables_created(db):
    assert current_version(db) == 2
    with db.connect() as c:
        tables = {r[0] for r in c.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"tb_execution_batch", "tb_batch_case_result",
            "tb_execution_log"} <= tables


def test_foreign_keys_match_ldm(db):
    """PRAGMA foreign_key_list 逐表核对级联策略（LDM 第 3 节）。"""
    with db.connect() as c:
        res_fks = c.exec_driver_sql(
            "PRAGMA foreign_key_list(tb_batch_case_result)"
        ).fetchall()
        log_fks = c.exec_driver_sql(
            "PRAGMA foreign_key_list(tb_execution_log)"
        ).fetchall()
    # (table, from, on_delete)
    res_map = {(f[2], f[3]): f[6] for f in res_fks}
    log_map = {(f[2], f[3]): f[6] for f in log_fks}
    assert res_map[("tb_execution_batch", "batch_id")].upper() == "CASCADE"
    assert res_map[("tb_test_case", "case_id")].upper() == "RESTRICT"
    assert log_map[("tb_execution_batch", "batch_id")].upper() == "CASCADE"
    assert log_map[("tb_batch_case_result", "result_id")].upper() == "CASCADE"


def test_unique_indexes_present(db):
    with db.connect() as c:
        rows = c.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND sql IS NOT NULL"
        ).fetchall()
    sql_map = {name: sql for name, sql in rows}
    assert "UNIQUE" in sql_map["uq_batch_no"].upper()
    assert "UNIQUE" in sql_map["uq_batch_case"].upper()
    assert "batch_id,case_id" in sql_map["uq_batch_case"].lower().replace(" ", "")
    assert "idx_result_case" in sql_map
    assert "idx_log_batch_result" in sql_map


# ---------------------------------------------------------------- 唯一约束

def _mk_batch(db, batch_no="#20261125-01", total=2) -> ExecutionBatch:
    """创建批次并返回游离实例（expire_on_commit=False 保证属性已加载）。"""
    with Session(db, expire_on_commit=False) as s:
        batch = ExecutionBatch(
            batch_no=batch_no, module_names="[模块一] 登录与基础功能",
            total_cases=total,
        )
        s.add(batch)
        s.commit()
        s.expunge(batch)
        return batch


def test_uq_batch_no_rejects_duplicate(db):
    _mk_batch(db, "#20261125-01")
    with Session(db) as s:
        dup = ExecutionBatch(
            batch_no="#20261125-01", module_names="重复批次号",
        )
        s.add(dup)
        with pytest.raises(IntegrityError):
            s.commit()


def test_uq_batch_case_rejects_duplicate_pair(db):
    case = _mk_case(db)
    batch = _mk_batch(db, "#20261125-02")
    with Session(db) as s:
        s.add(BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=1,
        ))
        s.commit()
        s.add(BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=2,
        ))
        with pytest.raises(IntegrityError):
            s.commit()


# ---------------------------------------------------------------- 检查约束

@pytest.mark.parametrize("field, value", [
    ("batch_status", "PAUSED"),                                  # ck_batch_status
    ("total_cases", -1),                                         # ck_batch_counts
    ("passed_cases", -1),                                        # ck_batch_counts
    ("pass_rate", 150.0),                                        # ck_batch_counts
])
def test_batch_check_constraints(db, field, value):
    with Session(db) as s:
        batch = ExecutionBatch(
            batch_no="#20261125-10", module_names="约束测试",
        )
        setattr(batch, field, value)
        s.add(batch)
        with pytest.raises(IntegrityError):
            s.commit()


def test_ck_batch_counts_rejects_overflow(db):
    """passed + failed > total 拒绝（LDM ck_batch_counts）。"""
    with Session(db) as s:
        batch = ExecutionBatch(
            batch_no="#20261125-11", module_names="溢出测试",
            total_cases=2, passed_cases=2, failed_cases=1,
        )
        s.add(batch)
        with pytest.raises(IntegrityError):
            s.commit()


@pytest.mark.parametrize("field, value", [
    ("exec_status", "SKIPPED"),      # ck_res_status
    ("queue_order", 0),              # ck_res_queue
    ("is_media_cleaned", 2),         # ck_res_media
    ("duration_sec", -1),            # ck_res_counters
])
def test_result_check_constraints(db, field, value):
    case = _mk_case(db)
    batch = _mk_batch(db, "#20261125-12")
    with Session(db) as s:
        result = BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=1,
        )
        setattr(result, field, value)
        s.add(result)
        with pytest.raises(IntegrityError):
            s.commit()


def test_log_level_check_constraint(db):
    batch = _mk_batch(db, "#20261125-13")
    with Session(db) as s:
        log = ExecutionLog(
            batch_id=batch.batch_id, seq_no=1,
            log_time="10:00:00", log_content="非法级别",
            log_level="FATAL",
        )
        s.add(log)
        with pytest.raises(IntegrityError):
            s.commit()


# ---------------------------------------------------------------- 默认值与确认项

def test_batch_defaults_and_executor_autofill(db):
    """确认项 5：executor_name 默认 getpass.getuser()；状态/统计默认值。"""
    import getpass
    with Session(db) as s:
        batch = ExecutionBatch(batch_no="#20261125-20", module_names="默认值测试")
        s.add(batch)
        s.commit()
        s.refresh(batch)
        assert batch.batch_status == "RUNNING"
        assert batch.executor_name == getpass.getuser()
        assert batch.total_cases == 0
        assert batch.pass_rate == 0.0
        assert batch.duration_sec == 0
        assert batch.end_time is None
        assert len(batch.start_time) == 23  # ISO-8601 毫秒


def test_result_defaults(db):
    case = _mk_case(db)
    batch = _mk_batch(db, "#20261125-21")
    with Session(db) as s:
        result = BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=1,
        )
        s.add(result)
        s.commit()
        s.refresh(result)
        assert result.exec_status == "WAITING"
        assert result.is_media_cleaned == 0
        assert result.duration_sec == 0
        assert result.retry_count == 0
        assert result.error_message is None
        assert result.screenshot_path is None


def test_suite_log_allows_null_result_id(db):
    """套件级启停日志 result_id 为 NULL；用例步骤日志关联 result_id。"""
    case = _mk_case(db)
    batch = _mk_batch(db, "#20261125-22")
    with Session(db) as s:
        result = BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=1,
        )
        s.add(result)
        s.flush()
        suite_log = ExecutionLog(
            batch_id=batch.batch_id, seq_no=1,
            log_time="10:00:00", log_content="开始执行测试套件: [模块一]",
        )
        case_log = ExecutionLog(
            batch_id=batch.batch_id, result_id=result.result_id, seq_no=2,
            log_time="10:00:01", log_content="[001] 登录测试: 打开登录页... 通过",
        )
        s.add_all([suite_log, case_log])
        s.commit()
        s.refresh(suite_log)
        assert suite_log.result_id is None
        assert case_log.result_id == result.result_id


# ---------------------------------------------------------------- 级联行为

def test_delete_batch_cascades_results_and_logs(db):
    """报告页删除历史批次：结果与日志级联清理（物理删除域）。"""
    case = _mk_case(db)
    batch = _mk_batch(db, "#20261125-30")
    with Session(db) as s:
        result = BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=1,
        )
        s.add(result)
        s.flush()
        s.add(ExecutionLog(
            batch_id=batch.batch_id, seq_no=1,
            log_time="10:00:00", log_content="套件日志",
        ))
        s.add(ExecutionLog(
            batch_id=batch.batch_id, result_id=result.result_id, seq_no=2,
            log_time="10:00:01", log_content="用例日志",
        ))
        s.commit()

        s.execute(text("DELETE FROM tb_execution_batch WHERE batch_id = :bid"),
                  {"bid": batch.batch_id})
        s.commit()

        assert s.execute(
            text("SELECT COUNT(*) FROM tb_batch_case_result")
        ).scalar_one() == 0
        assert s.execute(
            text("SELECT COUNT(*) FROM tb_execution_log")
        ).scalar_one() == 0


def test_delete_case_restricted_when_history_exists(db):
    """确认项 2：被历史结果引用的用例禁止物理删除（仅软删除）。"""
    case = _mk_case(db)
    batch = _mk_batch(db, "#20261125-31")
    with Session(db) as s:
        s.add(BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=1,
        ))
        s.commit()

        with pytest.raises(IntegrityError):
            s.execute(text("DELETE FROM tb_test_case WHERE case_id = :cid"),
                      {"cid": case.case_id})
            s.commit()


def test_delete_result_cascades_case_logs(db):
    """log → result CASCADE：结果删除后关联步骤日志级联清理。"""
    case = _mk_case(db)
    batch = _mk_batch(db, "#20261125-32")
    with Session(db) as s:
        result = BatchCaseResult(
            batch_id=batch.batch_id, case_id=case.case_id, queue_order=1,
        )
        s.add(result)
        s.flush()
        s.add(ExecutionLog(
            batch_id=batch.batch_id, result_id=result.result_id, seq_no=1,
            log_time="10:00:00", log_content="用例日志",
        ))
        s.commit()

        s.execute(text("DELETE FROM tb_batch_case_result WHERE result_id = :rid"),
                  {"rid": result.result_id})
        s.commit()
        assert s.execute(
            text("SELECT COUNT(*) FROM tb_execution_log")
        ).scalar_one() == 0
