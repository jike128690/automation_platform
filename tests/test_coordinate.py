"""坐标映射计算测试（开发计划 8.1 指定）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from app.widgets.browser_view import BrowserCanvas, compute_letterbox, map_rect


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_letterbox_1920x1080():
    # min(1920/1280, 1080/800) = 1.35；横向留白 (1920 - 1280*1.35) / 2 = 96，纵向满铺
    scale, ox, oy = compute_letterbox(1920, 1080)
    assert scale == pytest.approx(1.35)
    assert ox == pytest.approx(96.0)
    assert oy == pytest.approx(0.0)


def test_letterbox_1366x768():
    # min(1366/1280, 768/800) = 0.96；纵向满铺 (768 - 800*0.96) = 0
    scale, ox, oy = compute_letterbox(1366, 768)
    assert scale == pytest.approx(0.96)
    assert oy == pytest.approx(0.0)
    assert ox == pytest.approx((1366 - 1280 * 0.96) / 2)


def test_letterbox_small_canvas_centers_vertically():
    # min(640/1280, 480/800) = 0.5；上下留白 (480 - 800*0.5) / 2 = 40
    scale, ox, oy = compute_letterbox(640, 480)
    assert scale == pytest.approx(0.5)
    assert ox == pytest.approx(0.0)
    assert oy == pytest.approx(40.0)


def test_map_rect_transform():
    mapped = map_rect({"x": 100, "y": 50, "w": 200, "h": 30}, scale=1.35, offset_x=96, offset_y=0)
    assert mapped == {
        "x": pytest.approx(96 + 100 * 1.35),
        "y": pytest.approx(50 * 1.35),
        "w": pytest.approx(200 * 1.35),
        "h": pytest.approx(30 * 1.35),
    }


def test_canvas_keeps_latest_frame(qapp):
    canvas = BrowserCanvas()
    img = QImage(1280, 800, QImage.Format.Format_RGB32)
    canvas.set_frame(img)
    assert canvas._frame is img
    assert not canvas._frame.isNull()


def test_canvas_map_rect_uses_own_geometry(qapp):
    canvas = BrowserCanvas()
    canvas.resize(1920, 1080)
    mapped = canvas.map_rect({"x": 640, "y": 400, "w": 100, "h": 50})
    assert mapped["x"] == pytest.approx(96 + 640 * 1.35)
    assert mapped["h"] == pytest.approx(50 * 1.35)


def test_canvas_render_idle_and_with_frame(qapp):
    canvas = BrowserCanvas()
    canvas.resize(640, 480)
    out = QImage(640, 480, QImage.Format.Format_ARGB32)
    canvas.render(out)  # 空闲态渲染不崩溃
    assert not out.isNull()
    canvas.set_frame(QImage(1280, 800, QImage.Format.Format_RGB32))
    canvas.render(out)  # 有帧渲染不崩溃
    assert not out.isNull()