"""BrowserCanvas 高亮叠加层单元测试（T5.3）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from app.widgets.browser_view import BrowserCanvas, compute_bubble_pos


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_bubble_above_by_default():
    # 目标上方空间充足（y=50 > 32+8）：气泡显示在目标正上方
    x, y = compute_bubble_pos({"x": 100, "y": 50, "w": 200, "h": 30}, 280, 32, top=0)
    assert x == pytest.approx(100 + 100 - 140)
    assert y == pytest.approx(50 - 32 - 8)


def test_bubble_flips_below_when_near_top():
    # 目标贴近顶部（y=10 < 40）：翻转显示在目标下方
    x, y = compute_bubble_pos({"x": 100, "y": 10, "w": 200, "h": 30}, 280, 32, top=0)
    assert y == pytest.approx(10 + 30 + 8)


def test_bubble_clamps_left_edge():
    # 目标贴近左缘：气泡左边缘钳制到最小边距，防止越出画布
    x, y = compute_bubble_pos({"x": 0, "y": 100, "w": 50, "h": 30}, 280, 32, top=0)
    assert x == pytest.approx(8)


def test_set_and_clear_highlight(qapp):
    canvas = BrowserCanvas()
    canvas.resize(1920, 1080)
    canvas.set_highlight({"x": 100, "y": 50, "w": 200, "h": 30}, "点击 [登录] 按钮")
    assert canvas._highlight is not None
    assert canvas._highlight["tooltip"] == "点击 [登录] 按钮"
    canvas.set_highlight()  # 空参数清除叠加
    assert canvas._highlight is None


def test_render_with_highlight(qapp):
    canvas = BrowserCanvas()
    canvas.resize(640, 480)
    canvas.set_frame(QImage(1280, 800, QImage.Format.Format_RGB32))
    canvas.set_highlight({"x": 100, "y": 50, "w": 200, "h": 30}, "点击 [登录] 按钮")
    out = QImage(640, 480, QImage.Format.Format_ARGB32)
    canvas.render(out)
    assert not out.isNull()


def test_highlight_maps_viewport_to_canvas(qapp):
    canvas = BrowserCanvas()
    canvas.resize(1920, 1080)
    scale, ox, oy = canvas.frame_geometry()
    assert scale == pytest.approx(1.35)
    # 视口中心元素映射到画布几何中心附近（1920x1080 画布 1.35 倍缩放）
    mapped = canvas.map_rect({"x": 640, "y": 400, "w": 100, "h": 50})
    assert mapped["x"] == pytest.approx(96 + 640 * 1.35)
    assert mapped["y"] == pytest.approx(400 * 1.35)


def test_highlight_renders_without_new_frames(qapp):
    """阶段五零帧补偿（cdp.md 陷阱二）：静止页仅有缓存帧时，set_highlight 独立重绘即时显隐。"""
    canvas = BrowserCanvas()
    canvas.resize(640, 480)
    canvas.set_frame(QImage(1280, 800, QImage.Format.Format_RGB32))  # 唯一缓存帧（页面静止无新帧）
    canvas.set_highlight({"x": 100, "y": 50, "width": 200, "height": 30}, "点击 [登录] 按钮")
    out = QImage(640, 480, QImage.Format.Format_ARGB32)
    canvas.render(out)  # 无新 CDP 帧也渲染出高亮
    assert not out.isNull()
    canvas.set_highlight()  # 清除同样即时生效
    canvas.render(out)
    assert not out.isNull()