"""CDP 截图流客户端单元测试（节流/Ack/解码/停止，不真实启动浏览器）。"""
import asyncio
import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.engine.cdp_stream import CDPStreamClient

# 1x1 白色 JPEG：最小合法 JPEG 文件，可被 QImage 解码且非空
_JPEG_1PX = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
    "2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/"
    "8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/"
    "8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKS1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/"
    "9oADAMBAAIRAxEAPwD3+iiigD//2Q=="
)


class FakeSession:
    def __init__(self):
        self.events = {}
        self.sends = []
        self.detached = False

    def on(self, event, handler):
        self.events[event] = handler

    async def send(self, method, params=None):
        self.sends.append((method, params))
        return {}

    async def detach(self):
        self.detached = True


class FakeContext:
    def __init__(self):
        self.session = FakeSession()

    async def new_cdp_session(self, page):
        return self.session


class FakePage:
    def __init__(self):
        self.url = "http://127.0.0.1:8765/login"
        self.context = FakeContext()


def _b64(data) -> str:
    return base64.b64encode(data).decode()


async def _attach(client, frames):
    """注入假会话并模拟多帧到达（不真实启动浏览器）。"""
    session = FakeSession()
    client.session = session
    client._loop = asyncio.get_running_loop()
    client._is_streaming = True
    for data in frames:
        client._on_screencast_frame({"sessionId": 1, "data": _b64(data)})
        await asyncio.sleep(0.02)  # 让 Ack 协程有机会执行
    return session


def _run(coro):
    asyncio.run(coro)


def test_start_opens_session_and_starts_stream():
    async def scenario():
        page = FakePage()
        client = CDPStreamClient(page, lambda *a: None, target_fps=12)
        await client.start()
        methods = [m for m, _ in page.context.session.sends]
        assert "Page.startScreencast" in methods
        assert "Page.screencastFrame" in page.context.session.events
        assert client.session is page.context.session

    _run(scenario())


def test_throttle_drops_fast_frames():
    async def scenario():
        frames = []
        # 目标 1 FPS：两帧仅间隔 0.02s，第二帧必须被节流丢弃
        client = CDPStreamClient(FakePage(), lambda qimg, url: frames.append(qimg), target_fps=1)
        await _attach(client, [_JPEG_1PX, _JPEG_1PX])
        assert len(frames) == 1
        assert not frames[0].isNull()

    _run(scenario())


def test_ack_sent_for_every_frame_even_dropped():
    async def scenario():
        client = CDPStreamClient(FakePage(), lambda *a: None, target_fps=1)
        session = await _attach(client, [_JPEG_1PX, _JPEG_1PX])
        acks = [m for m, _ in session.sends if m == "Page.screencastFrameAck"]
        assert len(acks) == 2  # 背压：被节流丢弃的帧也必须 Ack

    _run(scenario())


def test_stop_sends_stop_and_detaches():
    async def scenario():
        client = CDPStreamClient(FakePage(), lambda *a: None)
        session = await _attach(client, [_JPEG_1PX])
        await client.stop()
        methods = [m for m, _ in session.sends]
        assert "Page.stopScreencast" in methods
        assert session.detached
        assert client.session is None

    _run(scenario())