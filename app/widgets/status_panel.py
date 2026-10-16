"""右侧状态面板：统计栏 + 进度条 + 用例状态队列（5.1.5）。"""
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

STATUS_WAITING = "waiting"  # 等待中（与 sig_case_status_changed 状态枚举一致）
STATUS_RUNNING = "running"  # 进行中
STATUS_PASSED = "passed"    # 已通过
STATUS_FAILED = "failed"    # 测试执行失败

_STATUS_MARK = {
    STATUS_WAITING: "⏳",
    STATUS_RUNNING: "🟢",
    STATUS_PASSED: "✔",
    STATUS_FAILED: "✖",
}
_STATUS_COLOR = {STATUS_FAILED: QColor("#D32F2F")}
_STATUS_ROLE = Qt.ItemDataRole.UserRole + 1  # 树节点存当前状态


class StatusPanel(QWidget):
    """上半区：已执行/成功/失败统计 + 进度条 + 状态队列（仅展示本次勾选用例）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total = 0
        self.executed = 0
        self.passed = 0
        self.failed = 0

        self.executed_label = QLabel("已执行: 0/0", self)
        self.passed_label = QLabel("成功: 0", self)
        self.failed_label = QLabel("失败: 0", self)
        stats = QHBoxLayout()
        stats.addWidget(self.executed_label)
        stats.addWidget(self.passed_label)
        stats.addWidget(self.failed_label)
        stats.addStretch(1)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setTextVisible(False)
        self.progress_label = QLabel("0% (0/0)", self)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label)

        self.queue = QTreeWidget(self)
        self.queue.setHeaderHidden(True)

        layout = QVBoxLayout(self)
        layout.addLayout(stats)
        layout.addLayout(progress_row)
        layout.addWidget(self.queue, 1)

    def load_queue(self, case_pairs):
        """初始化本次勾选队列：模块行 + 用例行（全部 waiting），并重置统计。"""
        self.queue.clear()
        self.total = len(case_pairs)
        self.executed = self.passed = self.failed = 0
        last_module = None
        module_item = None
        for module, case in case_pairs:
            if module is not last_module:
                module_item = QTreeWidgetItem(self.queue)
                module_item.setData(0, Qt.ItemDataRole.UserRole, module)
                module_item.setText(0, f"{_STATUS_MARK[STATUS_WAITING]} {module.module_name}")
                last_module = module
            case_item = QTreeWidgetItem(module_item)
            case_item.setData(0, Qt.ItemDataRole.UserRole, case)
            case_item.setData(0, _STATUS_ROLE, STATUS_WAITING)
            case_item.setText(0, f"{_STATUS_MARK[STATUS_WAITING]} [{case.case_id}] {case.case_title}")
        self.queue.expandAll()
        self._refresh_stats()

    def update_status(self, case_id: str, status: str):
        """用例状态变更：更新对应行（文本/颜色）、模块聚合、统计与进度，并聚焦当前行。"""
        for i in range(self.queue.topLevelItemCount()):
            module_item = self.queue.topLevelItem(i)
            for j in range(module_item.childCount()):
                case_item = module_item.child(j)
                case = case_item.data(0, Qt.ItemDataRole.UserRole)
                if case.case_id == case_id:
                    self._apply_case_status(case_item, case, status)
                    self._refresh_module(module_item)
                    self.queue.scrollToItem(case_item, QTreeWidget.ScrollHint.PositionAtCenter)
                    self._refresh_stats()
                    return

    def _apply_case_status(self, case_item, case, status):
        """更新用例行文本/颜色，并迁移 executed/passed/failed 计数（仅结果类状态计数）。"""
        old = case_item.data(0, _STATUS_ROLE)
        case_item.setData(0, _STATUS_ROLE, status)
        case_item.setText(0, f"{_STATUS_MARK[status]} [{case.case_id}] {case.case_title}")
        color = _STATUS_COLOR.get(status)
        case_item.setForeground(0, color if color else QBrush())
        if old in (STATUS_PASSED, STATUS_FAILED):
            self.executed -= 1
            self.passed -= old == STATUS_PASSED
            self.failed -= old == STATUS_FAILED
        if status in (STATUS_PASSED, STATUS_FAILED):
            self.executed += 1
            self.passed += status == STATUS_PASSED
            self.failed += status == STATUS_FAILED

    def _refresh_module(self, module_item):
        """模块行聚合：进行中 > 有失败 > 全部通过(已完成) > 等待中。"""
        module = module_item.data(0, Qt.ItemDataRole.UserRole)
        states = [module_item.child(j).data(0, _STATUS_ROLE) for j in range(module_item.childCount())]
        suffix = ""
        if STATUS_RUNNING in states:
            mark = _STATUS_MARK[STATUS_RUNNING]
        elif STATUS_FAILED in states:
            mark = _STATUS_MARK[STATUS_FAILED]
        elif all(s == STATUS_PASSED for s in states):
            mark = _STATUS_MARK[STATUS_PASSED]
            suffix = " 已完成"  # 开放问题 06：模块全部执行完毕的文案
        else:
            mark = _STATUS_MARK[STATUS_WAITING]
        module_item.setText(0, f"{mark} {module.module_name}{suffix}")

    def _refresh_stats(self):
        """刷新统计栏与进度（进度百分比 = floor(已执行/总数×100)，5.1.5）。"""
        percent = int(self.executed / self.total * 100) if self.total else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(f"{percent}% ({self.executed}/{self.total})")
        self.executed_label.setText(f"已执行: {self.executed}/{self.total}")
        self.passed_label.setText(f"成功: {self.passed}")
        self.failed_label.setText(f"失败: {self.failed}")