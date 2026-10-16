"""右侧状态面板单元测试（T6.1）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.data.demo_cases import DEMO_MODULES
from app.engine.executor import STATUS_FAILED, STATUS_PASSED, STATUS_RUNNING
from app.widgets.status_panel import STATUS_WAITING, _STATUS_ROLE, StatusPanel

CHECKED = [(m, c) for m in DEMO_MODULES for c in m.cases if c.default_checked]


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp):
    widget = StatusPanel()
    widget.load_queue(CHECKED)
    return widget


def _case_items(panel):
    result = []
    for i in range(panel.queue.topLevelItemCount()):
        module_item = panel.queue.topLevelItem(i)
        for j in range(module_item.childCount()):
            result.append(module_item.child(j))
    return result


def _case(item):
    return item.data(0, Qt.ItemDataRole.UserRole)


def test_load_queue_initial_state(panel):
    assert panel.queue.topLevelItemCount() == 3
    assert panel.total == 12
    assert panel.executed == panel.passed == panel.failed == 0
    assert panel.executed_label.text() == "已执行: 0/12"
    assert panel.progress_label.text() == "0% (0/12)"
    assert panel.progress_bar.value() == 0
    for item in _case_items(panel):
        assert item.text(0).startswith("⏳")
        assert item.data(0, _STATUS_ROLE) == STATUS_WAITING


def test_progress_floor_formula(panel):
    items = _case_items(panel)
    # 1/12 → floor(8.33)=8；2/12 → floor(16.67)=16
    panel.update_status(_case(items[0]).case_id, STATUS_PASSED)
    assert panel.progress_label.text() == "8% (1/12)"
    assert panel.progress_bar.value() == 8
    panel.update_status(_case(items[1]).case_id, STATUS_PASSED)
    assert panel.progress_label.text() == "16% (2/12)"


def test_passed_and_failed_stats(panel):
    items = _case_items(panel)
    panel.update_status(_case(items[0]).case_id, STATUS_PASSED)
    panel.update_status(_case(items[1]).case_id, STATUS_FAILED)
    assert panel.executed == 2
    assert panel.passed == 1
    assert panel.failed == 1
    assert panel.executed_label.text() == "已执行: 2/12"
    assert panel.failed_label.text() == "失败: 1"
    assert items[1].text(0).startswith("✖")
    assert items[0].text(0).startswith("✔")


def test_module_aggregation(panel):
    first_module = panel.queue.topLevelItem(0)
    for j in range(first_module.childCount()):
        panel.update_status(_case(first_module.child(j)).case_id, STATUS_PASSED)
    assert first_module.text(0).endswith("已完成")
    # 有失败 → ✖ 优先于已完成
    items = _case_items(panel)
    panel.update_status(_case(items[1]).case_id, STATUS_FAILED)
    assert first_module.text(0).startswith("✖")
    # 进行中 → 🟢 优先
    panel.update_status(_case(items[0]).case_id, STATUS_RUNNING)
    assert first_module.text(0).startswith("🟢")


def test_manual_stop_keeps_waiting(panel):
    items = _case_items(panel)
    panel.update_status(_case(items[0]).case_id, STATUS_PASSED)
    assert items[1].text(0).startswith("⏳")  # 未执行保持等待中
    assert items[1].data(0, _STATUS_ROLE) == STATUS_WAITING


def test_repeated_status_no_double_count(panel):
    items = _case_items(panel)
    case_id = _case(items[0]).case_id
    panel.update_status(case_id, STATUS_RUNNING)
    panel.update_status(case_id, STATUS_PASSED)
    panel.update_status(case_id, STATUS_PASSED)  # 重复 passed 不重复计数
    assert panel.executed == 1
    assert panel.passed == 1