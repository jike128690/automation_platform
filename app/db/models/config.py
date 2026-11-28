# -*- coding: utf-8 -*-
"""全局配置域 ORM 模型（LDM 2.10 节，表结构唯一权威来源）。

tb_system_config：批量配置页的持久化载体，单机全局唯一一条有效记录
（config_service 保证；无外键、无软删除，物理单行 upsert）。

落地要点：
- LDM 2.10 仅有 updated_at（"最后保存并应用的时间"），无 created_at；
- CHECK 枚举/数值域按 LDM 2.10 取值范围（第 3 节约束表未覆盖本表，
  与资产/执行域同规则：数据字典取值范围 → CHECK + 应用层 Enum 双层校验）；
- proxy_password 为敏感字段：入库由 UI 掩码展示，写日志/报表统一脱敏
  （数据库开发计划第 8 节）；
- media_retention_days ∈ {1,3,5,7,30,-1}，-1 表示永久保留（确认项 4）。
"""
import enum

from sqlalchemy import CheckConstraint, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import DEFAULT_SITE_URL
from app.db.base import Base, gen_uuid, now_iso

__all__ = ["SystemConfig", "RunMode", "BrowserType", "PageLoadStrategy",
           "ProxyMode", "EnvProfile"]


class RunMode(str, enum.Enum):
    """运行模式（图3：TEST 按需重跑 / DEBUG 单步暂停）。"""

    TEST = "TEST"
    DEBUG = "DEBUG"


class BrowserType(str, enum.Enum):
    """浏览器内核（图4：CHROME 本机内核 / CHROMIUM Playwright 内置）。"""

    CHROME = "CHROME"
    CHROMIUM = "CHROMIUM"


class PageLoadStrategy(str, enum.Enum):
    """页面加载策略（图4）→ Playwright wait_until 映射见 config_service。"""

    NORMAL = "NORMAL"
    EAGER = "EAGER"
    NONE = "NONE"


class ProxyMode(str, enum.Enum):
    """代理模式（图4）。"""

    NO_PROXY = "NO_PROXY"
    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"


class EnvProfile(str, enum.Enum):
    """环境配置（图4）。"""

    PROD = "PROD"
    STAGE = "STAGE"
    TEST = "TEST"
    DEV = "DEV"


class SystemConfig(Base):
    """系统与浏览器配置表（单机全局唯一一条有效记录）。"""

    __test__ = False  # 防止 pytest 按 Test* 前缀误收集 ORM 类
    __tablename__ = "tb_system_config"

    config_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    # ---- 常规设置（图3） ----
    project_name: Mapped[str] = mapped_column(
        Text(100), nullable=False, default="我的Web自动化测试",
    )
    site_url: Mapped[str] = mapped_column(
        Text(255), nullable=False, default=DEFAULT_SITE_URL,
    )
    report_save_path: Mapped[str] = mapped_column(
        Text(500), nullable=False, default=r"C:\TestReports\HTML",
    )
    run_mode: Mapped[str] = mapped_column(
        Text(20), nullable=False, default=RunMode.TEST.value,
    )
    start_delay_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # ---- 浏览器设置（图4） ----
    browser_type: Mapped[str] = mapped_column(
        Text(20), nullable=False, default=BrowserType.CHROME.value,
    )
    driver_path: Mapped[str | None] = mapped_column(Text(500), nullable=True)
    exec_timeout_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    implicit_wait_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    page_load_strategy: Mapped[str] = mapped_column(
        Text(20), nullable=False, default=PageLoadStrategy.NORMAL.value,
    )
    proxy_mode: Mapped[str] = mapped_column(
        Text(20), nullable=False, default=ProxyMode.NO_PROXY.value,
    )
    proxy_address: Mapped[str | None] = mapped_column(Text(255), nullable=True)
    proxy_auth_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proxy_username: Mapped[str | None] = mapped_column(Text(100), nullable=True)
    proxy_password: Mapped[str | None] = mapped_column(Text(255), nullable=True)
    clear_cache: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    clear_cookies: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    clear_history: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    env_profile: Mapped[str] = mapped_column(
        Text(30), nullable=False, default=EnvProfile.PROD.value,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    screenshot_on_fail: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    record_video: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    media_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    log_level: Mapped[str] = mapped_column(Text(10), nullable=False, default="INFO")
    updated_at: Mapped[str] = mapped_column(
        Text(23), nullable=False, default=now_iso, onupdate=now_iso,
    )

    __table_args__ = (
        # 枚举域（LDM 2.10 取值范围）
        CheckConstraint("run_mode IN ('TEST', 'DEBUG')", name="ck_cfg_run_mode"),
        CheckConstraint("browser_type IN ('CHROME', 'CHROMIUM')", name="ck_cfg_browser"),
        CheckConstraint(
            "page_load_strategy IN ('NORMAL', 'EAGER', 'NONE')", name="ck_cfg_pload",
        ),
        CheckConstraint(
            "proxy_mode IN ('NO_PROXY', 'SYSTEM', 'CUSTOM')", name="ck_cfg_proxy_mode",
        ),
        CheckConstraint(
            "env_profile IN ('PROD', 'STAGE', 'TEST', 'DEV')", name="ck_cfg_env",
        ),
        CheckConstraint(
            "log_level IN ('DEBUG', 'INFO', 'WARN', 'ERROR')", name="ck_cfg_log_level",
        ),
        # 数值域（LDM 2.10 取值范围）
        CheckConstraint("start_delay_sec BETWEEN 0 AND 60", name="ck_cfg_delay"),
        CheckConstraint("exec_timeout_sec BETWEEN 5 AND 300", name="ck_cfg_exec_timeout"),
        CheckConstraint("implicit_wait_sec BETWEEN 0 AND 60", name="ck_cfg_implicit"),
        CheckConstraint("retry_count BETWEEN 0 AND 10", name="ck_cfg_retry"),
        CheckConstraint(
            "media_retention_days IN (1, 3, 5, 7, 30, -1)", name="ck_cfg_retention",
        ),
        # 布尔域
        CheckConstraint(
            "proxy_auth_enabled IN (0, 1) AND clear_cache IN (0, 1) "
            "AND clear_cookies IN (0, 1) AND screenshot_on_fail IN (0, 1) "
            "AND record_video IN (0, 1)",
            name="ck_cfg_flags",
        ),
        # 代理联动：CUSTOM 模式必须提供地址
        CheckConstraint(
            "proxy_mode != 'CUSTOM' OR (proxy_address IS NOT NULL "
            "AND length(proxy_address) > 0)",
            name="ck_cfg_proxy_custom",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SystemConfig {self.project_name!r} {self.browser_type}>"
