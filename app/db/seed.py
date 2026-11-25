# -*- coding: utf-8 -*-
"""种子数据落库（T10.2）：真实业务数据（app/db/seed_data.py）→ 静态资产 5 表。

幂等策略（DB 为唯一事实源，数据库开发计划第 8 节）：
- 仅当 tb_test_module 为空时写入（首次建库初始化）；
- 模块表已有数据时跳过，返回 seeded=0，绝不覆盖/重复插入；
- 种子数据统一 is_builtin=1（用户后续导入/创建的用例为 0，T10.4 联动）。

落库映射（真实 Page Object → LDM）：
- seed_data.SEED_PAGES → tb_page + tb_page_element（CSS 定位器全量入库；
  文本型定位不入元素表，存步骤 target_override）；
- seed_data.SEED_MODULES → tb_test_module + tb_test_case + tb_test_step；
  步骤 element_id 关联已入库元素，GOTO_URL/文本型定位走 target_override；
- tb_page_interface 保持 0 条（Mock/真实站点均无 HTTP 接口资产，验收确认项 6）。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import (
    CommandType, LocatorType, Page, PageElement, TestCase, TestModule, TestStep,
)
from app.db.seed_data import SEED_MODULES, SEED_PAGES

# 命令缩写 → LDM command_type（数据库开发计划 4.5 映射规则）
_COMMAND_MAP = {
    "goto": CommandType.GOTO_URL,
    "fill": CommandType.INPUT_TEXT,
    "click": CommandType.CLICK_ELEMENT,
    "assert_visible": CommandType.ASSERT_ELEMENT_VISIBLE,
}


def seed_db(engine: Engine) -> dict[str, int]:
    """首次建库写入真实业务种子；模块表非空则跳过（幂等）。

    返回落库统计 {"seeded": 0/1, "modules": n, "pages": n, "elements": n,
                  "cases": n, "steps": n, "interfaces": 0}。
    """
    with Session(engine) as session:
        existing = session.scalar(select(func.count()).select_from(TestModule))
        if existing:
            return {"seeded": 0}

        counts = _insert_seed(session)
        session.commit()
        return {"seeded": 1, **counts}


def _insert_seed(session: Session) -> dict[str, int]:
    """按 页面→元素→模块→用例→步骤 顺序构建 ORM 对象树并插入。"""
    # 1) 页面 + 元素
    pages: dict[str, Page] = {}
    element_total = 0
    for page_name, page_url, remark, elements in SEED_PAGES:
        page = Page(page_name=page_name, page_url=page_url, remark=remark)
        for loc_type, loc_value, elem_name in elements:
            page.elements.append(PageElement(
                element_name=elem_name,
                locator_type=LocatorType(loc_type).value,
                locator_value=loc_value,
            ))
            element_total += 1
        session.add(page)
        pages[page_name] = page
    session.flush()  # 拿到 page_id / element_id 供外键关联

    # 元素名 → PageElement（全局名称唯一，见 seed_data 常量约定）
    elements_by_name: dict[str, PageElement] = {
        e.element_name: e
        for p in pages.values() for e in p.elements
    }

    # 2) 模块 + 用例 + 步骤
    module_total = case_total = step_total = 0
    for module_code, module_name, page_groups in SEED_MODULES:
        module = TestModule(
            module_code=module_code,
            module_name=module_name,
            sort_order=module_total,
        )
        session.add(module)

        case_sort = 0
        for page_name, cases in page_groups:
            page = pages[page_name]
            for (case_code, case_name, short_name, default_checked,
                 expected_summary, steps) in cases:
                case = TestCase(
                    module=module,
                    page=page,
                    case_code=case_code,
                    case_name=case_name,
                    short_name=short_name,
                    default_checked=default_checked,
                    is_builtin=1,
                    sort_order=case_sort,
                    expected_summary=expected_summary,
                )
                for order, (cmd, elem_name, override, value,
                            remark, secret, timeout) in enumerate(steps, 1):
                    command = _COMMAND_MAP[cmd].value
                    element = elements_by_name.get(elem_name) if elem_name else None
                    case.steps.append(TestStep(
                        step_order=order,
                        command_type=command,
                        element=element,                       # None → target_override 路径
                        target_override=override,
                        param_value=value or None,
                        is_secret=secret,
                        timeout_sec=timeout,
                        remark=remark,
                    ))
                    step_total += 1
                session.add(case)
                case_total += 1
                case_sort += 1
        module_total += 1

    session.flush()
    return {
        "modules": module_total,
        "pages": len(pages),
        "elements": element_total,
        "cases": case_total,
        "steps": step_total,
        "interfaces": 0,
    }
