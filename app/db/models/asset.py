"""静态资产域 ORM 模型（LDM 2.1–2.6 节，表结构唯一权威来源）。

6 张表：tb_test_module / tb_page / tb_page_element / tb_page_interface /
        tb_test_case / tb_test_step。

落地要点（LDM 第 3 节约束 + 《数据库开发.md》4.6）：
- 唯一约束：SQLite 部分唯一索引（WHERE is_deleted=0）无法用 ORM
  UniqueConstraint 表达，改在迁移脚本 v001 中显式 CREATE UNIQUE INDEX
  （uq_module_code / uq_case_code / uq_page_interface）；
- CHECK 枚举：表内 CHECK(...) 与应用层 Python Enum 双层校验（LDM 第 4 节）；
- 外键级联：element/interface → page RESTRICT；case → module/page RESTRICT；
  step → case CASCADE；step → element SET NULL；
- 软删除 5 表启用（module/page/page_element/page_interface/test_case）。
"""
import enum

from sqlalchemy import (
    CheckConstraint, ForeignKey, Index, Integer, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, gen_uuid

__all__ = [
    "TestModule", "Page", "PageElement", "PageInterface",
    "TestCase", "TestStep",
    "LocatorType", "HttpMethod", "CommandType",
]


# ---------------------------------------------------------------- 应用层枚举


class LocatorType(str, enum.Enum):
    """元素定位器类型（LDM 2.3 locator_type）。"""

    ID = "ID"
    CLASS = "CLASS"
    XPATH = "XPATH"
    CSS = "CSS"


class HttpMethod(str, enum.Enum):
    """页面接口请求方法（LDM 2.4 method，v1.1.0 增补）。"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class CommandType(str, enum.Enum):
    """测试步骤命令类型（LDM 2.6 command_type）。"""

    GOTO_URL = "GOTO_URL"
    INPUT_TEXT = "INPUT_TEXT"
    CLICK_ELEMENT = "CLICK_ELEMENT"
    ASSERT_ELEMENT_VISIBLE = "ASSERT_ELEMENT_VISIBLE"


# ---------------------------------------------------------------- 2.1 tb_test_module


class TestModule(Base, SoftDeleteMixin, TimestampMixin):
    """测试模块表：首页用例树顶层分组。"""

    __test__ = False  # 防止 pytest 按 Test* 前缀误收集 ORM 类
    __tablename__ = "tb_test_module"

    module_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    module_code: Mapped[str] = mapped_column(Text(32), nullable=False)
    module_name: Mapped[str] = mapped_column(Text(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        # uq_module_code：部分唯一索引（WHERE is_deleted=0）在 v001 迁移脚本中创建
        CheckConstraint("is_deleted IN (0, 1)", name="ck_module_del"),
        CheckConstraint(
            "module_code IS NOT NULL AND length(module_code) > 0",
            name="ck_module_code_nonempty",
        ),
        Index("ix_module_sort", "sort_order", "is_deleted"),
    )

    cases: Mapped[list["TestCase"]] = relationship(back_populates="module")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TestModule {self.module_code} {self.module_name!r}>"


# ---------------------------------------------------------------- 2.2 tb_page


class Page(Base, SoftDeleteMixin, TimestampMixin):
    """页面定义表：Page Object 元数据。"""

    __tablename__ = "tb_page"

    page_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    page_name: Mapped[str] = mapped_column(Text(100), nullable=False)
    page_url: Mapped[str] = mapped_column(Text(500), nullable=False)
    remark: Mapped[str | None] = mapped_column(Text(255), nullable=True)

    __table_args__ = (
        CheckConstraint("is_deleted IN (0, 1)", name="ck_page_del"),
        CheckConstraint(
            "page_url LIKE 'http://%' OR page_url LIKE 'https://%'",
            name="ck_page_url_scheme",
        ),
    )

    elements: Mapped[list["PageElement"]] = relationship(back_populates="page")
    interfaces: Mapped[list["PageInterface"]] = relationship(back_populates="page")
    cases: Mapped[list["TestCase"]] = relationship(back_populates="page")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Page {self.page_name!r}>"


# ---------------------------------------------------------------- 2.3 tb_page_element


class PageElement(Base, SoftDeleteMixin, TimestampMixin):
    """页面元素表：DOM 定位信息。"""

    __tablename__ = "tb_page_element"

    element_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    page_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_page.page_id", ondelete="RESTRICT", name="fk_elem_page"),
        nullable=False,
    )
    element_name: Mapped[str] = mapped_column(Text(100), nullable=False)
    locator_type: Mapped[str] = mapped_column(
        Text(20), nullable=False, default=LocatorType.CSS.value,
    )
    locator_value: Mapped[str] = mapped_column(Text(500), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "locator_type IN ('ID', 'CLASS', 'XPATH', 'CSS')",
            name="ck_elem_locator",
        ),
        CheckConstraint("is_deleted IN (0, 1)", name="ck_elem_del"),
        Index("ix_element_page", "page_id", "is_deleted"),
    )

    page: Mapped["Page"] = relationship(back_populates="elements")
    steps: Mapped[list["TestStep"]] = relationship(back_populates="element")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PageElement {self.element_name!r} {self.locator_value}>"


# ---------------------------------------------------------------- 2.4 tb_page_interface


class PageInterface(Base, SoftDeleteMixin, TimestampMixin):
    """页面接口表（LDM v1.1.0 增补）：页面归属的 HTTP API 资产。

    种子阶段 0 条（Mock 站点为纯前端静态页）；本期仅建表 + 仓储查询，
    接口资产由后续「接口录入页」或导入映射填充。
    """

    __tablename__ = "tb_page_interface"

    interface_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    page_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_page.page_id", ondelete="RESTRICT", name="fk_interface_page"),
        nullable=False,
    )
    interface_name: Mapped[str] = mapped_column(Text(100), nullable=False)
    method: Mapped[str] = mapped_column(
        Text(10), nullable=False, default=HttpMethod.GET.value,
    )
    interface_url: Mapped[str] = mapped_column(Text(500), nullable=False)
    request_template: Mapped[str | None] = mapped_column(Text(2000), nullable=True)
    response_template: Mapped[str | None] = mapped_column(Text(2000), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text(255), nullable=True)

    __table_args__ = (
        # uq_page_interface：部分唯一索引 (page_id, method, interface_url)
        # WHERE is_deleted=0，在 v001 迁移脚本中创建
        CheckConstraint(
            "method IN ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')",
            name="ck_interface_method",
        ),
        CheckConstraint("is_deleted IN (0, 1)", name="ck_interface_del"),
        Index("ix_interface_page", "page_id", "is_deleted"),
    )

    page: Mapped["Page"] = relationship(back_populates="interfaces")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PageInterface {self.method} {self.interface_url}>"


# ---------------------------------------------------------------- 2.5 tb_test_case


class TestCase(Base, SoftDeleteMixin, TimestampMixin):
    """测试用例表：显式绑定主页面（确认项 1），归属模块。"""

    __test__ = False  # 防止 pytest 按 Test* 前缀误收集 ORM 类
    __tablename__ = "tb_test_case"

    case_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    module_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_test_module.module_id", ondelete="RESTRICT", name="fk_case_module"),
        nullable=False,
    )
    page_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_page.page_id", ondelete="RESTRICT", name="fk_case_page"),
        nullable=False,
    )
    case_code: Mapped[str] = mapped_column(Text(20), nullable=False)
    case_name: Mapped[str] = mapped_column(Text(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(Text(50), nullable=True)
    default_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_builtin: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_summary: Mapped[str | None] = mapped_column(Text(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        # uq_case_code：部分唯一索引 WHERE is_deleted=0，在 v001 迁移脚本中创建
        CheckConstraint(
            "default_checked IN (0, 1) AND is_builtin IN (0, 1) "
            "AND is_deleted IN (0, 1)",
            name="ck_case_flags",
        ),
        CheckConstraint("version >= 1", name="ck_case_version"),
        CheckConstraint("sort_order >= 0", name="ck_case_sort"),
        Index("ix_case_module_sort", "module_id", "sort_order", "is_deleted"),
        Index("ix_case_page", "page_id"),
    )

    module: Mapped["TestModule"] = relationship(back_populates="cases")
    page: Mapped["Page"] = relationship(back_populates="cases")
    steps: Mapped[list["TestStep"]] = relationship(
        back_populates="case",
        order_by="TestStep.step_order",
        cascade="save-update, merge, delete, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TestCase {self.case_code} {self.case_name!r}>"


# ---------------------------------------------------------------- 2.6 tb_test_step


class TestStep(Base, TimestampMixin):
    """测试步骤表：用例下的有序原子操作（LDM 2.6；物理删除，无软删除列）。"""

    __test__ = False  # 防止 pytest 按 Test* 前缀误收集 ORM 类
    __tablename__ = "tb_test_step"

    step_id: Mapped[str] = mapped_column(
        Text(36), primary_key=True, default=gen_uuid,
    )
    case_id: Mapped[str] = mapped_column(
        Text(36),
        ForeignKey("tb_test_case.case_id", ondelete="CASCADE", name="fk_step_case"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    command_type: Mapped[str] = mapped_column(Text(30), nullable=False)
    element_id: Mapped[str | None] = mapped_column(
        Text(36),
        ForeignKey("tb_page_element.element_id", ondelete="SET NULL", name="fk_step_element"),
        nullable=True,
    )
    target_override: Mapped[str | None] = mapped_column(Text(500), nullable=True)
    param_value: Mapped[str | None] = mapped_column(Text(500), nullable=True)
    is_secret: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str] = mapped_column(Text(200), nullable=False)

    __table_args__ = (
        # uq_case_step_order：(case_id, step_order) 唯一，v001 迁移脚本创建
        CheckConstraint(
            "step_order >= 1 AND command_type IN "
            "('GOTO_URL', 'INPUT_TEXT', 'CLICK_ELEMENT', 'ASSERT_ELEMENT_VISIBLE')",
            name="ck_step_cmd",
        ),
        CheckConstraint("is_secret IN (0, 1)", name="ck_step_secret"),
        CheckConstraint(
            "timeout_sec IS NULL OR (timeout_sec >= 1 AND timeout_sec <= 300)",
            name="ck_step_timeout",
        ),
        CheckConstraint(
            "remark IS NOT NULL AND length(remark) > 0",
            name="ck_step_remark_nonempty",
        ),
        Index("ix_step_case_order", "case_id", "step_order"),
    )

    case: Mapped["TestCase"] = relationship(back_populates="steps")
    element: Mapped["PageElement | None"] = relationship(back_populates="steps")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TestStep {self.step_order} {self.command_type} {self.remark!r}>"
