"""用例队列执行引擎（状态机）。"""
import time
from typing import Protocol

from app.data.models import TestStep

STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"


class StepRunner(Protocol):
    """步骤执行器接口：T4.4 由 Playwright 实现。"""

    def run_step(self, step: TestStep) -> bool:
        ...


class QueueExecutor:
    """按队列顺序执行用例：单条失败续跑，支持手动停止。"""

    def __init__(self, runner, on_status=None, on_log=None, on_finished=None):
        self._runner = runner
        self._on_status = on_status or (lambda cid, st: None)
        self._on_log = on_log or (lambda ts, msg: None)
        self._on_finished = on_finished or (lambda manual: None)
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self, case_pairs):
        """执行 (TestModule, TestCase) 队列，返回 (通过数, 失败数)。"""
        passed = failed = 0
        last_module = None
        for module, case in case_pairs:
            if self._stop_requested:
                self._log("用户手动停止测试，任务已安全终止")
                break
            if module is not last_module:
                self._log(f"开始执行测试套件: {module.module_name}")
                last_module = module
            if self._run_case(case):
                passed += 1
            else:
                failed += 1
        self._on_finished(self._stop_requested)
        return passed, failed

    def _run_case(self, case) -> bool:
        self._on_status(case.case_id, STATUS_RUNNING)
        for step in case.steps:
            if self._stop_requested:
                break
            try:
                ok = self._runner.run_step(step)
            except Exception as exc:
                self._log(f"[{case.case_id}] {case.short_name}: {step.remark}... 失败: {exc}")
                self._on_status(case.case_id, STATUS_FAILED)
                return False
            if not ok:
                self._log(f"[{case.case_id}] {case.short_name}: {step.remark}... 失败")
                self._on_status(case.case_id, STATUS_FAILED)
                return False
            self._log(f"[{case.case_id}] {case.short_name}: {step.remark}... 通过")
        if self._stop_requested:
            self._on_status(case.case_id, STATUS_FAILED)
            return False
        self._on_status(case.case_id, STATUS_PASSED)
        return True

    def _log(self, message):
        self._on_log(time.strftime("%H:%M:%S"), message)