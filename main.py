import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from app.config import APP_TITLE
from app.core.logger import logger, setup_logging
from app.main_window import MainWindow
from app.utils.env_check import MISSING_BROWSER_MSG, check_browser_env


def main():
    setup_logging()
    logger.info(f"{APP_TITLE} 启动")
    app = QApplication(sys.argv)
    env = check_browser_env()
    if env is None:
        logger.warning(MISSING_BROWSER_MSG)
        QMessageBox.critical(None, "环境检测", MISSING_BROWSER_MSG)
        sys.exit(1)
    logger.info(f"浏览器通道: {env[0]}")
    window = MainWindow(env)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()