"""ORM 模型包：集中注册静态资产域、动态执行域与全局配置域模型到 Base.metadata。"""
from app.db.models.asset import (
    CommandType, HttpMethod, LocatorType,
    Page, PageElement, PageInterface,
    TestCase, TestModule, TestStep,
)
from app.db.models.config import (
    BrowserType, EnvProfile, PageLoadStrategy, ProxyMode, RunMode, SystemConfig,
)
from app.db.models.runtime import (
    BatchCaseResult, BatchStatus, ExecStatus, ExecutionBatch, ExecutionLog,
    LogLevel,
)

__all__ = [
    # 静态资产域
    "TestModule", "Page", "PageElement", "PageInterface",
    "TestCase", "TestStep",
    "LocatorType", "HttpMethod", "CommandType",
    # 动态执行域
    "ExecutionBatch", "BatchCaseResult", "ExecutionLog",
    "BatchStatus", "ExecStatus", "LogLevel",
    # 全局配置域
    "SystemConfig", "RunMode", "BrowserType", "PageLoadStrategy",
    "ProxyMode", "EnvProfile",
]
