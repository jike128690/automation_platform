"""用例队列异步执行引擎：Playwright 动作编排 + 视觉高亮节拍（见 cdp.md 阶段四 2.3）。

状态机：waiting → running → passed | failed（与 6.3 sig_case_status_changed 一致）。
保证：
  1. 单条用例失败/异常不中断批次（失败续跑，5.1.5）；
  2. 手动停止在「当前步骤执行完成后」安全退出，剩余用例保持 waiting（5.1.2/5.1.5）。

标准节拍（cdp.md 2.3 Step Execution Rhythm），让人眼看清"先定位高亮 → 再动作 → 画面变化"：
  Pre-Step 日志 → 定位/滚动取 BoundingBox（仅元素动作）→ 高亮信号 → 350ms 视觉停顿
  → 执行动作 → 清除高亮 → 成功日志 → 150ms 等待新画面帧推送。

动作执行经 AsyncPageActions 协议注入：
  真实实现 = AsyncPlaywrightActions（Playwright 异步 API，含陷阱三滚动进视口）；
  单元测试 = FakeActions（visual_pause/post_pause 置 0 提速）。
"""
import asyncio
import time
from pathlib import Path
from typing import Protocol

from loguru import logger
from playwright.async_api import expect

from app.data.models import TestStep

STATUS_RUNNING = "running"  # 进行中
STATUS_PASSED = "passed"    # 已通过
STATUS_FAILED = "failed"    # 测试执行失败


class AsyncPageActions(Protocol):
    """页面动作执行器接口（鸭子类型协议）。"""

    async def goto(self, url: str) -> None:
        """跳转到 URL（wait_until 由实现方配置，默认 domcontentloaded）。"""
        ...

    async def clear_session(self) -> None:
        """清除页面会话（localStorage/sessionStorage）：每条用例开始前调用，保证用例间状态隔离。"""
        ...

    async def locate(self, selector: str) -> dict | None:
        """滚动进视口并返回元素 BoundingBox（视口坐标 dict）；元素不存在返回 None。"""
        ...

    async def fill(self, selector: str, value: str) -> None:
        ...

    async def click(self, selector: str) -> None:
        ...

    async def assert_visible(self, selector: str) -> None:
        ...

    async def capture_failure_screenshot(self, case_id: str) -> str | None:
        """用例失败时保存报错截图，返回本地路径；不支持/未启用返回 None（T12.3）。"""
        ...


class AsyncPlaywrightActions:
    """基于 Playwright 异步 API 的真实动作实现（cdp.md 2.3 / 陷阱三）。

    T12.3 配置联动：
    - wait_until 由页面加载策略映射（NORMAL→load / EAGER→domcontentloaded / NONE→commit）；
    - implicit_wait_sec → page.set_default_timeout（元素等待）；
    - exec_timeout_sec → page.set_default_navigation_timeout（导航等待，独立于元素等待）；
    - clear_cookies/clear_history/clear_cache 按【批量配置】开关在用例开始前清理；
    - screenshot_on_fail 启用时 capture_failure_screenshot 保存报错截图。
    """

    def __init__(self, page, wait_until: str = "domcontentloaded",
                 implicit_wait_ms: int | None = None,
                 exec_timeout_ms: int | None = None,
                 clear_cookies: bool = False, clear_history: bool = False,
                 clear_cache: bool = False,
                 screenshot_dir: str | None = None,
                 screenshot_on_fail: bool = False):
        self.page = page
        self.wait_until = wait_until
        self._clear_cookies = clear_cookies
        self._clear_history = clear_history
        self._clear_cache = clear_cache
        self._screenshot_dir = screenshot_dir
        self._screenshot_on_fail = screenshot_on_fail
        if implicit_wait_ms is not None:
            # 元素查找等待 (Implicit Wait)：Playwright 以默认超时近似对应（图4）
            page.set_default_timeout(implicit_wait_ms)
        if exec_timeout_ms is not None:
            # 导航超时必须单独设置：否则会回落到元素默认超时（5s），
            # 设备站点首次加载（含大量资源）会被误判为超时
            page.set_default_navigation_timeout(exec_timeout_ms)

    async def goto(self, url: str):
        await self.page.goto(url, wait_until=self.wait_until)

    async def clear_session(self):
        """按批量配置的清除数据项开关逐项清理（失败忽略，不阻断用例）。"""
        if self._clear_history:
            try:
                await self.page.evaluate("localStorage.clear(); sessionStorage.clear();")
            except Exception:
                pass  # 首个用例前页面可能为 about:blank（无 origin），清除失败忽略即可
        if self._clear_cache:
            try:
                cdp = await self.page.context.new_cdp_session(self.page)
                await cdp.send("Network.clearBrowserCache")
                await cdp.detach()
            except Exception:
                pass  # CDP 会话不可用时忽略（浏览器缓存非关键状态）
        if self._clear_cookies:
            try:
                await self.page.context.clear_cookies()
            except Exception:
                pass

    async def locate(self, selector: str):
        locator = self.page.locator(selector)
        try:
            # 陷阱三：长页面元素可能在视口外，必须先滚动进视口再取坐标
            """
            scroll_into_view_if_needed(timeout=5000) —— Playwright 内置方法，滚动元素进视口，超时 5 秒抛异常。
            bounding_box() —— Playwright 内置方法，返回元素的 BoundingBox（视口坐标 dict），若元素不存在/不可定位则返回 None。
            """
            await locator.scroll_into_view_if_needed(timeout=5000)
            await asyncio.sleep(0.1)  # 等浏览器平滑滚动与新画面帧推送完成
            return await locator.bounding_box()
        except Exception:
            return None  # 元素不存在/不可定位：由执行器按失败处理

    async def fill(self, selector: str, value: str):
        await self.page.locator(selector).fill(value)

    async def click(self, selector: str):
        await self.page.locator(selector).click()

    async def assert_visible(self, selector: str):
        await expect(self.page.locator(selector)).to_be_visible()

    async def capture_failure_screenshot(self, case_id: str) -> str | None:
        """用例失败保存报错截图（配置 screenshot_on_fail 启用），返回路径或 None。"""
        if not self._screenshot_on_fail or not self._screenshot_dir:
            return None
        try:
            save_dir = Path(self._screenshot_dir)
            save_dir.mkdir(parents=True, exist_ok=True)
            path = save_dir / f"{case_id}_{int(time.time() * 1000)}.png"
            await self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return None  # 截图失败不掩盖原始失败原因


