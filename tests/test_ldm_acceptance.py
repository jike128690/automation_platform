# -*- coding: utf-8 -*-
"""LDM 验收对照与端到端回归（T13.3，《数据库开发.md》第 7 节验收清单）。

逐项映射 6 条确认项 + 框架回归：
  1. 用例显式绑定主页面（FK 必填 + ON DELETE RESTRICT，种子用例均有 page_id）
  2. 历史报表用例名实时同步 + 软删除联动
  3. 多模块混合执行记录（module_names 英文逗号分隔）
  4. 本地媒体过期清理跟踪
  5. 系统用户名自动采集（getpass.getuser()）
  6. 页面接口资产入库（FK/部分唯一/CHECK 五值/种子 0 条/按 page_id 检索）
  框架：迁移版本记录与升级重放；跑批 → 落库 → "重启"后历史可查。

端到端用真实 AsyncExecutor（动作 Fake）驱动 BatchRecorder：日志格式、
状态机、失败原因提取均走生产代码路径。
"""
import asyncio
import getpass
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.engine import create_app_engine
from app.db.migration import applied_count, current_version, init_db, load_scripts
from app.db.models import Page, PageInterface, TestCase
from app.db.repositories import interface_repo
from app.db.repositories.case_repo import load_tree, soft_delete_case
from app.db.repositories.history_repo import (
    get_batch_logs, get_batch_results, list_batches, list_case_history,
)
from app.db.seed import seed_db
from app.db.services.batch_recorder import BatchRecorder
from app.db.services.history_service import cleanup_expired_media
from app.engine.executor import AsyncExecutor
from tests.test_executor import FakeAsyncActions

CHECKED = "001", "005", "006", "015", "022", "023"  # 真实种子默认勾选 6 条


@pytest.fixture()
def db(tmp_path):
    engine = create_app_engine(tmp_path / "acceptance.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()


def _case_pk(db, code):
    with Session(db) as s:
        return s.execute(
            text("SELECT case_id FROM tb_test_case WHERE case_code = :c"), {"c": code},
        ).scalar_one()


def _run_real_engine(db, pairs, actions=None):
    """真实 AsyncExecutor → BatchRecorder（生产信号槽直连，不经 Qt）。"""
    module_names = ",".join(dict.fromkeys(m.module_name for m, _ in pairs))
    recorder = BatchRecorder(db, module_names, queue=pairs)
    executor = AsyncExecutor(
        actions=actions or FakeAsyncActions(),
        on_status=recorder.on_case_status,
        on_log=recorder.on_log,
        on_finished=recorder.on_batch_finished,
        visual_pause=0, post_pause=0,
    )
    asyncio.run(executor.run(pairs))
    return recorder


# ================================================================ 确认项 1

def test_item1_case_binds_page_with_restrict_fk(db):
    with db.connect() as c:
        fks = c.exec_driver_sql("PRAGMA foreign_key_list(tb_test_case)").fetchall()
        cols = c.exec_driver_sql("PRAGMA table_info(tb_test_case)").fetchall()
    page_fk = next(f for f in fks if f[2] == "tb_page")
    assert page_fk[6].upper() == "RESTRICT"
    page_col = next(col for col in cols if col[1] == "page_id")
    assert page_col[3] == 1  # NOT NULL（必填）

    # 24 → 真实种子 23 条用例均有有效 page_id
    with Session(db) as s:
        cases = s.query(TestCase).all()
        assert len(cases) == 23
        for case in cases:
            assert case.page_id and s.get(Page, case.page_id) is not None

    # 被用例引用的页面禁止物理删除
    with Session(db) as s:
        page_id = s.query(TestCase).first().page_id
        with pytest.raises(IntegrityError):
            s.execute(text("DELETE FROM tb_page WHERE page_id = :p"), {"p": page_id})
            s.flush()


# ================================================================ 确认项 2

def test_item2_case_name_sync_and_soft_delete_history(db):
    tree = load_tree(db)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    recorder = _run_real_engine(db, pairs)
    pk = _case_pk(db, "001")

    with Session(db) as s:  # 用例编辑器改名
        s.execute(text("UPDATE tb_test_case SET case_name = '登录功能（已改名）' "
                       "WHERE case_id = :pk"), {"pk": pk})
        assert soft_delete_case(s, pk) is True  # 随后删除用例
        s.commit()

    assert "001" not in [c.case_id for m in load_tree(db) for c in m.cases]  # 树不显示
    row = next(r for r in get_batch_results(db, recorder.batch_id) if r.case_pk == pk)
    assert row.case_name == "登录功能（已改名）"  # 历史实时同步新名称
    assert row.case_is_deleted == 1
    assert len(list_case_history(db, pk)) == 1    # 软删除后历史仍可查


# ================================================================ 确认项 3

def test_item3_multi_module_batch_records_module_names(db):
    tree = load_tree(db)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]  # 跨 4 个模块
    recorder = _run_real_engine(db, pairs)

    batch = list_batches(db)[0]
    module_order = list(dict.fromkeys(m.module_name for m, _ in pairs))
    assert len(module_order) == 4                 # 确为多模块混合（M01~M04）
    assert batch.module_names == ",".join(module_order)  # 英文逗号分隔，按勾选顺序


# ================================================================ 确认项 4

