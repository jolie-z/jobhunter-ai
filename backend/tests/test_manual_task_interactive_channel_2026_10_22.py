"""
前台手动任务 × 后台定时批量 并发撞车治理回归（2026-10-22）

病灶复盘：
- 手动「AI初步评估」与定时批量共用 caller=ai_evaluator，被闸门一律归入批处理通道
  （LLM_BATCH_MAX_CONCURRENCY=2）；定时批量打满 2 槽后，手动请求等 60s 超时 × N 次重试
  → 「AI评估失败」，期间前端零输出（痛点 2）。
- T2/T3 定时发射不建 SSE 队列、不置 GLOBAL_TASK_STATE，前端完全不可见（痛点 1）。
- 闸门拒绝原因只留在服务端 print，用户不知道是「被批量挤兑」还是「模型挂了」（根因 3）。

本文件锁定四条修复：
1. 交互通道覆写（ContextVar）：批处理 caller 在覆写下只占全局槽、不占批处理配额；
   同步与异步（run_in_executor 不拷贝上下文，必须显式透传）两条路径都生效。
2. run_batch_ai_task 整链置位交互通道，退出后复位。
3. scheduled_delivery_batch_task 登记/注销后台活动，impl 抛异常也必须注销。
4. /api/tasks/status 聚合 background（活动/全链路/闸门水位）；评估失败携带 user_msg 与 error_kind。
"""
import asyncio
import os
import types
from unittest.mock import patch

import pytest

from app.core.llm_errors import LLMGateTimeoutError
from app.core.llm_gate import (
    get_llm_gate,
    interactive_llm_channel,
    is_interactive_override_active,
    reset_llm_gate,
)
from app.tasks import state as task_state


@pytest.fixture(autouse=True)
def _isolated_gate_and_registry():
    """批处理配额压到 1，让「批处理槽被占满」一枪就能复现；活动登记表前后清空。"""
    with patch.dict(os.environ, {"LLM_BATCH_MAX_CONCURRENCY": "1", "LLM_MAX_CONCURRENCY": "4"}):
        reset_llm_gate()
        task_state.BACKGROUND_ACTIVITIES.clear()
        yield
        task_state.BACKGROUND_ACTIVITIES.clear()
        reset_llm_gate()


# ───────────────────────── 1. 交互通道覆写 ─────────────────────────

def test_interactive_override_bypasses_batch_quota_sync():
    gate = get_llm_gate()
    assert gate.is_batch_caller("ai_evaluator"), "前置：ai_evaluator 必须仍在批处理名单（不改名单只改通道）"

    # 定时批量占住唯一的批处理槽
    bg_guard = gate.acquire_slot("ai_evaluator", timeout=1.0)
    assert bg_guard is not None and bg_guard.is_batch

    # 旧行为：手动评估同 caller → 批处理配额已满 → 被拒
    assert gate.acquire_slot("ai_evaluator", timeout=0.2) is None

    # 新行为：交互通道覆写 → 只占全局槽 → 立刻拿到
    with interactive_llm_channel():
        assert is_interactive_override_active()
        fg_guard = gate.acquire_slot("ai_evaluator", timeout=0.2)
    assert fg_guard is not None
    assert fg_guard.is_batch is False, "覆写下不得标记为批处理槽，否则释放时会错误归还批处理 semaphore"
    assert not is_interactive_override_active(), "离开上下文必须复位"

    fg_guard.release()
    bg_guard.release()
    # 全部归还后批处理槽可再次获取（无泄漏/无双重释放）
    again = gate.acquire_slot("ai_evaluator", timeout=0.2)
    assert again is not None
    again.release()


@pytest.mark.asyncio
async def test_interactive_override_survives_run_in_executor_async_path():
    """async_acquire_slot 走 run_in_executor（不拷贝 ContextVar），覆写必须显式穿透。"""
    gate = get_llm_gate()
    bg_guard = gate.acquire_slot("ai_evaluator", timeout=1.0)
    assert bg_guard is not None

    # 无覆写：异步路径同样被批处理配额拦住
    assert await gate.async_acquire_slot("ai_evaluator", timeout=0.2) is None

    with interactive_llm_channel():
        fg_guard = await gate.async_acquire_slot("ai_evaluator", timeout=0.2)
    assert fg_guard is not None and fg_guard.is_batch is False

    fg_guard.release()
    bg_guard.release()


def test_override_does_not_affect_non_batch_or_disabled_gate():
    """覆写对非批处理 caller 无副作用；闸门关闭时仍 100% 直通。"""
    gate = get_llm_gate()
    with interactive_llm_channel():
        g = gate.acquire_slot("skill_rewrite", timeout=0.2)
    assert g is not None and g.is_batch is False
    g.release()

    with patch("app.core.llm_gate.is_llm_gate_enabled", return_value=False):
        with interactive_llm_channel():
            bypass = gate.acquire_slot("ai_evaluator", timeout=0.1)
    assert bypass is not None and bypass._bypassed


# ───────────────────────── 2. 手动任务入口整链置位 ─────────────────────────

@pytest.mark.asyncio
async def test_run_batch_ai_task_marks_interactive_channel_and_resets():
    from app.tasks import executor

    seen: dict = {}

    async def fake_body(task_id, task_type, job_ids, queue, scheduled_at=None):
        seen["inside"] = is_interactive_override_active()
        # 模拟 wave_pipeline 把评估丢进线程：asyncio.to_thread 拷贝上下文，标记必须穿透
        seen["in_thread"] = await asyncio.to_thread(is_interactive_override_active)

    with patch.object(executor, "_run_batch_ai_task_body", fake_body):
        await executor.run_batch_ai_task("t1", "evaluate", ["BOSS直聘-rec1"], asyncio.Queue())

    assert seen == {"inside": True, "in_thread": True}
    assert not is_interactive_override_active(), "任务结束后不得污染后续调用链"


