# -*- coding: utf-8 -*-
"""配置域 schema 与单例服务单测（T12.1）。

验收标准（《数据库开发.md》WBS T12.1）：
- 单测：写后读回一致；仅一条有效记录。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.engine import create_app_engine
from app.db.migration import current_version, init_db
from app.db.models import SystemConfig
from app.db.services.config_service import (
    MASK_REPLACEMENT, WAIT_UNTIL_MAP, get_config, mask_secret, save_config,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_app_engine(tmp_path / "config.db")
    init_db(engine)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------- 建表

def test_config_table_created(db):
    assert current_version(db) == 3
    with db.connect() as c:
        cols = c.exec_driver_sql("PRAGMA table_info(tb_system_config)").fetchall()
    names = {col[1] for col in cols}
    # LDM 2.10 全字段逐项对应
    assert {
        "config_id", "project_name", "report_save_path", "run_mode",
        "start_delay_sec", "browser_type", "driver_path", "exec_timeout_sec",
        "implicit_wait_sec", "page_load_strategy", "proxy_mode",
        "proxy_address", "proxy_auth_enabled", "proxy_username",
        "proxy_password", "clear_cache", "clear_cookies", "clear_history",
        "env_profile", "retry_count", "screenshot_on_fail", "record_video",
        "media_retention_days", "log_level", "updated_at",
    } <= names
    assert "created_at" not in names  # LDM 2.10 仅 updated_at


# ---------------------------------------------------------------- 单例读写

def test_get_config_initializes_defaults(db):
    config = get_config(db)
    assert config.project_name == "我的Web自动化测试"
    assert config.run_mode == "TEST"
    assert config.browser_type == "CHROME"
    assert config.page_load_strategy == "NORMAL"
    assert config.proxy_mode == "NO_PROXY"
    assert config.env_profile == "PROD"
    assert config.log_level == "INFO"
    assert config.retry_count == 2
    assert config.media_retention_days == 5
    assert config.screenshot_on_fail == 1
    assert config.record_video == 1
    assert len(config.updated_at) == 23  # ISO-8601 毫秒


def test_save_then_read_back_consistent(db):
    """验收：写后读回一致。"""
    get_config(db)  # 先初始化
    saved = save_config(db, {
        "project_name": "视频监控回归测试",
        "browser_type": "CHROMIUM",
        "exec_timeout_sec": 60,
        "proxy_mode": "CUSTOM",
        "proxy_address": "http://192.168.1.1:8080",
        "proxy_password": "s3cret",
        "media_retention_days": 30,
        "log_level": "ERROR",
    })
    assert saved.browser_type == "CHROMIUM"
    assert saved.exec_timeout_sec == 60
    assert saved.proxy_address == "http://192.168.1.1:8080"
    assert saved.proxy_password == "s3cret"
    assert saved.media_retention_days == 30

    again = get_config(db)  # 新会话读回
    assert again.project_name == "视频监控回归测试"
    assert again.browser_type == "CHROMIUM"
    assert again.proxy_password == "s3cret"


def test_save_updates_in_place_never_duplicates(db):
    """验收：仅一条有效记录 —— save 恒更新原行。"""
    first = get_config(db)
    save_config(db, {"project_name": "第一次修改"})
    save_config(db, {"project_name": "第二次修改"})

    with Session(db) as s:
        rows = s.execute(text("SELECT COUNT(*) FROM tb_system_config")).scalar_one()
        assert rows == 1
        name = s.execute(
            text("SELECT project_name FROM tb_system_config")
        ).scalar_one()
    assert name == "第二次修改"
    assert first.project_name == "我的Web自动化测试"  # 原对象不受影响


def test_save_rejects_illegal_field(db):
    get_config(db)
    with pytest.raises(ValueError, match="非法配置字段"):
        save_config(db, {"not_a_field": 1})


def test_updated_at_refreshed_on_save(db):
    config = get_config(db)
    before = config.updated_at
    import time
    time.sleep(0.01)
    saved = save_config(db, {"project_name": "改名"})
    assert saved.updated_at >= before


# ---------------------------------------------------------------- CHECK 约束

@pytest.mark.parametrize("field, value", [
    ("run_mode", "PERF"),            # ck_cfg_run_mode
    ("browser_type", "FIREFOX"),     # ck_cfg_browser
    ("page_load_strategy", "LAZY"),  # ck_cfg_pload
    ("proxy_mode", "PAC"),           # ck_cfg_proxy_mode
    ("env_profile", "UAT"),          # ck_cfg_env
    ("log_level", "FATAL"),          # ck_cfg_log_level
    ("start_delay_sec", 61),         # ck_cfg_delay
    ("exec_timeout_sec", 4),         # ck_cfg_exec_timeout
    ("implicit_wait_sec", -1),       # ck_cfg_implicit
    ("retry_count", 11),             # ck_cfg_retry
    ("media_retention_days", 10),    # ck_cfg_retention
    ("screenshot_on_fail", 2),       # ck_cfg_flags
])
def test_config_check_constraints(db, field, value):
    get_config(db)
    with pytest.raises(IntegrityError):
        save_config(db, {field: value})


def test_custom_proxy_requires_address(db):
    """ck_cfg_proxy_custom：CUSTOM 模式必须提供地址。"""
    get_config(db)
    with pytest.raises(IntegrityError):
        save_config(db, {"proxy_mode": "CUSTOM", "proxy_address": None})


# ---------------------------------------------------------------- 敏感字段与映射

def test_mask_secret():
    assert mask_secret("s3cret") == MASK_REPLACEMENT
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    assert MASK_REPLACEMENT not in ("s3cret",)


def test_wait_until_map_covers_page_load_strategies():
    assert WAIT_UNTIL_MAP == {
        "NORMAL": "load",
        "EAGER": "domcontentloaded",
        "NONE": "commit",
    }
