"""主窗口：三栏布局 + 顶部工具栏 + 页面切换 + 运行/停止联调（T8.1 核心闭环）。"""
import subprocess

from loguru import logger
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton, PushButton

from app.config import APP_TITLE, MOCK_SITE_URL
from app.data.demo_cases import DEMO_MODULES
from app.engine.worker_thread import WorkerThread
from app.pages.home_page import HomePage
from app.utils.mock_site import MockSite

EMPTY_QUEUE_MSG = "请至少勾选一条测试用例后再运行"  # 开放问题 04 默认方案


class MainWindow(QMainWindow):
    def __init__(self, browser_env=None):
        super().__init__()
        self.browser_env = browser_env
        self._worker = None           # 当前执行工作线程（运行中持有）
        self._mock_site = MockSite()  # 内置 Mock 站点：随客户端生命周期启停（T8.1）
        self._mock_site.start()
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

        self.home_page.case_tree.load_modules(DEMO_MODULES)

        self.btn_run.clicked.connect(self._on_run_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.btn_import.clicked.connect(self._show_todo)
        self.btn_batch.clicked.connect(self._show_todo)
        self.btn_export.clicked.connect(self._show_todo)

    # ---- 运行/停止核心控制（5.1.2 状态互斥） ----

    def _on_run_clicked(self):
        """启动批次：校验勾选 → 清空/初始化面板 → 锁定互斥 → 启动 WorkerThread。"""
        pairs = self.home_page.case_tree.selected_pairs()
        if not pairs:
            QMessageBox.information(self, "提示", EMPTY_QUEUE_MSG)
            return
        # 新一轮清空日志与状态队列（5.1.6 清空策略 / 5.1.5）
        self.home_page.log_panel.clear_log()
        self.home_page.status_panel.load_queue(pairs)
        # 运行期锁定（5.1.3 左侧 / 5.1.4 画布受控）
        self.home_page.case_tree.set_locked(True)
        self.home_page.browser_view.set_controlled(True)
        # 工具栏互斥：运行禁用、停止高亮、二级入口一并置灰（开放问题 03）
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText("□ 停止测试")
        self._set_secondary_enabled(False)
        # 工作线程全链路：浏览器(Mock 站点) + 队列 + 5 信号直连面板
        worker = WorkerThread()
        channel, path = self.browser_env or ("chrome", "")
        worker.set_browser(channel=channel, path=path, start_url=f"{MOCK_SITE_URL}/login")
        worker.set_queue(pairs)
        worker.sig_frame_ready.connect(self.home_page.browser_view.set_frame)
        worker.sig_highlight_element.connect(self.home_page.browser_view.set_highlight)
        worker.sig_case_status_changed.connect(self.home_page.status_panel.update_status)
        worker.sig_log_appended.connect(self.home_page.log_panel.append_log)
        worker.sig_batch_finished.connect(self._on_batch_finished)
        self._worker = worker
        worker.start()

    def _on_stop_clicked(self):
        """请求安全停止：置停止过渡态（5.1.2），线程在下一个步骤边界安全退出。"""
        if self._worker is None:
            return
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("正在停止...")
        self._worker.request_stop()

    def _on_batch_finished(self, manual_stopped):
        """批次结束：恢复空闲态（解锁左侧、解除受控、工具栏互斥还原、释放线程引用）。"""
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("□ 停止测试")
        self._set_secondary_enabled(True)
        self.home_page.case_tree.set_locked(False)
        self.home_page.browser_view.set_controlled(False)
        self._worker = None
        logger.info(f"批次结束（手动停止={manual_stopped}）")

    def _set_secondary_enabled(self, enabled):
        for button in (self.btn_import, self.btn_batch, self.btn_export):
            button.setEnabled(enabled)

    def _show_todo(self):
        QMessageBox.information(self, "提示", "功能开发中")

    # ---- 关闭拦截：第二级防僵尸回收（cdp.md 2.4） ----

    def closeEvent(self, event):
        """窗口关闭：线程运行中先请求停止并等待≤2s；超时对浏览器进程树兜底强杀（第三级）；
        最后关闭 Mock 站点，保证零残留进程。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.request_stop()
            if not worker.wait(2000):
                pid = worker.browser_pid() if hasattr(worker, "browser_pid") else None
                if pid:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True, check=False)
        self._mock_site.stop()
        event.accept()