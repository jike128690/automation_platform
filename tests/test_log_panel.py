"""日志面板单元测试（T6.2）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from app.widgets.log_panel import MAX_LINES, LogPanel


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def panel(qapp):
    return LogPanel()


def test_append_formats_timestamp(panel):
    panel.append_log("10:00:00", "开始执行测试套件: [模块一] 登录与基础功能")
    panel._flush()
    assert panel.view.toPlainText() == "[10:00:00] 开始执行测试套件: [模块一] 登录与基础功能"


def test_batch_append_flushes_once(panel):
    panel.append_log("10:00:00", "第 1 条")
    panel.append_log("10:00:01", "第 2 条")
    panel.append_log("10:00:02", "第 3 条")
    assert panel.view.toPlainText() == ""  # 未到刷新点不直接渲染
    panel._flush()
    lines = panel.view.toPlainText().split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("[10:00:00]")
    assert lines[2] == "[10:00:02] 第 3 条"


def test_clear_log(panel):
    panel.append_log("10:00:00", "日志")
    panel._flush()
    panel.clear_log()
    assert panel.view.toPlainText() == ""
    assert panel._pending == []


def test_max_lines_trim(panel):
    for i in range(MAX_LINES + 100):
        panel.append_log(f"10:00:0{i % 10}", f"日志 {i}")
    panel._flush()
    assert panel.view.blockCount() <= MAX_LINES


def test_readonly_copiable(panel):
    assert panel.view.isReadOnly() is True


def test_log_kept_until_clear(panel):
    panel.append_log("10:00:00", "保留日志")
    panel._flush()
    panel.append_log("10:00:01", "停止后继续追加")
    panel._flush()
    assert "保留日志" in panel.view.toPlainText()  # 停止后保留全部日志（5.1.6）