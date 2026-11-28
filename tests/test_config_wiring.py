# -*- coding: utf-8 -*-
"""T12.3 配置联动单测：executor 失败重试 / recorder 重试计数与日志级别 /
WorkerThread 启动参数来自配置表。"""
import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from app.db.services.batch_recorder import BatchRecorder
from app.db.services.config_service import get_config, save_config
from app.engine.executor import AsyncExecutor
from tests.test_executor import FakeAsyncActions


@pytest.fixture()
def db(tmp_path):
    from app.db.engine import create_app_engine
    from app.db.migration import init_db
    from app.db.seed import seed_db
    engine = create_app_engine(tmp_path / "t123.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def tree(db):
    from app.db.repositories.case_repo import load_tree
    return load_tree(db)


# ---------------------------------------------------------------- executor 重试

class FlakyActions(FakeAsyncActions):
    """第一次定位失败、重试成功的动作 Fake（验证 T12.3 retry_count）。"""

    def __init__(self, fail_times=1):
        super().__init__()
        self.fail_times = fail_times
        self.attempts = 0

    async def locate(self, selector):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            return None  # 元素未找到 → 步骤失败
        return {"x": 0, "y": 0, "width": 10, "height": 10}


def _one_case(tree):
    return [(m, c) for m in tree for c in m.cases if c.default_checked][:1]


def _statuses(caught):
    return [s for _, s in caught]


def test_executor_retry_recovers_failed_case(tree):
    """验收：重试后失败用例转通过；状态序列含 RUNNING→FAILED→RUNNING→PASSED。"""
    caught = []
    actions = FlakyActions(fail_times=1)
    executor = AsyncExecutor(
        actions=actions,
        on_status=lambda cid, st: caught.append((cid, st)),
        on_log=lambda ts, msg: None,
        on_finished=lambda manual: None,
        visual_pause=0, post_pause=0,
        retry_count=2,
    )
    passed, failed = _run(executor, _one_case(tree))
    assert (passed, failed) == (1, 0)
    statuses = _statuses(caught)
    assert statuses == ["running", "failed", "running", "passed"]


def test_executor_no_retry_fails_directly(tree):
    caught = []
    executor = AsyncExecutor(
        actions=FlakyActions(fail_times=5),
        on_status=lambda cid, st: caught.append((cid, st)),
        on_log=lambda ts, msg: None,
        on_finished=lambda manual: None,
        visual_pause=0, post_pause=0,
        retry_count=0,
    )
    passed, failed = _run(executor, _one_case(tree))
    assert (passed, failed) == (0, 1)
    assert "failed" in _statuses(caught)


def test_executor_retry_budget_exhausted(tree):
    """重试次数耗尽仍失败 → 用例按失败计数，不无限重试。"""
    caught = []
    actions = FlakyActions(fail_times=99)
    executor = AsyncExecutor(
        actions=actions,
        on_status=lambda cid, st: caught.append((cid, st)),
        on_log=lambda ts, msg: None,
        on_finished=lambda manual: None,
        visual_pause=0, post_pause=0,
        retry_count=2,
    )
    passed, failed = _run(executor, _one_case(tree))
    assert (passed, failed) == (0, 1)
    assert _statuses(caught).count("running") == 3  # 首次 + 2 次重试


def _run(executor, pairs):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(
        _run_async(executor, pairs)
    )


async def _run_async(executor, pairs):
    return await executor.run(pairs)


# ---------------------------------------------------------------- recorder 重试计数与日志级别

def test_recorder_tracks_retry_count(db, tree):
    """终态后重新 RUNNING → retry_count 落库（LDM 2.8 实际重试次数）。"""
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    recorder = BatchRecorder(db, "模块", queue=pairs)
    code = pairs[0][1].case_id

    recorder.on_case_status(code, "running")
    recorder.on_case_status(code, "failed")    # 第一次失败
    recorder.on_case_status(code, "running")   # 重试
    recorder.on_case_status(code, "passed")    # 重试通过

    from sqlalchemy import text
    from sqlalchemy.orm import Session
    with Session(db) as s:
        retry = s.execute(
            text("SELECT retry_count, exec_status FROM tb_batch_case_result "
                 "WHERE batch_id = :bid AND queue_order = 1"),
            {"bid": recorder.batch_id},
        ).one()
    assert retry[0] == 1
    assert retry[1] == "PASSED"


def test_recorder_min_log_level_filters(db, tree):
    """图4 日志级别联动：ERROR 级别配置下 INFO 日志不入库。"""
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    recorder = BatchRecorder(db, "模块", queue=pairs, min_log_level="ERROR")
    code = pairs[0][1].case_id
    recorder.on_log("10:00:00", f"[{code}] INFO 级日志")
    recorder.on_log("10:00:01", f"[{code}] 步骤失败: 元素未找到")  # 含"失败"→ERROR
    recorder.flush_logs()

    from sqlalchemy import text
    from sqlalchemy.orm import Session
    with Session(db) as s:
        levels = s.execute(
            text("SELECT log_level FROM tb_execution_log WHERE batch_id = :bid"),
            {"bid": recorder.batch_id},
        ).scalars().all()
    assert levels == ["ERROR"]  # INFO 被过滤


def test_recorder_default_level_keeps_all(db, tree):
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    recorder = BatchRecorder(db, "模块", queue=pairs)  # 默认 INFO
    code = pairs[0][1].case_id
    recorder.on_log("10:00:00", f"[{code}] 正常日志")
    recorder.flush_logs()
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    with Session(db) as s:
        assert s.execute(
            text("SELECT COUNT(*) FROM tb_execution_log WHERE batch_id = :bid"),
            {"bid": recorder.batch_id},
        ).scalar_one() == 1


# ---------------------------------------------------------------- MainWindow 配置联动

@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, monkeypatch, db_engine, tmp_path):
    from app.main_window import MainWindow
    monkeypatch.setattr("app.main_window.WorkerThread", MagicMock)
    # 报告路径指向临时目录：媒体目录创建不得落到工作区之外
    # （LDM 默认值 C:\TestReports\HTML 仅属生产默认配置）
    save_config(db_engine, {"report_save_path": str(tmp_path / "reports")})
    w = MainWindow(("chrome", "C:/fake/chrome.exe"), db_engine=db_engine)
    yield w
    w.close()


