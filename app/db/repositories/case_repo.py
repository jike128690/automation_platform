# -*- coding: utf-8 -*-
"""用例树仓储（T10.3）+ 用例软删除入口（T10.4）：DB 静态资产 → 阶段一内存 DTO。

兼容性保证（《数据库开发.md》4.5）：返回 app/data/models.py 现有
TestModule/TestCase/TestStep 结构，首页 CaseTree 与执行引擎零改动消费 DB 数据。

映射规则（LDM → DTO，与 4.5 种子映射互逆）：
- DTO.module_id   ← tb_test_module.module_code（"M01"）；
- DTO.case_id     ← tb_test_case.case_code（"001"）；
- DTO.case_title  ← "[{case_code}] {case_name}"（还原展示前缀）；
- DTO.action_type ← command_type 反向映射（GOTO_URL→goto / INPUT_TEXT→fill /
  CLICK_ELEMENT→click / ASSERT_ELEMENT_VISIBLE→assert_visible）；
- DTO.selector    ← tb_page_element.locator_value（已入库元素），
  未入库元素（文本型定位/网址）回退 target_override；
- DTO.value       ← param_value（NULL → ""）。

软删除约定（T10.4 统一封装）：
- 查询不手写 is_deleted 条件 —— soft_delete.py 在 Session 层全局注入过滤；
- 需要触达已删除记录（历史报表 JOIN、审计）必须走原生 SQL；
- soft_delete_case() 为唯一的用例删除入口（置 is_deleted=1，物理行保留，
  保证 tb_batch_case_result 历史仍可 JOIN 最新用例名 —— LDM 确认项 2）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import (
    TestCase as CaseDTO,
    TestModule as ModuleDTO,
    TestStep as StepDTO,
)
from app.db.engine import engine as default_engine
from app.db.models import PageElement, TestCase, TestModule, TestStep

# LDM command_type → 阶段一 action_type（executor._run_step 消费的短名）
_COMMAND_TO_ACTION = {
    "GOTO_URL": "goto",
    "INPUT_TEXT": "fill",
    "CLICK_ELEMENT": "click",
    "ASSERT_ELEMENT_VISIBLE": "assert_visible",
}


def load_tree(engine=None) -> list[ModuleDTO]:
    """加载模块→用例→步骤树（软删除由 Session 全局过滤，按 sort_order 排序）。

    Args:
        engine: SQLAlchemy 引擎；缺省用全局默认引擎（生产：data/automation.db）。
    """
    eng = engine if engine is not None else default_engine
    with Session(eng) as session:
        modules = session.scalars(
            select(TestModule).order_by(TestModule.sort_order)
        ).all()

        cases = session.scalars(
            select(TestCase).order_by(TestCase.module_id, TestCase.sort_order)
        ).all()

        steps = session.scalars(
            select(TestStep).order_by(TestStep.case_id, TestStep.step_order)
        ).all()

        # 步骤定位解析：已入库元素取 locator_value，其余回退 target_override
        element_ids = {s.element_id for s in steps if s.element_id}
        locators: dict[str, str] = {}
        if element_ids:
            rows = session.execute(
                select(PageElement.element_id, PageElement.locator_value)
                .where(PageElement.element_id.in_(element_ids))
            ).all()
            locators = {eid: val for eid, val in rows}

        # 内存装配：步骤按 case 分组 → 用例按 module 分组
        steps_by_case: dict[str, list[StepDTO]] = {}
        for step in steps:
            selector = (
                locators.get(step.element_id) or step.target_override
                if step.element_id else step.target_override
            ) or ""
            steps_by_case.setdefault(step.case_id, []).append(StepDTO(
                step_no=step.step_order,
                action_type=_COMMAND_TO_ACTION[step.command_type],
                selector=selector,
                value=step.param_value or "",
                remark=step.remark,
            ))

        cases_by_module: dict[str, list[CaseDTO]] = {}
        for case in cases:
            cases_by_module.setdefault(case.module_id, []).append(CaseDTO(
                case_id=case.case_code,
                case_title=f"[{case.case_code}] {case.case_name}",
                short_name=case.short_name or "",
                default_checked=bool(case.default_checked),
                steps=steps_by_case.get(case.case_id, []),
            ))

        return [
            ModuleDTO(
                module_id=module.module_code,
                module_name=module.module_name,
                cases=cases_by_module.get(module.module_id, []),
            )
            for module in modules
        ]


def soft_delete_case(session: Session, case_pk: str) -> bool:
    """按 DB 主键（UUID）软删除用例：置 is_deleted=1，物理行保留。

    - 幂等：用例不存在或已删除返回 False，不重复操作；
    - 删除后 load_tree() 不再展示（Session 全局过滤），历史报表仍可
      通过外键 JOIN 最新 case_name（LDM 确认项 2）；
    - 步骤随用例保留（无软删除列），供历史追溯与未来恢复。
    """
    case = session.get(TestCase, case_pk)
    if case is None or case.is_deleted == 1:
        return False
    case.is_deleted = 1
    session.flush()
    return True
