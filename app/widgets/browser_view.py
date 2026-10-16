"""中间浏览器视图：信息栏 + BrowserCanvas 画布（截图流渲染 / 坐标映射 / 高亮叠加 / 受控锁定）。"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

VIEWPORT_WIDTH = 1280   # cdp.md 固定视口尺寸（画布缩放与坐标映射的基准）
VIEWPORT_HEIGHT = 800
IDLE_HINT = "请勾选用例并点击【运行测试】启动自动化视图"

BUBBLE_HEIGHT = 32
BUBBLE_MAX_WIDTH = 280
BUBBLE_PADDING = 8
HIGHLIGHT_COLOR = QColor("#FF3B30")


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
    """把视口坐标 BoundingBox 换算为画布坐标（cdp.md 2.2.1 公式）。"""
    return {
        "x": offset_x + rect["x"] * scale,
        "y": offset_y + rect["y"] * scale,
        "w": rect["w"] * scale,
        "h": rect["h"] * scale,
    }


def compute_bubble_pos(rect: dict, bubble_w: int, bubble_h: int,
                       top: float, margin: int = BUBBLE_PADDING):
    """动作气泡位置：默认目标上方居中；上方不足（贴近画面顶部）翻转至下方；
    水平方向钳制最小边距，防止左侧越界。返回 (x, y)。"""
    x = max(margin, rect["x"] + rect["w"] / 2 - bubble_w / 2)
    y = rect["y"] - bubble_h - margin
    if y < top:
        y = rect["y"] + rect["h"] + margin
    return x, y


class BrowserInfoBar(QWidget):
    """顶部信息栏（5.1.4）：🔒 锁图标 + 只读 URL 地址栏 + 刷新按钮 + 受控指示灯。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lock_label = QLabel("🔒", self)
        self.url_edit = QLineEdit(self)
        self.url_edit.setReadOnly(True)  # 地址栏始终只读，仅由 worker 帧信号同步
        self.url_edit.setPlaceholderText("页面地址")
        self.refresh_btn = QPushButton("刷新", self)
        self.indicator = QLabel(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.lock_label)
        layout.addWidget(self.url_edit, 1)
        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.indicator)
        self.set_controlled(False)

    def set_url(self, url: str):
        """同步当前页面 URL（主线程接 sig_frame_ready 调用）。"""
        self.url_edit.setText(url)

    def set_controlled(self, controlled: bool):
        """受控状态切换：刷新按钮受控期禁用；指示灯绿点/灰点（开放问题 05 默认方案）。"""
        self.refresh_btn.setEnabled(not controlled)
        if controlled:
            self.indicator.setText("● 自动化受控中")
            self.indicator.setStyleSheet("color: #2EBD59;")
        else:
            self.indicator.setText("● 未运行")
            self.indicator.setStyleSheet("color: #9E9E9E;")


