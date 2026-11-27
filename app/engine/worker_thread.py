"""QThread 工作线程：Qt 主线程 + asyncio 工作循环的双事件循环桥接。

架构：PyQt6 GUI 事件循环运行在主线程；Playwright 基于 asyncio 实现高并发 CDP 通信，
因此引擎采用「主线程 Qt 循环 + 工作线程 asyncio 独立循环」双循环隔离架构：
  run() 在工作线程内创建独立 asyncio 事件循环并运行 _async_main()，
  期间通过 5 个 Qt 信号（QueuedConnection）把帧/状态/日志/高亮跨线程投递给主线程，
  避免主线程阻塞，也避免任何跨线程直接操作控件（4.3.2 全异步线程模型）。

信号契约与开发计划 6.3 / cdp.md 3.1 对齐；sig_frame_ready 携带 QImage——
工作线程只创建 QImage（平台无关、可安全跨线程），严禁创建 QPixmap（cdp.md 陷阱一）。

浏览器生命周期（cdp.md 2.4 三级回收的第一级）：
  _async_main 的 finally 中逆序关闭：停止截图流 → 剥离 CDPSession → close page →
  browser.close() → playwright.stop()，保证正常/手动停止后零残留 chrome.exe 进程。

使用方式（主线程侧）：
  worker = WorkerThread()
  worker.set_queue(pairs)              # 要执行的 (模块, 用例) 队列（可选）
  worker.set_actions(actions)          # 页面动作执行器（阶段四 Playwright 实现 / 测试 Fake）
  worker.set_browser("chrome", None, (1280, 800), "http://127.0.0.1:8765")  # 浏览器配置
  worker.sig_frame_ready.connect(...)  # 按需订阅信号
  worker.start()
  停止：worker.request_stop() —— 异步主流程在检查点安全退出。
"""
import asyncio
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage
from loguru import logger
from playwright.async_api import async_playwright

from app.engine.cdp_stream import CDPStreamClient
from app.engine.executor import AsyncExecutor, AsyncPlaywrightActions

DEFAULT_VIEWPORT = (1280, 800)  # 与 cdp.md 固定视口一致，画布等比缩放的基准


