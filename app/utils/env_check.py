"""启动环境自检（三级浏览器通道探测与自动降级）。"""
import glob
import os
import winreg

MISSING_BROWSER_MSG = "未检测到受支持的 Chrome/Edge 浏览器环境，请安装后重试"

_BROWSERS_DIR = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "ms-playwright"
)

# 系统通道按优先级排列：避免打包初期捆绑数百 MB 的 Chromium，优先复用本机 Chrome/Edge
_SYSTEM_CHANNELS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("chrome", "chrome.exe", (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )),
    ("msedge", "msedge.exe", (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )),
)


def _registry_app_path(name: str) -> str | None:
    """注册表探测：查 App Paths（HKLM/HKCU）安装器写入的可执行文件路径。"""
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


def _system_browser(basename: str, fallbacks: tuple[str, ...]) -> str | None:
    return _registry_app_path(basename) or next(
        (p for p in fallbacks if os.path.isfile(p)), None
    )


def _playwright_chromium() -> str | None:
    """缓存目录探测：查 %LOCALAPPDATA%/ms-playwright 下内置 Chromium。"""
    for pattern in ("chromium-*/chrome-win/chrome.exe", "chromium-*/chrome-win64/chrome.exe"):
        for path in glob.glob(os.path.join(_BROWSERS_DIR, pattern)):
            if os.path.isfile(path):
                return path
    return None


def check_browser_env() -> tuple[str, str] | None:
    """三级通道自动降级：Chrome → Edge → Playwright Chromium；全部缺失返回 None。"""
    for channel, basename, fallbacks in _SYSTEM_CHANNELS:
        path = _system_browser(basename, fallbacks)
        if path:
            return channel, path
    chromium = _playwright_chromium()
    if chromium:
        return "chromium", chromium
    return None