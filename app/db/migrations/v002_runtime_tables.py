# -*- coding: utf-8 -*-
r"""v002：动态执行域 3 表建表脚本（T11.1）。

升级脚本只增不改（《数据库开发.md》第 8 节风险表）——v001 已在既有客户端库
（data/automation.db）记录校验和，故本脚本自包含 DDL 逻辑，不回改 v001。

表创建顺序按外键依赖（tb_test_case 由 v001 创建）：
    tb_execution_batch → tb_batch_case_result → tb_execution_log

DDL 由 ORM metadata（runtime.py）编译生成并统一 IF NOT EXISTS，
与 LDM 2.7–2.9 / 第 3 节对齐：
- 级联：result/log → batch CASCADE；result → case RESTRICT；log → result CASCADE；
- 唯一：uq_batch_no、uq_batch_case(batch_id, case_id)；
- 索引：idx_result_case（按用例查历史，T11.5）、
        idx_log_batch_result（批次日志流，计划 4.6）。
"""
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.models import BatchCaseResult, ExecutionBatch, ExecutionLog

VERSION = 2

# 建表顺序按外键依赖
_TABLES = [ExecutionBatch, BatchCaseResult, ExecutionLog]


def _to_if_not_exists(ddl: str) -> str:
    """CREATE TABLE → CREATE TABLE IF NOT EXISTS（重放安全）。"""
    assert ddl.startswith("CREATE TABLE "), ddl[:40]
    return ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)


def _index_ddl(index) -> str:
    """编译索引 DDL 并补 IF NOT EXISTS（保留 UNIQUE/WHERE 子句）。"""
    ddl = str(CreateIndex(index).compile(dialect=sqlite_dialect.dialect())).strip()
    if ddl.startswith("CREATE UNIQUE INDEX "):
        return ddl.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
    return ddl.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)


def upgrade(conn) -> None:
    """在给定 sqlite3 连接上建表与索引（同一事务，失败整体回滚）。"""
    dialect = sqlite_dialect.dialect()

    for table_cls in _TABLES:
        table = table_cls.__table__
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        conn.execute(_to_if_not_exists(ddl))

        # 表级索引（含 uq_batch_no / uq_batch_case 唯一索引）
        for index in table.indexes:
            conn.execute(_index_ddl(index))
