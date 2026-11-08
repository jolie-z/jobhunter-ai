"""2026-11-05 僵尸链路/重连风暴事故修复回归。

覆盖：
1. abort 模块 aborted_at() 时间戳契约：未终止=0.0；置位后单调；end_pipeline 清零。
2. preflight PipelineAbortedError 检查点：终止置位后 ensure_platforms_ready
   在平台循环边界快速失败，不拉浏览器不做登录判定。
3. preflight 同步段看门狗：挂死的 to_thread 段在超时后返回「浏览器不可用」
   而非永久阻塞（用 monkeypatch 慢函数模拟 CDP 挂死）。
4. tasks/router expired_stream：task_expired end 帧后连接保持（哑流），不产生
   第二帧——防浏览器 EventSource 自动重连风暴。
5. control_router /trigger 审计：confirm=false 仍 400；confirm=true 记 WARNING
   审计行（caplog 断言）。
"""
import asyncio
import json
import time

import pytest

from app.automation import abort as abort_mod
from app.session.preflight import (
    PipelineAbortedError,
    _raise_if_aborted,
    _SYNC_SEGMENT_TIMEOUT_S,
    ensure_platforms_ready,
)


# ---------- 1. abort.aborted_at 契约 ----------

def test_aborted_at_contract(monkeypatch):
    abort_mod.begin_pipeline("pipeline_wd")
    assert abort_mod.aborted_at() == 0.0
    assert abort_mod.request_abort("pipeline_wd") is True
    ts = abort_mod.aborted_at()
    assert ts > 0
    # 重复 request 不覆盖时刻（首置位语义）
    abort_mod.request_abort("pipeline_wd")
    assert abort_mod.aborted_at() == ts
    abort_mod.end_pipeline()
    assert abort_mod.aborted_at() == 0.0
    assert not abort_mod.is_aborted()


# ---------- 2. preflight 终止检查点 ----------

@pytest.mark.asyncio
async def test_preflight_aborts_fast_when_flag_set(monkeypatch):
    """终止旗子置位后，预检应在平台循环边界抛 PipelineAbortedError，
    绝不触达浏览器探活/拉起（_ensure_browser_ready 被 mock 计数即证）。"""
    abort_mod.begin_pipeline("pipeline_chk")
    abort_mod.request_abort("pipeline_chk")

    calls = {"browser": 0}

    async def _fake_browser_ready(config, emit_log=None, out_reason=None):
        calls["browser"] += 1
        if out_reason is not None:
            out_reason["reason"] = "launched"
        return True

    import app.session.preflight as pf
    monkeypatch.setattr(pf, "_ensure_browser_ready", _fake_browser_ready)

    with pytest.raises(PipelineAbortedError):
        await ensure_platforms_ready(["boss", "zhilian"])
    assert calls["browser"] == 0  # 边界检查在浏览器探活之前
    abort_mod.end_pipeline()


@pytest.mark.asyncio
async def test_preflight_runs_when_not_aborted(monkeypatch):
    """未终止时检查点为空操作：第一平台正常走完探活判定（mock 健康放行）。"""
    abort_mod.begin_pipeline("pipeline_ok")

    async def _fake_browser_ready(config, emit_log=None, out_reason=None):
        if out_reason is not None:
            out_reason["reason"] = "alive"
        return True

    import app.session.preflight as pf
    monkeypatch.setattr(pf, "_ensure_browser_ready", _fake_browser_ready)
    # 在飞守卫直接放行（跳过 DOM 判定与租约）
    from app.automation import platform_mutex
    monkeypatch.setattr(platform_mutex, "is_delivery_busy", lambda p: True)
    monkeypatch.setattr(platform_mutex, "is_scrape_busy", lambda p: False)

    results = await ensure_platforms_ready(["boss"])
    assert results == {"boss": True}
    abort_mod.end_pipeline()


def test_raise_if_aborted_stages():
    _raise_if_aborted("stage_x")  # 未终止：空操作
    abort_mod.begin_pipeline("pipeline_stage")
    abort_mod.request_abort("pipeline_stage")
    with pytest.raises(PipelineAbortedError, match="stage_x"):
        _raise_if_aborted("stage_x")
    abort_mod.end_pipeline()


