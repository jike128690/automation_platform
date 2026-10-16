"""浏览器视图信息栏/受控锁定单元测试（T5.2）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QImage, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication

from app.widgets.browser_view import BrowserCanvas, BrowserInfoBar, BrowserView


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_info_bar_syncs_url(qapp):
    bar = BrowserInfoBar()
    bar.set_url("http://127.0.0.1:8765/login")
    assert bar.url_edit.text() == "http://127.0.0.1:8765/login"
    assert bar.url_edit.isReadOnly()  # 地址栏始终只读


def test_info_bar_controlled_toggle(qapp):
    bar = BrowserInfoBar()
    assert bar.refresh_btn.isEnabled()          # 空闲期刷新可点
    assert "未运行" in bar.indicator.text()
    bar.set_controlled(True)
    assert not bar.refresh_btn.isEnabled()      # 受控期刷新禁用
    assert "自动化受控中" in bar.indicator.text()
    bar.set_controlled(False)
    assert bar.refresh_btn.isEnabled()
    assert "未运行" in bar.indicator.text()


def test_canvas_controlled_blocks_mouse_and_key(qapp):
    canvas = BrowserCanvas()
    canvas.set_controlled(True)
    mouse = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(mouse)
    assert mouse.isAccepted()  # 事件被吞掉，不穿透给后台
    key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Enter, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(key)
    assert key.isAccepted()
    canvas.set_controlled(False)
    mouse2 = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(mouse2)
    assert not mouse2.isAccepted()  # 空闲期恢复默认行为


def test_browser_view_forwards_to_canvas_and_bar(qapp):
    view = BrowserView()
    img = QImage(1280, 800, QImage.Format.Format_RGB32)
    view.set_frame(img, "http://127.0.0.1:8765/login")
    assert view.canvas._frame is img
    assert view.info_bar.url_edit.text() == "http://127.0.0.1:8765/login"
    view.set_highlight({"x": 100, "y": 50, "w": 200, "h": 30}, "点击 [登录] 按钮")
    assert view.canvas._highlight is not None
    view.set_controlled(True)
    assert view.canvas._controlled is True
    assert not view.info_bar.refresh_btn.isEnabled()
    assert view.canvas.frame_geometry()[0] > 0