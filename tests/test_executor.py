"""异步队列执行与状态机单元测试（cdp.md 阶段四）。"""
import asyncio

from app.data.demo_cases import DEMO_MODULES
from app.data.models import TestCase, TestModule, TestStep
from app.engine.executor import STATUS_FAILED, STATUS_PASSED, STATUS_RUNNING, AsyncExecutor

CHECKED = [(m, c) for m in DEMO_MODULES for c in m.cases if c.default_checked]


class FakeAsyncActions:
    """按调用序号脚本化：记录调用、按序号抛异常、可选定位失败。"""

    def __init__(self, fail_calls=(), missing_selectors=()):
        self.fail_calls = set(fail_calls)
        self.missing_selectors = set(missing_selectors)
        self.calls = []
        self.count = 0
        self.session_clears = 0

    async def goto(self, url):
        self._touch("goto", url, "")

    async def clear_session(self):
        self.session_clears += 1

    async def locate(self, selector):
        self._touch("locate", selector, "")
        if selector in self.missing_selectors:
            return None
        return {"x": 10, "y": 20, "width": 100, "height": 30}

    async def fill(self, selector, value):
        self._touch("fill", selector, value)

    async def click(self, selector):
        self._touch("click", selector, "")

    async def assert_visible(self, selector):
        self._touch("assert_visible", selector, "")

    def _touch(self, action, selector, value):
        self.count += 1
        self.calls.append((action, selector, value))
        if self.count in self.fail_calls:
            raise RuntimeError("boom")


def _make_executor(actions, **callbacks):
    kwargs = {"visual_pause": 0, "post_pause": 0}
    kwargs.update(callbacks)
    return AsyncExecutor(actions, **kwargs)


def _run(executor):
    return asyncio.run(executor.run(CHECKED))


def test_sequential_execution_all_passed():
    statuses, logs, finished = [], [], []
    executor = _make_executor(
        FakeAsyncActions(),
        on_status=lambda cid, st: statuses.append((cid, st)),
        on_log=lambda ts, msg: logs.append(msg),
        on_finished=finished.append,
    )
    passed, failed = _run(executor)
    assert (passed, failed) == (12, 0)
    assert finished == [False]
    running = [s for s in statuses if s[1] == STATUS_RUNNING]
    passed_st = [s for s in statuses if s[1] == STATUS_PASSED]
    assert len(running) == 12 and len(passed_st) == 12
    assert not any(s[1] == STATUS_FAILED for s in statuses)


def _action_calls(steps):
    """Fake 中每次动作产生一次调用：goto=1，元素步骤(locate+动作)=2。"""
    return sum(1 if s.action_type == "goto" else 2 for s in steps)


def test_failure_continues_to_next_case():
    fail_call = sum(_action_calls(c.steps) for _, c in CHECKED[:1]) + 1  # 第二条用例第一步
    statuses = []
    executor = _make_executor(
        FakeAsyncActions(fail_calls={fail_call}),
        on_status=lambda cid, st: statuses.append((cid, st)),
    )
    passed, failed = _run(executor)
    assert (passed, failed) == (11, 1)
    second, third = CHECKED[1][1].case_id, CHECKED[2][1].case_id
    assert (second, STATUS_FAILED) in statuses
    assert (third, STATUS_PASSED) in statuses


def test_locate_missing_fails_case_and_continues():
    statuses, logs = [], []
    executor = _make_executor(
        FakeAsyncActions(missing_selectors={"#login-error"}),  # 002 用例断言元素缺失
        on_status=lambda cid, st: statuses.append((cid, st)),
        on_log=lambda ts, msg: logs.append(msg),
    )
    passed, failed = _run(executor)
    assert (passed, failed) == (11, 1)
    assert (CHECKED[1][1].case_id, STATUS_FAILED) in statuses
    assert (CHECKED[2][1].case_id, STATUS_PASSED) in statuses
    assert any("失败: 元素未找到" in m for m in logs)


def test_module_suite_logs_once_per_module():
    logs = []
    executor = _make_executor(FakeAsyncActions(), on_log=lambda ts, msg: logs.append(msg))
    _run(executor)
    suite_logs = [m for m in logs if m.startswith("开始执行测试套件")]
    assert len(suite_logs) == 3
    assert suite_logs[0] == "开始执行测试套件: [模块一] 登录与基础功能"
    assert suite_logs[2] == "开始执行测试套件: [模块三] 交易与订单管理"


def test_manual_stop_keeps_remaining_waiting():
    statuses, finished = [], []
    holder = {}

    def on_status(cid, st):
        statuses.append((cid, st))
        if st == STATUS_RUNNING and cid == CHECKED[1][1].case_id:
            holder["executor"].request_stop()

    executor = _make_executor(
        FakeAsyncActions(),
        on_status=on_status,
        on_finished=finished.append,
    )
    holder["executor"] = executor
    passed, failed = _run(executor)
    assert (passed, failed) == (1, 1)
    assert finished == [True]
    ran = [cid for cid, st in statuses if st == STATUS_RUNNING]
    assert ran == [CHECKED[0][1].case_id, CHECKED[1][1].case_id]
    assert (CHECKED[1][1].case_id, STATUS_FAILED) in statuses


def test_highlight_rhythm_set_then_clear_per_element_step():
    highlights = []
    executor = _make_executor(
        FakeAsyncActions(),
        on_highlight=lambda rect, tooltip: highlights.append((rect, tooltip)),
    )
    _run(executor)
    non_goto = sum(1 for _, c in CHECKED for s in c.steps if s.action_type != "goto")
    assert len(highlights) == non_goto * 2  # 每个元素步骤：设置 + 清除
    for i, (rect, _) in enumerate(highlights):
        if i % 2 == 0:
            assert isinstance(rect, dict) and rect  # 定位后设置高亮（视口坐标）
        else:
            assert rect == {}                        # 步骤完成后清除高亮（空 dict）


def test_unknown_action_type_fails_case():
    case = TestCase("999", "[999] 未知动作类型", "未知动作", True, [
        TestStep(1, "goto", "http://127.0.0.1:8765/login", "", "打开登录页"),
        TestStep(2, "hover", "#x", "", "悬停操作"),
    ])
    module = TestModule("M99", "[模块九] 测试模块", [case])
    statuses = []
    executor = _make_executor(FakeAsyncActions(), on_status=lambda cid, st: statuses.append((cid, st)))

    async def run_single():
        return await executor.run([(module, case)])

    passed, failed = asyncio.run(run_single())
    assert (passed, failed) == (0, 1)
    assert (case.case_id, STATUS_FAILED) in statuses


def test_session_isolation_cleared_per_case():
    """每条用例开始前清一次会话（T8.1 真机联调：登录态跨用例污染导致 002/004/005 失败）。"""
    actions = FakeAsyncActions()
    executor = _make_executor(actions)
    _run(executor)
    assert actions.session_clears == 12  # 12 条勾选用例各一次