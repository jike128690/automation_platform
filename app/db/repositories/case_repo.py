# -*- coding: utf-8 -*-
"""用例树仓储（T10.3）：DB 静态资产 → 阶段一内存 DTO。

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

查询约定（T10.4 软删除统一过滤）：
- 模块/用例固定 WHERE is_deleted=0；步骤随未删除用例加载；
- 启动期一次性三条查询 + 内存装配（低配机约束：禁止 UI 线程大结果集遍历）。
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
    """加载未删除的模块→用例→步骤树（按 sort_order / step_order 排序）。

    Args:
        engine: SQLAlchemy 引擎；缺省用全局默认引擎（生产：data/automation.db）。
    """
    eng = engine if engine is not None else default_engine
    with Session(eng) as session:
        modules = session.scalars(
            select(TestModule)
            .where(TestModule.is_deleted == 0)
            .order_by(TestModule.sort_order)
        ).all()

        cases = session.scalars(
            select(TestCase)
            .where(TestCase.is_deleted == 0)
            .order_by(TestCase.module_id, TestCase.sort_order)
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
