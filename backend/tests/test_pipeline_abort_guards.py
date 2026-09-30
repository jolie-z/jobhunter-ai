"""0928 事故修复批测试：预检接终止信号 / 幽灵 running 对账 / 引擎崩溃快停。

事故链：Edge 拉起失败（dyld SIGABRT）→ run_task 对退出码 1 无分支 → 崩溃-休眠
死循环（288s/页无上限）→ 用户点终止被无视（preflight 等待循环不查 is_aborted）
→ 后端重启 → DB 幽灵 running=1 → 前端永久卡 running。本文件锁定三个修复点。
"""
import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
LIEPIN_DIR = BACKEND_DIR / "liepin_scraper"
if str(LIEPIN_DIR) not in sys.path:
    sys.path.insert(0, str(LIEPIN_DIR))

from app.session import preflight  # noqa: E402
from app.session.models import PlatformConfig  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_emit_log(messages: list):
    async def emit(msg: str):
        messages.append(msg)
    return emit


# ==========================================
# ④ preflight 等待循环接入 is_aborted
# ==========================================

def _liepin_config_without_cookie(tmp_path) -> PlatformConfig:
    return PlatformConfig(
        name="liepin",
        display_name="猎聘",
        port=9226,
        requires_login=False,
        legacy_cookie_file=str(tmp_path / "missing.json"),
    )


def test_preflight_wait_breaks_on_abort_signal(tmp_path, monkeypatch):
    """等待窗口内检测到终止信号：立即跳出（不干等满 300s），平台按终止跳过。"""
    config = _liepin_config_without_cookie(tmp_path)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 60)  # 故意给长窗口
    monkeypatch.setattr(preflight, "_poll_seconds", lambda: 1)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)

    import app.automation.abort as abort_mod
    monkeypatch.setattr(abort_mod, "is_aborted", lambda: True)  # 终止信号已在高位

    notified: list[int] = []

    async def fake_notify(items, wait_s):
        notified.append(len(items))

    monkeypatch.setattr(preflight, "_notify_login_needed", fake_notify)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}
    assert notified == [1]  # 只通知一次，未进入长轮询
    assert any("终止信号" in m for m in logs)
    assert any("因任务终止被跳过" in m for m in logs)
    assert not any("等待超时" in m for m in logs)  # 终止路径与超时路径文案分开


def test_preflight_no_abort_keeps_timeout_semantics(tmp_path, monkeypatch):
    """无终止信号：维持原超时语义（回归确认，终止分支不干扰既有路径）。"""
    config = _liepin_config_without_cookie(tmp_path)
    monkeypatch.setattr(preflight, "resolve_platform", lambda key: config)
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 0)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)

    import app.automation.abort as abort_mod
    monkeypatch.setattr(abort_mod, "is_aborted", lambda: False)

    logs: list[str] = []
    result = _run(preflight.ensure_platforms_ready(["liepin"], emit_log=_fake_emit_log(logs)))

    assert result == {"liepin": False}
    assert any("等待超时" in m for m in logs)


# ==========================================
# ⑥ run_snapshot 启动幽灵 running 对账
# ==========================================

def test_reconcile_clears_ghost_running():
    from app.automation import run_snapshot as rs

    with rs._lock:
        rs._runtime["running"] = True
        rs._runtime["task_id"] = "pipeline_ghost_test"
    try:
        assert rs.reconcile_startup_ghost() is True
        assert rs._runtime["running"] is False
        # 二次对账：无残留返回 False，幂等
        assert rs.reconcile_startup_ghost() is False
    finally:
        with rs._lock:
            rs._runtime["running"] = False


def test_reconcile_noop_when_clean():
    from app.automation import run_snapshot as rs

    with rs._lock:
        rs._runtime["running"] = False
    assert rs.reconcile_startup_ghost() is False


# ==========================================
# ③ run_task 引擎崩溃快停
# ==========================================

def test_run_task_fast_stops_on_engine_crash(monkeypatch):
    """子进程非 0/99 退出（如浏览器拉起失败）：立即中止翻页循环，不再睡 288s 翻下页。"""
    import liepin_nl_controller as nlc

    popen_calls: list = []

    class _FakeProc:
        returncode = 1  # 崩溃退出码（0928 事故真实场景）

        def __init__(self):
            self.stdout = iter([])

        def wait(self):
            return 1

    def fake_popen(*args, **kwargs):
        popen_calls.append(args)
        return _FakeProc()

    monkeypatch.setattr(nlc.subprocess, "Popen", fake_popen)

    total = nlc.run_task("生物信息", "上海", 1, 5, "20-30K")

    assert total == 0
    assert len(popen_calls) == 1  # 快停：绝不发起第二次翻页
    assert nlc.LAST_ENGINE_CRASH is not None
    assert "异常退出" in nlc.LAST_ENGINE_CRASH
    assert "code=1" in nlc.LAST_ENGINE_CRASH


def test_run_task_does_not_flag_normal_exit(monkeypatch):
    """子进程正常退出（0）：不置崩溃标记（回归确认）。

    零入库+正常退出会进入翻页休眠循环（生产行为，由终止指令打断）——
    测试里用休眠中拉高终止旗标模拟用户打断，避免真睡 288s。
    """
    import liepin_nl_controller as nlc

    class _FakeProc:
        returncode = 0

        def __init__(self):
            self.stdout = iter([])

        def wait(self):
            return 0

    monkeypatch.setattr(nlc.subprocess, "Popen", lambda *a, **k: _FakeProc())

    def fake_sleep(seconds):
        nlc.GLOBAL_STOP_FLAG = True  # 模拟用户在翻页休眠中点终止

    monkeypatch.setattr(nlc, "countdown_sleep", fake_sleep)
    nlc.GLOBAL_STOP_FLAG = False

    nlc.run_task("生物信息", "上海", 1, 5, "20-30K")

    assert nlc.LAST_ENGINE_CRASH is None
