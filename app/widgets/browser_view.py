"""中间画布控件：CDP 帧渲染 + Letterbox 等比坐标映射（见 cdp.md 2.2）。"""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QWidget

VIEWPORT_WIDTH = 1280   # cdp.md 固定视口尺寸（画布缩放与坐标映射的基准）
VIEWPORT_HEIGHT = 800
IDLE_HINT = "请勾选用例并点击【运行测试】启动自动化视图"


def compute_letterbox(canvas_w: int, canvas_h: int,
                      viewport_w: int = VIEWPORT_WIDTH, viewport_h: int = VIEWPORT_HEIGHT):
    """Letterbox 等比缩放参数（cdp.md 2.2.1）：返回 (scale, offset_x, offset_y)。

    取最小缩放因子保证画面完整容纳于画布，剩余空间居中平铺留白，
    避免任何方向拉伸变形；偏移量供帧绘制与叠加层坐标换算共用。
    """
    scale = min(canvas_w / viewport_w, canvas_h / viewport_h)
    offset_x = (canvas_w - viewport_w * scale) / 2
    offset_y = (canvas_h - viewport_h * scale) / 2
    return scale, offset_x, offset_y


def map_rect(rect: dict, scale: float, offset_x: float, offset_y: float) -> dict:
    """把视口坐标 BoundingBox 换算为画布坐标（cdp.md 2.2.1 公式，T5.3 叠加层使用）。"""
    return {
        "x": offset_x + rect["x"] * scale,
        "y": offset_y + rect["y"] * scale,
        "w": rect["w"] * scale,
        "h": rect["h"] * scale,
    }


class BrowserCanvas(QWidget):
    """双图层画布（cdp.md 2.2.2）：Layer0 底色/空闲占位 + Layer1 CDP 视频帧。

    T5.1 交付帧渲染；Layer2 红框/手势/气泡叠加在 T5.3 补充。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame: QImage | None = None  # 最新 CDP 帧（主线程 set_frame 写入）
        self.setMinimumSize(320, 200)

    def set_frame(self, qimage: QImage, url: str = ""):
        """主线程接收 sig_frame_ready 后更新当前帧并触发重绘（10~15 FPS 入口）。"""
        self._frame = qimage
        self.update()

    def frame_geometry(self):
        """当前画布尺寸下的 Letterbox 参数 (scale, offset_x, offset_y)。"""
        return compute_letterbox(self.width(), self.height())

    def map_rect(self, rect: dict) -> dict:
        """基于当前画布几何，把视口坐标换算为画布坐标（供叠加层）。"""
        scale, offset_x, offset_y = self.frame_geometry()
        return map_rect(rect, scale, offset_x, offset_y)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._frame is None:
            # Layer0 空闲态：浅灰底 + 居中引导文案
            painter.fillRect(self.rect(), QColor("#F0F0F0"))
            painter.setPen(QColor("#888888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, IDLE_HINT)
            return
        # Layer0 运行态：深灰底作为 Letterbox 留白
        painter.fillRect(self.rect(), QColor("#2B2B2B"))
        # Layer1：视频帧等比缩放后居中绘制（平滑缩放保证清晰度）
        scale, offset_x, offset_y = compute_letterbox(self.width(), self.height())
        target = QRectF(offset_x, offset_y,
                        self._frame.width() * scale, self._frame.height() * scale)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._frame)