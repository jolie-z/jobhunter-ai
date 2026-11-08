"""冷启动登录误判根治回归（2026-11-03）。

事故：全链路启动拉起 4 个 Edge 后 0.5~7 秒即做 DOM 登录判定，Edge 配置文件会话
尚在恢复中，四平台全员被误判「登录态异常」并误发飞书告警（用户被迫手动刷新）。

锁定三层防线：
1. registry.auth_cookie_keys：四平台凭证键集合就位（CDP 实证的数据基础）；
2. 判定器：全键齐且未过期（session 键落账即有效）；
3. 预检主链路：冷启动平台凭证实证优先（零导航），实证窗口内通过即跳过 DOM。
"""
import time
from unittest.mock import patch

import pytest

import app.session.preflight as preflight_mod
from app.session.health_checker import (
    _judge_login_keys_for,
    check_platform_login_cookie_evidence,
)
from app.session.registry import PLATFORM_CONFIGS

# ───────────────────────── 1. registry 键集合 ─────────────────────────

def test_auth_cookie_keys_present_for_four_platforms():
    assert PLATFORM_CONFIGS["boss"].auth_cookie_keys == ("wt2", "zp_at")
    assert PLATFORM_CONFIGS["liepin"].auth_cookie_keys == ("lt_auth", "liepin_login_valid")
    assert PLATFORM_CONFIGS["zhilian"].auth_cookie_keys == ("at",)
    assert PLATFORM_CONFIGS["51job"].auth_cookie_keys == ("51job",)
    # 未摸底平台必须显式为空（回退 DOM 路径），不得编造键名
    assert PLATFORM_CONFIGS["xiaohongshu"].auth_cookie_keys == ()


# ───────────────────────── 2. 凭证判定器 ─────────────────────────

NOW = time.time()


def test_judge_all_keys_present_and_unexpired():
    assert _judge_login_keys_for({"wt2": NOW + 3600, "zp_at": NOW + 3600}, ("wt2", "zp_at")) is True


def test_judge_session_cookie_counts_as_valid():
    # expires<=0（session cookie）落账即有效：51job 的 "51job" 键是 session 键
    assert _judge_login_keys_for({"51job": 0.0}, ("51job",)) is True
    assert _judge_login_keys_for({"51job": -1.0}, ("51job",)) is True


def test_judge_expired_or_missing_key_fails():
    assert _judge_login_keys_for({"wt2": NOW - 1, "zp_at": NOW + 3600}, ("wt2", "zp_at")) is False
    assert _judge_login_keys_for({"wt2": NOW + 3600}, ("wt2", "zp_at")) is False
    assert _judge_login_keys_for({}, ("at",)) is False
    # 空键集合（未摸底平台）恒 False，绝不误放行
    assert _judge_login_keys_for({"anything": NOW + 3600}, ()) is False


def test_platform_evidence_fail_closed_for_unknown_or_keyless():
    # 未知平台 / 未摸底平台：fail-closed False，调用方回退 DOM 路径
    assert check_platform_login_cookie_evidence("nonexistent") is False
    assert check_platform_login_cookie_evidence("xiaohongshu") is False


# ───────────────────────── 3. 预检主链路：证据优先 ─────────────────────────

def _ready_ok(_config, _emit_log=None, out_reason=None):
    if out_reason is not None:
        out_reason.clear()
        out_reason["reason"] = "launched"
    return True


@pytest.mark.asyncio
async def test_fresh_launch_with_valid_evidence_skips_dom():
    """冷启动 + 凭证实证通过 → 直接放行，不做任何 DOM 导航。"""
    dom_calls = []

    def _fake_dom(_config):
        dom_calls.append(_config.name)
        raise AssertionError("凭证实证通过时不得走 DOM 判定")

    with patch.object(preflight_mod, "_ensure_browser_ready", side_effect=_ready_ok), \
         patch.object(preflight_mod, "_wait_login_cookie_evidence", return_value=True), \
         patch.object(preflight_mod, "check_login_with_fallback", side_effect=_fake_dom):
        results = await preflight_mod.ensure_platforms_ready(["boss"], emit_log=None)
    assert results["boss"] is True
    assert dom_calls == []


@pytest.mark.asyncio
async def test_fresh_launch_platform_without_keys_goes_dom():
    """未摸底平台（无 auth_cookie_keys）：不走实证路径，直接 DOM 判定。"""
    evidence_calls = []

    async def _fake_wait(_config, **_kwargs):
        evidence_calls.append(_config.name)
        return True

    with patch.object(preflight_mod, "_ensure_browser_ready", side_effect=_ready_ok), \
         patch.object(preflight_mod, "_wait_login_cookie_evidence", side_effect=_fake_wait), \
         patch.object(preflight_mod, "check_login_with_fallback",
                      return_value=preflight_mod.SessionStatus(
                          platform="xiaohongshu", state=preflight_mod.SessionState.HEALTHY)):
        results = await preflight_mod.ensure_platforms_ready(["xiaohongshu"], emit_log=None)
    assert results["xiaohongshu"] is True
    assert evidence_calls == []  # 空键集合 → 实证路径整体跳过


@pytest.mark.asyncio
async def test_dom_expired_but_recheck_evidence_valid_upgrades_to_ok():
    """双重判定：冷启动平台 DOM 判死 → 8s 后凭证实证翻案 → 改判放行，不进挂起告警。"""
    sleeps = []

    async def _fast_sleep(_s):
        sleeps.append(_s)

    expired = preflight_mod.SessionStatus(
        platform="boss", state=preflight_mod.SessionState.EXPIRED, message="DOM 判定未命中登录标识")

    with patch.object(preflight_mod, "_ensure_browser_ready", side_effect=_ready_ok), \
         patch.object(preflight_mod, "_wait_login_cookie_evidence", return_value=False), \
         patch.object(preflight_mod, "check_login_with_fallback", return_value=expired), \
         patch.object(preflight_mod, "check_platform_login_cookie_evidence", return_value=True), \
         patch.object(preflight_mod.asyncio, "sleep", side_effect=_fast_sleep):
        results = await preflight_mod.ensure_platforms_ready(["boss"], emit_log=None)
    assert results["boss"] is True
    assert sleeps == [8]  # 走了 8s 复核等待


@pytest.mark.asyncio
async def test_warm_browser_skips_settle_window():
    """浏览器本来就在跑（非冷启动）：不进稳定期，直接 DOM 判定，零额外等待。"""
    waits = []

    def _ready_warm(_config, _emit_log=None, out_reason=None):
        if out_reason is not None:
            out_reason.clear()
            out_reason["reason"] = "alive"
        return True

    async def _fake_wait(_config, **_kwargs):
        waits.append(_config.name)
        return True

    with patch.object(preflight_mod, "_ensure_browser_ready", side_effect=_ready_warm), \
         patch.object(preflight_mod, "_wait_login_cookie_evidence", side_effect=_fake_wait), \
         patch.object(preflight_mod, "check_login_with_fallback",
                      return_value=preflight_mod.SessionStatus(
                          platform="boss", state=preflight_mod.SessionState.HEALTHY)):
        results = await preflight_mod.ensure_platforms_ready(["boss"], emit_log=None)
    assert results["boss"] is True
    assert waits == []