# ---------- 3. 同步段看门狗 ----------

@pytest.mark.asyncio
async def test_sync_segment_watchdog(monkeypatch):
    """挂死的 to_thread 段（模拟 CDP 无超时读）在 _SYNC_SEGMENT_TIMEOUT_S 后
    被放弃：_ensure_browser_ready 返回 False + reason=probe_timeout，
    而不是永久阻塞主链。

    R1-P2 采纳：不再整体替换 _to_thread_guarded（那会绕过被测本体），
    改为把 _SYNC_SEGMENT_TIMEOUT_S 缩到 0.05s，让真实看门狗去掐断慢函数。"""
    import app.session.preflight as pf

    def _hang_forever_sync(*a, **k):
        time.sleep(3600)

    monkeypatch.setattr(pf, "_SYNC_SEGMENT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(pf, "ensure_browser_ready_sync", _hang_forever_sync)
    from app.automation import platform_mutex
    monkeypatch.setattr(platform_mutex, "is_scrape_busy", lambda p: False)
    monkeypatch.setattr(platform_mutex, "is_delivery_busy", lambda p: False)

    out: dict = {}
    from app.session.registry import resolve_platform
    boss_cfg = resolve_platform("boss")
    assert boss_cfg is not None
    ok = await pf._ensure_browser_ready(boss_cfg, None, out_reason=out)
    assert ok is False
    assert out["reason"] == "probe_timeout"


@pytest.mark.asyncio
async def test_to_thread_degradable_falls_back_on_timeout(monkeypatch):
    """R1-P1-2 降级契约：看门狗超时返回 fallback 值而非击穿异常。"""
    import app.session.preflight as pf

    def _hang_sync(*a, **k):
        time.sleep(30)

    monkeypatch.setattr(pf, "_SYNC_SEGMENT_TIMEOUT_S", 0.05)
    got = await pf._to_thread_degradable(_hang_sync, "arg1", fallback="FALLBACK")
    assert got == "FALLBACK"


@pytest.mark.asyncio
async def test_degradable_normal_path_passes_config_through(monkeypatch):
    """R2-P0 回归：未超时正常路径必须把 config 正确透传给判定函数（此前
    fallback 位置传参曾把 SessionStatus 当 config 传入）。"""
    import app.session.preflight as pf
    from app.session.models import SessionStatus, SessionState

    received: dict = {}

    def _fake_judge(config):
        received["config"] = config
        return SessionStatus(platform=getattr(config, "name", "?"),
                             state=SessionState.HEALTHY, message="ok")

    # 走真实 registry 的 PlatformConfig("boss")：判定链路原样，替换判定函数本身
    from app.automation import platform_mutex
    monkeypatch.setattr(platform_mutex, "is_scrape_busy", lambda p: False)
    monkeypatch.setattr(pf, "check_login_with_fallback", _fake_judge)

    # 非在飞 + 租约恒获锁 → 必走 DOM 判定路径（R2-P0 曾在此处误传 SessionStatus）
    class _Lease:
        async def __aenter__(self):
            return True

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(platform_mutex, "preflight_lease",
                        lambda name, owner=None: _Lease())
    monkeypatch.setattr(platform_mutex, "is_delivery_busy", lambda p: False)

    async def _browser_ok(config, emit_log=None, out_reason=None):
        if out_reason is not None:
            out_reason["reason"] = "alive"
        return True

    monkeypatch.setattr(pf, "_ensure_browser_ready", _browser_ok)

    results = await ensure_platforms_ready(["boss"])
    assert results == {"boss": True}
    # config 透传正确性（R2-P0 核心）：判定函数收到的是 config 对象，
    # 而非曾被误传的 SessionStatus（无 name 属性即 SessionStatus 误传的特征）
    cfg = received.get("config")
    assert cfg is not None and hasattr(cfg, "profile_dir"), \
        f"config 未被正确透传（收到 SessionStatus 或 None）: {cfg!r}"


@pytest.mark.asyncio
async def test_degradable_timeout_yields_unknown_status(monkeypatch):
    """R2-P0 回归：判定函数挂死超时 → 返回 UNKNOWN SessionStatus（非 OK 态）
    进 pending 等待窗，绝不抛 AttributeError/击穿整轮预检。"""
    import app.session.preflight as pf

    def _hang_judge(config):
        time.sleep(30)

    from app.automation import platform_mutex
    monkeypatch.setattr(pf, "_SYNC_SEGMENT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(platform_mutex, "is_scrape_busy", lambda p: False)
    monkeypatch.setattr(platform_mutex, "is_delivery_busy", lambda p: False)

    class _Lease:
        async def __aenter__(self):
            return True

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(platform_mutex, "preflight_lease",
                        lambda name, owner=None: _Lease())
    monkeypatch.setattr(pf, "check_login_with_fallback", _hang_judge)

    async def _browser_ok(config, emit_log=None, out_reason=None):
        if out_reason is not None:
            out_reason["reason"] = "alive"
        return True

    monkeypatch.setattr(pf, "_ensure_browser_ready", _browser_ok)
    # pending 等待窗压缩到 1s（默认 300s 是真实窗口，测试不等满窗）+ 通知 mock 掉
    monkeypatch.setenv("PIPELINE_LOGIN_WAIT_S", "1")
    async def _noop_notify(*a, **k):
        return None

    monkeypatch.setattr(pf, "_notify_login_needed", _noop_notify)

    results = await ensure_platforms_ready(["boss"])
    # UNKNOWN 非 OK 态 → 挂起进等待窗，等待窗内无恢复 → 平台按跳过处理（False）
    assert results == {"boss": False}


@pytest.mark.asyncio
async def test_watchdog_force_finalize_closes_ledger_and_sse(monkeypatch):
    """R1-P1-1 看门狗强收路径闭环：宿主挂死被 cancel 后，
    automation_logs 补写 failed 终态、SSE 队列补发 end 帧、占坑释放、
    CancelledError 向上传播（不吞取消）。"""
    from app.automation import pipeline_orchestrator as orch
    from app.automation import pipeline_broadcast as pb
    from app.automation.db import get_recent_autopilot_logs

    orch.PIPELINE_ABORT_GRACE_SECONDS = 0.2  # 测试宽限 200ms
    try:
        task_id = "pipeline_wdtest"
        pb.create_pipeline_queue(task_id)
        pb.set_current_pipeline(task_id, True)
        abort_mod.begin_pipeline(task_id)
        abort_mod.request_abort(task_id)  # 先置终止：看门狗计时开始，body 感知后挂死

        seen = {"end": None, "log_id": None}

        async def _fake_execute(pipeline_task_id, config, search, stop_at_review=False,
                                trigger_source="scheduled", log_task_id=None):
            # 模拟生产行为：链路启动即写台账 running 行（_execute_pipeline 首行）
            from app.automation.db import append_autopilot_log as _append
            seen["log_id"] = log_task_id
            _append(log_task_id, "running", 0, "看门狗测试轮")
            # 等终止旗子置位后继续挂死（模拟不检查旗子的深调用）
            while not abort_mod.is_aborted():
                await asyncio.sleep(0.05)
            await asyncio.sleep(3600)

        async def _fake_emit_end(tid, summary):
            seen["end"] = (tid, summary)

        async def _fake_reap(*a, **k):
            return None

        monkeypatch.setattr(orch, "_execute_pipeline", _fake_execute)
        monkeypatch.setattr(orch.pb, "emit_end", _fake_emit_end)
        monkeypatch.setattr(orch, "_reap_orphan_scrapers", _fake_reap)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(
                orch._run_pipeline_with_watchdog(
                    task_id, {}, {"keyword": "k", "city": "c"},
                    stop_at_review=False, trigger_source="manual"),
                timeout=15,
            )
        # assert 强收补了 end 帧与台账终态（用 body 实际登记的 log id 查）
        assert seen["end"] is not None and seen["end"][0] == task_id
        assert seen["end"][1].get("reason") == "aborted"
        assert seen["log_id"], "log_task_id 未下传到 body"
        rows = [r for r in get_recent_autopilot_logs(limit=10) if r.get("task_id") == seen["log_id"]]
        assert rows and rows[0]["status"] == "failed", f"台账未收口: {rows}"
        assert "看门狗" in (rows[0].get("details") or "")
        # 占坑已释放
        assert not pb.get_current_pipeline().get("running")
    finally:
        orch.PIPELINE_ABORT_GRACE_SECONDS = 600.0
        abort_mod.end_pipeline()


def test_sync_timeout_bound():
    # 看门狗上限必须显著小于终止宽限（600s），保证检查点+看门狗先行收口
    from app.automation.pipeline_orchestrator import PIPELINE_ABORT_GRACE_SECONDS
    assert _SYNC_SEGMENT_TIMEOUT_S * 2 < PIPELINE_ABORT_GRACE_SECONDS


# ---------- 4. expired_stream 哑流（防 EventSource 自动重连风暴） ----------
@pytest.mark.asyncio
async def test_expired_stream_single_end_then_silent():
    """expired 流在 end 帧后保持连接（哑流）：直接驱动生成器验证。

    不走 TestClient——app.main 全量导入在沙箱会拉起真实子系统（Playwright/
    飞书 WS）导致测试挂死。生成器是纯 asyncio，足够验证行为契约：
    帧序列 = 1 条 task_expired end 帧 + 无限心跳注释（绝不 return 关流）。"""
    import app.tasks.router as tr

    async def _consume():
        agen = tr._make_expired_stream("pipeline_neverexisted")
        chunks = []
        try:
            # 第一块必须是 end 帧
            chunks.append(await agen.__anext__())
            # 第二块必须是心跳注释（若生成器 return，__anext__ 抛 StopAsyncIteration；
            # 心跳立即发一拍，无需等待）
            chunks.append(await agen.__anext__())
        finally:
            await agen.aclose()
        return chunks

    chunks = await asyncio.wait_for(_consume(), timeout=10)
    assert '"task_expired"' in chunks[0], f"第一帧不是 task_expired end: {chunks[0]}"
    assert chunks[0].strip().startswith("data:"), "end 帧必须是 SSE data 帧"
    assert chunks[1].startswith(": heartbeat"), \
        f"end 帧后必须是常驻心跳（流被关闭则 EventSource 将自动重连成风暴）: {chunks[1]!r}"


# ---------- 5. /trigger 审计 ----------

@pytest.mark.asyncio
async def test_trigger_requires_confirm():
    """confirm=false 必须 400（Q17 守卫仍在）。直接调端点函数，不经 app.main。"""
    import app.automation.routes.control_router as cr

    class _Req:
        confirm = False

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await cr.trigger_autopilot_manual(_Req(), request=_fake_request())
    assert ei.value.status_code == 400


class _FakeRequest:
    """最小 Request stub：trigger 审计只读 client/headers。"""
    class _C:
        host = "127.0.0.1"
        port = 52149
    client = _C()
    headers = {"user-agent": "audit-test-agent", "referer": "http://localhost/test"}


def _fake_request() -> _FakeRequest:
    return _FakeRequest()


@pytest.mark.asyncio
async def test_trigger_audit_logged(caplog):
    """confirm=true 触发必须留 WARNING 审计行（含 client 端口与 UA），取证需求。
    直接调端点函数 + monkeypatch 编排器，绕开 app.main 全量导入。"""
    import app.automation.routes.control_router as cr

    async def _fake_run(**kwargs):
        return "pipeline_auditfake"

    import pytest as _pytest
    from app.automation import full_auto
    mp = _pytest.MonkeyPatch()
    # 端点函数体内 from app.automation.full_auto import run_full_auto_pipeline 是
    # 运行时查找，patch 源模块属性即可被取到
    mp.setattr(full_auto, "run_full_auto_pipeline", _fake_run)
    try:
        import logging
        with caplog.at_level(logging.WARNING, logger="app.automation.routes.control_router"):
            class _Req:
                confirm = True
            resp = await cr.trigger_autopilot_manual(_Req(), request=_fake_request())
        assert resp["status"] == "success"
        assert any(
            "trigger-audit" in r.message and "audit-test-agent" in r.message
            for r in caplog.records
        ), f"未找到审计行: {[r.message for r in caplog.records]}"
    finally:
        mp.undo()
