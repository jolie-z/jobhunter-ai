"""
Phase 2 LLM 进程级全局限流闸门单元测试 (backend/tests/test_llm_gate.py)

测试规范：
1. 跨线程全局并发槽上限约束
2. 双通道配额隔离：批处理受限且交互调用保底不被霸占
3. RPM 令牌桶扣减与补充
4. 429 全局冷却窗闸外等待生效
5. 重试退避休眠期间并发槽已释放（不占槽）
6. GovernedStream / AsyncGovernedStream 流式期间全程占槽、耗尽或 close 幂等释放
7. LLM_GATE_ENABLED 回滚开关 settings.json 优先于环境变量
8. diagnose_llm 诊断接口挂载 gate_stats 验证
"""
import asyncio
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from app.core.llm_errors import LLMGateTimeoutError, LLMErrorKind
from app.core.llm_gate import (
    LLMGate,
    SlotGuard,
    get_llm_gate,
    is_llm_gate_enabled,
    reset_llm_gate,
)
from app.core.llm_governed import (
    AsyncGovernedStream,
    GovernedStream,
    govern_async_call,
    govern_sync_call,
)
from app.core.llm_retry import RetryPolicy


@pytest.fixture(autouse=True)
def reset_gate_fixture():
    reset_llm_gate()
    yield
    reset_llm_gate()


def test_gate_concurrency_slots_blocking_and_release():
    """验证全局并发槽上限：槽位占满时超时阻塞，释放后立即可获取。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "2", "LLM_BATCH_MAX_CONCURRENCY": "2"}):
        reset_llm_gate()
        gate = get_llm_gate()

        guard1 = gate.acquire_slot(caller="agent_map", timeout=1.0)
        guard2 = gate.acquire_slot(caller="agent_map", timeout=1.0)
        assert guard1 is not None
        assert guard2 is not None
        assert gate.stats()["active_slots"] == 2

        # 3. 槽位满时，第 3 个请求超时并返回 None
        guard3 = gate.acquire_slot(caller="agent_map", timeout=0.1)
        assert guard3 is None

        # 4. 释放 1 个槽位后，第 3 个请求成功获取
        guard1.release()
        assert gate.stats()["active_slots"] == 1
        guard3_retry = gate.acquire_slot(caller="agent_map", timeout=1.0)
        assert guard3_retry is not None
        assert gate.stats()["active_slots"] == 2

        # 5. 重复 release 幂等不报错
        guard1.release()
        guard2.release()
        guard3_retry.release()
        assert gate.stats()["active_slots"] == 0


def test_batch_caller_concurrency_quota_isolation():
    """验证双通道配额隔离：批处理占满配额后，交互通道仍保留专属空位。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "4", "LLM_BATCH_MAX_CONCURRENCY": "2"}):
        reset_llm_gate()
        gate = get_llm_gate()

        # 批处理调用方（侦察兵真实 caller：step1_rule_filter）占用 2 个批处理槽位
        batch1 = gate.acquire_slot(caller="step1_rule_filter", timeout=1.0)
        batch2 = gate.acquire_slot(caller="step1_rule_filter", timeout=1.0)
        assert batch1 is not None and batch1.is_batch is True
        assert batch2 is not None and batch2.is_batch is True

        # 第 3 个批处理请求因批处理配额耗尽而超时
        batch3 = gate.acquire_slot(caller="step1_rule_filter", timeout=0.1)
        assert batch3 is None

        # 交互调用方（agent_map 等非 BATCH_CALLERS 成员）仍可立即申请剩余的 2 个全局空位
        interactive1 = gate.acquire_slot(caller="agent_map", timeout=1.0)
        assert interactive1 is not None and interactive1.is_batch is False
        assert gate.stats()["active_slots"] == 3

        batch1.release()
        batch2.release()
        interactive1.release()
        assert gate.stats()["active_slots"] == 0


def test_token_bucket_wait_and_consume():
    """验证 RPM 令牌桶扣减。"""
    gate = LLMGate()
    gate._token_bucket.tokens = 1.0  # 仅留 1 个令牌

    # 首次消耗成功
    assert gate.wait_for_rpm_token(timeout=1.0) is True
    # 令牌耗尽后短超时失败
    assert gate._token_bucket.tokens < 1.0
    assert gate.wait_for_rpm_token(timeout=0.01) is False


