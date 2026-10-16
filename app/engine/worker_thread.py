"""QThread 工作线程（信号定义，见开发计划 6.3）。"""
from PyQt6.QtCore import QThread, pyqtSignal


class WorkerThread(QThread):
    """后台执行线程，仅通过信号向主线程推送数据（见 4.3.2 全异步线程模型）。"""

    sig_frame_ready = pyqtSignal(bytes, str)
    sig_highlight_element = pyqtSignal(dict, str)
    sig_case_status_changed = pyqtSignal(str, str)
    sig_log_appended = pyqtSignal(str, str)
    sig_batch_finished = pyqtSignal(bool)

    def run(self):
        # T4.3 接入队列执行器
        pass