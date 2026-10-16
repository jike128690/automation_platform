"""core 日志模块测试。"""
from app.core.logger import LOG_FILE, logger, setup_logging


def test_setup_logging_writes_log_file():
    setup_logging("DEBUG")
    logger.info("loguru 自检消息")
    assert LOG_FILE.exists()


def test_logger_exported():
    assert logger is not None