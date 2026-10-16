"""左侧用例树（勾选/搜索/统计/锁定）。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class CaseTree(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._syncing = False

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("搜索")
        self.search_box.setMaxLength(50)

        self.check_all = QCheckBox("全选", self)
        self.check_all.setTristate(True)

        top = QHBoxLayout()
        top.addWidget(self.search_box, 1)
        top.addWidget(self.check_all)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        self.empty_label = QLabel("无匹配用例", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888;")
        self.empty_label.hide()

        self.stats_label = QLabel(self)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.stats_label)

        self.tree.itemChanged.connect(self._on_item_changed)
        self.check_all.stateChanged.connect(self._on_check_all)
        self.search_box.textChanged.connect(self._on_search)

    def load_modules(self, modules):
        self._syncing = True
        self.tree.clear()
        self.search_box.clear()
        for module in modules:
            module_item = QTreeWidgetItem(self.tree)
            module_item.setText(0, module.module_name)
            module_item.setData(0, Qt.ItemDataRole.UserRole, module)
            module_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
            module_item.setFlags(
                module_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate
            )
            for case in module.cases:
                case_item = QTreeWidgetItem(module_item)
                case_item.setText(0, case.case_title)
                case_item.setData(0, Qt.ItemDataRole.UserRole, case)
                case_item.setFlags(case_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                case_item.setCheckState(
                    0, Qt.CheckState.Checked if case.default_checked else Qt.CheckState.Unchecked
                )
        self.tree.expandAll()
        self._syncing = False
        self._refresh()

    def total_count(self):
        return sum(
            self.tree.topLevelItem(i).childCount() for i in range(self.tree.topLevelItemCount())
        )

    def selected_count(self):
        return sum(
            1
            for i in range(self.tree.topLevelItemCount())
            for j in range(self.tree.topLevelItem(i).childCount())
            if self.tree.topLevelItem(i).child(j).checkState(0) == Qt.CheckState.Checked
        )

    def selected_cases(self):
        result = []
        for i in range(self.tree.topLevelItemCount()):
            module_item = self.tree.topLevelItem(i)
            for j in range(module_item.childCount()):
                case_item = module_item.child(j)
                if case_item.checkState(0) == Qt.CheckState.Checked:
                    result.append(case_item.data(0, Qt.ItemDataRole.UserRole))
        return result

    def selected_pairs(self):
        """返回按树序的 (TestModule, TestCase) 勾选用例对，供执行队列使用。"""
        result = []
        for i in range(self.tree.topLevelItemCount()):
            module_item = self.tree.topLevelItem(i)
            module = module_item.data(0, Qt.ItemDataRole.UserRole)
            for j in range(module_item.childCount()):
                case_item = module_item.child(j)
                if case_item.checkState(0) == Qt.CheckState.Checked:
                    result.append((module, case_item.data(0, Qt.ItemDataRole.UserRole)))
        return result

    def set_locked(self, locked):
        self.tree.setEnabled(not locked)
        self.search_box.setEnabled(not locked)
        self.check_all.setEnabled(not locked)

    def _on_item_changed(self, item, column):
        if self._syncing:
            return
        self._refresh()

    def _on_check_all(self, state):
        if self._syncing:
            return
        self._syncing = True
        check = (
            Qt.CheckState.Checked
            if Qt.CheckState(state) == Qt.CheckState.Checked
            else Qt.CheckState.Unchecked
        )
        for i in range(self.tree.topLevelItemCount()):
            module_item = self.tree.topLevelItem(i)
            for j in range(module_item.childCount()):
                module_item.child(j).setCheckState(0, check)
        self._syncing = False
        self._refresh()

    def _on_search(self, text):
        text = text.strip()
        matched = False
        for i in range(self.tree.topLevelItemCount()):
            module_item = self.tree.topLevelItem(i)
            module_match = text in module_item.text(0)
            child_match = False
            for j in range(module_item.childCount()):
                case_item = module_item.child(j)
                case_match = text in case_item.text(0)
                case_item.setHidden(not case_match)
                child_match |= case_match
            module_item.setHidden(not (module_match or child_match))
            matched |= module_match or child_match
        self.empty_label.setVisible(not matched and bool(text))

    def _refresh(self):
        self._sync_check_all()
        self._update_stats()

    def _sync_check_all(self):
        checked = self.selected_count()
        total = self.total_count()
        if checked == 0 or total == 0:
            state = Qt.CheckState.Unchecked
        elif checked == total:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self._syncing = True
        self.check_all.setCheckState(state)
        self._syncing = False

    def _update_stats(self):
        self.stats_label.setText(
            f"总计: {self.total_count()} 个用例, 已选中: {self.selected_count()} 个"
        )
