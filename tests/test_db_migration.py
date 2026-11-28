"""迁移机制单测（T9.3）：幂等重放、版本记录、升级重放、校验和防篡改。"""
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.engine import create_app_engine
from app.db.migration import (
    MigrationScript, applied_count, current_version, init_db, load_scripts,
)
from app.db.migrations.v001_static_asset import VERSION as V001_VERSION


@pytest.fixture()
def engine(tmp_path):
    eng = create_app_engine(tmp_path / "mig.db")
    yield eng
    eng.dispose()


def _tables(engine) -> list[str]:
    with engine.connect() as c:
        rows = c.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------- 脚本加载

def test_load_scripts_sorted_and_validated():
    scripts = load_scripts()
    assert [s.version for s in scripts] == sorted(s.version for s in scripts)
    assert len(scripts) >= 1
    v1 = next(s for s in scripts if s.version == V001_VERSION)
    assert v1.name == "static_asset"
    assert v1.script_name == "v001_static_asset.py"
    assert len(v1.checksum) == 64  # SHA-256 hex


# ---------------------------------------------------------------- 建库与幂等

def test_init_db_creates_version_table_and_runs_scripts(engine):
    applied = init_db(engine)
    assert V001_VERSION in applied
    assert current_version(engine) == max(s.version for s in load_scripts())
    assert applied_count(engine) == len(load_scripts())
    assert "tb_schema_migration" in _tables(engine)


def test_init_db_idempotent_rerun_noop(engine):
    init_db(engine)
    applied_again = init_db(engine)
    assert applied_again == []            # 幂等：无脚本重复执行
    assert applied_count(engine) == len(load_scripts())  # 版本记录不重复


def test_version_table_records_script_name_and_checksum(engine):
    init_db(engine)
    with engine.connect() as c:
        row = c.execute(
            text("SELECT version, script_name, checksum FROM tb_schema_migration "
                 "WHERE version = :v"),
            {"v": V001_VERSION},
        ).fetchone()
    assert row is not None
    version, script_name, checksum = row
    assert version == V001_VERSION
    assert script_name == "v001_static_asset.py"
    assert len(checksum) == 64


# ---------------------------------------------------------------- 升级重放（新脚本自动执行）

def test_upgrade_replay_applies_new_script_only(engine, monkeypatch, tmp_path):
    init_db(engine)  # 已应用真实注册表全部脚本

    # 构造假脚本（版本号顺延）：用独立模块对象承载，避免 import 缓存污染真实包
    scripts = load_scripts()
    real_versions = [s.version for s in scripts]
    v1 = next(s for s in scripts if s.version == V001_VERSION)

    class _FakeNext:
        def upgrade(self, conn) -> None:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tb_tmp_v002 (id INTEGER PRIMARY KEY)"
            )

    fake_next = MigrationScript(
        version=max(real_versions) + 1, name="fake",
        checksum="a" * 64, upgrade=_FakeNext().upgrade,
    )
    assert fake_next.script_name == f"v{fake_next.version:03d}_fake.py"

    monkeypatch.setattr(
        "app.db.migration.load_scripts",
        lambda: scripts + [fake_next],
    )

    applied = init_db(engine)
    assert applied == [fake_next.version]
    assert "tb_tmp_v002" in _tables(engine)
    assert current_version(engine) == fake_next.version
    assert applied_count(engine) == len(scripts) + 1

    # 再次重放（保持 fake 脚本）→ 幂等：全部已记录，无新执行
    assert init_db(engine) == []


# ---------------------------------------------------------------- v004 登录前置步骤

