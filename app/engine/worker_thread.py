"""QThread 工作线程（信号定义 + 队列执行入口）。"""
from PyQt6.QtCore import QThread, pyqtSignal

from app.engine.executor import QueueExecutor


class WorkerThread(QThread):
    """后台执行线程，仅通过信号向主线程推送数据（见 4.3.2 全异步线程模型）。"""

    sig_frame_ready = pyqtSignal(bytes, str)
    sig_highlight_element = pyqtSignal(dict, str)
    sig_case_status_changed = pyqtSignal(str, str)
    sig_log_appended = pyqtSignal(str, str)
    sig_batch_finished = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._case_pairs = []
        self._runner = None
        self._pending_stop = False
        self._executor = None

    def set_queue(self, case_pairs):
        self._case_pairs = list(case_pairs)

    def set_step_runner(self, runner):
        self._runner = runner

    def request_stop(self):
        self._pending_stop = True
        if self._executor is not None:
            self._executor.request_stop()

    def run(self):
        if not self._case_pairs or self._runner is None:
            self.sig_batch_finished.emit(self._pending_stop)
            return
        executor = QueueExecutor(
            runner=self._runner,
            on_status=lambda cid, st: self.sig_case_status_changed.emit(cid, st),
            on_log=lambda ts, msg: self.sig_log_appended.emit(ts, msg),
            on_finished=lambda manual: self.sig_batch_finished.emit(manual),
        )
        self._executor = executor
        if self._pending_stop:
            executor.request_stop()
        executor.run(self._case_pairs)
        self._executor = None