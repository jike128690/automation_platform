"""启动环境自检测试（三级通道降级链路）。"""
import os

from app.utils import env_check
from app.utils.env_check import MISSING_BROWSER_MSG, check_browser_env


def test_browser_env_available():
    env = check_browser_env()
    assert env is not None
    assert env[0] in ("chrome", "msedge", "chromium")
    assert os.path.isfile(env[1])


def test_chrome_priority(monkeypatch):
    monkeypatch.setattr(env_check, "_system_browser", lambda basename, fallbacks: "C:/chrome.exe")
    monkeypatch.setattr(env_check, "_playwright_chromium", lambda: "C:/chromium.exe")
    assert check_browser_env() == ("chrome", "C:/chrome.exe")


def test_edge_fallback_when_no_chrome(monkeypatch):
    def fake_system(basename, fallbacks):
        return "C:/msedge.exe" if basename == "msedge.exe" else None

    monkeypatch.setattr(env_check, "_system_browser", fake_system)
    monkeypatch.setattr(env_check, "_playwright_chromium", lambda: None)
    assert check_browser_env() == ("msedge", "C:/msedge.exe")


def test_chromium_fallback(monkeypatch):
    monkeypatch.setattr(env_check, "_system_browser", lambda basename, fallbacks: None)
    monkeypatch.setattr(env_check, "_playwright_chromium", lambda: "C:/chromium.exe")
    assert check_browser_env() == ("chromium", "C:/chromium.exe")


def test_missing_all_returns_none(monkeypatch):
    monkeypatch.setattr(env_check, "_SYSTEM_CHANNELS", ())
    monkeypatch.setattr(env_check, "_playwright_chromium", lambda: None)
    assert check_browser_env() is None


def test_missing_message_is_standard():
    assert MISSING_BROWSER_MSG == "未检测到受支持的 Chrome/Edge 浏览器环境，请安装后重试"