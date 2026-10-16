"""左侧用例树单元测试。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from app.data.demo_cases import DEMO_MODULES
from app.data.models import TestCase as CaseModel, TestModule as ModuleModel
from app.widgets.case_tree import CaseTree


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tree(qapp):
    widget = CaseTree()
    widget.load_modules(DEMO_MODULES)
    return widget


def _modules(tree):
    return [tree.tree.topLevelItem(i) for i in range(tree.tree.topLevelItemCount())]


def test_tree_structure_and_default_stats(tree):
    assert len(_modules(tree)) == 3
    assert tree.total_count() == 24
    assert tree.selected_count() == 12
    assert tree.check_all.checkState() == Qt.CheckState.PartiallyChecked
    assert "总计: 24 个用例, 已选中: 12 个" in tree.stats_label.text()


def test_module_check_syncs_children(tree):
    module = _modules(tree)[0]
    module.setCheckState(0, Qt.CheckState.Unchecked)
    assert all(
        module.child(j).checkState(0) == Qt.CheckState.Unchecked
        for j in range(module.childCount())
    )
    module.setCheckState(0, Qt.CheckState.Checked)
    assert all(
        module.child(j).checkState(0) == Qt.CheckState.Checked
        for j in range(module.childCount())
    )


def test_case_check_updates_stats(tree):
    before = tree.selected_count()
    case_item = _modules(tree)[0].child(0)
    case_item.setCheckState(0, Qt.CheckState.Unchecked)
    assert tree.selected_count() == before - 1
    case_item.setCheckState(0, Qt.CheckState.Checked)
    assert tree.selected_count() == before


def test_check_all(tree):
    tree.check_all.setCheckState(Qt.CheckState.Checked)
    assert tree.selected_count() == tree.total_count()
    assert tree.check_all.checkState() == Qt.CheckState.Checked
    tree.check_all.setCheckState(Qt.CheckState.Unchecked)
    assert tree.selected_count() == 0


def test_search_filter(tree):
    tree.search_box.setText("登录")
    assert not _modules(tree)[0].isHidden()
    tree.search_box.setText("zzz_no_match_xyz")
    assert not tree.empty_label.isHidden()
    tree.search_box.setText("")
    assert tree.empty_label.isHidden()
    assert all(not m.isHidden() for m in _modules(tree))


def test_selected_cases(tree):
    selected = tree.selected_cases()
    assert len(selected) == 12
    assert all(isinstance(c, CaseModel) for c in selected)
    expected = {"001", "002", "003", "004", "005", "006", "009", "010", "017", "018", "019", "022"}
    assert {c.case_id for c in selected} == expected


def test_selected_pairs_group_by_module(tree):
    pairs = tree.selected_pairs()
    assert len(pairs) == 12
    assert all(isinstance(m, ModuleModel) and isinstance(c, CaseModel) for m, c in pairs)
    module_ids = [m.module_id for m, _ in pairs]
    assert module_ids == ["M01"] * 6 + ["M02"] * 2 + ["M03"] * 4


def test_lock_disables_controls(tree):
    tree.set_locked(True)
    assert not tree.tree.isEnabled()
    assert not tree.search_box.isEnabled()
    assert not tree.check_all.isEnabled()
    tree.set_locked(False)
    assert tree.tree.isEnabled()
    assert tree.search_box.isEnabled()
    assert tree.check_all.isEnabled()
