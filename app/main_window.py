"""主窗口：三栏布局 + 顶部工具栏 + 页面切换 + 运行/停止联调（T8.1 核心闭环）。"""
import subprocess
from pathlib import Path

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
from app.db.engine import engine as default_db_engine
from app.db.migration import init_db
from app.db.repositories.case_repo import load_tree
from app.db.seed import seed_db
from app.db.services.batch_recorder import BatchRecorder
from app.db.services.config_service import WAIT_UNTIL_MAP, get_config
from app.db.services.history_service import cleanup_expired_media
from app.engine.worker_thread import WorkerThread
from app.pages.batch_config_page import BatchConfigPage
from app.pages.home_page import HomePage
from app.utils.mock_site import MockSite

EMPTY_QUEUE_MSG = "请至少勾选一条测试用例后再运行"  # 开放问题 04 默认方案


class MainWindow(QMainWindow):
    def __init__(self, browser_env=None, db_engine=None):
        super().__init__()
        self.browser_env = browser_env
        self._db_engine = db_engine or default_db_engine  # 测试可注入 tmp 库
        self._worker = None           # 当前执行工作线程（运行中持有）
        self._recorder = None         # 当前批次落库器（运行中持有，T11.2-11.4）
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)

        # 数据库启动期一次性初始化（低配机约束：启动期完成，运行期不查询）：
        # 迁移（幂等，客户端升级自动补齐）→ 种子（仅空库写入真实业务数据）。
        # 必须先于任何页面构造：批量配置页 __init__ 即读取 tb_system_config。
        init_db(self._db_engine)
        seed_db(self._db_engine)

        self._mock_site = MockSite()  # 内置 Mock 站点：随客户端生命周期启停（T8.1）
        self._mock_site.start()

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
        self.batch_config_page = BatchConfigPage(self._db_engine, self)
        self.batch_config_page.sig_back_home.connect(
            lambda: self.pages.setCurrentWidget(self.home_page)
        )
        self.pages.addWidget(self.batch_config_page)

        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.addWidget(toolbar)
        central_layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        # 库表已就绪，此时才加载用例树与读配置（媒体过期清理 T13.1，仅清文件不动记录）
        self.home_page.case_tree.load_modules(load_tree(self._db_engine))
        try:
            retention = get_config(self._db_engine).media_retention_days
            cleanup_expired_media(self._db_engine, retention)
        except Exception as exc:  # 清理失败不阻断启动
            logger.warning(f"媒体过期清理失败（忽略）: {exc}")

        self.btn_run.clicked.connect(self._on_run_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.btn_import.clicked.connect(self._show_todo)
        self.btn_batch.clicked.connect(self._show_batch_config)
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
        # 工作线程全链路：浏览器 + 队列 + 信号直连面板
        # T12.3：启动参数来自 tb_system_config（修改配置后重新运行即生效）
        config = get_config(self._db_engine)
        worker = WorkerThread()
        # 浏览器内核选择（图4）：CHROME → env_check 探测的本机内核；
        # CHROMIUM → Playwright 内置内核（用户显式选择，覆盖探测结果）
        if config.browser_type == "CHROME":
            channel, path = self.browser_env or ("chrome", "")
        else:
            channel, path = None, ""
        worker.set_browser(channel=channel, path=path, start_url=f"{MOCK_SITE_URL}/login")
        worker.set_queue(pairs)
        screenshot_dir, video_dir = self._media_dirs(config)
        worker.set_runtime_options(
            start_delay_sec=config.start_delay_sec,
            wait_until=WAIT_UNTIL_MAP[config.page_load_strategy],
            implicit_wait_ms=config.implicit_wait_sec * 1000,
            exec_timeout_ms=config.exec_timeout_sec * 1000,
            retry_count=config.retry_count,
            screenshot_on_fail=bool(config.screenshot_on_fail),
            screenshot_dir=screenshot_dir,
            record_video=bool(config.record_video),
            video_dir=video_dir,
            clear_cache=bool(config.clear_cache),
            clear_cookies=bool(config.clear_cookies),
            clear_history=bool(config.clear_history),
        )

        # 批次落库（T11.2-11.4）：建批 + 信号直连，回调在 WorkerThread 内写库
        module_names = ",".join(dict.fromkeys(m.module_name for m, _ in pairs))
        recorder = BatchRecorder(
            self._db_engine, module_names=module_names, queue=pairs,
            min_log_level=config.log_level,  # 图4 日志级别：低于阈值不入库
        )
        worker.sig_case_status_changed.connect(recorder.on_case_status)
        worker.sig_log_appended.connect(recorder.on_log)
        worker.sig_batch_finished.connect(recorder.on_batch_finished)
        # T12.3 失败自动截图：路径写入 result.screenshot_path
        worker.sig_media_saved.connect(recorder.update_case_media)
        self._recorder = recorder

        """
        信号桥接：工作线程 → 主线程（跨线程队列化投递，主线程事件循环中执行）
        """

        #worker 每拿到一帧画面，就发 sig_frame_ready，触发主界面浏览器视图的 set_frame 更新画面。
        worker.sig_frame_ready.connect(self.home_page.browser_view.set_frame)

        #worker 要高亮某个元素时，触发 set_highlight。
        worker.sig_highlight_element.connect(self.home_page.browser_view.set_highlight)

        #worker 更新用例状态，触发状态面板刷新。
        worker.sig_case_status_changed.connect(self.home_page.status_panel.update_status)

        #worker 产生新日志，触发日志面板追加一行。
        worker.sig_log_appended.connect(self.home_page.log_panel.append_log)

        #worker 整批任务结束，触发当前对象的收尾逻辑。
        worker.sig_batch_finished.connect(self._on_batch_finished)

        #把 worker 保存为实例属性，防止它被 Python 垃圾回收。
        self._worker = worker

        """
        后台执行线程启动
        """
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
        self._recorder = None  # 落库器随批次结束释放（日志已在 on_batch_finished 冲刷）
        logger.info(f"批次结束（手动停止={manual_stopped}）")

    def _set_secondary_enabled(self, enabled):
        for button in (self.btn_import, self.btn_batch, self.btn_export):
            button.setEnabled(enabled)

    def _show_todo(self):
        QMessageBox.information(self, "提示", "功能开发中")

    def _show_batch_config(self):
        """打开批量配置页（T12.2）：进入时刷新表单为当前配置。"""
        self.batch_config_page.refresh()
        self.pages.setCurrentWidget(self.batch_config_page)

    def _media_dirs(self, config):
        """截图/录像媒体目录：优先配置的报告路径，不可写时回退项目 data/media。"""
        base = Path(config.report_save_path) if config.report_save_path else None
        if base is not None:
            try:
                (base / "screenshots").mkdir(parents=True, exist_ok=True)
                (base / "videos").mkdir(parents=True, exist_ok=True)
                return str(base / "screenshots"), str(base / "videos")
            except OSError:
                logger.warning(f"报告路径不可写，媒体目录回退至 data/media: {base}")
        fallback = Path(__file__).resolve().parent.parent / "data" / "media"
        fallback.mkdir(parents=True, exist_ok=True)
        return str(fallback / "screenshots"), str(fallback / "videos")

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