def test_global_429_cooldown_window():
    """验证遇到 429 时全局原子开启冷却窗，后续请求必须在闸外等待。"""
    gate = LLMGate()
    gate.notify_rate_limited(retry_after=0.2)

    stats = gate.stats()
    assert stats["total_rate_limited"] == 1
    assert stats["cooldown_remaining"] > 0

    t0 = time.monotonic()
    assert gate.wait_if_global_cooldown(timeout=1.0) is True
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.15, "必须闸外等待冷却窗直至到期"


def test_retry_sleep_does_not_hold_concurrency_slot():
    """【核心约束断言】重试退避休眠期间并发槽已释放，绝不霸占并发槽。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "1"}):
        reset_llm_gate()
        gate = get_llm_gate()

        call_count = 0
        slot_occupied_during_sleep = False

        class Mock429(Exception):
            status_code = 429

        def mock_raw_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Mock429("Rate limit")
            return MagicMock()

        def custom_sleep(delay):
            nonlocal slot_occupied_during_sleep
            # 在退避休眠期间，尝试申请并发槽；若申请成功说明休眠期间槽位已释放
            g = gate.acquire_slot(caller="inspector", timeout=0.1)
            if g is not None:
                slot_occupied_during_sleep = False
                g.release()
            else:
                slot_occupied_during_sleep = True

        policy = RetryPolicy(max_attempts=2, base_delay=0.1)

        with patch("time.sleep", side_effect=custom_sleep):
            govern_sync_call(mock_raw_create, (), {}, caller="test", policy=policy)

        assert call_count == 2
        assert slot_occupied_during_sleep is False, "退避休眠期间并发槽必须已释放，不阻塞其他请求"


def test_governed_stream_holds_slot_until_consumed():
    """【GLM2-P1-1 验证】同步流式响应期间全程占槽，消费完毕后幂等释放槽位。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "1"}):
        reset_llm_gate()
        gate = get_llm_gate()

        def fake_raw_stream_create(*args, **kwargs):
            def _gen():
                yield "chunk1"
                yield "chunk2"
            return _gen()

        stream = govern_sync_call(fake_raw_stream_create, (), {"stream": True}, caller="stream_caller")
        assert isinstance(stream, GovernedStream)
        # 流还未读完，并发槽正被持有
        assert gate.stats()["active_slots"] == 1
        assert gate.acquire_slot(caller="another", timeout=0.05) is None

        # 消费流
        chunks = list(stream)
        assert chunks == ["chunk1", "chunk2"]
        # 读完流后槽位已释放
        assert gate.stats()["active_slots"] == 0

        # 重复 close 幂等且不抛异常
        stream.close()
        assert gate.stats()["active_slots"] == 0


