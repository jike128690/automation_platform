# QWEN.md — automation_platform 项目上下文

## 项目定位

Web 自动化测试平台 v2.5（Windows 桌面端）：PyQt6 桌面客户端 + Playwright 异步引擎。运行时经 CDP 截图流把真实浏览器画面实时渲染到中央画布，叠加元素高亮红框与动作气泡；左侧用例树勾选用例，右侧状态面板与日志面板实时反馈。内置本地 Mock 站点保证任何环境演示 100% 可用。

**技术栈**：Python ≥3.12 · PyQt6（6.11）· PyQt6-Fluent-Widgets（1.11.3，导入名 `qfluentwidgets`）· playwright 1.63.0（`async_api`）· loguru · pytest。

**依赖管理**：统一走 **uv**（pyproject.toml + uv.lock，`[tool.uv] package = false`）。`requirements.txt` 由 `uv export` 生成，勿手改；不要用 pip 直接操作 .venv。

**进度**：M1–M8 全部完成（阶段一 UI 骨架 → 阶段五性能调优 / T8.2 单元验证），当前 81 个测试全绿。

## 常用命令

| 用途 | 命令 |
|---|---|
| 同步依赖 | `uv sync` |
| 运行应用 | `uv run python main.py` |
| 运行测试 | `uv run pytest`（当前 81 passed，约 9s） |
| 重新生成 requirements.txt | `uv export --format requirements-txt --no-hashes > requirements.txt` |

启动流程（main.py）：`setup_logging()` → QApplication → `check_browser_env()` 三级探测（Chrome → Edge → Playwright Chromium，见 `app/utils/env_check.py`，返回 `(channel, path)`，channel ∈ `chrome/msedge/chromium`）；全部缺失则弹窗 `MISSING_BROWSER_MSG` 并退出。

## 目录结构

```
main.py                       # 入口：日志 → 环境自检 → MainWindow
pyproject.toml / uv.lock      # uv 依赖声明与锁文件
requirements.txt              # uv export 产物（勿手改）
app/
├── config.py                 # APP_TITLE = "自动化测试平台 v2.5"、MOCK_SITE_URL = http://127.0.0.1:8765
├── main_window.py            # 主窗口：工具栏 + 运行/停止联调 + closeEvent 三级回收 + MockSite 生命周期
├── core/logger.py            # loguru 配置：stderr + log/app.log（10MB 轮转 / 7 天 / utf-8）
├── engine/
│   ├── worker_thread.py      # QThread + asyncio 双事件循环底座，5 个 Qt 信号桥接主线程
│   ├── executor.py           # AsyncExecutor 用例队列引擎 + AsyncPlaywrightActions 真实动作
│   ├── cdp_stream.py         # CDPStreamClient：Screencast 推-应答背压 / 12FPS 节流 / QImage 解码
│   └── cdp_demo.py           # 独立 CDP-over-WebSocket 演示脚本（用户并行维护，勿改）
├── pages/
│   ├── home_page.py          # 首页三栏布局：CaseTree(280) + BrowserView + 右栏(340)
│   └── batch_config_page.py  # 批量配置页（阶段二占位）
├── widgets/
│   ├── case_tree.py          # 用例树：勾选/搜索过滤/全选(三态)/统计/锁定
│   ├── browser_view.py       # 信息栏 + BrowserCanvas 双图层画布（帧/高亮/受控锁定）
│   ├── status_panel.py       # 统计栏 + 进度条(floor) + 用例状态队列（模块聚合/失败红字）
│   └── log_panel.py          # 100ms 批量刷日志 + 2000 行裁剪 + 自动滚动 + 只读可复制
├── data/
│   ├── models.py             # TestModule / TestCase / TestStep dataclass（均带 __test__ = False）
│   └── demo_cases.py         # 硬编码演示数据：3 模块（M01–M03）24 用例，选择器全部由 Mock 站点覆盖
└── utils/
    ├── env_check.py          # 浏览器三级通道探测（注册表 App Paths + 常见路径 + ms-playwright 缓存）
    └── mock_site.py          # MockSite：ThreadingHTTPServer（127.0.0.1:8765），6 个静态页
tests/                        # 镜像 app 结构：每模块一个 test_*.py
log/                          # 运行日志（gitignore）
```

## 核心架构

### 双事件循环引擎（app/engine/worker_thread.py）
主线程跑 Qt 事件循环，`run()` 在工作线程内创建独立 asyncio 事件循环并执行 `_async_main()`；工作线程只发信号、永不直接操作控件。**5 个信号契约**（与开发计划 6.3 / cdp.md 3.1 对齐）：

| 信号 | 类型 | 语义 |
|---|---|---|
| `sig_frame_ready` | `(QImage, str)` | 解码帧 + 当前页面 URL |
| `sig_highlight_element` | `(dict, str)` | 视口坐标 BoundingBox + 气泡文案；**空 dict `{}` 表示清除** |
| `sig_case_status_changed` | `(str, str)` | case_id + `running/passed/failed` |
| `sig_log_appended` | `(str, str)` | `HH:mm:ss` 时间戳 + 消息 |
| `sig_batch_finished` | `(bool)` | True=手动停止，False=全部执行完 |

配置 API：`set_queue(pairs)`（须在 start() 前）、`set_actions(impl)`、`set_browser(channel, path, viewport, start_url)`（start_url 为 None 则不启浏览器，纯队列/测试模式）、`set_rhythm(visual, post)`。`request_stop()` 置位停止标志并转发给执行器。浏览器生命周期第一级回收在 `_async_main` 的 finally 逆序执行：stopScreencast → detach → page.close → browser.close → playwright.stop，防僵尸 chrome.exe。

