"""页面接口仓储（T10.1 验收点：仓储查询可按 page_id 检索接口资产）。

软删除过滤由 soft_delete.py 在 Session 层全局注入（T10.4 统一封装），
本仓储不再手写 is_deleted 条件。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PageInterface


def list_by_page(session: Session, page_id: str) -> list[PageInterface]:
    """按页面查全部有效接口（软删除由全局过滤排除）。"""
    stmt = (
        select(PageInterface)
        .where(PageInterface.page_id == page_id)
        .order_by(PageInterface.interface_name)
    )
    return list(session.scalars(stmt))


def count_by_page(session: Session, page_id: str) -> int:
    """按页面统计有效接口数（种子阶段应为 0）。"""
    stmt = select(PageInterface.interface_id).where(
        PageInterface.page_id == page_id
    )
    return len(list(session.scalars(stmt)))