# ───────────────────────── 3. 定时发射后台活动登记 ─────────────────────────

@pytest.mark.asyncio
async def test_scheduled_delivery_registers_and_clears_background_activity(monkeypatch):
    from app.automation import delivery_tasks as dt

    snapshot: dict = {}

    async def fake_impl(window_label, pipeline_app=None):
        snapshot["during"] = task_state.get_background_activities()

    monkeypatch.setattr(dt, "_scheduled_delivery_batch_task_impl", fake_impl)
    await dt.scheduled_delivery_batch_task("测试波次")

    during = snapshot["during"]
    assert len(during) == 1
    assert during[0]["key"] == "scheduled_delivery"
    assert "测试波次" in during[0]["label"]
    assert "started_at" in during[0]
    assert task_state.get_background_activities() == [], "任务结束必须注销，否则横幅永久常亮"


@pytest.mark.asyncio
async def test_scheduled_delivery_clears_activity_even_when_impl_raises(monkeypatch):
    from app.automation import delivery_tasks as dt

    async def boom(window_label, pipeline_app=None):
        raise RuntimeError("impl 炸了")

    monkeypatch.setattr(dt, "_scheduled_delivery_batch_task_impl", boom)
    with pytest.raises(RuntimeError, match="impl 炸了"):
        await dt.scheduled_delivery_batch_task("异常波次")
    assert task_state.get_background_activities() == []


@pytest.mark.asyncio
async def test_scheduled_delivery_skips_without_registering_when_manual_lock_busy(monkeypatch):
    """手动批量投递占锁时本轮跳过——不得留下任何活动登记（否则横幅误报「正在运行」）。"""
    from app.automation import delivery_tasks as dt
    from app.automation.routes import delivery_router

    busy_lock = asyncio.Lock()
    await busy_lock.acquire()
    monkeypatch.setattr(delivery_router, "_deliver_worker_lock", busy_lock)

    called = {"n": 0}

    async def fake_impl(window_label, pipeline_app=None):
        called["n"] += 1

    monkeypatch.setattr(dt, "_scheduled_delivery_batch_task_impl", fake_impl)
    await dt.scheduled_delivery_batch_task("占锁波次")
    busy_lock.release()

    assert called["n"] == 0
    assert task_state.get_background_activities() == []


def test_set_background_activity_updates_detail_in_place():
    task_state.set_background_activity("k", True, label="定时投递·上午")
    first_started = task_state.BACKGROUND_ACTIVITIES["k"]["started_at"]
    task_state.set_background_activity("k", True, label="定时投递·上午", detail="12 个岗位待发射")
    entry = task_state.get_background_activities()[0]
    assert entry["detail"] == "12 个岗位待发射"
    assert entry["started_at"] == first_started, "更新明细不得重置开始时间"
    task_state.set_background_activity("k", False)
    assert task_state.get_background_activities() == []


# ───────────────────────── 4. 状态接口聚合 + 失败原因上抛 ─────────────────────────

def test_task_status_endpoint_aggregates_background_signals():
    from app.tasks.router import get_task_status

    task_state.set_background_activity("scheduled_delivery", True, label="定时投递·下午波次")
    res = get_task_status()

    bg = res["background"]
    assert bg["activities"][0]["label"] == "定时投递·下午波次"
    assert "running" in bg["pipeline"]
    assert bg["llm_gate"]["max_concurrency"] == 4
    assert bg["llm_gate"]["batch_max_concurrency"] == 1
    assert "cooldown_remaining" in bg["llm_gate"]


def test_eval_failure_surfaces_gate_user_msg_and_kind():
    """闸门拒绝的 user_msg 必须进入 parse_error（→ SSE「初评失败: …」），而非只剩异常类名。"""
    from ai_agents import ai_evaluator as ae

    def rejected_create(**kwargs):
        raise LLMGateTimeoutError("并发槽位已满（caller=ai_evaluator），等待超时被闸门拒绝", retry_after=2.0)

    with patch.object(ae, "get_openai_client") as m_client, patch.object(ae, "_EVAL_PARSE_MAX_RETRY", 0):
        m_client.return_value.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=rejected_create))
        result, _usage = ae._call_10dim_evaluation("简历", "JD")

    assert result["parse_failed"] is True
    assert "并发槽位已满" in result["parse_error"]
    assert "被闸门拒绝" in result["parse_error"]
    assert result["error_kind"] == "rate_limited"
    assert "LLMGateTimeoutError" not in result["parse_error"], "有 user_msg 时不得再暴露裸异常类名"


def test_eval_failure_falls_back_to_exception_text_without_user_msg():
    from ai_agents import ai_evaluator as ae

    def plain_boom(**kwargs):
        raise ConnectionError("socket closed")

    with patch.object(ae, "get_openai_client") as m_client, patch.object(ae, "_EVAL_PARSE_MAX_RETRY", 0):
        m_client.return_value.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=plain_boom))
        result, _usage = ae._call_10dim_evaluation("简历", "JD")

    assert "ConnectionError: socket closed" in result["parse_error"]
    assert result["error_kind"] == "unknown"
