# 阶段一 验收对照清单与演示脚本（T8.3）

> 对应《开发计划》8.1/8.2/8.3 与 PRD 6.1；核对日期：2026-10-17。
> 验证基线：`uv run pytest -q`（81 passed）；真机脚本 `.qwen/tmp/verify_t81.py`（端到端闭环）、`.qwen/tmp/verify_stage5.py`（极端停止）、`.qwen/tmp/verify_stage4.py`（失败续跑）。
> 结论：**阶段一 PRD 6.1 验收场景全部达成**，仅"二级入口弹窗/主窗口拖动零卡顿"两项属人工演示项（实现已就绪）。

---

## 一、PRD 6.1 验收标准逐条核对

### 模块 1：启动与顶部（5.1.1 / 5.1.2）

| 验收场景 | 预期行为 | 实现位置 | 验证状态 |
|:---|:---|:---|:---|
| 场景 1 启动与预置加载 | 标题"自动化测试平台 v2.5"；浏览器自检（缺失弹窗退出）；3 模块 24 用例默认勾选 12；Mock 站点随客户端启停 | `app/config.py`、`main.py`、`app/utils/env_check.py`、`app/main_window.py`、`app/utils/mock_site.py` | ✅ 单元（test_env_check / test_models / test_case_tree / test_mock_site）+ 真机（chrome 通道探测） |
| 场景 2 二级入口拦截 | 导入用例/批量配置/导出报告 → 弹窗"功能开发中" | `MainWindow._show_todo` | ✅ 实现；⏳ 人工演示 + 截图留存 |
| 场景 3 运行期按钮锁定 | 运行中：运行禁用、停止高亮、二级入口一并置灰 | `MainWindow._on_run_clicked / _on_batch_finished / _set_secondary_enabled` | ✅ 单元（test_main_window_flow） |
| 场景 4 安全停止测试 | 停止过渡态"正在停止..."；当前步骤完成后安全退出；关闭客户端零残留 | `_on_stop_clicked`、`executor` 步骤边界检查、`closeEvent` 三级回收 | ✅ 单元（stop transition / closeEvent / taskkill 兜底 / 连点幂等）+ 真机（T8.1 场景 B、T8.2 场景 A/B、零残留） |

### 模块 2：左侧用例列表（5.1.3）

| 验收场景 | 预期行为 | 实现位置 | 验证状态 |
|:---|:---|:---|:---|
| 场景 1 勾选联动统计 | 全选三态；模块级联动子用例；单条勾选实时刷新"总计: X 个用例, 已选中: Y 个" | `CaseTree`（ItemIsAutoTristate / check_all / stats_label） | ✅ 单元（test_case_tree ×8） |
| 场景 2 关键词搜索 | 占位"搜索"、实时过滤模块名/用例编号/名称、无匹配空状态 | `CaseTree._on_search / empty_label` | ✅ 单元（test_case_tree） |
| 场景 3 运行期交互锁定 | 运行中复选框/搜索框禁用；结束后恢复并保持勾选 | `CaseTree.set_locked` | ✅ 单元 + 真机（T8.1 左侧解锁） |

### 模块 3：中间浏览器自动化视图（5.1.4）

| 验收场景 | 预期行为 | 实现位置 | 验证状态 |
|:---|:---|:---|:---|
| 场景 1 截图流同步无外部弹窗 | Headless 画面渲染画布、URL 实时同步、10~15 FPS | `BrowserView / BrowserCanvas` + `CDPStreamClient` + `WorkerThread` | ✅ 真机（T4.4 10.0 FPS、T8.1 画布有帧 + URL 同步） |
| 场景 2 非侵入式红框气泡 | 红框+准星+气泡"正在执行：…"，坐标等比准确，不污染被测 DOM | `BrowserCanvas Layer2 / map_rect / compute_bubble_pos`（纯画布层绘制） | ✅ 单元（test_canvas / test_coordinate，含 Playwright width/height 字段）+ 真机（T8.1 红框随步骤跳动） |
| 场景 3 受控状态人工操作拦截 | 受控期鼠标/键盘事件吞掉；地址栏只读；刷新按钮禁用 | `BrowserCanvas.set_controlled`（5 类事件拦截）+ `BrowserInfoBar` | ✅ 单元（test_browser_view） |

### 模块 4：右侧状态面板（5.1.5）