def test_item4_media_cleanup_keeps_records(db, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    tree = load_tree(db)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    recorder = _run_real_engine(db, pairs)
    shot = media / "001.png"
    shot.write_bytes(b"png")
    recorder.update_case_media("001", screenshot_path=str(shot))
    old = "2020-01-01 00:00:00.000"
    with Session(db) as s:
        s.execute(text("UPDATE tb_batch_case_result SET end_time = :t"), {"t": old})
        s.commit()

    result = cleanup_expired_media(db, media_retention_days=5)
    assert result["files_deleted"] == 1 and not shot.exists()
    with Session(db) as s:
        flagged = s.execute(text(
            "SELECT COUNT(*) FROM tb_batch_case_result "
            "WHERE is_media_cleaned = 1 AND exec_status = 'PASSED'"
        )).scalar_one()
        assert flagged == 6               # 状态位置 1，执行记录保留
        assert s.execute(text("SELECT COUNT(*) FROM tb_execution_batch")).scalar_one() == 1
        assert s.execute(text("SELECT COUNT(*) FROM tb_execution_log")).scalar_one() > 0


# ================================================================ 确认项 5

def test_item5_executor_name_is_os_user(db):
    tree = load_tree(db)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    _run_real_engine(db, pairs)
    assert list_batches(db)[0].executor_name == getpass.getuser()


# ================================================================ 确认项 6

def test_item6_page_interface_asset_table(db):
    with db.connect() as c:
        fks = c.exec_driver_sql("PRAGMA foreign_key_list(tb_page_interface)").fetchall()
        idx = {n: s for n, s in c.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall()}
    assert next(f for f in fks if f[2] == "tb_page")[6].upper() == "RESTRICT"
    uq = idx["uq_page_interface"].upper()
    assert "UNIQUE" in uq and "IS_DELETED = 0" in uq

    with Session(db) as s:
        assert s.query(PageInterface).count() == 0          # 种子阶段 0 条
        page = s.query(Page).filter_by(page_name="登录页").one()
        assert interface_repo.list_by_page(s, page.page_id) == []  # 可按 page_id 检索

        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):  # 五值均合法
            s.add(PageInterface(page_id=page.page_id, interface_name=method,
                                method=method, interface_url=f"/api/{method}"))
        s.flush()
        s.add(PageInterface(page_id=page.page_id, interface_name="bad",
                            method="HEAD", interface_url="/api/bad"))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


# ================================================================ 框架回归

def test_framework_migration_recorded_and_replay_idempotent(db):
    scripts = load_scripts()
    assert current_version(db) == max(s.version for s in scripts)
    assert applied_count(db) == len(scripts)
    assert init_db(db) == []   # 升级重放幂等


def test_framework_run_persist_restart_queryable(db, tmp_path):
    """跑批 → 落库 → "重启客户端"（新引擎打开同一库文件）后历史仍可查。"""
    tree = load_tree(db)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    assert tuple(c.case_id for _, c in pairs) == CHECKED
    recorder = _run_real_engine(db, pairs)
    db_path = db.url.database

    with Session(db) as s:  # 成功标准 2.3-2（按真实种子 6 条勾选用例）
        assert s.execute(text("SELECT COUNT(*) FROM tb_execution_batch")).scalar_one() == 1
        assert s.execute(text(
            "SELECT COUNT(*) FROM tb_batch_case_result WHERE exec_status = 'PASSED'"
        )).scalar_one() == 6
        # 日志行数 = 套件日志（每模块 1 条）+ 每步骤 2 行（步骤开始 + 通过）
        step_total = sum(len(case.steps) for _, case in pairs)
        assert step_total == 38  # 26 + 006/015/022/023 各补 3 步登录
        suite_total = len(dict.fromkeys(m.module_name for m, _ in pairs))
        assert s.execute(text("SELECT COUNT(*) FROM tb_execution_log")).scalar_one() \
            == suite_total + 2 * step_total
    batch = list_batches(db)[0]
    assert (batch.total_cases, batch.passed_cases, batch.failed_cases) == (6, 6, 0)
    assert batch.pass_rate == 100.0 and batch.batch_status == "COMPLETED"

    db.dispose()  # 模拟客户端退出
    restarted = create_app_engine(Path(db_path))  # 模拟重启：新引擎打开同一库文件
    try:
        assert init_db(restarted) == []
        assert [b.batch_no for b in list_batches(restarted)] == [batch.batch_no]
        assert len(get_batch_results(restarted, recorder.batch_id)) == 6
        assert len(get_batch_logs(restarted, recorder.batch_id)) > 0
        assert len(load_tree(restarted)) == 4
    finally:
        restarted.dispose()


def test_framework_failed_case_records_real_engine_error(db):
    """真实引擎失败路径：error_message 来自生产日志格式，截图路径经回调落库。"""
    tree = load_tree(db)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    module_names = ",".join(dict.fromkeys(m.module_name for m, _ in pairs))
    recorder = BatchRecorder(db, module_names, queue=pairs)
    media = {}

    class ShotActions(FakeAsyncActions):
        async def capture_failure_screenshot(self, case_id):
            path = f"/reports/{case_id}.png"
            media[case_id] = path
            return path

    executor = AsyncExecutor(
        actions=ShotActions(missing_selectors={"#loginbtn"}),
        on_status=recorder.on_case_status,
        on_log=recorder.on_log,
        on_finished=recorder.on_batch_finished,
        on_media=lambda cid, path: media.setdefault("saved", path),
        visual_pause=0, post_pause=0,
    )
    asyncio.run(executor.run(pairs))

    failed = [r for r in get_batch_results(db, recorder.batch_id)
              if r.exec_status == "FAILED"]
    # 006+ 已补登录前置步骤：缺失 #loginbtn 时所有勾选用例都会在登录步失败
    assert {r.case_code for r in failed} == set(CHECKED)
    assert all("元素未找到" in r.error_message for r in failed)
    assert media["saved"].endswith(".png")
