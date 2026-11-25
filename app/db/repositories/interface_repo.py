"""页面接口仓储（T10.1 验收点：仓储查询可按 page_id 检索接口资产）。

软删除过滤统一在本层封装（is_deleted=0），业务侧禁止裸拼查询。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PageInterface


def list_by_page(session: Session, page_id: str) -> list[PageInterface]:
    """按页面查全部有效接口（不含软删除记录）。"""
    stmt = (
        select(PageInterface)
        .where(
            PageInterface.page_id == page_id,
            PageInterface.is_deleted == 0,
        )
        .order_by(PageInterface.interface_name)
    )
    return list(session.scalars(stmt))


def count_by_page(session: Session, page_id: str) -> int:
    """按页面统计有效接口数（种子阶段应为 0）。"""
    stmt = (
        select(PageInterface.interface_id)
        .where(
            PageInterface.page_id == page_id,
            PageInterface.is_deleted == 0,
        )
    )
    return len(list(session.scalars(stmt)))
