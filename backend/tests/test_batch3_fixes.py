"""第三批加固（2026-11-02 审计 P2-13~25）后端单测：SSE 生命周期/批量停止/console-stream。"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.automation import console_stream as cs
from app.tasks import state as tstate


# ---------- 修 14：console-stream seq 去重与订阅 ----------

def test_console_stream_seq_dedup_and_snapshot():
    """快照与订阅重叠行以 seq 精确跳过；文本相同的合法行不被误吞"""
    cs._buffer.clear()
    cs._seq_counter = 0
    cs._fanout("第一行")
    cs._fanout("分隔线")
    cs._fanout("分隔线")  # 文本相同、seq 不同——都应保留
    snap = cs.snapshot()
    assert [line for _, line in snap] == ["第一行", "分隔线", "分隔线"]
    seqs = [s for s, _ in snap]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3


@pytest.mark.asyncio
async def test_console_stream_subscribe_unsubscribe_no_leak():
    q = cs.subscribe()
    assert q in cs._subscribers
    cs.unsubscribe(q)
    assert q not in cs._subscribers


# ---------- 修 15：批量任务停止 ----------

def test_request_batch_stop_current_task_accepted():
    tstate.GLOBAL_TASK_STATE["current_task_id"] = "t1"
    tstate.task_status["t1"] = {"status": "running"}
    try:
        assert tstate.request_batch_stop("t1") is True
        assert tstate.is_batch_stop_requested("t1") is True
        assert tstate.is_batch_stop_requested("t2") is False
    finally:
        tstate.clear_batch_stop()
        tstate.GLOBAL_TASK_STATE["current_task_id"] = None


def test_request_batch_stop_pending_task_accepted():
    """pending 窗口（未持锁、current_task_id 未写）也可停止（CR-B3-R1 修正）"""
    tstate.GLOBAL_TASK_STATE["current_task_id"] = None
    tstate.task_status["t-pending"] = {"status": "pending"}
    try:
        assert tstate.request_batch_stop("t-pending") is True
        assert tstate.is_batch_stop_requested("t-pending") is True
    finally:
        tstate.clear_batch_stop()
        tstate.task_status.pop("t-pending", None)


def test_request_batch_stop_unknown_rejected():
    tstate.GLOBAL_TASK_STATE["current_task_id"] = None
    assert tstate.request_batch_stop("t-ghost") is False


@pytest.mark.asyncio
async def test_stop_endpoint_404_for_finished_task():
    from app.tasks.router import stop_batch_task
    tstate.task_status["t-done"] = {"status": "success"}
    try:
        with pytest.raises(Exception) as exc:
            await stop_batch_task("t-done")
        assert "404" in str(getattr(exc.value, "status_code", "")) or getattr(exc.value, "status_code", None) == 404
    finally:
        tstate.task_status.pop("t-done", None)


# ---------- 修 20：dashboard-sync 子源降级（调用生产 _sync_source_ok，非手抄） ----------

def test_dashboard_sync_downgrade_ignores_exception_but_reraises_base():
    """Exception 降级；CancelledError 等 BaseException 重抛（CR-B3-R1-P2；R2-P2 改调生产函数）"""
    from app.automation.routes.control_router import _sync_source_ok as _ok
    assert _ok(ValueError("x"), None) is None
    assert _ok("data", None) == "data"
    with pytest.raises(asyncio.CancelledError):
        _ok(asyncio.CancelledError(), None)


# ---------- CR-B3-R2-P0-1 回归护栏：_fanout 入队 (seq, line) 二元组，消费端可解包 ----------

@pytest.mark.asyncio
async def test_fanout_enqueues_seq_line_tuples():
    """订阅→fanout→从队列消费：元素必须是 (seq, line) 二元组且 seq 递增（R2-P0-1 护栏）"""
    cs._buffer.clear()
    cs._seq_counter = 0
    # 测试进程无 FastAPI startup（install 未跑，_loop=None 时不投递）——保存原值并
    # 捕获当前 loop（CR-B3-R3-P2：原版 finally 硬置 None 会清掉其他用例经 install
    # 初始化的 loop）
    prev_loop = cs._loop
    cs._loop = asyncio.get_running_loop()
    q = cs.subscribe()
    try:
        cs._fanout("实时日志 A")
        item = await asyncio.wait_for(q.get(), timeout=2)
        assert isinstance(item, tuple) and len(item) == 2
        seq1, line1 = item
        assert line1 == "实时日志 A"
        cs._fanout("实时日志 B")
        seq2, line2 = await asyncio.wait_for(q.get(), timeout=2)
        assert seq2 > seq1 and line2 == "实时日志 B"
    finally:
        cs.unsubscribe(q)
        cs._loop = prev_loop  # 还原保存的原值
        cs._buffer.clear()


# ---------- CR-B3-R2-P0-2 回归护栏：pending 停止早退不复位污染全局 ----------

@pytest.mark.asyncio
async def test_pending_stop_requested_skips_processing_without_state_pollution():
    """pending 期停止：body 持锁后早退，is_processing 不被置 True（全局无污染，P0-2 修复点）"""
    tstate.GLOBAL_TASK_STATE["is_processing"] = False
    tstate.GLOBAL_TASK_STATE["current_task_id"] = None
    tstate.task_status["t-pstop"] = {"status": "pending"}
    assert tstate.request_batch_stop("t-pstop") is True
    sent: list[str] = []

    async def fake_put(msg):
        sent.append(msg)

    fake_queue = MagicMock()
    fake_queue.put = fake_put
    try:
        from app.tasks.executor import _run_batch_ai_task_body
        await _run_batch_ai_task_body("t-pstop", "evaluate", ["job1"], fake_queue, None)
        assert any("end" in m for m in sent)
        # 关键断言：早退路径不污染全局
        assert tstate.GLOBAL_TASK_STATE["is_processing"] is False
        assert tstate.GLOBAL_TASK_STATE["current_task_id"] is None
        assert tstate.is_batch_stop_requested("t-pstop") is False  # clear_batch_stop 已执行
    finally:
        tstate.task_status.pop("t-pstop", None)
        tstate.clear_batch_stop()


def test_dashboard_sync_route_bound_to_real_handler():
    """路由劫持回归护栏（CR-B3-R3-P0）：/dashboard-sync 必须绑定 dashboard_sync
    协程函数，而非 _sync_source_ok（R3 审出生产 422 事故的护栏）"""
    from app.automation.routes import control_router as cr
    route = next(r for r in cr.router.routes
                 if getattr(r, "path", "").endswith("/dashboard-sync") and "GET" in getattr(r, "methods", set()))
    assert route.endpoint is cr.dashboard_sync
    assert asyncio.iscoroutinefunction(route.endpoint)


# ---------- 拆分子任务：control_router key 兼容读单测（R1 遗留补齐） ----------

def test_mass_resume_id_compat_read():
    """「继续任务」key 兼容读（第一批 P1-4；CR-Split-R1-P1 修正：直调生产函数）：
    真实 key mass_apply_resume_id 优先、旧 key mass_resume_id 兜底、全空 None"""
    from app.automation.routes.control_router import resolve_mass_resume_id
    assert resolve_mass_resume_id({"mass_apply_resume_id": "res-new", "mass_resume_id": "res-old"}) == "res-new"
    assert resolve_mass_resume_id({"mass_resume_id": "res-old"}) == "res-old"
    assert resolve_mass_resume_id({}) is None
    assert resolve_mass_resume_id(None) is None