class BrowserCanvas(QWidget):
    """双图层画布（cdp.md 2.2.2）：Layer0 底色/空闲占位 + Layer1 视频帧 + Layer2 高亮叠加。
    受控期拦截鼠标/键盘输入，不向后台穿透（5.1.4 受控期锁定）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame: QImage | None = None   # 最新 CDP 帧（主线程 set_frame 写入）
        self._highlight = None              # {"rect": 视口BBox, "tooltip": str} | None
        self._controlled = False            # 受控期：吞掉人工输入事件
        self.setMinimumSize(320, 200)

    def set_frame(self, qimage: QImage, url: str = ""):
        """主线程接收 sig_frame_ready 后更新当前帧并触发重绘（10~15 FPS 入口）。"""
        self._frame = qimage
        self.update()

    def set_highlight(self, rect=None, tooltip: str = ""):
        """主线程接收 sig_highlight_element：设置或清除高亮，并独立重绘。

        独立于帧更新调用 update()（cdp.md 陷阱二）——网页静止无新帧时，
        叠加层也必须即时显隐，不能依赖 sig_frame_ready 触发重绘。
        """
        self._highlight = {"rect": dict(rect), "tooltip": tooltip} if rect else None
        self.update()

    def set_controlled(self, controlled: bool):
        """受控状态切换：受控期拦截一切人工输入，杜绝误触干扰自动化（5.1.4）。"""
        self._controlled = controlled

    def frame_geometry(self):
        """当前画布尺寸下的 Letterbox 参数 (scale, offset_x, offset_y)。"""
        return compute_letterbox(self.width(), self.height())

    def map_rect(self, rect: dict) -> dict:
        """基于当前画布几何，把视口坐标换算为画布坐标（高亮/气泡共用）。"""
        scale, offset_x, offset_y = self.frame_geometry()
        return map_rect(rect, scale, offset_x, offset_y)

    # ---- 受控期事件拦截：直接吞掉，不调用默认实现、不穿透给后台浏览器 ----
    def mousePressEvent(self, event: QMouseEvent):
        if self._controlled:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._controlled:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._controlled:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        if self._controlled:
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._controlled:
            event.accept()
            return
        super().keyPressEvent(event)

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
        # Layer2：高亮叠加层（仅在存在激活高亮时绘制）
        if self._highlight:
            self._paint_highlight(painter, offset_y)

    def _paint_highlight(self, painter: QPainter, frame_top: float):
        """绘制红色外框 + 半透明遮罩 + 准星指示 + 动作气泡（cdp.md 2.2.2 Layer2）。"""
        rect = self.map_rect(self._highlight["rect"])  # 视口 BBox → 画布坐标
        highlight_rect = QRectF(rect["x"], rect["y"], rect["w"], rect["h"])
        # 1) 红色高亮外框 + 半透明红色遮罩
        painter.setPen(QPen(HIGHLIGHT_COLOR, 2.5))
        painter.setBrush(QColor(255, 59, 48, 35))
        painter.drawRoundedRect(highlight_rect, 4, 4)
        # 2) 准星指示图标：目标框右下角
        self._draw_crosshair(painter, rect)
        # 3) 动作气泡：目标框上方，空间不足自动翻转下方（防贴近顶部越界）
        bubble_w = min(BUBBLE_MAX_WIDTH, self.width() - 2 * BUBBLE_PADDING)
        bx, by = compute_bubble_pos(rect, bubble_w, BUBBLE_HEIGHT, frame_top)
        self._draw_bubble(painter, bx, by, bubble_w, f"正在执行：{self._highlight['tooltip']}")

    def _draw_crosshair(self, painter: QPainter, rect: dict):
        """准星图标：白底红点 + 四向短十字（模拟手型指示，位置为框右下角）。"""
        cx = rect["x"] + rect["w"] - 8
        cy = rect["y"] + rect["h"] - 8
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(QColor(255, 59, 48, 200))
        painter.drawEllipse(QPointF(cx, cy), 6, 6)
        painter.drawLine(QPointF(cx - 10, cy), QPointF(cx - 4, cy))
        painter.drawLine(QPointF(cx + 4, cy), QPointF(cx + 10, cy))
        painter.drawLine(QPointF(cx, cy - 10), QPointF(cx, cy - 4))
        painter.drawLine(QPointF(cx, cy + 4), QPointF(cx, cy + 10))

    def _draw_bubble(self, painter: QPainter, x: float, y: float, w: int, text: str):
        """白色圆角气泡：底部偏移阴影 + 白底 + 黑字（超宽省略号截断）。"""
        bubble = QRectF(x, y, w, BUBBLE_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawRoundedRect(bubble.translated(2, 2), 6, 6)  # 阴影
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(bubble, 6, 6)  # 白底
        font = painter.font()
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor("#000000"))
        elided = painter.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, int(w - 2 * BUBBLE_PADDING))
        painter.drawText(bubble.adjusted(BUBBLE_PADDING, 0, -BUBBLE_PADDING, 0),
                         Qt.AlignmentFlag.AlignVCenter, elided)


class BrowserView(QWidget):
    """浏览器视图整体：顶部信息栏 + 中间画布（5.1.4）。

    统一对外接口，M8 联调时由 MainWindow 把 WorkerThread 信号直接接到本视图：
      sig_frame_ready → set_frame(QImage, url)；sig_highlight_element → set_highlight(rect, tooltip)；
      运行/停止 → set_controlled(True/False)。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.info_bar = BrowserInfoBar(self)
        self.canvas = BrowserCanvas(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.info_bar)
        layout.addWidget(self.canvas, 1)

    def set_frame(self, qimage: QImage, url: str = ""):
        self.canvas.set_frame(qimage)
        self.info_bar.set_url(url)

    def set_highlight(self, rect=None, tooltip: str = ""):
        self.canvas.set_highlight(rect, tooltip)

    def set_controlled(self, controlled: bool):
        self.canvas.set_controlled(controlled)
        self.info_bar.set_controlled(controlled)