"""MainWindow 运行/停止联调逻辑单元测试（T8.1）。"""
import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr("app.main_window.WorkerThread", MagicMock)  # 不启动真浏览器
    w = MainWindow(("chrome", "C:/fake/chrome.exe"))
    yield w
    w.close()


def _unselect_all(window):
    window.home_page.case_tree.check_all.setCheckState(Qt.CheckState.Unchecked)


def test_run_without_selection_prompts(window, monkeypatch):
    _unselect_all(window)
    prompts = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.information",
        lambda *a, **k: prompts.append(a) or QMessageBox.StandardButton.Ok,
    )
    window._on_run_clicked()
    assert prompts  # 提示"请至少勾选一条测试用例后再运行"
    assert window._worker is None


def test_run_flow_locks_and_initializes(window):
    window._on_run_clicked()
    assert window._worker is not None
    assert window._worker.start.called          # 工作线程已启动
    assert not window.btn_run.isEnabled()        # 运行禁用
    assert window.btn_stop.isEnabled()           # 停止高亮
    assert not window.btn_import.isEnabled()     # 二级入口置灰（开放问题 03）
    assert window.home_page.case_tree.tree.isEnabled() is False  # 左侧锁定
    assert window.home_page.browser_view.canvas._controlled       # 画布受控
    assert window.home_page.status_panel.total == 12  # 队列初始化（默认勾选 12）


def test_run_clears_previous_log(window):
    window.home_page.log_panel.append_log("10:00:00", "旧日志")
    window._on_run_clicked()
    assert window.home_page.log_panel.view.toPlainText() == ""  # 新一轮清空（5.1.6）


def test_stop_transition(window):
    window._on_run_clicked()
    window._on_stop_clicked()
    assert window._worker.request_stop.called
    assert not window.btn_stop.isEnabled()
    assert window.btn_stop.text() == "正在停止..."  # 停止过渡态（5.1.2）


def test_batch_finished_unlocks(window):
    window._on_run_clicked()
    window._on_batch_finished(False)
    assert window.btn_run.isEnabled()
    assert not window.btn_stop.isEnabled()
    assert window.btn_stop.text() == "□ 停止测试"
    assert window.btn_import.isEnabled()
    assert window.home_page.case_tree.tree.isEnabled()
    assert window.home_page.browser_view.canvas._controlled is False
    assert window._worker is None  # 释放线程引用


def test_close_event_stops_running_worker(window):
    class FakeWorker:
        def __init__(self):
            self.stopped = False

        def isRunning(self):
            return True

        def request_stop(self):
            self.stopped = True

        def wait(self, ms):
            return True

    window._worker = FakeWorker()
    window.close()  # 触发 closeEvent：请求停止 + 关闭 Mock 站点（cdp.md 2.4 第二级）
    assert window._worker.stopped
    assert window._mock_site._server is None  # noqa: SLF001