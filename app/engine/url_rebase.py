# -*- coding: utf-8 -*-
"""运行期站点地址替换：把用例 goto 步骤的 origin 统一改为配置页填写的被测站点。

设备 IP 在种子数据里固化过（见 seed_data.SITE_URL），换设备时不必改库或改代码：
主窗口启动批次前调用 apply_site_url()，仅替换内存 DTO 中 goto 步骤的
scheme + host[:port]，路径/查询串保留，数据库资产保持不动。
"""
from urllib.parse import urlsplit, urlunsplit


def rebase_url(url: str, site_url: str) -> str:
    """把绝对 http(s) URL 的 origin 换成 site_url 的 origin（相对地址原样返回）。"""
    if not url.startswith(("http://", "https://")):
        return url
    base = urlsplit(site_url)
    if not base.scheme or not base.netloc:
        return url
    parts = urlsplit(url)
    return urlunsplit((base.scheme, base.netloc, parts.path, parts.query, parts.fragment))


def apply_site_url(pairs, site_url: str):
    """就地改写队列中所有 goto 步骤的地址，返回同一队列（便于链式调用）。"""
    if not site_url:
        return pairs
    for _, case in pairs:
        for step in case.steps:
            if step.action_type == "goto":
                step.selector = rebase_url(step.selector, site_url)
    return pairs
