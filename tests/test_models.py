"""数据结构单元测试。"""
from app.data.demo_cases import DEMO_MODULES


def test_demo_module_count():
    assert len(DEMO_MODULES) == 3


def test_demo_case_count_and_checked():
    cases = [c for m in DEMO_MODULES for c in m.cases]
    assert len(cases) == 24
    assert sum(c.default_checked for c in cases) == 12


def test_demo_steps_within_range():
    for m in DEMO_MODULES:
        for c in m.cases:
            assert 3 <= len(c.steps) <= 6


def test_step_action_types_and_order():
    valid = ("goto", "fill", "click", "assert_visible")
    for m in DEMO_MODULES:
        for c in m.cases:
            assert all(s.action_type in valid for s in c.steps)
            assert [s.step_no for s in c.steps] == list(range(1, len(c.steps) + 1))
