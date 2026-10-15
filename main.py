import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow
from app.utils.env_check import check_browser_env


def main():
    app = QApplication(sys.argv)
    env = check_browser_env()
    if env is None:
        QMessageBox.critical(None, "环境检测", "未检测到受支持的 Chrome/Edge 浏览器环境，请安装后重试")
        sys.exit(1)
    window = MainWindow(env)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
