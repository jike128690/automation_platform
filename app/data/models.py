"""TestModule/TestCase/TestStep 数据类。"""
from dataclasses import dataclass, field


@dataclass
class TestStep:
    __test__ = False  # 防止 pytest 按 Test* 前缀误收集

    step_no: int
    action_type: str
    selector: str
    value: str
    remark: str


@dataclass
class TestCase:
    __test__ = False

    case_id: str
    case_title: str
    short_name: str
    default_checked: bool
    steps: list[TestStep] = field(default_factory=list)


@dataclass
class TestModule:
    __test__ = False

    module_id: str
    module_name: str
    cases: list[TestCase] = field(default_factory=list)
