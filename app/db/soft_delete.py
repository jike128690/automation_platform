# -*- coding: utf-8 -*-
"""软删除全局过滤（T10.4，LDM 第 5 节策略 1 / 数据库开发计划 4.6）。

机制：SQLAlchemy 官方 with_loader_criteria —— 在 Session 层对全部实体
SELECT 自动追加 `is_deleted = 0`（含 relationship 懒加载与别名）。

设计意图（计划 4.6 "仓储层统一封装，防止漏过滤"）：
- 业务代码/仓储禁止再手写 is_deleted 条件（单一入口，防幽灵数据）；
- 需要查询已删除记录的场景（如历史报表 JOIN 软删用例、媒体清理扫描）
  必须走原生 SQL（text()）或 Core 查询 —— 钩子只作用于 ORM 实体加载；
- 本模块经 app/db/__init__.py 导入即注册，覆盖 SessionLocal 与测试直建的
  Session（事件挂载在 sqlalchemy.orm.Session 基类）。
"""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.db.base import SoftDeleteMixin


@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(execute_state):
    """全部 ORM 实体查询自动排除软删除记录。"""
    if not execute_state.is_select:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            SoftDeleteMixin,
            lambda cls: cls.is_deleted == 0,
            include_aliases=True,
        )
    )
