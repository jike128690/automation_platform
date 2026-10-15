"""启动环境自检测试。"""
import os

from app.utils.env_check import check_browser_env


def test_browser_env_available():
    env = check_browser_env()
    assert env is not None
    assert env[0] in ("chrome", "msedge", "chromium")
    assert os.path.isfile(env[1])
