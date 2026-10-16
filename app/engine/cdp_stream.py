"""CDP 截图流客户端：开启 Screencast、帧接收/节流/Ack/解码回传（见 cdp.md 阶段二）。

CDP Page.startScreencast 采用「推-应答（Push-Ack）」背压机制：
内核推送一帧后必须收到 Page.screencastFrameAck 才会继续推送下一帧。
因此每一帧到达后都要**第一时间异步 Ack**，避免挂起 Chromium 渲染管线；
随后按目标帧率（默认 12 FPS）做时间戳节流，丢弃过密帧，只解码展示帧。

线程约定（cdp.md 陷阱一）：本客户端运行在 WorkerThread 的 asyncio 事件循环中，
解码产物只能用 QImage（平台无关、可跨线程安全创建），严禁在工作线程创建 QPixmap。
"""
import asyncio
import base64
import time

from PyQt6.QtGui import QImage
from loguru import logger

SCREENCAST_FORMAT = "jpeg"
SCREENCAST_QUALITY = 75  # 兼顾清晰度与低配 CPU 解码速度
SCREENCAST_MAX_WIDTH = 1280  # 与固定 Viewport 严格对齐
SCREENCAST_MAX_HEIGHT = 800
SCREENCAST_EVERY_NTH_FRAME = 2  # 内核级初步降频


class CDPStreamClient:
    """管理单页面的 CDP 截图流：建立会话、Push-Ack 背压、帧率节流、解码回传。"""

    def __init__(self, page, on_frame_callback, target_fps: int = 12):
        """
        Args:
            page: Playwright 异步 Page 对象。
            on_frame_callback: 解码后回调 (QImage, str url)，WorkerThread 绑定 sig_frame_ready.emit。
            target_fps: 目标帧率（默认 12），节流依据。
        """
        self.page = page
        self.on_frame_callback = on_frame_callback
        self.min_frame_interval = 1.0 / target_fps  # 两帧最小间隔（秒）
        self.last_frame_time = 0.0  # 上一帧处理时刻（time.monotonic 单调时钟）
        self.session = None  # CDPSession，start() 建立
        self._is_streaming = False
        self._loop = None  # start() 时记录的运行中事件循环，供同步回调调度 Ack 协程

    async def start(self):
        """建立页面级 CDP 会话并开启 Screencast。"""
        self._loop = asyncio.get_running_loop()
        self.session = await self.page.context.new_cdp_session(self.page)
        self.session.on("Page.screencastFrame", self._on_screencast_frame)
        self._is_streaming = True
        await self.session.send("Page.startScreencast", {
            "format": SCREENCAST_FORMAT,
            "quality": SCREENCAST_QUALITY,
            "maxWidth": SCREENCAST_MAX_WIDTH,
            "maxHeight": SCREENCAST_MAX_HEIGHT,
            "everyNthFrame": SCREENCAST_EVERY_NTH_FRAME,
        })
        logger.info(f"CDP 截图流已开启（目标 {int(1 / self.min_frame_interval)} FPS）")

    def _on_screencast_frame(self, params: dict):
        """CDP 帧到达（同步回调）：先 Ack 保背压，再节流判定，最后解码回传。"""
        if not self._is_streaming or self.session is None:
            return
        session_id = params.get("sessionId")
        # 1. 立即异步 Ack，不等解码完成，避免浏览器内核阻塞等待
        if session_id is not None and self._loop is not None:
            self._loop.create_task(self._ack_frame(session_id))

        # 2. 帧率节流：距上一帧不足最小间隔则整帧丢弃（Drop Frame），不做解码
        now = time.monotonic()
        if now - self.last_frame_time < self.min_frame_interval:
            return
        self.last_frame_time = now

        # 3. 工作线程内解码：Base64 → JPEG 字节 → QImage（仅 QImage，陷阱一）
        b64_data = params.get("data", "")
        if b64_data:
            raw_bytes = base64.b64decode(b64_data)
            qimage = QImage.fromData(raw_bytes, "JPEG")
            if not qimage.isNull():
                self.on_frame_callback(qimage, self.page.url)

    async def _ack_frame(self, session_id):
        """回复 screencastFrameAck，通知内核继续推送下一帧。"""
        try:
            if self.session is not None and self._is_streaming:
                await self.session.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception:
            # 页面关闭瞬间会话断开属正常，忽略
            pass

    async def stop(self):
        """停止截图流并剥离 CDP 会话（幂等，可重复调用）。"""
        self._is_streaming = False
        if self.session is not None:
            try:
                await self.session.send("Page.stopScreencast")
                await self.session.detach()
            except Exception:
                pass
            finally:
                self.session = None
            logger.info("CDP 截图流已停止")