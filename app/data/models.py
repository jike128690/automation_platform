"""TestModule/TestCase/TestStep 数据类。"""
from dataclasses import dataclass, field


@dataclass
class TestStep:
    step_no: int
    action_type: str
    selector: str
    value: str
    remark: str


@dataclass
class TestCase:
    case_id: str
    case_title: str
    short_name: str
    default_checked: bool
    steps: list[TestStep] = field(default_factory=list)


@dataclass
class TestModule:
    module_id: str
    module_name: str
    cases: list[TestCase] = field(default_factory=list)
