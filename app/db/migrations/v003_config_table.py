# -*- coding: utf-8 -*-
r"""v003：全局配置域建表脚本（T12.1）。

升级脚本只增不改 —— v001/v002 已在既有客户端库记录校验和，
本脚本自包含 DDL 逻辑（DDL 由 ORM metadata 编译生成，IF NOT EXISTS）。

tb_system_config 无外键依赖；CHECK 约束与 models/config.py 一致（LDM 2.10）。
"""
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.schema import CreateTable

from app.db.models import SystemConfig

VERSION = 3

_TABLES = [SystemConfig]


def _to_if_not_exists(ddl: str) -> str:
    """CREATE TABLE → CREATE TABLE IF NOT EXISTS（重放安全）。"""
    assert ddl.startswith("CREATE TABLE "), ddl[:40]
    return ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)


def _index_ddl(index) -> str:
    """编译索引 DDL 并补 IF NOT EXISTS。"""
    from sqlalchemy.schema import CreateIndex
    ddl = str(CreateIndex(index).compile(dialect=sqlite_dialect.dialect())).strip()
    if ddl.startswith("CREATE UNIQUE INDEX "):
        return ddl.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
    return ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)


def upgrade(conn) -> None:
    """在给定 sqlite3 连接上建表（同一事务，失败整体回滚）。"""
    dialect = sqlite_dialect.dialect()
    for table_cls in _TABLES:
        table = table_cls.__table__
        conn.execute(_to_if_not_exists(
            str(CreateTable(table).compile(dialect=dialect)).strip()
        ))
        for index in table.indexes:
            conn.execute(_index_ddl(index))
