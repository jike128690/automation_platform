"""ORM 模型包：集中注册静态资产域与动态执行域模型到 Base.metadata（迁移建表的数据源）。"""
from app.db.models.asset import (
    CommandType, HttpMethod, LocatorType,
    Page, PageElement, PageInterface,
    TestCase, TestModule, TestStep,
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
]