class AsyncExecutor:
    """异步用例队列引擎：标准节拍 + 状态机 + 失败续跑 + 安全停止。"""

    def __init__(self, actions, on_status=None, on_log=None, on_finished=None,
                 on_highlight=None, on_media=None, visual_pause: float = 0.35,
                 post_pause: float = 0.15, retry_count: int = 0):
        """
        Args:
            actions: 实现 AsyncPageActions 协议的对象（Playwright 实现或测试 Fake）。
            on_status: 用例状态回调 (case_id, status)。
            on_log: 日志回调 (timestamp, message)。
            on_finished: 批次结束回调 (is_manual_stopped)。
            on_highlight: 高亮回调 (rect|None, tooltip)——WorkerThread 桥接 sig_highlight_element。
            on_media: 报错截图回调 (case_id, screenshot_path)——T12.3 失败自动截图落库。
            visual_pause: 高亮后的人眼观察停顿秒数（cdp.md 2.3，测试可置 0）。
            post_pause: 动作成功后等待新画面帧推送的秒数。
            retry_count: 失败重试次数（T12.3，配置表 retry_count；0=不重试）。
        """
        self._actions = actions
        self._on_status = on_status or (lambda cid, st: None)
        self._on_log = on_log or (lambda ts, msg: None)
        self._on_finished = on_finished or (lambda manual: None)
        self._on_highlight = on_highlight or (lambda rect, tooltip: None)
        self._on_media = on_media
        self._visual_pause = visual_pause
        self._post_pause = post_pause
        self._retry_count = max(0, int(retry_count))
        self._stop_requested = False

    def request_stop(self):
        """请求安全停止：执行引擎在下一个步骤边界响应。"""
        self._stop_requested = True

    async def run(self, case_pairs):
        """执行 (TestModule, TestCase) 队列，返回 (通过数, 失败数)。"""
        logger.info(f"开始执行测试批次，共 {len(case_pairs)} 条用例")
        passed = failed = 0
        last_module = None  # 记录上一模块，用于「每个模块只打一次套件开始日志」
        for module, case in case_pairs:
            # 停止检查：手动停止后不再启动新用例，直接收尾
            if self._stop_requested:
                logger.info("收到手动停止请求，安全退出")
                self._log("用户手动停止测试，任务已安全终止")
                break
            # 模块切换时输出套件级日志（对齐 5.1.6 日志格式）
            if module is not last_module:
                self._log(f"开始执行测试套件: {module.module_name}")
                last_module = module
            # 单条失败不中断批次：无论成败都继续下一条（含失败重试，T12.3）
            ok = await self._run_case(case)
            attempt = 0
            while not ok and attempt < self._retry_count and not self._stop_requested:
                attempt += 1
                self._log(f"[{case.case_id}] {case.short_name}: 第 {attempt}/{self._retry_count} 次失败重试...")
                ok = await self._run_case(case)  # 重跑重新进入 RUNNING 态
            if ok:
                passed += 1
            else:
                failed += 1
        # 通知主线程批次结束（True=手动停止，False=全部执行完）
        self._on_finished(self._stop_requested)
        logger.info(f"测试批次结束：通过 {passed} 条，失败 {failed} 条")
        return passed, failed

    async def _run_case(self, case) -> bool:
        """执行单条用例的全部步骤（标准节拍），返回该用例是否通过。"""
        self._on_status(case.case_id, STATUS_RUNNING)  # 进入「进行中」
        # 用例级会话隔离：清掉上一条用例残留的登录态。
        # 008 会话保持用例需要用例内两次 goto 保留会话，故不放在 goto 里清。
        await self._actions.clear_session()
        for step in case.steps:
            # 步骤边界停止检查：保证当前动作执行完才安全退出
            if self._stop_requested:
                break
            # Pre-Step：记录步骤开始
            self._log(f"[{case.case_id}] {case.short_name}: {step.remark}...")
            try:
                await self._run_step(step)
            except Exception as exc:
                # 步骤抛异常（元素未找到/超时/断言失败）视为用例失败，附异常原因
                logger.exception(f"用例 {case.case_id} {case.short_name} 步骤执行异常")
                self._on_highlight({}, "")  # 异常路径同样清除画布叠加层（空 dict=清除）
                message = f"[{case.case_id}] {case.short_name}: {step.remark}... 失败: {exc}"
                if step.action_type == "goto" and "Timeout" in str(exc):
                    message += "（可调大【测试执行超时】或将【页面加载策略】改为 EAGER）"
                self._log(message)
                # T12.3 失败自动截图：路径经 on_media 回调落库（screenshot_path）
                await self._capture_failure_media(case.case_id)
                self._on_status(case.case_id, STATUS_FAILED)
                return False
            # Post-Step：成功日志 + 短暂等待让新页面帧推送到画布（高亮清除在 _run_step 内完成）
            self._log(f"[{case.case_id}] {case.short_name}: {step.remark}... 通过")
            await asyncio.sleep(self._post_pause)
        if self._stop_requested:
            # 手动停止导致未跑完：该用例归为失败，剩余用例由外层保持 waiting
            self._on_status(case.case_id, STATUS_FAILED)
            return False
        self._on_status(case.case_id, STATUS_PASSED)  # 全部步骤通过
        return True

    async def _run_step(self, step: TestStep):
        """单步标准节拍（cdp.md 2.3）：goto 直达；fill/click/assert_visible 走高亮时序。"""
        if step.action_type == "goto":
            # goto 无目标元素：直接跳转（加载策略由 AsyncPlaywrightActions 配置）
            await self._actions.goto(step.selector)
            return
        # 1) 定位：滚动进视口并提取 BoundingBox（陷阱三）
        box = await self._actions.locate(step.selector)
        if box is None:
            raise LookupError(f"元素未找到: {step.selector}")
        # 2) 高亮信号：BoundingBox（视口坐标）+ 气泡文案 → 画布叠加层（M5 已实现）
        self._on_highlight(box, step.remark)
        # 3) 视觉观察停顿：此间截图流持续推送画面，红框/气泡稳定呈现在画布
        await asyncio.sleep(self._visual_pause)
        # 4) 执行核心动作
        if step.action_type == "fill":
            await self._actions.fill(step.selector, step.value)
        elif step.action_type == "click":
            await self._actions.click(step.selector)
        elif step.action_type == "assert_visible":
            await self._actions.assert_visible(step.selector)
        else:
            raise ValueError(f"未知动作类型: {step.action_type}")
        # 5) 动作完成：清除高亮（空 dict=清除，cdp.md 2.3；设置/清除成对收敛在本方法，goto 步骤无高亮信号）
        self._on_highlight({}, "")

    async def _capture_failure_media(self, case_id: str):
        """失败自动截图（T12.3）：协议方法缺失或未启用时静默跳过。"""
        capture = getattr(self._actions, "capture_failure_screenshot", None)
        if capture is None or self._on_media is None:
            return
        try:
            path = await capture(case_id)
            if path:
                self._on_media(case_id, path)
        except Exception as exc:
            logger.warning(f"失败截图保存异常（忽略）: {exc}")

    def _log(self, message):
        """按 5.1.6 格式上报日志：时间戳与消息分开传，由面板统一渲染 [HH:mm:ss]。"""
        self._on_log(time.strftime("%H:%M:%S"), message)