@pytest.mark.asyncio
async def test_async_governed_stream_holds_slot_until_aclose():
    """【异步流式验证】异步流式响应在迭代期间持有槽位，aclose 释放。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "1"}):
        reset_llm_gate()
        gate = get_llm_gate()

        async def fake_raw_async_stream(*args, **kwargs):
            class _AsyncGen:
                def __init__(self):
                    self.items = ["a1", "a2"]
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    if not self.items:
                        raise StopAsyncIteration
                    return self.items.pop(0)
            return _AsyncGen()

        stream = await govern_async_call(fake_raw_async_stream, (), {"stream": True}, caller="async_stream")
        assert isinstance(stream, AsyncGovernedStream)
        assert gate.stats()["active_slots"] == 1

        chunks = []
        async for c in stream:
            chunks.append(c)
        assert chunks == ["a1", "a2"]
        assert gate.stats()["active_slots"] == 0

        await stream.aclose()
        assert gate.stats()["active_slots"] == 0


def test_gate_rollback_switch_settings_overrides_env():
    """【GLM2-P1-4 验证】回滚开关 settings.json 优先于系统环境变量，关闭即完全旁路。"""
    with patch.dict(os.environ, {"LLM_GATE_ENABLED": "true"}), \
         patch("common.config.get_setting", return_value=False):
        assert is_llm_gate_enabled() is False

        gate = get_llm_gate()
        guard = gate.acquire_slot(caller="bypass_test")
        assert guard is not None
        assert guard._bypassed is True
        assert gate.stats()["active_slots"] == 0
        guard.release()
        assert gate.stats()["active_slots"] == 0


@pytest.mark.asyncio
async def test_diagnose_llm_includes_gate_stats():
    """验证系统诊断接口 diagnose_llm 正常输出 gate_stats 状态字典。"""
    from app.settings.diagnostics import diagnose_llm

    with patch("app.settings.diagnostics.get_missing_llm_keys", return_value=["OPENAI_API_KEY"]), \
         patch("app.settings.diagnostics.get_missing_vision_keys", return_value=["VISION_API_KEY"]):
        res = await diagnose_llm()
        assert res["code"] == 0
        assert "gate_stats" in res["data"]
        stats = res["data"]["gate_stats"]
        assert stats is not None
        assert "max_concurrency" in stats
        assert "active_slots" in stats
        assert "max_rpm" in stats
        assert "enabled" in stats


def test_gate_acquire_slot_timeout_raises_timeout_error_and_does_not_call_raw_create():
    """【P1 验证】并发槽打满且等待超时（acquire_slot 返回 None）时，绝不旁路直调 raw_create，抛出 LLMGateTimeoutError。"""
    raw_called = False

    def fake_create(*args, **kwargs):
        nonlocal raw_called
        raw_called = True
        return {"ok": True}

    gate = get_llm_gate()
    with patch.object(gate, "acquire_slot", return_value=None):
        with pytest.raises(LLMGateTimeoutError) as exc_info:
            govern_sync_call(
                fake_create,
                (),
                {},
                caller="test_timeout",
                policy=RetryPolicy(max_attempts=1),
            )

    assert not raw_called, "并发槽获取超时后严禁裸发请求上游！"
    assert exc_info.value.status_code == 429
    assert exc_info.value.kind == LLMErrorKind.rate_limited
    assert "并发槽位已满" in str(exc_info.value)


def test_gate_cooldown_exceeds_timeout_rejects_and_does_not_call_raw_create():
    """【P1 验证】全局 429 冷却窗口剩余时间超限时，绝不旁路直调 raw_create，抛出 LLMGateTimeoutError。"""
    raw_called = False

    def fake_create(*args, **kwargs):
        nonlocal raw_called
        raw_called = True
        return {"ok": True}

    gate = get_llm_gate()
    with patch.object(gate, "wait_if_global_cooldown", return_value=False), \
         patch.object(gate, "get_cooldown_remaining", return_value=120.0):
        with pytest.raises(LLMGateTimeoutError) as exc_info:
            govern_sync_call(
                fake_create,
                (),
                {},
                caller="test_cooldown",
                policy=RetryPolicy(max_attempts=1),
            )

    assert not raw_called, "冷却超限后严禁裸发请求上游！"
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 120.0
    assert "全局 429 冷却期" in str(exc_info.value)


def test_gate_rpm_token_timeout_rejects_and_does_not_call_raw_create():
    """【P1 验证】RPM 令牌等待超时时，绝不旁路直调 raw_create，抛出 LLMGateTimeoutError。"""
    raw_called = False

    def fake_create(*args, **kwargs):
        nonlocal raw_called
        raw_called = True
        return {"ok": True}

    gate = get_llm_gate()
    with patch.object(gate, "wait_for_rpm_token", return_value=False):
        with pytest.raises(LLMGateTimeoutError) as exc_info:
            govern_sync_call(
                fake_create,
                (),
                {},
                caller="test_rpm",
                policy=RetryPolicy(max_attempts=1),
            )

    assert not raw_called, "RPM 超时后严禁裸发请求上游！"
    assert exc_info.value.status_code == 429
    assert "请求速率 (RPM) 达上限" in str(exc_info.value)


@pytest.mark.asyncio
async def test_async_gate_acquire_slot_timeout_rejects_and_does_not_call_raw_create():
    """【P1 验证】异步并发槽获取超时（async_acquire_slot 返回 None）时，绝不旁路直调 raw_create。"""
    raw_called = False

    async def fake_raw_async(*args, **kwargs):
        nonlocal raw_called
        raw_called = True
        return {"ok": True}

    gate = get_llm_gate()
    with patch.object(gate, "async_acquire_slot", return_value=None):
        with pytest.raises(LLMGateTimeoutError) as exc_info:
            await govern_async_call(
                fake_raw_async,
                (),
                {},
                caller="async_timeout",
                policy=RetryPolicy(max_attempts=1),
            )

    assert not raw_called, "异步并发槽获取超时后严禁裸发请求上游！"
    assert exc_info.value.status_code == 429
    assert "并发槽位已满" in str(exc_info.value)