def test_v004_adds_login_steps_to_existing_cases(engine):
    """存量库升级：006 用例由 [goto, click, assert] 补成 [goto, 登录3步, click, assert]。"""
    from app.db.migrations import v004_login_prereq_steps as v4
    from app.db.seed import seed_db

    init_db(engine)
    seed_db(engine)

    with engine.connect() as connection:
        raw = connection.connection
        case_id = raw.execute(
            "SELECT case_id FROM tb_test_case WHERE case_code = '006'"
        ).fetchone()[0]
        # 还原为 v004 之前的步骤定义（goto + 点击预览 + 断言）
        raw.execute("DELETE FROM tb_test_step WHERE case_id = ?", (case_id,))
        raw.executemany(
            "INSERT INTO tb_test_step (step_id, case_id, step_order, "
            "command_type, element_id, target_override, param_value, is_secret, "
            "timeout_sec, remark, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, ?, NULL, 0, NULL, ?, ?, ?)",
            [
                (f"old-1-{case_id}", case_id, 1, "GOTO_URL",
                 "https://192.168.3.102/", "打开主框架", "2026-01-01T00:00:00.000",
                 "2026-01-01T00:00:00.000"),
                (f"old-2-{case_id}", case_id, 2, "CLICK_ELEMENT",
                 "//a[normalize-space()='预览']", "点击导航 [预览]",
                 "2026-01-01T00:00:00.000", "2026-01-01T00:00:00.000"),
                (f"old-3-{case_id}", case_id, 3, "ASSERT_ELEMENT_VISIBLE",
                 "#playbackarea", "断言播放画面区域可见",
                 "2026-01-01T00:00:00.000", "2026-01-01T00:00:00.000"),
            ],
        )
        raw.commit()

        v4.upgrade(raw)
        rows = raw.execute(
            "SELECT step_order, command_type, is_secret FROM tb_test_step "
            "WHERE case_id = ? ORDER BY step_order",
            (case_id,),
        ).fetchall()
        assert [r[0] for r in rows] == [1, 2, 3, 4, 5, 6]
        assert [r[1] for r in rows] == [
            "GOTO_URL", "INPUT_TEXT", "INPUT_TEXT", "CLICK_ELEMENT",
            "CLICK_ELEMENT", "ASSERT_ELEMENT_VISIBLE",
        ]
        assert rows[2][2] == 1  # 密码步骤 is_secret=1

        # 幂等：再次执行不重复插入
        v4.upgrade(raw)
        count = raw.execute(
            "SELECT COUNT(*) FROM tb_test_step WHERE case_id = ?", (case_id,)
        ).fetchone()[0]
        assert count == 6
        raw.rollback()


# ---------------------------------------------------------------- v005 站点地址

def test_v005_adds_site_url_column_idempotent(engine):
    """存量库补 site_url 列；重复执行不报错。"""
    from app.config import DEFAULT_SITE_URL
    from app.db.migrations import v005_site_url as v5

    with engine.connect() as connection:
        raw = connection.connection
        raw.execute("CREATE TABLE tb_system_config (config_id TEXT(36) PRIMARY KEY)")
        raw.commit()
        assert "site_url" not in {
            r[1] for r in raw.execute("PRAGMA table_info(tb_system_config)")
        }

        v5.upgrade(raw)
        columns = {r[1] for r in raw.execute("PRAGMA table_info(tb_system_config)")}
        assert "site_url" in columns
        default = raw.execute(
            "SELECT dflt_value FROM pragma_table_info('tb_system_config') "
            "WHERE name = 'site_url'"
        ).fetchone()[0]
        assert DEFAULT_SITE_URL in default

        v5.upgrade(raw)  # 幂等：不重复 ALTER
        raw.rollback()


# ---------------------------------------------------------------- 防篡改

def test_tampered_executed_script_rejected(engine, monkeypatch):
    init_db(engine)

    scripts = load_scripts()
    v1 = next(s for s in scripts if s.version == V001_VERSION)
    tampered = type(v1)(
        version=v1.version, name=v1.name,
        checksum="0" * 64,  # 与已记录的不一致
        upgrade=v1.upgrade,
    )
    monkeypatch.setattr(
        "app.db.migration.load_scripts", lambda: [tampered, *scripts[1:]]
    )

    with pytest.raises(RuntimeError, match="篡改"):
        init_db(engine)


def test_failed_script_rolls_back_and_not_recorded(engine, monkeypatch):
    scripts = load_scripts()
    v1 = next(s for s in scripts if s.version == V001_VERSION)

    def _boom(conn):
        raise ValueError("boom")

    broken = type(v1)(
        version=v1.version, name=v1.name, checksum=v1.checksum, upgrade=_boom,
    )
    monkeypatch.setattr("app.db.migration.load_scripts", lambda: [broken])

    with pytest.raises(RuntimeError, match="执行失败"):
        init_db(engine)

    # 失败脚本未记录版本；版本表已存在（建表步骤先行成功）
    assert applied_count(engine) == 0
    assert "tb_test_module" not in _tables(engine)  # DDL 已回滚，未留半成品
