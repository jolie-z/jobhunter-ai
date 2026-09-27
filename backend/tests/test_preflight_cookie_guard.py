"""preflight 免登录平台 Cookie 文件守卫测试（2026-09-26 新机体验小批）。

背景：猎聘 requires_login=False 全豁免 vs 抓取引擎硬依赖 liepin_cookies.json
（缺文件直接 0 条收工）的设计断裂，导致新克隆机器整轮链路空转"快速结束"。
修复后：豁免分支对配置了 legacy_cookie_file 的平台做文件存在性检查，
缺失 → 进等待窗口（飞书通知指引扫码 + hot-polling 文件落盘即放行 + 超时跳过）。
"""
import asyncio
import os
import threading
import time

import pytest

from app.session import preflight
from app.session.models import PlatformConfig


def _make_config(tmp_path, cookie_exists: bool) -> PlatformConfig:
    cookie_file = os.path.join(str(tmp_path), "liepin_cookies.json")
    if cookie_exists:
        with open(cookie_file, "w", encoding="utf-8") as f:
            f.write("{}")
    return PlatformConfig(
        name="liepin",
        display_name="猎聘",
        port=9226,
        requires_login=False,
        legacy_cookie_file=cookie_file,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_emit_log(messages: list):
    async def emit(msg: str):
        messages.append(msg)
    return emit


def test_cookie_file_present_passes_through(tmp_path, monkeypatch):
    """文件存在（现行为回归）：豁免放行，不进等待窗口。"""
    config = _make_config(tmp_path, cookie_exists=True)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert any("豁免预检登录校验" in m for m in logs)


def test_cookie_file_missing_intercepts_with_guide(tmp_path, monkeypatch):
    """文件缺失：拦截进等待窗口，通知文案含扫码脚本指引。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)  # 窗口=0，直接走超时跳过分支
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)  # 实证也否，防真机端口探测

    notified: list[str] = []

    async def fake_notify(items, wait_s):
        for cfg, _status, kind in items:
            assert kind == preflight._PENDING_KIND_COOKIE_FILE
            notified.append(f"{cfg.display_name}:{kind}")

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}  # 超时跳过该平台
    assert notified == ["猎聘:cookie_file"]
    assert any("缺少 Cookie 文件" in m and "liepin_cookie_harvester" in m for m in logs)
    assert any("等待超时仍未生成 Cookie 文件" in m for m in logs)


def test_cookie_file_hot_poll_releases_when_created(tmp_path, monkeypatch):
    """hot-polling：等待窗口内文件被扫码脚本落盘的瞬间放行，不做 DOM 判定。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 8)
    monkeypatch.setattr(preflight, "_poll_seconds", lambda: 1)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)  # 实证恒否，专测文件路径

    def _touch_later():
        time.sleep(1.2)
        with open(config.legacy_cookie_file, "w", encoding="utf-8") as f:
            f.write("{}")

    threading.Thread(target=_touch_later, daemon=True).start()

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert any("登录已恢复" in m for m in logs)


def test_cookie_file_check_never_crashes_on_io_error(tmp_path, monkeypatch):
    """文件检查 IO 异常（权限等）按缺失处理，预检不 crash。"""
    config = _make_config(tmp_path, cookie_exists=True)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)  # 实证也否，防真机端口探测

    def _boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(preflight.os.path, "exists", _boom)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}  # 按缺失走等待窗口→超时跳过，而非异常冒泡


# ==========================================
# 双判据新增用例（2026-09-27：文件 OR Edge profile 登录实证）
# ==========================================

def test_cookie_file_missing_but_evidence_ok_passes(tmp_path, monkeypatch):
    """双判据：文件缺失但 Edge profile 登录实证有效 → 直接放行，不进等待窗口。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)

    evidence_calls = []

    def fake_evidence():
        evidence_calls.append(1)
        return True

    monkeypatch.setattr(preflight, "check_liepin_login_evidence", fake_evidence)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert len(evidence_calls) == 1  # 守卫期一次实证即放行，不进等待循环
    assert any("登录实证有效" in m for m in logs)


def test_cookie_file_missing_and_evidence_false_intercepts(tmp_path, monkeypatch):
    """双判据皆否：维持原拦截路径（等待窗口+飞书通知+超时跳过）。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)

    notified: list[int] = []

    async def fake_notify(items, wait_s):
        notified.append(len(items))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}
    assert notified == [1]
    # 文案双通道指引：会话条登录 与 harvester 脚本并列
    assert any("唤起浏览器" in m and "liepin_cookie_harvester" in m for m in logs)


def test_wait_window_recheck_releases_on_evidence(tmp_path, monkeypatch):
    """等待窗口复检双判据：文件始终缺失，实证中途转真 → 放行（会话条登录解锁路径）。"""
    config = _make_config(tmp_path, cookie_exists=False)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 8)
    monkeypatch.setattr(preflight, "_poll_seconds", lambda: 1)

    seq = [False, True]  # 守卫期实证否 → 窗口内复检实证转真（模拟用户完成登录）

    def fake_evidence():
        return seq.pop(0) if seq else True

    monkeypatch.setattr(preflight, "check_liepin_login_evidence", fake_evidence)

    notified: list[int] = []

    async def fake_notify(items, wait_s):
        notified.append(len(items))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": True}
    assert any("登录已恢复" in m for m in logs)
