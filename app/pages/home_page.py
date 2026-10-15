"""首页（阶段一）。"""
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.widgets.browser_view import BrowserView
from app.widgets.case_tree import CaseTree
from app.widgets.log_panel import LogPanel
from app.widgets.status_panel import StatusPanel


class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.case_tree = CaseTree(self)
        self.browser_view = BrowserView(self)
        self.status_panel = StatusPanel(self)
        self.log_panel = LogPanel(self)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.status_panel, 2)
        right_layout.addWidget(self.log_panel, 3)

        layout = QHBoxLayout(self)
        layout.addWidget(self.case_tree, 0)
        layout.addWidget(self.browser_view, 1)
        layout.addWidget(right, 0)
        self.case_tree.setFixedWidth(280)
        right.setFixedWidth(340)
