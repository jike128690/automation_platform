# -*- coding: utf-8 -*-
r"""v004：为依赖登录态的用例补登录前置步骤（真机回归修复）。

设备 Web 端（192.168.3.102）的登录态只保存在页面 JS 内存中：重新 goto
即掉线，且默认配置每条用例前还会清理 Cookies。M02–M04 的 006–023 用例
都以 goto 开头并依赖登录态，因此在其 goto 之后补 3 步登录（账号/密码/
登录按钮），与 seed_data._login_steps() 保持一致。

仅处理内置用例且首个步骤为 https GOTO_URL 的用例；已存在密码输入步骤的
用例直接跳过（可重放安全）。新建库此时尚未 seed，脚本为空操作。
"""
import uuid

from app.db.base import now_iso

VERSION = 4

_LOGIN_CASE_CODES = tuple(f"{i:03d}" for i in range(6, 24))

_INSERT_SQL = (
    "INSERT INTO tb_test_step (step_id, case_id, step_order, command_type, "
    "element_id, target_override, param_value, is_secret, timeout_sec, remark, "
    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?)"
)


def _login_elements(conn) -> dict[str, str]:
    """登录三元素（用户名/密码/登录按钮）的 element_id 映射。"""
    rows = conn.execute(
        "SELECT element_name, element_id FROM tb_page_element "
        "WHERE element_name IN (?, ?, ?) AND is_deleted = 0",
        ("用户名输入框", "密码输入框", "登录按钮"),
    ).fetchall()
    return {name: element_id for name, element_id in rows}


def _new_steps(elements: dict[str, str]) -> tuple[tuple, ...]:
    """(step_order, command_type, element_id, param_value, is_secret, remark)。"""
    return (
        (2, "INPUT_TEXT", elements["用户名输入框"], "admin", 0, '输入账号 "admin"'),
        (3, "INPUT_TEXT", elements["密码输入框"], "admin", 1, '输入密码 "admin"'),
        (4, "CLICK_ELEMENT", elements["登录按钮"], None, 0, "点击 [登录] 按钮"),
    )


def upgrade(conn) -> None:
    """在给定 sqlite3 连接上补齐登录步骤（同一事务，失败整体回滚）。"""
    elements = _login_elements(conn)
    if len(elements) < 3:
        return  # 非种子库（登录元素缺失）：无可补

    placeholders = ",".join("?" for _ in _LOGIN_CASE_CODES)
    cases = conn.execute(
        f"SELECT case_id FROM tb_test_case "
        f"WHERE is_builtin = 1 AND is_deleted = 0 "
        f"AND case_code IN ({placeholders})",
        _LOGIN_CASE_CODES,
    ).fetchall()

    now = now_iso()
    password_eid = elements["密码输入框"]
    for (case_id,) in cases:
        steps = conn.execute(
            "SELECT command_type, target_override, element_id FROM tb_test_step "
            "WHERE case_id = ? ORDER BY step_order",
            (case_id,),
        ).fetchall()
        if not steps:
            continue
        command, target, _ = steps[0]
        if command != "GOTO_URL" or not (target or "").startswith("https://"):
            continue
        if any(s[0] == "INPUT_TEXT" and s[2] == password_eid for s in steps):
            continue  # 已补过登录步骤

        # 原步骤 2..n 后移 3 位：先 +100 再 -97，避开 (case_id, step_order) 唯一约束
        conn.execute(
            "UPDATE tb_test_step SET step_order = step_order + 100 "
            "WHERE case_id = ? AND step_order >= 2",
            (case_id,),
        )
        for order, cmd, element_id, value, secret, remark in _new_steps(elements):
            conn.execute(_INSERT_SQL, (
                str(uuid.uuid4()), case_id, order, cmd,
                element_id, value, secret, remark, now, now,
            ))
        conn.execute(
            "UPDATE tb_test_step SET step_order = step_order - 97 "
            "WHERE case_id = ? AND step_order > 100",
            (case_id,),
        )
