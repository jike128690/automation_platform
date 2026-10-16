"""内置 Mock 站点单元测试（T7.1）。"""
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

import pytest

from app.config import MOCK_SITE_URL
from app.data.demo_cases import DEMO_MODULES
from app.utils.mock_site import MockSite, PAGES


@pytest.fixture(scope="module")
def site():
    mock = MockSite()
    mock.start()
    yield mock
    mock.stop()


def _get(path):
    with urllib.request.urlopen(f"{MOCK_SITE_URL}{path}", timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_login_page_available(site):
    status, html = _get("/login")
    assert status == 200
    assert 'id="username"' in html
    assert 'id="password"' in html
    assert 'id="login-btn"' in html


def test_all_pages_available(site):
    for path in PAGES:
        status, html = _get(path)
        assert status == 200
        assert html.startswith("<!doctype html>")


def test_unknown_page_404(site):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get("/no-such-page")
    assert exc.value.code == 404


def test_demo_data_selectors_all_covered_by_site(site):
    """demo 24 用例引用的全部选择器都必须被站点页面覆盖（任一页面存在即可）。
    跨页面跳转的导航时序（click 链接→新页）由 M8 真机联调验证，单元层只保证无缺失选择器。
    """
    all_html = "".join(_get(path)[1] for path in PAGES)
    missing = []
    for module in DEMO_MODULES:
        for case in module.cases:
            for step in case.steps:
                if step.action_type == "goto":
                    continue
                if f'id="{step.selector.lstrip("#")}"' not in all_html:
                    missing.append((case.case_id, step.selector))
    assert not missing, f"站点缺失选择器: {missing}"


def test_stop_releases_port():
    port = _free_port()
    mock = MockSite(url=f"http://127.0.0.1:{port}")
    mock.start()
    mock.stop()
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/login", timeout=2)