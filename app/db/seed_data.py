# -*- coding: utf-8 -*-
r"""真实业务种子数据（转录自 D:\WebAutomation\pages 视频监控系统 Page Object）。

数据来源（2026-11-25 转录，替代 demo_cases.py 内置 Demo）：
- pages/login/login_page.py      登录页（#login_common 登录框）
- pages/base_page.py             页面基类（站点 URL：https://192.168.3.102/）
- pages/preview/preview_page.py  实时预览视图（云台/扩展/工具栏）
- pages/preview/ptz_control.py   云台控件定位器 dataclass
- pages/preview/extend_control.py 扩展功能定位器 dataclass
- pages/preview/tool_box.py      视频工具栏定位器 dataclass
- pages/playback/playback_page.py 录像回放视图（#playbackbtn）
- pages/setup/setup_page.py      系统设置视图（#setupbtn）

转录规则：
- 站点为 SPA：登录前显示登录框，登录后同 URL 切换视图（预览/回放/设置），
  故各页面 page_url 相同，以 page_name + remark 区分进入方式；
- Page Object 类常量中确定的 CSS 定位器全部入 tb_page_element；
  文本型定位（get_by_text/get_by_role/get_by_title 的"变倍""预置位:"等）
  不入元素表，按 LDM 2.6 存步骤 target_override；
- 命令缩写与《数据库开发.md》4.5 映射一致：
  goto→GOTO_URL / fill→INPUT_TEXT / click→CLICK_ELEMENT /
  assert_visible→ASSERT_ELEMENT_VISIBLE；
- 密码步骤（#userPwd）is_secret=1，UI/日志脱敏。

步骤元组格式：
    (command, element_name|None, target_override|None, value, remark,
     is_secret, timeout_sec)
  - element_name 非 None 时步骤关联元素（element_id），target_override 置空；
  - GOTO_URL 步骤 element_name=None、target_override=页面 URL；
  - 文本型定位 element_name=None、target_override=XPATH 表达式。

用例元组格式：
    (case_code, case_name, short_name, default_checked, expected_summary,
     [steps])
模块元组格式：
    (module_code, module_name, [(page_name, [cases])])
页面元组格式：
    (page_name, page_url, remark, [(locator_type, locator_value, element_name)])
"""
from __future__ import annotations

SITE_URL = "https://192.168.3.102/"

ADMIN_USER = "admin"
ADMIN_PWD = "admin"

# 步骤元素引用常量（避免魔法字符串漂移）
E_USERNAME = "用户名输入框"
E_PASSWORD = "密码输入框"
E_REMEMBER = "记住密码复选框"
E_LOGIN_BTN = "登录按钮"
E_DOWNLOAD_LINK = "插件下载链接"
E_LANGUAGE = "语言下拉框"
E_PLAYBACK_NAV = "回放导航按钮"
E_SETUP_NAV = "设置导航按钮"
E_OPEN_LEFT = "左侧栏展开按钮"
E_CLOSE_LEFT = "左侧栏收起按钮"
E_PLAYER_SCREEN = "播放画面区域"
E_PTZ_UP = "云台方向键-上"
E_PTZ_RIGHT_UP = "云台方向键-右上"
E_PTZ_RIGHT = "云台方向键-右"
E_PTZ_RIGHT_DOWN = "云台方向键-右下"
E_PTZ_DOWN = "云台方向键-下"
E_PTZ_LEFT_DOWN = "云台方向键-左下"
E_PTZ_LEFT = "云台方向键-左"
E_PTZ_LEFT_UP = "云台方向键-左上"
E_ZOOM_ADD = "云台变倍放大"
E_ZOOM_SUB = "云台变倍缩小"
E_FOCUS_LBL = "云台聚焦标签"
E_FOCUS_ADD = "云台聚焦近焦"
E_FOCUS_SUB = "云台聚焦远焦"
E_IRIS_ADD = "云台光圈增大"
E_IRIS_SUB = "云台光圈减小"
E_PTZ_SPEED = "云台速度按钮"
E_SLIDER_VAL = "云台速度值"
E_PREPOINT = "预置位输入框"
E_ICON_3D = "3D定位图标"
E_AREA_FOCUS = "区域聚焦图标"
E_ZONE_EXPOSURE = "区域曝光图标"
E_AUTO_SCAN = "自动扫描图标"
E_FUNC_VOICE = "语音对讲图标"
E_DEFAULT_SCALE = "默认尺寸按钮"
E_ORIGINAL = "原始尺寸按钮"
E_FIT_WINDOW = "适应窗口按钮"
E_MAIN_STREAM = "主码流按钮"
E_SUB_STREAM = "辅码流按钮"
E_FULLSCREEN = "全屏按钮"
E_ELECZOOM = "电子放大按钮"
E_VOICE = "声音开关按钮"
E_RECORD = "手动录像按钮"
E_SNAP = "抓图按钮"
E_TALK = "对讲按钮"

