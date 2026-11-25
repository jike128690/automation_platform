"""数据库层：引擎 / 会话 / ORM 模型 / 迁移 / 仓储 / 服务。

公共入口约定：
- init_db(engine)：建库/升级（幂等，启动期调用一次）；
- current_version(engine)：当前 Schema 版本（诊断用）。
"""
from app.db.engine import DB_PATH, create_app_engine, engine, SessionLocal, DbSession
from app.db.migration import current_version, init_db
from app.db import soft_delete  # noqa: F401  导入即注册软删除全局过滤（T10.4）

__all__ = [
    "DB_PATH", "create_app_engine", "engine", "SessionLocal", "DbSession",
    "init_db", "current_version",
]
