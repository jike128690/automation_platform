"""ORM 声明基类与公共列 mixin（LDM 第 2/5 节约定）。

- UUID 主键：应用层 uuid.uuid4() 生成（各表主键列名不同，如 module_id/page_id，
  由各模型显式定义并统一使用 gen_uuid 作默认工厂，不依赖数据库生成）；
- 时间：TEXT(23) ISO-8601（YYYY-MM-DD HH:MM:SS.SSS），应用层产出；
- 布尔：INTEGER 0/1；
- 软删除：is_deleted INTEGER NOT NULL DEFAULT 0，查询默认过滤（仓储层统一封装）。
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def gen_uuid() -> str:
    """应用层生成 36 位 UUIDv4 字符串（LDM：不依赖数据库生成）。"""
    return str(uuid4())


def now_iso() -> str:
    """当前本地时间 ISO-8601 字符串，精确到毫秒（与 TEXT(23) 对应）。"""
    return datetime.now().isoformat(timespec="milliseconds")


class Base(DeclarativeBase):
    """全项目唯一声明基类；子类经 app.db.models 包集中注册到 Base.metadata。"""


class TimestampMixin:
    """审计时间戳公共列（LDM 第 5 节：所有核心表保留 created_at/updated_at）。"""

    created_at: Mapped[str] = mapped_column(
        Text(23), nullable=False, default=now_iso,
    )
    updated_at: Mapped[str] = mapped_column(
        Text(23), nullable=False, default=now_iso, onupdate=now_iso,
    )


class SoftDeleteMixin:
    """软删除公共列（仅静态资产表启用，LDM 第 5 节策略 1）。"""

    is_deleted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
