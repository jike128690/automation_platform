"""tb_schema_migration 版本表与迁移机制（自研轻量方案，T9.3）。

职责：
1. 建库入口 init_db()：幂等建 tb_schema_migration → 按版本号升序重放未执行脚本；
2. 版本表记录 version / script_name / checksum / applied_at；
3. checksum 防篡改：已执行脚本的内容摘要被改动 → 拒绝启动（防止改历史脚本破坏数据）；
4. 升级重放：新脚本放入 migrations 包即自动按序执行，旧脚本不重复执行。

设计依据：
- 《数据库开发.md》4.1：迁移选型"alembic 或自研轻量"，本机为单文件 SQLite、
  DDL 数量少，采用自研机制（版本表与 alembic version_table 同构）；
- LDM 第 1 节表 11：tb_schema_migration 记录 Schema 版本升级脚本执行历史；
- LDM 第 5 节策略 4：SQLite WAL 并发模式由 engine 层保证，迁移复用同一 engine。

脚本契约（见 migrations/__init__.py 文档）：
- 每脚本 VERSION: int + upgrade(conn) -> None；
- 脚本在单个事务内执行 DDL，成功才记录版本，失败整体回滚不留半成品库。
"""
import hashlib
import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db import migrations as migrations_pkg

# ---------------------------------------------------------------- 常量

VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS tb_schema_migration (
    version     INTEGER PRIMARY KEY,          -- 脚本版本号（vNNN 的 NNN）
    script_name TEXT NOT NULL,                -- 脚本文件名（含 .py）
    checksum    TEXT(64) NOT NULL,            -- 脚本内容 SHA-256（防篡改）
    applied_at  TEXT(23) NOT NULL             -- 应用时间 ISO-8601 毫秒
)
"""


# ---------------------------------------------------------------- 脚本加载


@dataclass(frozen=True)
class MigrationScript:
    """单个迁移脚本的元数据与执行体。"""

    version: int
    name: str
    checksum: str
    upgrade: "callable"  # upgrade(conn: sqlite3.Connection) -> None

    @property
    def script_name(self) -> str:
        return f"v{self.version:03d}_{self.name}.py"


def _script_checksum(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def load_scripts() -> list[MigrationScript]:
    """扫描 migrations 包，返回按版本号升序的脚本列表。

    命名规范强制校验：文件名必须匹配 vNNN_<名称>.py，且与脚本内 VERSION 一致。
    """
    scripts: list[MigrationScript] = []
    seen_versions: dict[int, str] = {}

    for module_info in sorted(pkgutil.iter_modules(migrations_pkg.__path__),
                              key=lambda m: m.name):
        name = module_info.name
        if not (name.startswith("v") and name[1:4].isdigit() and len(name) > 4
                and name[4] == "_"):
            # __init__ 等非脚本模块直接跳过
            continue
        expected_version = int(name[1:4])

        module = importlib.import_module(f"app.db.migrations.{name}")
        source_path = Path(migrations_pkg.__file__).parent / f"{name}.py"
        source = source_path.read_text(encoding="utf-8")

        version = getattr(module, "VERSION", None)
        upgrade = getattr(module, "upgrade", None)
        if version is None or not callable(upgrade):
            raise RuntimeError(f"迁移脚本 {name} 缺少 VERSION 或 upgrade()")
        if version != expected_version:
            raise RuntimeError(
                f"迁移脚本 {name} 命名版本 v{expected_version:03d} 与内部 VERSION={version} 不一致"
            )
        if version in seen_versions:
            raise RuntimeError(
                f"迁移版本号重复：{version}（{seen_versions[version]} 与 {name}）"
            )
        seen_versions[version] = name

        scripts.append(MigrationScript(
            version=version,
            name=name[5:-3] if name.endswith(".py") else name[5:],
            checksum=_script_checksum(source),
            upgrade=upgrade,
        ))

    scripts.sort(key=lambda s: s.version)
    return scripts


# ---------------------------------------------------------------- 版本表读写


def _ensure_version_table(conn) -> None:
    """幂等建版本表（首次建库与升级重放共用）。"""
    conn.executescript(VERSION_TABLE_DDL)


def _applied_versions(conn) -> dict[int, tuple[str, str]]:
    """已执行脚本 {version: (script_name, checksum)}。"""
    rows = conn.execute(
        "SELECT version, script_name, checksum FROM tb_schema_migration"
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def _record_version(conn, script: MigrationScript, applied_at: str) -> None:
    conn.execute(
        "INSERT INTO tb_schema_migration (version, script_name, checksum, applied_at) "
        "VALUES (?, ?, ?, ?)",
        (script.version, script.script_name, script.checksum, applied_at),
    )


# ---------------------------------------------------------------- 迁移入口


def init_db(engine: Engine) -> list[int]:
    """建库/升级入口：幂等、可重复执行、带校验和防篡改。

    返回本次实际执行的脚本版本号列表（空列表 = 已是最新，无操作）。

    流程：
    1. 建版本表（IF NOT EXISTS 幂等）；
    2. 逐个核对已执行脚本的 checksum，不一致抛 RuntimeError（防篡改）；
    3. 按版本号升序执行未应用的脚本，每个脚本独立事务：
       成功 → 记录版本并提交；失败 → 回滚该脚本，抛出异常；
    4. 事务隔离由 sqlite3 的隐式事务保证（DDL 也受事务保护）。
    """
    from app.db.base import now_iso

    applied: list[int] = []

    with engine.connect() as connection:
        raw = connection.connection  # sqlite3 原生连接
        _ensure_version_table(raw)
        raw.commit()

        done = _applied_versions(raw)

        for script in load_scripts():
            if script.version in done:
                recorded_name, recorded_checksum = done[script.version]
                if recorded_checksum != script.checksum:
                    raise RuntimeError(
                        f"迁移脚本被篡改：{script.script_name} 的内容与已执行版本不一致，"
                        f"拒绝继续执行（升级脚本只增不改）"
                    )
                continue  # 已执行且一致 → 跳过（幂等关键路径）

            try:
                script.upgrade(raw)
            except Exception as exc:
                raw.rollback()
                raise RuntimeError(f"迁移脚本 v{script.version:03d} 执行失败: {exc}") from exc

            _record_version(raw, script, now_iso())
            raw.commit()
            applied.append(script.version)

    return applied


def current_version(engine: Engine) -> int | None:
    """当前库的 Schema 版本（无版本表/无记录返回 None，对应首次建库前）。"""
    with engine.connect() as connection:
        raw = connection.connection
        exists = raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='tb_schema_migration'"
        ).fetchone()
        if not exists:
            return None
        row = raw.execute(
            "SELECT MAX(version) FROM tb_schema_migration"
        ).fetchone()
        return row[0] if row else None


def applied_count(engine: Engine) -> int:
    """已执行脚本数（用于测试与诊断）。"""
    with engine.connect() as connection:
        raw = connection.connection
        try:
            return raw.execute("SELECT COUNT(*) FROM tb_schema_migration").fetchone()[0]
        except Exception:
            return 0