### 用例队列执行引擎（app/engine/executor.py）
状态机 waiting → running → passed | failed；**单条失败不中断批次**（失败续跑）；手动停止在步骤边界安全退出，剩余用例保持 waiting。标准节拍（cdp.md 2.3）：Pre-Step 日志 → `locate()` 滚动进视口取 BoundingBox → 高亮信号 → 350ms 视觉停顿 → 动作 → 清高亮 → 成功日志 → 150ms 等新帧。动作经 `AsyncPageActions` 协议注入：真实实现 `AsyncPlaywrightActions`（Playwright 异步 API），测试用 FakeActions（节奏置 0）。**用例级会话隔离**：每条用例开始前 `clear_session()`（localStorage/sessionStorage），008 会话保持用例需用例内两次 goto 保留会话，故清理不放 goto。

### CDP 截图流（app/engine/cdp_stream.py）
`Page.startScreencast`（jpeg / q75 / 1280x800 / everyNthFrame=2）采用**推-应答背压**：每帧先第一时间异步 `screencastFrameAck`（丢弃帧也要 Ack，防挂起渲染管线），再按目标 12 FPS 时间戳节流，过密帧整帧丢弃；Base64 → JPEG → QImage 解码后回调。`stop()` 幂等可重复调用。

### 主窗口运行/停止联调（app/main_window.py）
`_on_run_clicked`：校验至少勾选一条（否则 `EMPTY_QUEUE_MSG`）→ 清空日志/重载状态队列 → 锁定用例树 + 画布受控 → 工具栏互斥（运行禁用/停止高亮/二级入口置灰）→ WorkerThread 全链路（浏览器指向 Mock 登录页 + 队列 + 5 信号直连面板）。`_on_stop_clicked` 请求安全停止。`closeEvent` 第二级回收：worker.wait(2000) 超时后 `taskkill /F /T /PID` 强杀浏览器进程树（第三级），最后停 Mock 站点。

### 中间画布（app/widgets/browser_view.py）
固定视口 1280x800（`VIEWPORT_WIDTH/HEIGHT`），`compute_letterbox` 等比缩放居中（取 min 缩放因子防变形），`map_rect` 把视口 BBox 换算画布坐标（兼容 `{x,y,width,height}` 与 `{x,y,w,h}` 两套字段——T8.1 真机崩溃点）。BrowserCanvas 三图层：Layer0 底色/空闲占位 → Layer1 视频帧 → Layer2 高亮叠加（红框 + 半透明遮罩 + 准星 + 动作气泡，气泡贴顶自动翻转下方）。受控期吞掉鼠标/键盘事件。**`set_highlight` 独立调用 `update()`**（零帧补偿，cdp.md 陷阱二）：网页静止无新帧时叠加层也必须即时显隐。

### 内置 Mock 站点（app/utils/mock_site.py）
`ThreadingHTTPServer` + daemon 线程，随 MainWindow 生命周期 `start()/stop()`（幂等）。6 个静态页：`/login`（admin/123456 校验，开放问题 01 默认方案）、`/register`、`/index`、`/product/1`、`/cart`、`/orders`，覆盖 demo_cases 全部选择器。

## 测试约定

- `tests/` 镜像 `app/` 结构，纯 pytest（无其他 dev 依赖）；widget 测试需 `QT_QPA_PLATFORM=offscreen` + session 级 `qapp` fixture（见 test_worker_thread.py）。
- 引擎测试用 `FakeAsyncActions` 脚本化（记录调用/按序号抛异常/可选定位失败），`visual_pause/post_pause` 置 0 提速；环境探测用 `monkeypatch`。
- 新增功能须配套单元测试并跑通 `uv run pytest`。

## 开发约定

- 代码注释、日志、提交信息全中文；**注释默认精简**，engine 包（worker_thread/executor/cdp_stream）是用户点名要求详述的例外，保持现有详细注释。
- 提交风格带里程碑前缀：`M8: 阶段五/T8.2 单元验证补充（closeEvent 兜底/连点停止/防抖/零帧补偿）`。
- **提交前只显式暂存本任务文件**（`git add <具体文件>`），禁止 `git add -A`——曾误卷入用户并行改动（cdp_demo.py、pyproject.toml）。
- `app/engine/cdp_demo.py`、`pyproject.toml` 等用户并行维护的文件不属于自动化任务范围，改动前先确认。
- 低配机约束（双核/8GB）：帧率节流、日志防抖、行数裁剪、批次内浏览器复用、三级资源回收均为既定设计，不可回退。

## 关键陷阱（踩坑记录）

- **PyQt6 信号严格类型检查**：`pyqtSignal(dict, str)` 等强类型信号 `emit(None, "")` 抛 TypeError，QThread 内未捕获会 0xC0000409 进程快速失败崩溃；"清除"语义用对应类型空值（dict→`{}`、list→`[]`），绝不传 None。
- **工作线程严禁创建 QPixmap**，解码产物只用 QImage（平台无关、可安全跨线程）。
- **Playwright `bounding_box()` 字段是 `{x,y,width,height}`**，`map_rect` 需兼容两套字段命名。
- **PyQt6 枚举与 int 不直接相等**（`Qt.CheckState == int` 恒 False，`int()` 转换会抛 TypeError），用 `Qt.CheckState(state)` 显式转换。
- 高亮的设置/清除在 `_run_step` 内成对收敛（goto 步骤无高亮信号；异常路径也要清高亮）。

## 参考文档

代码注释频繁引用 `cdp.md`（CDP 截图流架构蓝图：双事件循环/背压/坐标映射/三级回收）与《开发计划》章节号（5.1.x、6.3、第 9 节、T7.1/T8.x）。这些文档不在仓库内（QWEN.md 是仓库唯一 md 文件），需要时可向用户索取。
