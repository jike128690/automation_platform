# -*- coding: utf-8 -*-
"""tb_system_config 单例读写服务（T12.1）。

单例保障策略：
- get_config()：读唯一配置；表空（首次启动）时写入 LDM 2.10 默认值并返回；
- save_config()：仅更新已存在记录（行数恒为 1，绝不做第二次 INSERT）；
- 表内多条记录视为异常状态，get_config 取 updated_at 最新一条并告警
  （防御性收敛，正常路径不会发生）。

敏感字段（数据库开发计划第 8 节）：proxy_password 写日志/报表时必须
经 mask_secret() 脱敏；本服务提供 MASK_REPLACEMENT 常量供 UI/日志统一使用。

Playwright wait_until 映射（T12.3 消费）：
- NORMAL → "load"；EAGER → "domcontentloaded"；NONE → "commit"。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SystemConfig

# 敏感字段脱敏常量（写日志/报表统一使用）
MASK_REPLACEMENT = "********"

# 页面加载策略 → Playwright wait_until（AsyncPlaywrightActions 消费）
WAIT_UNTIL_MAP = {
    "NORMAL": "load",
    "EAGER": "domcontentloaded",
    "NONE": "commit",
}

_logger = logging.getLogger(__name__)


def get_config(engine) -> SystemConfig:
    """读取全局唯一配置；表空时初始化 LDM 2.10 默认配置（首次启动）。"""
    with Session(engine) as s:
        config = _latest(s)
        if config is None:
            config = SystemConfig()
            s.add(config)
            s.commit()
            s.refresh(config)
            _logger.info("首次启动：已初始化默认系统配置")
        s.expunge(config)
        return config


def save_config(engine, updates: dict) -> SystemConfig:
    """更新唯一配置记录（部分字段合并），返回更新后的配置。

    行不存在时补建（防御）；行数 >1 时收敛为最新一条（防御）。
    updated_at 由 ORM onupdate 自动刷新（"最后保存并应用的时间"）。
    """
    allowed = {c.name for c in SystemConfig.__table__.columns} - {"config_id"}
    illegal = set(updates) - allowed
    if illegal:
        raise ValueError(f"非法配置字段: {sorted(illegal)}")

    with Session(engine) as s:
        config = _latest(s)
        if config is None:
            config = SystemConfig()
            s.add(config)
            s.flush()
        for key, value in updates.items():
            setattr(config, key, value)
        s.commit()
        s.refresh(config)
        s.expunge(config)
        return config


def _latest(s: Session) -> SystemConfig | None:
    """取 updated_at 最新的配置行；多于一条时告警（正常恒为 1 条）。"""
    configs = s.scalars(
        select(SystemConfig).order_by(SystemConfig.updated_at.desc())
    ).all()
    if len(configs) > 1:
        _logger.warning(
            "tb_system_config 出现 %d 条记录（应为单例），已收敛为最新一条",
            len(configs),
        )
    return configs[0] if configs else None


def mask_secret(value: str | None) -> str:
    """敏感字段脱敏：非空一律掩码，不泄露原文长度。"""
    return MASK_REPLACEMENT if value else ""
