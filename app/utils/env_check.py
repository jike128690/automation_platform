"""启动环境自检（浏览器/驱动检测）。"""
import glob
import os
import winreg

_BROWSERS_DIR = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "ms-playwright"
)


def _registry_app_path(name: str) -> str | None:
    key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + name
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "")
        except OSError:
            continue
        if value and os.path.isfile(value):
            return value
    return None


def _system_browser(basename: str, *candidates: str) -> str | None:
    path = _registry_app_path(basename)
    if path:
        return path
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _playwright_chromium() -> str | None:
    for pattern in ("chromium-*/chrome-win/chrome.exe", "chromium-*/chrome-win64/chrome.exe"):
        for path in glob.glob(os.path.join(_BROWSERS_DIR, pattern)):
            if os.path.isfile(path):
                return path
    return None


def check_browser_env() -> tuple[str, str] | None:
    """返回 (浏览器来源, 可执行文件路径)；均不可用时返回 None。"""
    checks = (
        ("chrome", _system_browser(
            "chrome.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        )),
        ("msedge", _system_browser(
            "msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        )),
        ("chromium", _playwright_chromium()),
    )
    for source, path in checks:
        if path:
            return source, path
    return None
