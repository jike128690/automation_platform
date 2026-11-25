"""静态资产域 schema 与约束单测（T10.1 完成标准：约束/索引与 LDM 第 3 节一致）。

覆盖验收点：
- 6 表建表成功（含 tb_page_interface）；
- 接口表 FK（RESTRICT）/ 部分唯一 / CHECK 五值（验收确认项 6）；
- 用例表 page_id 必填 FK（确认项 1）、uq_case_code 部分唯一；
- 步骤表 uq_case_step_order 唯一、command_type 枚举 CHECK；
- 软删除记录豁免部分唯一索引（软删除后可复用编码）。
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.engine import create_app_engine
from app.db.migration import init_db
from app.db.models import (
    Page, PageElement, PageInterface, TestCase, TestModule, TestStep,
)
from app.db.repositories import interface_repo

NOW = "2026-11-25T10:00:00.000"
UUID_A = str(uuid.uuid4())
UUID_B = str(uuid.uuid4())


@pytest.fixture()
def session():
    engine = create_app_engine(_tmp_db_path())
    init_db(engine)
    from app.db.engine import SessionLocal
    s = SessionLocal(bind=engine)
    yield s
    s.rollback()
    s.close()
    engine.dispose()


def _tmp_db_path() -> "Path":
    import tempfile
    from pathlib import Path
    import os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return Path(path)


# ---------------------------------------------------------------- 建表与结构

def test_all_six_asset_tables_created(session):
    with session.get_bind().connect() as c:
        rows = c.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    tables = {r[0] for r in rows}
    assert {
        "tb_test_module", "tb_page", "tb_page_element",
        "tb_page_interface", "tb_test_case", "tb_test_step",
    } <= tables


def test_step_table_has_no_soft_delete_column(session):
    with session.get_bind().connect() as c:
        cols = c.exec_driver_sql("PRAGMA table_info(tb_test_step)").fetchall()
    names = {col[1] for col in cols}
    assert "is_deleted" not in names
    assert {"step_id", "case_id", "step_order", "command_type",
            "element_id", "target_override", "param_value", "is_secret",
            "timeout_sec", "remark", "created_at", "updated_at"} <= names


def test_partial_unique_indexes_exist(session):
    with session.get_bind().connect() as c:
        indexes = c.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND sql IS NOT NULL"
        ).fetchall()
    sql_map = {name: sql for name, sql in indexes}
    assert "uq_module_code" in sql_map
    assert "UNIQUE" in sql_map["uq_module_code"].upper()
    assert "WHERE is_deleted = 0" in sql_map["uq_module_code"]
    assert "uq_case_code" in sql_map
    assert "UNIQUE" in sql_map["uq_case_code"].upper()
    assert "WHERE is_deleted = 0" in sql_map["uq_case_code"]
    assert "uq_page_interface" in sql_map
    assert "UNIQUE" in sql_map["uq_page_interface"].upper()
    assert "WHERE is_deleted = 0" in sql_map["uq_page_interface"]
    assert "uq_case_step_order" in sql_map
    assert "UNIQUE" in sql_map["uq_case_step_order"].upper()


# ---------------------------------------------------------------- 通用工具

def _mk_module(session, code="M01", name="[模块一] 登录与基础功能"):
    m = TestModule(module_code=code, module_name=name, sort_order=0)
    session.add(m)
    session.flush()
    return m


def _mk_page(session, name="系统登录页", url="http://127.0.0.1:8765/login"):
    p = Page(page_name=name, page_url=url)
    session.add(p)
    session.flush()
    return p


def _mk_case(session, module, page, code="001", name="账号密码登录功能测试"):
    c = TestCase(
        module_id=module.module_id, page_id=page.page_id,
        case_code=code, case_name=name, short_name="登录测试",
    )
    session.add(c)
    session.flush()
    return c


def _mk_step(session, case, order=1, cmd="GOTO_URL", remark="打开登录页"):
    s = TestStep(
        case_id=case.case_id, step_order=order, command_type=cmd,
        target_override="http://127.0.0.1:8765/login", remark=remark,
    )
    session.add(s)
    session.flush()
    return s


# ---------------------------------------------------------------- 验收确认项 1

def test_case_page_id_required_fk_on_delete_restrict(session):
    with session.get_bind().connect() as c:
        fks = c.exec_driver_sql("PRAGMA foreign_key_list(tb_test_case)").fetchall()
    fk = next(f for f in fks if f[2] == "tb_page")
    # PRAGMA foreign_key_list: (id, seq, table, from, to, on_update, on_delete)
    assert fk[3] == "page_id" and fk[4] == "page_id"
    assert fk[6].upper() == "RESTRICT"

    # 必填：page_id 为 NULL 拒绝插入
    m = _mk_module(session)
    bad = TestCase(
        module_id=m.module_id, page_id=None, case_code="X01", case_name="无页面",
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------- 验收确认项 6

def test_interface_fk_restrict_and_method_check_and_partial_unique(session):
    with session.get_bind().connect() as c:
        fks = c.exec_driver_sql(
            "PRAGMA foreign_key_list(tb_page_interface)"
        ).fetchall()
    fk = next(f for f in fks if f[2] == "tb_page")
    assert fk[6].upper() == "RESTRICT"

    page = _mk_page(session)
    iface = PageInterface(
        page_id=page.page_id, interface_name="登录提交接口",
        method="POST", interface_url="/api/login",
    )
    session.add(iface)
    session.commit()  # 前置数据先落库（rollback 不影响已提交数据）

    # method 枚举 CHECK 五值
    bad_method = PageInterface(
        page_id=page.page_id, interface_name="坏方法",
        method="TRACE", interface_url="/api/other",
    )
    session.add(bad_method)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    assert session.get(Page, page.page_id) is not None  # page 仍在

    # 重新挂载已提交数据后验证部分唯一
    iface = session.get(PageInterface, iface.interface_id)
    assert iface is not None

    # 部分唯一：(page_id, method, url) 未删除态重复 → 拒绝
    dup = PageInterface(
        page_id=page.page_id, interface_name="重复接口",
        method="POST", interface_url="/api/login",
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    assert session.get(PageInterface, iface.interface_id) is not None

    # 软删除后同名接口可重新注册（部分唯一豁免 is_deleted=1 记录）
    iface = session.get(PageInterface, iface.interface_id)
    iface.is_deleted = 1
    session.flush()
    re_reg = PageInterface(
        page_id=page.page_id, interface_name="再次注册",
        method="POST", interface_url="/api/login",
    )
    session.add(re_reg)
    session.flush()  # 软删除豁免部分唯一 → 不抛异常


def test_interface_repo_filters_soft_deleted_and_returns_by_page(session):
    page = _mk_page(session)
    live = PageInterface(
        page_id=page.page_id, interface_name="搜索商品接口",
        method="GET", interface_url="/api/search",
    )
    dead = PageInterface(
        page_id=page.page_id, interface_name="已删除接口",
        method="GET", interface_url="/api/deleted",
    )
    session.add_all([live, dead])
    session.flush()
    dead.is_deleted = 1
    session.flush()

    assert interface_repo.count_by_page(session, page.page_id) == 1
    got = interface_repo.list_by_page(session, page.page_id)
    assert [i.interface_name for i in got] == ["搜索商品接口"]


# ---------------------------------------------------------------- 模块与用例约束

def test_module_code_partial_unique_allows_reuse_after_soft_delete(session):
    _mk_module(session, code="M01")
    session.flush()
    dup = TestModule(module_code="M01", module_name="重复模块")
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    m = _mk_module(session, code="M01")
    m.is_deleted = 1
    session.flush()
    reused = TestModule(module_code="M01", module_name="复用编码")
    session.add(reused)
    session.flush()


def test_case_code_unique_where_not_deleted(session):
    m = _mk_module(session)
    p = _mk_page(session)
    _mk_case(session, m, p, code="001")
    dup = TestCase(
        module_id=m.module_id, page_id=p.page_id, case_code="001",
        case_name="重复编号", is_builtin=0,
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.flush()


def test_case_flags_check_constraint(session):
    m = _mk_module(session)
    p = _mk_page(session)
    bad = TestCase(
        module_id=m.module_id, page_id=p.page_id, case_code="X02",
        case_name="坏标志", default_checked=2,  # 非 0/1
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()


def test_case_version_check_constraint(session):
    m = _mk_module(session)
    p = _mk_page(session)
    bad = TestCase(
        module_id=m.module_id, page_id=p.page_id, case_code="X03",
        case_name="坏版本", version=0,  # < 1
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------- 步骤约束

def test_step_order_unique_within_case(session):
    m = _mk_module(session)
    p = _mk_page(session)
    case = _mk_case(session, m, p)
    _mk_step(session, case, order=1)
    dup = TestStep(
        case_id=case.case_id, step_order=1, command_type="CLICK_ELEMENT",
        remark="重复行号",
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        session.flush()


def test_step_command_type_check_and_order_ge_1(session):
    m = _mk_module(session)
    p = _mk_page(session)
    case = _mk_case(session, m, p)

    bad_cmd = TestStep(
        case_id=case.case_id, step_order=1, command_type="SWIPE",
        remark="非法命令",
    )
    session.add(bad_cmd)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    bad_order = TestStep(
        case_id=case.case_id, step_order=0, command_type="GOTO_URL",
        remark="行号从0开始",
    )
    session.add(bad_order)
    with pytest.raises(IntegrityError):
        session.flush()


def test_step_cascade_delete_with_case(session):
    m = _mk_module(session)
    p = _mk_page(session)
    case = _mk_case(session, m, p)
    s1 = _mk_step(session, case, order=1)
    s2 = _mk_step(session, case, order=2, cmd="CLICK_ELEMENT", remark="步骤二")

    session.delete(case)
    session.flush()

    with session.get_bind().connect() as c:
        remaining = c.exec_driver_sql(
            f"SELECT COUNT(*) FROM tb_test_step WHERE case_id = '{case.case_id}'"
        ).scalar()
    assert remaining == 0  # CASCADE：用例物理删除 → 步骤级联清理


# ---------------------------------------------------------------- 外键 RESTRICT

def test_page_delete_restricted_when_element_exists(session):
    page = _mk_page(session)
    elem = PageElement(
        page_id=page.page_id, element_name="用户名输入框",
        locator_type="CSS", locator_value="#username",
    )
    session.add(elem)
    session.flush()

    with pytest.raises(IntegrityError):
        session.execute(
            text("DELETE FROM tb_page WHERE page_id = :pid"),
            {"pid": page.page_id},
        )
        session.flush()


def test_element_delete_sets_step_element_null(session):
    m = _mk_module(session)
    page = _mk_page(session)
    case = _mk_case(session, m, page)
    elem = PageElement(
        page_id=page.page_id, element_name="登录按钮",
        locator_type="CSS", locator_value="#login-btn",
    )
    session.add(elem)
    session.flush()
    step = TestStep(
        case_id=case.case_id, step_order=1, command_type="CLICK_ELEMENT",
        element_id=elem.element_id, remark="点击登录",
    )
    session.add(step)
    session.flush()

    session.execute(
        text("DELETE FROM tb_page_element WHERE element_id = :eid"),
        {"eid": elem.element_id},
    )
    session.flush()
    session.expire_all()
    reloaded = session.get(TestStep, step.step_id)
    assert reloaded.element_id is None  # SET NULL：元素物理删除 → 步骤置空


def test_page_url_scheme_check(session):
    bad = Page(page_name="坏地址", page_url="ftp://x")
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()