class WorkerThread(QThread):
    """后台执行线程：承载 asyncio 事件循环，仅通过信号向主线程推送数据。

    5 个信号与开发计划 6.3 节定义一一对应：
      主线程只需 connect 这些信号即可拿到工作线程的数据；
      跨线程连接默认走队列化投递（queued），回调在主线程事件循环中执行。
    """

    # CDP 截图帧解码为 QImage 后 + 当前页面 URL
    # 主线程处理：渲染至中间画布、同步只读地址栏（M5）
    sig_frame_ready = pyqtSignal(QImage, str)

    # 元素动作执行前：BoundingBox 矩形（视口坐标，已按缩放系数换算）+ 气泡文案
    # 主线程处理：画布叠加层绘制红框/手型/气泡（M5，不注入真实 DOM）
    sig_highlight_element = pyqtSignal(dict, str)

    # 用例状态变更：case_id + running/passed/failed
    # 主线程处理：更新右栏状态队列行、统计栏与进度条（M6）
    sig_case_status_changed = pyqtSignal(str, str)

    # 实时日志：HH:mm:ss 时间戳 + 消息内容
    # 主线程处理：追加到日志面板并自动滚动到底部（M6）
    sig_log_appended = pyqtSignal(str, str)

    # 批次执行完毕或安全停止：True=手动停止，False=全部执行完成
    # 主线程处理：关闭指示灯、解锁左侧控件、保留进度与日志（M6）
    sig_batch_finished = pyqtSignal(bool)

    # 失败自动截图已保存：case_id + 本地路径（T12.3，screenshot_on_fail 启用时）
    # 主线程处理：桥接 BatchRecorder.update_case_media 写入 screenshot_path
    sig_media_saved = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._case_pairs = []          # 待执行队列，set_queue 写入（须在 start() 前设置）
        self._actions = None           # 页面动作执行器（AsyncPageActions 协议）
        self._visual_pause = 0.35      # 高亮观察停顿（cdp.md 2.3，验证脚本可调小提速）
        self._post_pause = 0.15        # 动作后画面消化等待
        self._stop_requested = False   # 停止标志（布尔原子写：主线程置位、工作线程轮询）
        self._executor = None          # 队列执行期间持有的执行器引用，供 request_stop 转发
        # 浏览器配置（由 env_check 探测结果 + 启动参数组合）
        self._browser_channel = None   # "chrome" | "msedge" | None（None=Playwright 内置 Chromium）
        self._browser_path = None
        self._viewport = DEFAULT_VIEWPORT
        self._start_url = None         # 为 None 则不启动浏览器（纯队列/测试场景）
        # 运行时资源（run() 期间创建，_shutdown_browser 逆序释放）
        self._loop = None
        self._playwright = None
        self._browser = None
        self._browser_process = None  # 浏览器宿主进程（closeEvent 第三级兜底强杀用）
        self._page = None
        self._stream = None
        # 批量配置运行时选项（set_runtime_options 注入，默认值 = 无联动）
        self._start_delay_sec = 0
        self._wait_until = "domcontentloaded"
        self._implicit_wait_ms = None
        self._retry_count = 0
        self._screenshot_on_fail = False
        self._screenshot_dir = None
        self._record_video = False
        self._video_dir = None
        self._clear_cache = False
        self._clear_cookies = False
        self._clear_history = False

    def set_queue(self, case_pairs):
        """设置本次要执行的 (TestModule, TestCase) 队列（须在 start() 前调用）。"""
        self._case_pairs = list(case_pairs)

    def set_actions(self, actions):
        """注入页面动作执行器（AsyncPageActions 协议：Playwright 实现或测试 Fake）。"""
        self._actions = actions

    def set_rhythm(self, visual_pause: float, post_pause: float):
        """调整标准节拍停顿（秒）：真机演示/验证可调小提速，默认 0.35/0.15。"""
        self._visual_pause = visual_pause
        self._post_pause = post_pause

    def set_browser(self, channel=None, path=None, viewport=DEFAULT_VIEWPORT, start_url=None):
        """配置浏览器：channel/path 来自 env_check 三级探测；start_url 为要访问的页面。
        仅当 start_url 非 None 时才会真正启动浏览器与截图流。
        """
        self._browser_channel = channel
        self._browser_path = path
        self._viewport = viewport
        self._start_url = start_url

    def set_runtime_options(self, start_delay_sec: int = 0,
                            wait_until: str = "domcontentloaded",
                            implicit_wait_ms: int | None = None,
                            retry_count: int = 0,
                            screenshot_on_fail: bool = False,
                            screenshot_dir: str | None = None,
                            record_video: bool = False,
                            video_dir: str | None = None,
                            clear_cache: bool = False,
                            clear_cookies: bool = False,
                            clear_history: bool = False):
        """注入批量配置运行时选项（T12.3：启动参数来自 tb_system_config）。

        每次点击【运行测试】由主线程读取配置后调用 —— 修改配置后重新运行
        即生效（运行中的批次不受影响）。
        """
        self._start_delay_sec = max(0, int(start_delay_sec))
        self._wait_until = wait_until
        self._implicit_wait_ms = implicit_wait_ms
        self._retry_count = retry_count
        self._screenshot_on_fail = screenshot_on_fail
        self._screenshot_dir = screenshot_dir
        self._record_video = record_video
        self._video_dir = video_dir
        self._clear_cache = clear_cache
        self._clear_cookies = clear_cookies
        self._clear_history = clear_history

    def request_stop(self):
        """请求安全停止（主线程调用）。

        置位线程安全停止标志；若队列执行器已创建则立即转发，
        执行引擎在下一个步骤边界响应；异步主流程在检查点安全退出。
        """
        logger.info("收到停止请求")
        self._stop_requested = True
        if self._executor is not None:
            self._executor.request_stop()

    def is_stop_requested(self) -> bool:
        """供异步主流程轮询的停止状态（线程安全读）。"""
        return self._stop_requested

    def browser_pid(self):
        """当前浏览器宿主进程 PID（无浏览器/已回收返回 None；closeEvent 第三级兜底强杀用）。"""
        process = self._browser_process
        return process.pid if process is not None else None

    def run(self):
        """线程入口：创建独立 asyncio 事件循环，运行异步主流程，结束后关闭循环。"""
        logger.info("工作线程启动")
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        finally:
            self._loop.close()
            self._loop = None
            logger.info("工作线程结束")

    async def _async_main(self):
        """异步主流程：可选启动浏览器/截图流 → 异步队列执行或演示模式 → 资源回收。"""
        try:
            if self._start_url:
                await self._launch_browser()
                await self._start_screencast()
                # 真实执行路径：动作执行器绑定真实页面（T12.3：注入批量配置选项）
                self._actions = self._actions or AsyncPlaywrightActions(
                    self._page,
                    wait_until=self._wait_until,
                    implicit_wait_ms=self._implicit_wait_ms,
                    clear_cache=self._clear_cache,
                    clear_cookies=self._clear_cookies,
                    clear_history=self._clear_history,
                    screenshot_dir=self._screenshot_dir,
                    screenshot_on_fail=self._screenshot_on_fail,
                )

            # 队列非空且动作执行器已注入 → 异步队列执行；
            # 否则 start_url 非 None → 浏览器演示模式（持续推进截图流直到停止）；
            # 否则直接宣告批次结束（无队列且无页面）。
            if self._case_pairs and self._actions is not None:
                # 阶段四：AsyncExecutor 异步动作编排（标准节拍 + 高亮信号）
                await self._run_queue_async()
            elif self._start_url:
                # 浏览器演示模式：持续推进截图流直到收到停止请求
                while not self._stop_requested:
                    await asyncio.sleep(0.2)
                self.sig_batch_finished.emit(self._stop_requested)
            else:
                # 未配置任何任务（无队列且无页面）：直接宣告结束
                self.sig_batch_finished.emit(self._stop_requested)
        finally:
            await self._shutdown_browser()  # 第一级回收，防僵尸进程

    async def _launch_browser(self):
        """Headless 启动 Playwright 浏览器（按 env_check 通道 + 固定视口）并打开页面。"""
        self._playwright = await async_playwright().start()
        kwargs = {"headless": True}
        if self._browser_channel:  # chrome / msedge：复用本机内核，降低安装包体积
            kwargs["channel"] = self._browser_channel
        self._browser = await self._playwright.chromium.launch(**kwargs)
        self._browser_process = getattr(self._browser, "process", None)  # Popen 或 None
        page_kwargs = {
            "viewport": {"width": self._viewport[0], "height": self._viewport[1]},
            # 设备站点常用自签/过期证书（如 192.168.3.102 的 mkcert 证书），
            # 不忽略会停在 chrome-error://chromewebdata 拦截页（ERR_CERT_AUTHORITY_INVALID）
            "ignore_https_errors": True,
        }
        if self._record_video and self._video_dir:  # T12.3：录制执行过程（配置开关）
            # 录制参数属于浏览器上下文，只能随 new_page 传入（launch 不接受）
            Path(self._video_dir).mkdir(parents=True, exist_ok=True)
            page_kwargs["record_video_dir"] = self._video_dir
            page_kwargs["record_video_size"] = {"width": self._viewport[0],
                                                "height": self._viewport[1]}
        self._page = await self._browser.new_page(**page_kwargs)
        await self._page.goto(self._start_url, wait_until=self._wait_until)
        logger.info(f"Headless 浏览器已启动（channel={self._browser_channel or 'chromium'}）")

    async def _start_screencast(self):
        """开启 CDP 截图流，帧回调直接桥接 sig_frame_ready。
        emit() 是 Qt 信号对象的方法
        作用是：发射信号，把这个信号和参数通知给所有连接了它的槽函数/回调。
        """
        self._stream = CDPStreamClient(
            self._page,
            on_frame_callback=lambda qimg, url: self.sig_frame_ready.emit(qimg, url),
        )
        await self._stream.start()

    async def _run_queue_async(self):
        """异步队列执行：AsyncExecutor 回调全部桥接为 Qt 信号。"""
        if self._start_delay_sec > 0:  # T12.3：测试启动前延迟（图3 配置）
            logger.info(f"启动前延迟 {self._start_delay_sec}s（批量配置）")
            await asyncio.sleep(self._start_delay_sec)

        executor = AsyncExecutor(
            actions=self._actions,
            on_status=lambda cid, st: self.sig_case_status_changed.emit(cid, st),
            on_log=lambda ts, msg: self.sig_log_appended.emit(ts, msg),
            on_finished=lambda manual: self.sig_batch_finished.emit(manual),
            on_highlight=lambda rect, tooltip: self.sig_highlight_element.emit(rect, tooltip),
            on_media=lambda cid, path: self.sig_media_saved.emit(cid, path),
            visual_pause=self._visual_pause,
            post_pause=self._post_pause,
            retry_count=self._retry_count,
        )
        self._executor = executor
        if self._stop_requested:
            executor.request_stop()
        await executor.run(self._case_pairs)
        self._executor = None

    async def _shutdown_browser(self):
        """第一级资源回收（cdp.md 2.4）：逆序关闭截图流 → 会话 → 页面 → 浏览器 → Playwright。
        各步独立 try 包裹，保证中途异常不阻断后续清理。
        """
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None
        if self._page is not None:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._browser_process = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None