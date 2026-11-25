# -*- coding: utf-8 -*-
"""软删除统一过滤与 is_builtin 标识单测（T10.4）。

验收标准（《数据库开发.md》WBS T10.4 / LDM 确认项 2）：
- 删除某用例后树不显示（Session 全局过滤）；
- 记录物理保留，历史仍可通过外键 JOIN（原生 SQL 验证 —— 动态执行域
  tb_batch_case_result 于 T11.1 建表，此处以原生 JOIN 模拟历史报表语义）；
- is_builtin=1 标记种子数据；非种子插入默认 0。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.engine import create_app_engine
from app.db.migration import init_db
from app.db.models import (
    Page, PageElement, PageInterface, TestCase, TestModule, TestStep,
)
from app.db.repositories.case_repo import load_tree, soft_delete_case
from app.db.seed import seed_db


@pytest.fixture()
def db(tmp_path):
    engine = create_app_engine(tmp_path / "soft_del.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------- 全局过滤

def test_global_filter_hides_soft_deleted_rows_across_all_tables(db):
    """5 张软删除表：任一记录置 is_deleted=1 后，ORM 实体查询自动排除。"""
    with Session(db) as s:
        module = s.query(TestModule).first()
        page = s.query(Page).first()
        element = s.query(PageElement).first()
        case = s.query(TestCase).first()

        module.is_deleted = 1
        page.is_deleted = 1
        element.is_deleted = 1
        case.is_deleted = 1
        s.commit()

        # 重建会话（绕过 identity map 缓存，验证查询层过滤）
        s2 = Session(db)
        assert s2.query(TestModule).count() == 3      # 4 - 1
        assert s2.query(Page).count() == 4            # 5 - 1
        assert s2.query(PageElement).count() == 44    # 45 - 1（登录6+主框架2+预览37）
        assert s2.query(TestCase).count() == 22       # 23 - 1
        # 接口表无数据，仅验证查询可执行（种子阶段 0 条）
        assert s2.query(PageInterface).count() == 0
        s2.close()


def test_soft_deleted_case_hidden_from_tree(db):
    """验收：删除某用例后树不显示。"""
    with Session(db) as s:
        case_pk = s.execute(
            text("SELECT case_id FROM tb_test_case WHERE case_code = '001'")
        ).scalar_one()
        assert soft_delete_case(s, case_pk) is True
        s.commit()

    tree = load_tree(db)
    codes = [c.case_id for m in tree for c in m.cases]
    assert "001" not in codes
    assert len(codes) == 22
    # 所属模块仍显示，但用例数减一（M01: 5 条 → 4 条）
    m01 = next(m for m in tree if m.module_id == "M01")
    assert len(m01.cases) == 4


def test_soft_deleted_case_row_still_joinable_for_history(db):
    """验收：历史仍可 JOIN —— 物理行保留，原生 SQL JOIN 可取最新用例名。

    模拟动态执行域历史报表语义（tb_batch_case_result.case_id 外键 JOIN
    tb_test_case 实时获取名称，LDM 确认项 2；执行域 T11.1 建表后补集成用例）。
    """
    with Session(db) as s:
        case_pk = s.execute(
            text("SELECT case_id FROM tb_test_case WHERE case_code = '002'")
        ).scalar_one()
        soft_delete_case(s, case_pk)
        s.commit()

    # 原生 SQL（绕过 ORM 过滤）：行仍在且 is_deleted=1
    with Session(db) as s:
        row = s.execute(
            text(
                "SELECT c.case_code, c.case_name, c.is_deleted "
                "FROM tb_test_case c WHERE c.case_code = '002'"
            )
        ).one()
        assert row[0] == "002"
        assert row[2] == 1
        # 模拟历史 JOIN：历史结果表按 case_id 关联后仍能取到用例名
        joined = s.execute(
            text(
                "SELECT r.fake_ref, c.case_name FROM tb_test_case c "
                "JOIN (SELECT :pk AS fake_ref) r ON r.fake_ref = c.case_id"
            ),
            {"pk": case_pk},
        ).one()
        assert joined[1] == "错误密码登录失败测试"


# ---------------------------------------------------------------- 删除入口

def test_soft_delete_case_idempotent_and_missing_pk(db):
    with Session(db) as s:
        case_pk = s.execute(
            text("SELECT case_id FROM tb_test_case WHERE case_code = '003'")
        ).scalar_one()

        assert soft_delete_case(s, case_pk) is True
        assert soft_delete_case(s, case_pk) is False   # 已删除 → 幂等 False
        assert soft_delete_case(s, "no-such-uuid") is False  # 主键不存在
        s.commit()

    codes = [c.case_id for m in load_tree(db) for c in m.cases]
    assert "003" not in codes


def test_soft_deleted_case_keeps_steps_rows(db):
    """步骤无软删除列：用例删除后步骤行保留（历史追溯/恢复依据）。"""
    with Session(db) as s:
        case_pk = s.execute(
            text("SELECT case_id FROM tb_test_case WHERE case_code = '001'")
        ).scalar_one()
        soft_delete_case(s, case_pk)
        s.commit()

        remain = s.execute(
            text("SELECT COUNT(*) FROM tb_test_step WHERE case_id = :pk"),
            {"pk": case_pk},
        ).scalar_one()
        assert remain == 5  # 001 用例的 5 个步骤未物理删除


# ---------------------------------------------------------------- is_builtin

def test_seed_cases_marked_builtin(db):
    with Session(db) as s:
        flags = s.execute(
            text("SELECT DISTINCT is_builtin FROM tb_test_case")
        ).scalars().all()
        assert flags == [1]  # 种子数据全部 is_builtin=1


def test_non_seed_case_defaults_to_not_builtin(db, tmp_path):
    """非种子来源（模拟用户导入）默认 is_builtin=0。"""
    engine2 = create_app_engine(tmp_path / "plain.db")
    init_db(engine2)
    seed_db(engine2)
    try:
        with Session(engine2) as s:
            page = s.query(Page).first()
            module = s.query(TestModule).first()
            user_case = TestCase(
                module_id=module.module_id,
                page_id=page.page_id,
                case_code="900",
                case_name="用户导入用例",
            )
            s.add(user_case)
            s.commit()
            assert user_case.is_builtin == 0  # ORM 默认值
            assert user_case.default_checked == 1
    finally:
        engine2.dispose()
