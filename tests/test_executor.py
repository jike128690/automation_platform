"""队列执行与状态机单元测试。"""
from app.data.demo_cases import DEMO_MODULES
from app.engine.executor import STATUS_FAILED, STATUS_PASSED, STATUS_RUNNING, QueueExecutor

CHECKED = [(m, c) for m in DEMO_MODULES for c in m.cases if c.default_checked]


class ScriptedRunner:
    """按调用序号返回预设结果。"""

    def __init__(self, fail_calls=()):
        self.fail_calls = set(fail_calls)
        self.calls = 0

    def run_step(self, step):
        self.calls += 1
        return self.calls not in self.fail_calls


def test_sequential_execution_all_passed():
    statuses, logs, finished = [], [], []
    runner = ScriptedRunner()
    executor = QueueExecutor(
        runner,
        on_status=lambda cid, st: statuses.append((cid, st)),
        on_log=lambda ts, msg: logs.append(msg),
        on_finished=finished.append,
    )
    passed, failed = executor.run(CHECKED)
    assert (passed, failed) == (12, 0)
    assert finished == [False]
    running = [s for s in statuses if s[1] == STATUS_RUNNING]
    passed_st = [s for s in statuses if s[1] == STATUS_PASSED]
    assert len(running) == 12 and len(passed_st) == 12
    assert not any(s[1] == STATUS_FAILED for s in statuses)
    assert runner.calls == sum(len(c.steps) for _, c in CHECKED)


def test_failure_continues_to_next_case():
    fail_call = sum(len(c.steps) for _, c in CHECKED[:1]) + 1  # 第二条用例第一步失败
    runner = ScriptedRunner(fail_calls={fail_call})
    statuses = []
    executor = QueueExecutor(runner, on_status=lambda cid, st: statuses.append((cid, st)))
    passed, failed = executor.run(CHECKED)
    assert (passed, failed) == (11, 1)
    second, third = CHECKED[1][1].case_id, CHECKED[2][1].case_id
    assert (second, STATUS_FAILED) in statuses
    assert (third, STATUS_PASSED) in statuses


def test_runner_exception_fails_case_and_continues():
    class BoomRunner(ScriptedRunner):
        def run_step(self, step):
            self.calls += 1
            if self.calls == sum(len(c.steps) for _, c in CHECKED[:1]) + 1:
                raise RuntimeError("boom")
            return True

    statuses, logs = [], []
    executor = QueueExecutor(
        BoomRunner(),
        on_status=lambda cid, st: statuses.append((cid, st)),
        on_log=lambda ts, msg: logs.append(msg),
    )
    passed, failed = executor.run(CHECKED)
    assert (passed, failed) == (11, 1)
    assert any("失败: boom" in msg for msg in logs)


def test_module_suite_logs_once_per_module():
    logs = []
    executor = QueueExecutor(ScriptedRunner(), on_log=lambda ts, msg: logs.append(msg))
    executor.run(CHECKED)
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

    executor = QueueExecutor(ScriptedRunner(), on_status=on_status, on_finished=finished.append)
    holder["executor"] = executor
    passed, failed = executor.run(CHECKED)
    assert (passed, failed) == (1, 1)
    assert finished == [True]
    ran = [cid for cid, st in statuses if st == STATUS_RUNNING]
    assert ran == [CHECKED[0][1].case_id, CHECKED[1][1].case_id]
    assert (CHECKED[1][1].case_id, STATUS_FAILED) in statuses