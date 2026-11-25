"""v001：静态资产域 6 表建表脚本（T10.1）。

建表 DDL 与 LDM 第 2/3 节逐字段对齐；表内 CHECK 约束与 ORM asset.py 一致。

设计说明：
- DDL 手写而非 metadata.create_all()：
  1) 部分唯一索引（WHERE is_deleted=0）必须显式 CREATE UNIQUE INDEX；
  2) 迁移脚本即"版本化 Schema 快照"，冻结于脚本内，符合"升级脚本只增不改"原则，
     后续 ORM 调整须以新版本脚本（v002+）增量变更；
- 建表语句全部 IF NOT EXISTS：保证脚本在已有旧库（阶段一遗留空库）上重放安全；
- tb_test_step 无软删除列（物理删除，随用例 CASCADE 级联清理）。
"""
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.schema import Index as SchemaIndex

from app.db.models import (
    Page, PageElement, PageInterface, TestCase, TestModule, TestStep,
)

VERSION = 1

# 建表顺序按外键依赖：module/page → element/interface → case → step
_TABLES = [TestModule, Page, PageElement, PageInterface, TestCase, TestStep]

# SQLite 部分唯一索引（LDM 第 3 节）：软删除记录不参与唯一性校验。
# unique=True 由 CreateIndex 编译为 UNIQUE 关键字；WHERE 子句经
# sqlite_where 生成（必须显式传 unique=True，否则退化为普通索引）。
_PARTIAL_UNIQUE_INDEXES = [
    SchemaIndex(
        "uq_module_code", TestModule.__table__.c.module_code,
        unique=True,
        sqlite_where=TestModule.__table__.c.is_deleted == 0,
    ),
    SchemaIndex(
        "uq_case_code", TestCase.__table__.c.case_code,
        unique=True,
        sqlite_where=TestCase.__table__.c.is_deleted == 0,
    ),
    SchemaIndex(
        "uq_page_interface",
        PageInterface.__table__.c.page_id,
        PageInterface.__table__.c.method,
        PageInterface.__table__.c.interface_url,
        unique=True,
        sqlite_where=PageInterface.__table__.c.is_deleted == 0,
    ),
    SchemaIndex(
        "uq_case_step_order",
        TestStep.__table__.c.case_id,
        TestStep.__table__.c.step_order,
        unique=True,
    ),
]


def _to_if_not_exists(ddl: str) -> str:
    """CREATE TABLE → CREATE TABLE IF NOT EXISTS（老库重放安全）。"""
    assert ddl.startswith("CREATE TABLE "), ddl[:40]
    return ddl.replace(
        "CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1,
    )


def upgrade(conn) -> None:
    """在给定 sqlite3 连接上执行建表（同一事务，失败整体回滚）。"""
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    dialect = sqlite_dialect.dialect()

    for table_cls in _TABLES:
        table = table_cls.__table__
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        conn.execute(_to_if_not_exists(ddl))

        # 表内普通索引（ORM Index(...) 定义）
        for index in table.indexes:
            if any(index.name == pu.name for pu in _PARTIAL_UNIQUE_INDEXES):
                continue
            idx_ddl = str(CreateIndex(index).compile(dialect=dialect)).strip()
            idx_ddl = idx_ddl.replace(
                "CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1,
            )
            conn.execute(idx_ddl)

    # 部分唯一索引 + 完整唯一索引（uq_case_step_order）
    for index in _PARTIAL_UNIQUE_INDEXES:
        stmt = str(CreateIndex(index).compile(dialect=dialect)).strip()
        # CreateIndex 已含 UNIQUE/WHERE；仅补 IF NOT EXISTS
        if stmt.startswith("CREATE UNIQUE INDEX "):
            stmt = stmt.replace(
                "CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1,
            )
        elif stmt.startswith("CREATE INDEX "):
            stmt = stmt.replace(
                "CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1,
            )
        conn.execute(stmt)
