"""QThread 工作线程：信号定义 + 队列执行入口。

架构位置（见开发计划 4.2 分层架构 / 4.3.2 全异步线程模型）：
  GUI 主线程只负责渲染 UI 与响应信号；
  所有 Playwright 执行、队列调度、截图流解码等耗时操作都在本工作线程完成；
  工作线程与主线程之间**仅通过 Qt 信号**传递数据，
  避免任何跨线程直接调用控件，保证主线程永不阻塞、不崩溃。

使用方式（主线程侧）：
  worker = WorkerThread()
  worker.set_queue(pairs)          # 要执行的 (模块, 用例) 队列
  worker.set_step_runner(runner)   # 步骤执行器（T4.4=Playwright，测试=FakeRunner）
  worker.sig_case_status_changed.connect(...)   # 按需订阅信号
  worker.start()
  停止：worker.request_stop() —— 线程在下一个步骤边界安全退出。
"""
from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

from app.engine.executor import QueueExecutor


class WorkerThread(QThread):
    """后台执行线程，仅通过信号向主线程推送数据。

    5 个信号与开发计划 6.3 节定义一一对应：
      主线程只需 connect 这些信号即可拿到工作线程的数据；
      跨线程连接默认走队列化投递（queued），回调在主线程事件循环中执行。
    """

    # CDP 收到新画面帧：base64 解码后的 JPEG 字节 + 当前页面 URL
    # 主线程处理：渲染至中间画布、同步只读地址栏（M5）
    sig_frame_ready = pyqtSignal(bytes, str)

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._case_pairs = []        # 待执行队列，set_queue 写入（须在 start() 前设置）
        self._runner = None          # 步骤执行器（StepRunner 协议）
        self._pending_stop = False   # 停止标志：线程启动前就被置位时也要生效
        self._executor = None        # run() 执行期间持有的执行器引用，供 request_stop 转发

    def set_queue(self, case_pairs):
        """设置本次要执行的 (TestModule, TestCase) 队列（须在 start() 前调用）。"""
        self._case_pairs = list(case_pairs)

    def set_step_runner(self, runner):
        """注入步骤执行器（StepRunner 协议，T4.4 接入 Playwright 实现）。"""
        self._runner = runner

    def request_stop(self):
        """请求安全停止（主线程调用）。

        先记下待处理标志，覆盖「栈还没建好就收到停止」的场景；
        若执行器已创建，立即转发停止请求，执行引擎在下一个步骤边界响应。
        """
        logger.info("收到停止请求")
        self._pending_stop = True
        if self._executor is not None:
            self._executor.request_stop()

    def run(self):
        """线程主体：创建执行器，并把回调桥接成 Qt 信号。"""
        logger.info("工作线程启动")
        # 队列或执行器缺失（如未配置直接 start）时不执行任何任务，直接宣告结束
        if not self._case_pairs or self._runner is None:
            logger.warning("工作线程启动但队列或执行器未配置")
            self.sig_batch_finished.emit(self._pending_stop)
            return
        # 执行器的工作线程回调 → 信号发射（接收方在主线程，自动队列化投递）
        executor = QueueExecutor(
            runner=self._runner,
            on_status=lambda cid, st: self.sig_case_status_changed.emit(cid, st),
            on_log=lambda ts, msg: self.sig_log_appended.emit(ts, msg),
            on_finished=lambda manual: self.sig_batch_finished.emit(manual),
        )
        self._executor = executor
        # 启动前就收到过停止请求也要生效
        if self._pending_stop:
            executor.request_stop()
        executor.run(self._case_pairs)
        self._executor = None  # 执行结束，释放引用
        logger.info("工作线程结束")