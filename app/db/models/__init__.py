"""ORM 模型包：集中注册静态资产域模型到 Base.metadata（迁移建表的数据源）。"""
from app.db.models.asset import (
    CommandType, HttpMethod, LocatorType,
    Page, PageElement, PageInterface,
    TestCase, TestModule, TestStep,
)

__all__ = [
    "TestModule", "Page", "PageElement", "PageInterface",
    "TestCase", "TestStep",
    "LocatorType", "HttpMethod", "CommandType",
]
