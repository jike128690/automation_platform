# -*- coding: utf-8 -*-
"""运行期站点地址替换单测（批量配置页 site_url → goto origin）。"""
from app.data.models import TestCase, TestModule, TestStep
from app.engine.url_rebase import apply_site_url, rebase_url


def test_rebase_url_keeps_path_and_query():
    assert rebase_url(
        "https://192.168.3.102/playback?ch=1#top", "http://10.0.0.9:8080/"
    ) == "http://10.0.0.9:8080/playback?ch=1#top"


def test_rebase_url_leaves_relative_and_invalid_base():
    assert rebase_url("/api/login", "https://10.0.0.9/") == "/api/login"
    assert rebase_url("https://192.168.3.102/", "192.168.3.150") == \
        "https://192.168.3.102/"


def test_apply_site_url_only_rewrites_goto_steps():
    steps = [
        TestStep(1, "goto", "https://192.168.3.102/", "", "打开主框架"),
        TestStep(2, "fill", "#userName", "admin", "输入账号"),
        TestStep(3, "assert_visible", "#preview", "", "断言预览可见"),
    ]
    case = TestCase("001", "[001] 用例", "用例", True, steps)
    pair = (TestModule("M01", "模块", [case]), case)

    apply_site_url([pair], "https://10.0.0.9/")

    assert steps[0].selector == "https://10.0.0.9/"
    assert steps[1].selector == "#userName"      # 选择器不受影响
    assert steps[2].selector == "#preview"


def test_apply_site_url_empty_value_noop():
    steps = [TestStep(1, "goto", "https://192.168.3.102/", "", "打开")]
    case = TestCase("001", "[001] 用例", "用例", True, steps)
    apply_site_url([(TestModule("M01", "模块", [case]), case)], "")
    assert steps[0].selector == "https://192.168.3.102/"
