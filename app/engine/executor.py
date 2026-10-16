"""用例队列执行引擎（状态机）。

职责：按用户勾选的用例顺序一条条执行，维护每条用例的
「等待中 → 进行中 → 已通过 / 测试执行失败」状态机，并保证：
  1. 单条用例失败不中断整个批次（失败续跑，见 5.1.5）；
  2. 手动停止时在「当前步骤执行完成后」安全退出，剩余用例保持等待中（见 5.1.2）。

设计要点（对应 4.3.2 全异步线程模型）：
  - 本模块为纯 Python 实现，不依赖 PyQt，可脱离 Qt 环境直接做单元测试；
  - 执行结果通过三个回调（on_status / on_log / on_finished）上报，
    WorkerThread 负责把它们桥接成 Qt 信号投递到主线程；
  - 真实浏览器操作通过 StepRunner 接口注入（T4.4 由 Playwright 实现），
    测试时可注入假执行器，因此本模块不关心步骤内部怎么跑。
"""
import time
from typing import Protocol

from loguru import logger

from app.data.models import TestStep

# 用例状态常量（与开发计划 6.3 节 sig_case_status_changed 的 status 取值一致）
STATUS_RUNNING = "running"  # 进行中
STATUS_PASSED = "passed"    # 已通过
STATUS_FAILED = "failed"    # 测试执行失败


class StepRunner(Protocol):
    """步骤执行器接口（鸭子类型协议）。

    任何实现了 run_step 的对象都可作为执行器注入：
      - T4.4 正式实现：Playwright 无头浏览器实际操作（goto/fill/click/断言）；
      - 单元测试：ScriptedRunner 之类按预设脚本返回结果。
    run_step 返回 False 或抛出异常都视为该步骤失败。
    """

    def run_step(self, step: TestStep) -> bool:
        """执行单个测试步骤。

        Args:
            step: 一条 TestStep 数据（action_type/selector/value/remark）。
        Returns:
            True 表示步骤成功；False 或抛异常表示失败。
        """
        ...


class QueueExecutor:
    """按队列顺序执行用例的引擎。

    状态机流转（「等待中」由 UI 面板负责展示，本类只上报进行中与最终结果）：
      waiting → running → passed | failed

    停止语义：
      - 步骤循环每轮开头检查停止标志，保证「当前步骤执行完成后」才退出；
      - 被停止时正在跑的用例记为 failed，尚未开始的用例保持 waiting；
      - 结束时回调 on_finished(True) 通知主线程释放控件（见 6.3 sig_batch_finished）。
    """

    def __init__(self, runner, on_status=None, on_log=None, on_finished=None):
        """
        Args:
            runner: 实现 StepRunner 协议的对象，负责真正执行每个步骤。
            on_status: 用例状态变更回调 (case_id, status)，status 取 STATUS_* 常量。
            on_log: 日志回调 (timestamp, message)，timestamp 为 HH:mm:ss。
            on_finished: 批次结束回调 (is_manual_stopped)，供 UI 解锁控件。
        """
        self._runner = runner
        self._on_status = on_status or (lambda cid, st: None)
        self._on_log = on_log or (lambda ts, msg: None)
        self._on_finished = on_finished or (lambda manual: None)
        # 手动停止标志：主线程经 WorkerThread.request_stop 置位，本线程轮询读取
        self._stop_requested = False

    def request_stop(self):
        """请求安全停止：执行引擎在下一个步骤边界响应。"""
        self._stop_requested = True

    def run(self, case_pairs):
        """执行整个用例队列。

        Args:
            case_pairs: (TestModule, TestCase) 列表，按树展示顺序排列
                        （来自 CaseTree.selected_pairs()）。
        Returns:
            (通过数, 失败数) 二元组，供右栏统计使用。
        """
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
            # 单条失败不中断批次：无论成败都继续下一条用例
            if self._run_case(case):
                passed += 1
            else:
                failed += 1
        # 通知主线程批次结束（True=手动停止，False=全部执行完）
        self._on_finished(self._stop_requested)
        logger.info(f"测试批次结束：通过 {passed} 条，失败 {failed} 条")
        return passed, failed

    def _run_case(self, case) -> bool:
        """执行单条用例的全部步骤，返回该用例是否通过。"""
        self._on_status(case.case_id, STATUS_RUNNING)  # 进入「进行中」
        for step in case.steps:
            # 步骤边界停止检查：保证当前动作执行完才安全退出
            if self._stop_requested:
                break
            try:
                ok = self._runner.run_step(step)
            except Exception as exc:
                # 步骤抛异常（如元素定位失败）同样视为用例失败，附异常原因
                logger.exception(f"用例 {case.case_id} {case.short_name} 步骤执行异常")
                self._log(f"[{case.case_id}] {case.short_name}: {step.remark}... 失败: {exc}")
                self._on_status(case.case_id, STATUS_FAILED)
                return False
            if not ok:
                self._log(f"[{case.case_id}] {case.short_name}: {step.remark}... 失败")
                self._on_status(case.case_id, STATUS_FAILED)
                return False
            self._log(f"[{case.case_id}] {case.short_name}: {step.remark}... 通过")
        if self._stop_requested:
            # 手动停止导致未跑完：该用例归为失败，剩余用例由外层保持 waiting
            self._on_status(case.case_id, STATUS_FAILED)
            return False
        self._on_status(case.case_id, STATUS_PASSED)  # 全部步骤通过
        return True

    def _log(self, message):
        """按 5.1.6 格式上报日志：时间戳与消息分开传，由面板统一渲染 [HH:mm:ss]。"""
        self._on_log(time.strftime("%H:%M:%S"), message)