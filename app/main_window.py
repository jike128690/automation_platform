"""主窗口：三栏布局 + 顶部工具栏 + 页面切换。"""
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton, PushButton

from app.config import APP_TITLE
from app.pages.home_page import HomePage


class MainWindow(QMainWindow):
    def __init__(self, browser_env=None):
        super().__init__()
        self.browser_env = browser_env
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)

        self.btn_run = PrimaryPushButton("▷ 运行测试", self)
        self.btn_stop = PushButton("□ 停止测试", self)
        self.btn_stop.setEnabled(False)
        self.btn_import = PushButton("导入用例", self)
        self.btn_batch = PushButton("批量配置", self)
        self.btn_export = PushButton("导出报告", self)

        toolbar = QWidget(self)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.addWidget(self.btn_run)
        toolbar_layout.addWidget(self.btn_stop)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.btn_import)
        toolbar_layout.addWidget(self.btn_batch)
        toolbar_layout.addWidget(self.btn_export)

        self.pages = QStackedWidget(self)
        self.home_page = HomePage(self)
        self.pages.addWidget(self.home_page)

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.addWidget(toolbar)
        central_layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        self.btn_import.clicked.connect(self._show_todo)
        self.btn_batch.clicked.connect(self._show_todo)
        self.btn_export.clicked.connect(self._show_todo)

    def _show_todo(self):
        QMessageBox.information(self, "提示", "功能开发中")
