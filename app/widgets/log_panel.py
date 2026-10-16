"""日志面板：实时日志流（5.1.6）——时间戳格式、批量刷新、自动滚动、只读可复制。"""
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

BATCH_MS = 100     # 日志批量刷新间隔（开发计划第 9 节：100ms 合并，低配机防卡顿）
MAX_LINES = 2000   # 最大行数，超出自动裁剪最旧日志


class LogPanel(QWidget):
    """下半区日志面板：工作线程每步触发 sig_log_appended → append_log 入缓冲批量渲染。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)  # 只读可复制（5.1.6）
        self._pending = []           # 待写入的日志行（批量合并）
        self._timer = QTimer(self)   # 100ms 单次刷新定时器
        self._timer.setInterval(BATCH_MS)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)

    def append_log(self, timestamp: str, message: str):
        """追加一条日志（入缓冲，100ms 合并刷新）；格式 `[{HH:mm:ss}] {消息}`。"""
        self._pending.append(f"[{timestamp}] {message}")
        if not self._timer.isActive():
            self._timer.start()

    def clear_log(self):
        """清空日志与缓冲（每次新运行测试前调用，5.1.6 清空策略）。"""
        self._pending.clear()
        self._timer.stop()
        self.view.clear()

    def _flush(self):
        """批量写入缓冲日志：追加文本、滚动到底部、裁剪超限行数。"""
        if not self._pending:
            return
        self.view.appendPlainText("\n".join(self._pending))
        self._pending.clear()
        self._trim()
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _trim(self):
        """超过 MAX_LINES 行时删除最旧日志，并把光标移回末尾保证后续追加位置正确。"""
        if self.view.blockCount() <= MAX_LINES:
            return
        lines = self.view.toPlainText().split("\n")
        self.view.setPlainText("\n".join(lines[-MAX_LINES:]))
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.view.setTextCursor(cursor)