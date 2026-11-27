# -*- coding: utf-8 -*-
r"""种子数据单测（T10.2）：真实业务数据落库的完整性、幂等与映射正确性。

验收标准（《数据库开发.md》WBS T10.2，数据源已按用户指示替换为
D:\WebAutomation\pages 真实业务 Page Object）：
- 落库后模块/页面/元素/用例/步骤计数与 seed_data 定义完全一致；
- tb_page_interface 为空（无 HTTP 接口资产）；
- 重复执行幂等（DB 为唯一事实源）。
"""
import pytest
from sqlalchemy import func, select

from app.db.engine import create_app_engine
from app.db.migration import init_db
from app.db.models import (
    Page, PageElement, PageInterface, TestCase, TestModule, TestStep,
)
from app.db.repositories import interface_repo
from app.db.seed import seed_db
from app.db.seed_data import SEED_MODULES, SEED_PAGES


@pytest.fixture()
def session(tmp_path):
    engine = create_app_engine(tmp_path / "seed.db")
    init_db(engine)
    with engine.begin():
        pass
    from app.db.seed import seed_db as _seed
    _seed(engine)
    from sqlalchemy.orm import Session
    s = Session(engine)
    yield s
    s.rollback()
    s.close()
    engine.dispose()


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------- 计数一致性

def test_seed_counts_match_definitions(session):
    expect_pages = len(SEED_PAGES)
    expect_elements = sum(len(p[3]) for p in SEED_PAGES)
    expect_cases = sum(
        len(cases)
        for _, _, page_groups in SEED_MODULES
        for _, cases in page_groups
    )
    expect_steps = sum(
        len(steps)
        for _, _, page_groups in SEED_MODULES
        for _, cases in page_groups
        for _, _, _, _, _, steps in cases
    )
    expect_modules = len(SEED_MODULES)

    assert _count(session, TestModule) == expect_modules
    assert _count(session, Page) == expect_pages
    assert _count(session, PageElement) == expect_elements
    assert _count(session, TestCase) == expect_cases
    assert _count(session, TestStep) == expect_steps


def test_seed_idempotent_second_run_skipped(tmp_path):
    engine = create_app_engine(tmp_path / "seed2.db")
    init_db(engine)
    first = seed_db(engine)
    assert first["seeded"] == 1

    second = seed_db(engine)
    assert second["seeded"] == 0  # 幂等：已有数据跳过

    from sqlalchemy.orm import Session
    with Session(engine) as s:
        assert _count(s, TestModule) == len(SEED_MODULES)
        assert _count(s, TestCase) == sum(
            len(cases) for _, _, pg in SEED_MODULES for _, cases in pg
        )
    engine.dispose()


# ---------------------------------------------------------------- 软删除/内置标识

def test_seed_all_builtin_and_not_deleted(session):
    cases = session.scalars(select(TestCase)).all()
    assert len(cases) > 0
    assert all(c.is_builtin == 1 for c in cases)
    assert all(c.is_deleted == 0 for c in cases)
    assert all(m.is_deleted == 0 for m in session.scalars(select(TestModule)))
    assert all(p.is_deleted == 0 for p in session.scalars(select(Page)))


# ---------------------------------------------------------------- 确认项 1：用例绑定主页面

def test_seed_cases_bind_valid_page(session):
    cases = session.scalars(select(TestCase)).all()
    assert cases
    for case in cases:
        assert case.page_id
        page = session.get(Page, case.page_id)
        assert page is not None, f"用例 {case.case_code} 页面缺失"
        assert page.page_url.startswith("https://")


def test_seed_cases_bind_valid_module(session):
    for case in session.scalars(select(TestCase)).all():
        assert session.get(TestModule, case.module_id) is not None


# ---------------------------------------------------------------- 步骤映射正确性

def test_seed_step_commands_and_bindings(session):
    steps = session.scalars(select(TestStep)).all()
    assert steps
    legal = {"GOTO_URL", "INPUT_TEXT", "CLICK_ELEMENT", "ASSERT_ELEMENT_VISIBLE"}
    for step in steps:
        assert step.command_type in legal
        assert step.step_order >= 1
        assert step.remark  # LDM 2.6：备注必填
        if step.command_type == "GOTO_URL":
            assert step.element_id is None
            assert step.target_override.startswith("https://")
        elif step.target_override:
            # 文本型定位（XPATH）走 target_override，元素未入库
            assert step.element_id is None
        else:
            # CSS 定位步骤必须关联已入库元素
            assert step.element_id is not None
            assert session.get(PageElement, step.element_id) is not None


def test_seed_password_step_marked_secret(session):
    """密码输入步骤（#userPwd）is_secret=1；可见性断言步骤不受影响。"""
    stmt = (
        select(TestStep)
        .join(PageElement, TestStep.element_id == PageElement.element_id)
        .where(PageElement.locator_value == "#userPwd")
    )
    pwd_steps = session.scalars(stmt).all()
    assert pwd_steps

    input_steps = [s for s in pwd_steps if s.command_type == "INPUT_TEXT"]
    assert input_steps
    assert all(s.is_secret == 1 for s in input_steps)
    assert all(s.param_value for s in input_steps)  # 输入值非空

    # 断言类步骤（非参数）保持 is_secret=0
    assert_steps = [s for s in pwd_steps if s.command_type == "ASSERT_ELEMENT_VISIBLE"]
    assert all(s.is_secret == 0 for s in assert_steps)


def test_seed_step_orders_continuous_per_case(session):
    for case in session.scalars(select(TestCase)).all():
        orders = [s.step_order for s in case.steps]
        assert orders == list(range(1, len(orders) + 1))


def test_dependent_cases_include_login_steps(session):
    """006–023 依赖登录态：goto 之后自带登录步骤（设备登录态不跨 goto 保留）。"""
    cases = session.scalars(
        select(TestCase).where(TestCase.case_code >= "006")
    ).all()
    assert cases
    for case in cases:
        commands = [s.command_type for s in case.steps]
        assert commands[:4] == [
            "GOTO_URL", "INPUT_TEXT", "INPUT_TEXT", "CLICK_ELEMENT",
        ], case.case_code
        assert case.steps[1].param_value == "admin"
        assert case.steps[2].is_secret == 1
        assert case.steps[3].element_id is not None  # 登录按钮已入库


# ---------------------------------------------------------------- 确认项 6：接口表为空

def test_seed_interface_table_empty(session):
    assert _count(session, PageInterface) == 0
    login_page = session.scalar(
        select(Page).where(Page.page_name == "登录页")
    )
    assert interface_repo.count_by_page(session, login_page.page_id) == 0


# ---------------------------------------------------------------- 用例编号唯一

def test_seed_case_codes_unique_and_sorted(session):
    codes = [c.case_code for c in session.scalars(
        select(TestCase).order_by(TestCase.case_code)
    ).all()]
    assert len(codes) == len(set(codes))  # uq_case_code 双保险
    assert codes == sorted(codes)
