"""WorkerThread 5 个信号跨线程收发单元测试。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from app.engine.worker_thread import WorkerThread


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class EmittingWorker(WorkerThread):
    """测试专用：run() 中依次触发 5 个信号。"""

    def run(self):
        self.sig_frame_ready.emit(b"fake-jpeg", "http://127.0.0.1:8765/login")
        self.sig_highlight_element.emit({"x": 100, "y": 200, "w": 80, "h": 30}, "点击 [登录] 按钮")
        self.sig_case_status_changed.emit("001", "running")
        self.sig_log_appended.emit("10:00:00", "开始执行测试套件")
        self.sig_batch_finished.emit(False)


def test_five_signals_received_on_main_thread(qapp):
    frame, highlight, status, log, finished = [], [], [], [], []

    worker = EmittingWorker()
    worker.sig_frame_ready.connect(lambda *a: frame.append(a))
    worker.sig_highlight_element.connect(lambda *a: highlight.append(a))
    worker.sig_case_status_changed.connect(lambda *a: status.append(a))
    worker.sig_log_appended.connect(lambda *a: log.append(a))
    worker.sig_batch_finished.connect(lambda *a: finished.append(a))

    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    worker.start()
    loop.exec()
    assert worker.isFinished(), "worker 未在 5 秒内结束"

    assert frame == [(b"fake-jpeg", "http://127.0.0.1:8765/login")]
    assert highlight == [({"x": 100, "y": 200, "w": 80, "h": 30}, "点击 [登录] 按钮")]
    assert status == [("001", "running")]
    assert log == [("10:00:00", "开始执行测试套件")]
    assert finished == [(False,)]


def test_signals_declared_on_class(qapp):
    assert WorkerThread.sig_frame_ready is not None
    assert WorkerThread.sig_highlight_element is not None
    assert WorkerThread.sig_case_status_changed is not None
    assert WorkerThread.sig_log_appended is not None
    assert WorkerThread.sig_batch_finished is not None