# 文本型定位（不入元素表，XPATH 存 target_override）
X_NAV_PREVIEW = "//a[normalize-space()='预览']"          # get_by_role("link", name="预览")
X_TAB_ZOOM = "//*[normalize-space()='变倍']"             # get_by_text("变倍")
X_TAB_IRIS = "//*[normalize-space()='光圈']"             # get_by_text("光圈")
X_TAB_EXTEND = "//*[normalize-space()='扩展功能']"        # get_by_text("扩展功能")
X_LINK_PRESET = "//a[contains(normalize-space(),'预置位')]"  # get_by_role("link", name="预置位:")
X_BTN_PRESET_SET = "//*[@title='设置预置点']"             # get_by_title("设置预置点")

# ---------------------------------------------------------------- 页面与元素

SEED_PAGES: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    (
        "登录页", SITE_URL,
        "登录框 #login_common 所在页面（站点根 URL，登录前展示）",
        [
            ("CSS", "#userName", E_USERNAME),
            ("CSS", "#userPwd", E_PASSWORD),
            ("CSS", "#squaredFour", E_REMEMBER),
            ("CSS", "#loginbtn", E_LOGIN_BTN),
            ("CSS", "#downloadLink", E_DOWNLOAD_LINK),
            ("CSS", "#language", E_LANGUAGE),
        ],
    ),
    (
        "主框架页", SITE_URL,
        "登录成功后的导航框架（同 URL 切换视图），含预览/回放/设置入口",
        [
            ("CSS", "#playbackbtn", E_PLAYBACK_NAV),
            ("CSS", "#setupbtn", E_SETUP_NAV),
        ],
    ),
    (
        "实时预览页", SITE_URL,
        "点击导航\"预览\"进入的实时监控视图（云台/扩展功能/视频工具栏）",
        [
            ("CSS", "#open_left", E_OPEN_LEFT),
            ("CSS", "#close_left", E_CLOSE_LEFT),
            ("CSS", "#player_screen", E_PLAYER_SCREEN),
            ("CSS", "#ptzup", E_PTZ_UP),
            ("CSS", "#ptzrightup", E_PTZ_RIGHT_UP),
            ("CSS", "#ptz_right", E_PTZ_RIGHT),
            ("CSS", "#ptzrightdown", E_PTZ_RIGHT_DOWN),
            ("CSS", "#ptzdown", E_PTZ_DOWN),
            ("CSS", "#ptzleftdown", E_PTZ_LEFT_DOWN),
            ("CSS", "#ptzleft", E_PTZ_LEFT),
            ("CSS", "#ptzleftup", E_PTZ_LEFT_UP),
            ("CSS", "#ptz_zoomAdd", E_ZOOM_ADD),
            ("CSS", "#ptz_zoomSub", E_ZOOM_SUB),
            ("CSS", "#focuslbl", E_FOCUS_LBL),
            ("CSS", "#ptz_focusAdd", E_FOCUS_ADD),
            ("CSS", "#ptz_focusSub", E_FOCUS_SUB),
            ("CSS", "#ptz_irisAdd", E_IRIS_ADD),
            ("CSS", "#ptz_irisSub", E_IRIS_SUB),
            ("CSS", "#ptzspeed", E_PTZ_SPEED),
            ("CSS", "#horizontal_slider_val", E_SLIDER_VAL),
            ("CSS", "#prepoint", E_PREPOINT),
            ("CSS", ".icon_3D", E_ICON_3D),
            ("CSS", ".icon_Area_focus", E_AREA_FOCUS),
            ("CSS", ".icon_Zone_exposure", E_ZONE_EXPOSURE),
            ("CSS", ".auto-scan", E_AUTO_SCAN),
            ("CSS", ".func_voice", E_FUNC_VOICE),
            ("CSS", "#web_defaultScaleBtn", E_DEFAULT_SCALE),
            ("CSS", "#web_originalBtn", E_ORIGINAL),
            ("CSS", "#web_fitWindowBtn", E_FIT_WINDOW),
            ("CSS", "#web_main_stream", E_MAIN_STREAM),
            ("CSS", "#web_sub_stream", E_SUB_STREAM),
            ("CSS", "#web_fullscreen", E_FULLSCREEN),
            ("CSS", "#web_eleczoom", E_ELECZOOM),
            ("CSS", "#web_voice", E_VOICE),
            ("CSS", "#web_record", E_RECORD),
            ("CSS", "#web_snap", E_SNAP),
            ("CSS", "#web_talk", E_TALK),
        ],
    ),
    (
        "录像回放页", SITE_URL,
        "点击 #playbackbtn 导航进入的录像回放视图（控件定位器待补录）",
        [],
    ),
    (
        "系统设置页", SITE_URL,
        "点击 #setupbtn 导航进入的系统设置视图（控件定位器待补录）",
        [],
    ),
]