@pytest.fixture
def no_dialogs(monkeypatch):
    """屏蔽配置页全部模态框（offscreen 下无人点击会永久阻塞）。"""
    shown = {"information": [], "warning": []}
    monkeypatch.setattr(
        "app.pages.batch_config_page.QMessageBox.information",
        lambda *a, **k: shown["information"].append(a[2]),
    )
    monkeypatch.setattr(
        "app.pages.batch_config_page.QMessageBox.warning",
        lambda *a, **k: shown["warning"].append(a[2]),
    )
    return shown


def test_worker_options_come_from_config(window):
    """验收：WorkerThread 启动参数来自配置表（默认配置 → 默认参数）。"""
    window._on_run_clicked()
    worker = window._worker
    kwargs = worker.set_runtime_options.call_args.kwargs
    assert kwargs["start_delay_sec"] == 2        # LDM 2.10 默认值
    assert kwargs["wait_until"] == "load"        # NORMAL → load
    assert kwargs["implicit_wait_ms"] == 5000    # 5s * 1000
    assert kwargs["exec_timeout_ms"] == 30000    # 30s * 1000（导航超时独立于隐式等待）
    assert kwargs["retry_count"] == 2
    assert kwargs["screenshot_on_fail"] is True
    assert kwargs["record_video"] is True
    assert kwargs["clear_cookies"] is True
    assert window._recorder is not None


def test_config_change_applies_on_next_run(window):
    """验收：修改配置后重启（重新运行）生效。"""
    save_config(window._db_engine, {
        "browser_type": "CHROMIUM",
        "start_delay_sec": 7,
        "page_load_strategy": "EAGER",
        "exec_timeout_sec": 60,
        "retry_count": 5,
        "log_level": "WARN",
        "screenshot_on_fail": 0,
        "record_video": 0,
        "clear_cookies": 0,
    })
    window._on_run_clicked()
    worker = window._worker
    kwargs = worker.set_runtime_options.call_args.kwargs
    assert kwargs["start_delay_sec"] == 7
    assert kwargs["wait_until"] == "domcontentloaded"  # EAGER 映射
    assert kwargs["exec_timeout_ms"] == 60000
    assert kwargs["retry_count"] == 5
    assert kwargs["screenshot_on_fail"] is False
    assert kwargs["record_video"] is False
    assert kwargs["clear_cookies"] is False
    # 浏览器内核：CHROMIUM → Playwright 内置（channel=None）
    browser_kwargs = worker.set_browser.call_args.kwargs
    assert browser_kwargs["channel"] is None
    # 日志级别联动：WARN 配置下 INFO 日志不入库
    assert window._recorder._min_level_rank >= 2


