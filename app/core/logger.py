"""全局日志配置（loguru）。

loguru 的 logger 是全局单例：各模块直接 `from loguru import logger` 即可共享，
只需在程序入口（main.py）调用一次 setup_logging() 配置控制台与文件输出。
"""
import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path(__file__).resolve().parents[2] / "log"
LOG_FILE = LOG_DIR / "app.log"


def setup_logging(level: str = "INFO") -> None:
    """初始化日志输出：移除默认处理器，改为 控制台(stderr) + 文件(log/app.log)。

    Args:
        level: 日志级别 DEBUG/INFO/WARNING/ERROR（阶段二可接入批量配置的日志级别项）。
    文件策略：10 MB 轮转、保留 7 天、UTF-8 编码（Windows 中文日志必需）。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level)
    logger.add(str(LOG_FILE), level=level, rotation="10 MB", retention="7 days", encoding="utf-8")