| 验收场景 | 预期行为 | 实现位置 | 验证状态 |
|:---|:---|:---|:---|
| 场景 1 队列仅展示勾选用例 | 未勾选用例严禁出现；模块行随子用例推进更新 | `StatusPanel.load_queue`（只收 pairs）+ `_refresh_module` | ✅ 单元（test_status_panel） |
| 场景 2 进度与成功状态更新 | 已执行/成功/失败统计；进度 floor 取整（`N% (X/Y)`）；状态枚举 | `StatusPanel._refresh_stats / update_status` | ✅ 单元（1/12→8%、2/12→16%）+ 真机（T8.1 100% (12/12)） |
| 场景 3 用例失败表现与继续执行 | 失败红字 ✖；模块聚合（进行中>有失败>已完成>等待中）；失败续跑 | `StatusPanel` + `AsyncExecutor` 失败续跑 | ✅ 单元 + 真机（阶段四失败用例续跑、T8.1 12 全过） |

### 模块 5：右侧日志面板（5.1.6）

| 验收场景 | 预期行为 | 实现位置 | 验证状态 |
|:---|:---|:---|:---|
| 场景 1 实时日志输出与格式 | `[{HH:mm:ss}] {消息}`；实时滚动；只读可复制 | `LogPanel.append_log / _flush`（100ms 批刷 + 自动滚动） | ✅ 单元（格式/批量/1000 条防抖）+ 真机（T8.1 109 条） |
| 场景 2 停止后日志保留 | 不自动清空；手动停止追加"用户手动停止测试，任务已安全终止" | `LogPanel`（clear 由运行前显式调用）+ executor 停止日志 | ✅ 单元 + 真机（T8.1 场景 B 停止日志） |

---

## 二、8.1 测试策略核对

| 测试类型 | 范围与方式 | 执行情况 |
|:---|:---|:---|
| 单元测试 | test_models / test_executor / test_coordinate（+ 扩展） | ✅ 81 passed：test_case_tree、test_status_panel、test_log_panel、test_canvas、test_browser_view、test_worker_thread、test_cdp_stream、test_env_check、test_mock_site、test_logger、test_main_window_flow |
| 集成验证 | 端到端跑通 12 条勾选用例：画面同步、状态统计、日志输出、失败续跑、手动停止 | ✅ T8.1 真机：12/12 全过、100% 进度、109 条日志、画布有帧、解锁；阶段四真机：失败续跑 |
| 手工验收 | 对照 PRD 6.1 逐条操作核对 | ✅ 本清单（T8.3）；二级入口弹窗/拖动零卡顿待正式演示确认 |
| 资源验证 | 停止/关闭后无残留 Chromium；主窗口拖动、点击停止零卡顿 | ✅ 零残留（T8.1/T8.2 真机 PowerShell 校验）；⏳ 拖动零卡顿人工演示 |

## 三、第 9 节性能优化核对

帧率动态调节（低配下限 10 FPS）✅（真机 10.0 FPS）｜ 解码入 WorkerThread ✅｜ 日志 100ms 批刷 ✅｜ 画布仅当前帧 + 日志 2000 行裁剪 ✅｜ 批次内浏览器单实例复用 ✅｜ Mock 站点轻量随客户端启停 ✅

---

## 四、Demo 演示脚本（开发计划 8.3 固化）

> 人工演示流程（每步含预期结果）；自动化闭环演示可运行 `.qwen/tmp/verify_t81.py`（场景 A/B 自动验证）。

| 步骤 | 操作 | 预期结果 | 验证依据 |
|:---|:---|:---|:---|
| 1 | 启动客户端 | 标题"自动化测试平台 v2.5"；3 模块 24 用例树，默认勾选 12；右侧"未运行"灰灯 | 模块 1 场景 1 |
| 2 | 点击【批量配置】 | 弹窗"功能开发中" | 模块 1 场景 2 |
| 3 | 勾选 `[003] 密码重置与找回` | 底部统计变为 13 条 | 模块 2 场景 1 |
| 4 | 搜索框输入"登录" | 列表实时过滤，仅显示匹配模块/用例 | 模块 2 场景 2 |
| 5 | 清空搜索、点击【运行测试】 | 运行按钮置灰、左侧锁定、画面同步（无外部窗口）、红框+气泡随步骤移动、右侧队列/进度实时更新、日志实时滚动 | 模块 1 场景 3 / 模块 3 / 模块 4 / 模块 5 |
| 6 | 第 2 条用例执行时点击【停止测试】 | 当前动作完成后安全停止；进度与日志保留；控件恢复 | 模块 1 场景 4 / 模块 5 场景 2 |
| 7 | 再次运行 | 队列与日志清空重来 | 模块 4/5（清空策略） |
| 8 | 关闭客户端 | 任务管理器无残留浏览器进程 | 模块 1 场景 4（closeEvent 三级回收） |