def test_batch_config_page_roundtrip(window, no_dialogs):
    """T12.2：配置页装载 → 表单收集 → 校验通过保存 → 读回一致。"""
    page = window.batch_config_page
    page.refresh()
    page.project_name.setText("联动测试项目")
    page.site_url.setText("https://192.168.3.150/")
    page.browser_type.setCurrentText("CHROMIUM")
    updates = page.collect_updates()
    assert page.validate(updates) is None  # 校验通过
    page._on_save()

    config = get_config(window._db_engine)
    assert config.project_name == "联动测试项目"
    assert config.site_url == "https://192.168.3.150/"
    assert config.browser_type == "CHROMIUM"
    assert no_dialogs["information"]      # 保存成功提示已弹出（非阻塞）
    assert not no_dialogs["warning"]


def test_batch_config_page_validation(window, no_dialogs):
    """T12.2 保存校验：CUSTOM 代理地址格式错误阻断保存，修正后可保存。"""
    page = window.batch_config_page
    page.refresh()
    page.proxy_mode.setCurrentText("CUSTOM")
    page.proxy_address.setText("192.168.1.1:8080")  # 缺 http:// 前缀
    page._on_save()
    assert no_dialogs["warning"] and "代理地址格式错误" in no_dialogs["warning"][0]
    assert not no_dialogs["information"]           # 校验失败：未保存
    assert get_config(window._db_engine).proxy_mode == "NO_PROXY"

    page.proxy_address.setText("http://192.168.1.1:8080")
    page._on_save()
    config = get_config(window._db_engine)
    assert config.proxy_mode == "CUSTOM"
    assert config.proxy_address == "http://192.168.1.1:8080"


def test_batch_config_page_site_url_validation(window, no_dialogs):
    """被测站点地址校验：空值/非法格式阻断保存，合法地址可保存。"""
    page = window.batch_config_page
    page.refresh()

    page.site_url.setText("")
    page._on_save()
    assert no_dialogs["warning"] and "被测站点地址不能为空" in no_dialogs["warning"][0]

    page.site_url.setText("192.168.3.150")
    page._on_save()
    assert "被测站点地址格式错误" in no_dialogs["warning"][-1]

    page.site_url.setText("http://192.168.3.150:8080/")
    page._on_save()
    assert get_config(window._db_engine).site_url == "http://192.168.3.150:8080/"


def test_run_rewrites_goto_origin_from_site_url(window):
    """配置页改 IP 后，运行期把用例 goto 的 origin 统一替换（不改数据库资产）。"""
    save_config(window._db_engine, {"site_url": "https://10.0.0.9/"})
    window._on_run_clicked()

    pairs = window._worker.set_queue.call_args.args[0]
    gotos = [s.selector for _, case in pairs for s in case.steps
             if s.action_type == "goto"]
    assert gotos
    assert all(url.startswith("https://10.0.0.9/") for url in gotos)

    # 数据库中的步骤仍保持原地址（只改内存 DTO）
    from app.db.repositories.case_repo import load_tree
    tree = load_tree(window._db_engine)
    db_gotos = [s.selector for m in tree for c in m.cases for s in c.steps
                if s.action_type == "goto"]
    assert all(url.startswith("https://192.168.3.102/") for url in db_gotos)


def test_media_dirs_follow_report_save_path(window):
    """媒体目录跟随配置的报告路径（不写工作区之外的默认路径）。"""
    from pathlib import Path
    screenshot_dir, video_dir = window._media_dirs(get_config(window._db_engine))
    assert Path(screenshot_dir).is_dir() and Path(video_dir).is_dir()
    assert Path(screenshot_dir).name == "screenshots"
    assert Path(video_dir).name == "videos"


# ---------------------------------------------------------------- 导航超时与隐式等待分离

class FakeTimeoutPage:
    """只记录 Playwright 超时设置的假页面。"""

    def __init__(self):
        self.default_timeout = None
        self.navigation_timeout = None

    def set_default_timeout(self, ms):
        self.default_timeout = ms

    def set_default_navigation_timeout(self, ms):
        self.navigation_timeout = ms


def test_goto_timeout_uses_exec_timeout_not_implicit_wait():
    """回归：设备站点加载慢时，goto 不应被 5s 隐式等待卡死。"""
    from app.engine.executor import AsyncPlaywrightActions
    page = FakeTimeoutPage()
    AsyncPlaywrightActions(page, implicit_wait_ms=5000, exec_timeout_ms=30000)
    assert page.default_timeout == 5000
    assert page.navigation_timeout == 30000
