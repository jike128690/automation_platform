"""WorkerThread 信号与队列执行集成测试（asyncio 双事件循环架构）。"""
import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

import app.engine.worker_thread as worker_module
from app.data.demo_cases import DEMO_MODULES
from app.engine.worker_thread import WorkerThread


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeAsyncActions:
    """测试专用：全部动作成功，定位恒返回视口坐标。"""

    async def goto(self, url):
        pass

    async def clear_session(self):
        pass

    async def locate(self, selector):
        return {"x": 10, "y": 20, "width": 100, "height": 30}

    async def fill(self, selector, value):
        pass

    async def click(self, selector):
        pass

    async def assert_visible(self, selector):
        pass


class EmittingWorker(WorkerThread):
    """测试专用：run() 中依次触发 5 个信号。"""

    def run(self):
        self.sig_frame_ready.emit(
            QImage(1, 1, QImage.Format.Format_RGB32), "http://127.0.0.1:8765/login"
        )
        self.sig_highlight_element.emit({"x": 100, "y": 200, "w": 80, "h": 30}, "点击 [登录] 按钮")
        self.sig_case_status_changed.emit("001", "running")
        self.sig_log_appended.emit("10:00:00", "开始执行测试套件")
        self.sig_batch_finished.emit(False)


def _wait_finished(worker):
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(10000, loop.quit)
    worker.start()
    loop.exec()
    assert worker.isFinished(), "worker 未在 10 秒内结束"


def test_five_signals_received_on_main_thread(qapp):
    frame, highlight, status, log, finished = [], [], [], [], []

    worker = EmittingWorker()
    worker.sig_frame_ready.connect(lambda *a: frame.append(a))
    worker.sig_highlight_element.connect(lambda *a: highlight.append(a))
    worker.sig_case_status_changed.connect(lambda *a: status.append(a))
    worker.sig_log_appended.connect(lambda *a: log.append(a))
    worker.sig_batch_finished.connect(lambda *a: finished.append(a))
    _wait_finished(worker)

    assert len(frame) == 1 and isinstance(frame[0][0], QImage)
    assert frame[0][1] == "http://127.0.0.1:8765/login"
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


def test_worker_runs_queued_cases_and_emits_signals(qapp):
    pairs = [(m, c) for m in DEMO_MODULES for c in m.cases if c.default_checked]
    statuses, logs, finished = [], [], []

    worker = WorkerThread()
    worker.set_actions(FakeAsyncActions())
    worker.set_rhythm(0, 0)  # 单测提速：跳过视觉停顿
    worker.set_queue(pairs)
    worker.sig_case_status_changed.connect(lambda *a: statuses.append(a))
    worker.sig_log_appended.connect(lambda *a: logs.append(a))
    worker.sig_batch_finished.connect(lambda *a: finished.append(a))
    _wait_finished(worker)

    passed = [s for s in statuses if s[1] == "passed"]
    assert len(passed) == 12
    suite_logs = [msg for ts, msg in logs if msg.startswith("开始执行测试套件")]
    assert len(suite_logs) == 3
    assert finished == [(False,)]


class FakePage:
    def __init__(self):
        self.goto_args = None

    async def goto(self, url, wait_until=None):
        self.goto_args = (url, wait_until)


class FakeBrowser:
    process = None

    def __init__(self):
        self.launch_kwargs = None
        self.page_kwargs = None
        self.page = FakePage()

    async def new_page(self, **kwargs):
        self.page_kwargs = kwargs
        return self.page


class FakeChromium:
    def __init__(self):
        self.launch_kwargs = None
        self.browser = FakeBrowser()

    async def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.browser


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()

    async def stop(self):
        pass


class FakeStarter:
    def __init__(self):
        self.playwright = FakePlaywright()

    async def start(self):
        return self.playwright


def test_record_video_options_passed_to_page_context(qapp, monkeypatch, tmp_path):
    """record_video_* 属于上下文参数：随 new_page 传入，launch 只收启动参数。"""
    starter = FakeStarter()
    monkeypatch.setattr(worker_module, "async_playwright", lambda: starter)
    video_dir = tmp_path / "videos"

    worker = WorkerThread()
    worker.set_browser("chrome", None, (1280, 800), "http://127.0.0.1:8765/login")
    worker.set_runtime_options(record_video=True, video_dir=str(video_dir))
    asyncio.run(worker._launch_browser())

    browser = starter.playwright.chromium.browser
    assert starter.playwright.chromium.launch_kwargs == {"headless": True, "channel": "chrome"}
    assert browser.page_kwargs == {
        "viewport": {"width": 1280, "height": 800},
        "record_video_dir": str(video_dir),
        "record_video_size": {"width": 1280, "height": 800},
    }
    assert video_dir.is_dir()
    assert browser.page.goto_args == ("http://127.0.0.1:8765/login", "domcontentloaded")


def test_record_video_disabled_keeps_page_options_clean(qapp, monkeypatch):
    starter = FakeStarter()
    monkeypatch.setattr(worker_module, "async_playwright", lambda: starter)

    worker = WorkerThread()
    worker.set_browser(None, None, (1280, 800), "http://127.0.0.1:8765/login")
    asyncio.run(worker._launch_browser())

    browser = starter.playwright.chromium.browser
    assert starter.playwright.chromium.launch_kwargs == {"headless": True}
    assert browser.page_kwargs == {"viewport": {"width": 1280, "height": 800}}


def test_worker_without_queue_finishes_immediately(qapp):
    finished = []
    worker = WorkerThread()
    worker.sig_batch_finished.connect(lambda *a: finished.append(a))
    _wait_finished(worker)
    assert finished == [(False,)]