# ---------------------------------------------------------------- 模块/用例/步骤


def _goto(url: str, remark: str) -> tuple:
    return ("goto", None, url, "", remark, 0, None)


def _fill(element: str, value: str, remark: str, *, secret: int = 0) -> tuple:
    return ("fill", element, None, value, remark, secret, None)


def _click(element: str, remark: str) -> tuple:
    return ("click", element, None, "", remark, 0, None)


def _click_x(xpath: str, remark: str) -> tuple:
    return ("click", None, xpath, "", remark, 0, None)


def _assert(element: str, remark: str, timeout: int = 5) -> tuple:
    return ("assert_visible", element, None, "", remark, 0, timeout)


def _assert_x(xpath: str, remark: str, timeout: int = 5) -> tuple:
    return ("assert_visible", None, xpath, "", remark, 0, timeout)


def _login_steps() -> list[tuple]:
    """设备登录态只存于页面内存（重新 goto 即掉线），依赖登录的用例须自行登录。"""
    return [
        _fill(E_USERNAME, ADMIN_USER, '输入账号 "admin"'),
        _fill(E_PASSWORD, ADMIN_PWD, '输入密码 "admin"', secret=1),
        _click(E_LOGIN_BTN, "点击 [登录] 按钮"),
    ]


SEED_MODULES: list[tuple[str, str, list[tuple[str, list[tuple]]]]] = [
    (
        "M01", "[模块一] 登录与基础功能", [
            ("登录页", [
                ("001", "账号密码登录功能测试", "登录测试", 1,
                 "admin/admin 登录成功进入主框架视图", [
                     _goto(SITE_URL, "打开登录页"),
                     _fill(E_USERNAME, ADMIN_USER, '输入账号 "admin"'),
                     _fill(E_PASSWORD, ADMIN_PWD, '输入密码 "admin"', secret=1),
                     _click(E_REMEMBER, "勾选 [记住密码]"),
                     _click(E_LOGIN_BTN, "点击 [登录] 按钮"),
                 ]),
                ("002", "错误密码登录失败测试", "错误密码测试", 0,
                 "错误密码登录后仍停留在登录页", [
                     _goto(SITE_URL, "打开登录页"),
                     _fill(E_USERNAME, ADMIN_USER, '输入账号 "admin"'),
                     _fill(E_PASSWORD, "wrongpwd", '输入错误密码 "wrongpwd"', secret=1),
                     _click(E_LOGIN_BTN, "点击 [登录] 按钮"),
                 ]),
                ("003", "登录页核心元素可见测试", "登录元素测试", 0,
                 "用户名/密码/登录按钮/语言下拉框均可见", [
                     _goto(SITE_URL, "打开登录页"),
                     _assert(E_USERNAME, "断言用户名输入框可见"),
                     _assert(E_PASSWORD, "断言密码输入框可见"),
                     _assert(E_LOGIN_BTN, "断言登录按钮可见"),
                     _assert(E_LANGUAGE, "断言语言下拉框可见"),
                 ]),
                ("004", "插件下载入口可见测试", "插件下载测试", 0,
                 "插件下载链接可见", [
                     _goto(SITE_URL, "打开登录页"),
                     _assert(E_DOWNLOAD_LINK, "断言插件下载链接可见"),
                 ]),
                ("005", "不记住密码登录测试", "不记住密码测试", 1,
                 "不勾选记住密码直接登录", [
                     _goto(SITE_URL, "打开登录页"),
                     _fill(E_USERNAME, ADMIN_USER, '输入账号 "admin"'),
                     _fill(E_PASSWORD, ADMIN_PWD, '输入密码 "admin"', secret=1),
                     _click(E_LOGIN_BTN, "点击 [登录] 按钮（不勾选记住密码）"),
                 ]),
            ]),
        ],
    ),
    (
        "M02", "[模块二] 实时预览", [
            ("实时预览页", [
                ("006", "进入实时预览视图测试", "进入预览测试", 1,
                 "导航进入预览后播放画面可见（依赖登录态）", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _assert(E_PLAYER_SCREEN, "断言播放画面区域可见"),
                 ]),
                ("007", "左侧栏开合测试", "左侧栏测试", 0,
                 "左侧栏可展开并收起", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_OPEN_LEFT, "展开左侧栏"),
                     _click(E_CLOSE_LEFT, "收起左侧栏"),
                 ]),
                ("008", "画面尺寸切换测试", "尺寸切换测试", 0,
                 "适应窗口/默认/原始三种尺寸可切换", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_FIT_WINDOW, "切换 [适应窗口]"),
                     _click(E_DEFAULT_SCALE, "切换 [默认尺寸]"),
                     _click(E_ORIGINAL, "切换 [原始尺寸]"),
                 ]),
                ("009", "主辅码流切换测试", "码流切换测试", 0,
                 "主码流/辅码流可切换", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_MAIN_STREAM, "切换 [主码流]"),
                     _click(E_SUB_STREAM, "切换 [辅码流]"),
                 ]),
                ("010", "声音开关测试", "声音开关测试", 0,
                 "声音可开启/关闭", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_VOICE, "点击 [声音] 开关"),
                 ]),
                ("011", "手动录像测试", "手动录像测试", 0,
                 "手动录像可触发", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_RECORD, "点击 [录像] 按钮"),
                 ]),
                ("012", "抓图功能测试", "抓图测试", 0,
                 "抓图可触发", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_SNAP, "点击 [抓图] 按钮"),
                 ]),
                ("013", "全屏播放测试", "全屏测试", 0,
                 "进入全屏播放", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_FULLSCREEN, "点击 [全屏] 按钮"),
                 ]),
                ("014", "电子放大测试", "电子放大测试", 0,
                 "局部放大功能可触发", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_ELECZOOM, "点击 [电子放大] 按钮"),
                 ]),
            ]),
        ],
    ),
    (
        "M03", "[模块三] 云台与扩展功能", [
            ("实时预览页", [
                ("015", "云台八方向控制测试", "云台方向测试", 1,
                 "上/右上/右/右下/下/左下/左/左上 8 个方向键均可点击", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_PTZ_UP, "云台 [上]"),
                     _click(E_PTZ_RIGHT_UP, "云台 [右上]"),
                     _click(E_PTZ_RIGHT, "云台 [右]"),
                     _click(E_PTZ_RIGHT_DOWN, "云台 [右下]"),
                     _click(E_PTZ_DOWN, "云台 [下]"),
                     _click(E_PTZ_LEFT_DOWN, "云台 [左下]"),
                     _click(E_PTZ_LEFT, "云台 [左]"),
                     _click(E_PTZ_LEFT_UP, "云台 [左上]"),
                 ]),
                ("016", "云台变倍测试", "云台变倍测试", 0,
                 "变倍放大/缩小可操作", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click_x(X_TAB_ZOOM, "点击 [变倍] 页签"),
                     _click(E_ZOOM_ADD, "点击 [变倍放大]"),
                     _click(E_ZOOM_SUB, "点击 [变倍缩小]"),
                 ]),
                ("017", "云台聚焦测试", "云台聚焦测试", 0,
                 "聚焦近焦/远焦可操作", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_FOCUS_LBL, "点击 [聚焦] 页签"),
                     _click(E_FOCUS_ADD, "点击 [近焦]"),
                     _click(E_FOCUS_SUB, "点击 [远焦]"),
                 ]),
                ("018", "云台光圈测试", "云台光圈测试", 0,
                 "光圈增大/减小可操作", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click_x(X_TAB_IRIS, "点击 [光圈] 页签"),
                     _click(E_IRIS_ADD, "点击 [光圈增大]"),
                     _click(E_IRIS_SUB, "点击 [光圈减小]"),
                 ]),
                ("019", "云台速度面板测试", "云台速度测试", 0,
                 "速度面板打开且速度值显示可见", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click(E_PTZ_SPEED, "点击 [速度] 打开速度面板"),
                     _assert(E_SLIDER_VAL, "断言云台速度值可见"),
                 ]),
                ("020", "扩展功能面板测试", "扩展功能测试", 0,
                 "扩展功能页签打开后 3D 定位图标可见", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click_x(X_TAB_EXTEND, "点击 [扩展功能] 页签"),
                     _assert(E_ICON_3D, "断言 3D 定位图标可见"),
                 ]),
                ("021", "预置位设置测试", "预置位测试", 0,
                 "预置位 1 可设置", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click_x(X_NAV_PREVIEW, '点击导航 [预览]'),
                     _click_x(X_LINK_PRESET, "点击 [预置位:] 链接"),
                     _fill(E_PREPOINT, "1", '输入预置位编号 "1"'),
                     _click_x(X_BTN_PRESET_SET, "点击 [设置预置点]"),
                 ]),
            ]),
        ],
    ),
    (
        "M04", "[模块四] 回放与系统设置", [
            ("主框架页", [
                ("022", "进入录像回放视图测试", "进入回放测试", 1,
                 "点击回放导航后进入回放视图（依赖登录态）", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click(E_PLAYBACK_NAV, "点击 [回放] 导航按钮"),
                 ]),
                ("023", "进入系统设置视图测试", "进入设置测试", 1,
                 "点击设置导航后进入设置视图（依赖登录态）", [
                     _goto(SITE_URL, "打开主框架"),
                     *_login_steps(),
                     _click(E_SETUP_NAV, "点击 [设置] 导航按钮"),
                 ]),
            ]),
        ],
    ),
]
