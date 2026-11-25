# -*- coding: utf-8 -*-
"""左侧用例树单元测试（T10.3：改用 DB fixture 加载真实业务种子数据）。

数据源：db_engine（tmp_path + init_db + seed_db）→ case_repo.load_tree()。
真实种子计数：4 模块 / 23 用例 / 默认勾选 6 条
（M01: 001,005；M02: 006；M03: 015；M04: 022,023）。
"""
import pytest
from PyQt6.QtCore import Qt

from app.data.models import TestCase as CaseModel, TestModule as ModuleModel
from app.db.repositories.case_repo import load_tree
from app.widgets.case_tree import CaseTree


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tree(qapp, db_engine):
    widget = CaseTree()
    widget.load_modules(load_tree(db_engine))
    return widget


def _modules(tree):
    return [tree.tree.topLevelItem(i) for i in range(tree.tree.topLevelItemCount())]


def test_tree_structure_and_default_stats(tree):
    assert len(_modules(tree)) == 4
    assert tree.total_count() == 23
    assert tree.selected_count() == 6
    assert tree.check_all.checkState() == Qt.CheckState.PartiallyChecked
    assert "总计: 23 个用例, 已选中: 6 个" in tree.stats_label.text()


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
    assert not _modules(tree)[0].isHidden()  # 模块一"登录与基础功能"命中
    tree.search_box.setText("zzz_no_match_xyz")
    assert not tree.empty_label.isHidden()
    tree.search_box.setText("")
    assert tree.empty_label.isHidden()
    assert all(not m.isHidden() for m in _modules(tree))


def test_selected_cases(tree):
    selected = tree.selected_cases()
    assert len(selected) == 6
    assert all(isinstance(c, CaseModel) for c in selected)
    expected = {"001", "005", "006", "015", "022", "023"}
    assert {c.case_id for c in selected} == expected


def test_selected_pairs_group_by_module(tree):
    pairs = tree.selected_pairs()
    assert len(pairs) == 6
    assert all(isinstance(m, ModuleModel) and isinstance(c, CaseModel) for m, c in pairs)
    module_ids = [m.module_id for m, _ in pairs]
    assert module_ids == ["M01"] * 2 + ["M02"] * 1 + ["M03"] * 1 + ["M04"] * 2


def test_lock_disables_controls(tree):
    tree.set_locked(True)
    assert not tree.tree.isEnabled()
    assert not tree.search_box.isEnabled()
    assert not tree.check_all.isEnabled()
    tree.set_locked(False)
    assert tree.tree.isEnabled()
    assert tree.search_box.isEnabled()
    assert tree.check_all.isEnabled()


def test_case_title_keeps_code_prefix(tree):
    """case_title 还原 "[001] " 编号前缀（计划 4.5 映射互逆）。"""
    case = _modules(tree)[0].child(0).data(0, Qt.ItemDataRole.UserRole)
    assert case.case_id == "001"
    assert case.case_title.startswith("[001] ")


def test_steps_restored_with_selector_and_remark(qapp, db_engine):
    """步骤 DTO 含 selector（元素定位或 target_override）与 remark。"""
    modules = load_tree(db_engine)
    login_case = next(
        c for m in modules for c in m.cases if c.case_id == "001"
    )
    assert login_case.steps[0].action_type == "goto"
    assert login_case.steps[0].selector == "https://192.168.3.102/"
    # 密码输入步骤：selector 来自已入库元素 #userPwd
    fill_steps = [s for s in login_case.steps if s.action_type == "fill"]
    assert any(s.selector == "#userPwd" for s in fill_steps)
    assert all(s.remark for s in login_case.steps)
