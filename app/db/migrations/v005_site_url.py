# -*- coding: utf-8 -*-
r"""v005：tb_system_config 增加被测站点地址（site_url）。

背景：设备 IP 原先固化在种子用例的 GOTO_URL（tb_page.page_url /
tb_step.target_override）中，换设备只能改代码或手工改库。新增配置字段后，
批量配置页可直接修改，运行期由 url_rebase 统一替换 goto 的 origin。

新建库由 v003 按当前 ORM 建表（已含本列，PRAGMA 检测后跳过）；
存量库走 ALTER TABLE 补列，默认值与 app.config.DEFAULT_SITE_URL 一致。
SQLite 的 ALTER TABLE 无法补 CHECK 约束，格式校验由配置页完成。
"""
from app.config import DEFAULT_SITE_URL

VERSION = 5


def upgrade(conn) -> None:
    """幂等补列：已存在 site_url 时直接返回。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tb_system_config)")}
    if "site_url" in columns:
        return
    conn.execute(
        "ALTER TABLE tb_system_config ADD COLUMN site_url TEXT(255) "
        "NOT NULL DEFAULT '%s'" % DEFAULT_SITE_URL.replace("'", "''")
    )
