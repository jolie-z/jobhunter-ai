"""LLM 闸门弹性并发单元测试（2026-11-03 弹性批处理改造）。

需求：机器空闲（前台零需求）时批处理可用满全局槽——全链路指挥中心深评/初评
不再被「硬顶 2 槽」饿死（0.4.2 当日 ai_scorer 60s 等槽超时 8 次的根治）；
前台（主页/定制面板/在线简历回写等）到来即时收缩，保底不低于 batch_max_concurrency。

锁定：
- 空闲 → 批处理 4 槽全开（LLM_BATCH_ELASTIC_MAX 默认=全局槽）；
- 前台 +1 → 上限即时 -1；前台释放 → 即时回涨；
- 前台持槽等待期间批处理在飞请求不被打断（只约束新获取）；
- 弹性只影响批处理上限，全局槽与前台配额语义不变。
"""
import os
from unittest.mock import patch

import pytest

from app.core.llm_gate import get_llm_gate, reset_llm_gate


@pytest.fixture(autouse=True)
def reset_gate_fixture():
    reset_llm_gate()
    yield
    reset_llm_gate()


def test_idle_all_slots_available_to_batch():
    """前台零需求：批处理可连续拿满全局 4 槽（旧契约只能拿 2）。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "4", "LLM_BATCH_MAX_CONCURRENCY": "2"}):
        reset_llm_gate()
        gate = get_llm_gate()
        assert gate.stats()["batch_effective_cap"] == 4

        guards = [gate.acquire_slot(caller="ai_scorer", timeout=1.0) for _ in range(4)]
        assert all(g is not None and g.is_batch for g in guards)
        assert gate.stats()["batch_active"] == 4
        assert gate.stats()["fg_demand"] == 0

        for g in guards:
            g.release()
        assert gate.stats()["batch_active"] == 0


def test_foreground_arrival_shrinks_batch_cap():
    """前台到来：批处理上限即时收缩；第 4 个批处理请求被弹性和全局槽双重拒绝。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "4", "LLM_BATCH_MAX_CONCURRENCY": "2"}):
        reset_llm_gate()
        gate = get_llm_gate()

        fg = gate.acquire_slot(caller="agent_map", timeout=1.0)
        assert fg is not None and fg.is_batch is False
        assert gate.stats()["fg_demand"] == 1
        assert gate.stats()["batch_effective_cap"] == 3

        b1 = gate.acquire_slot(caller="ai_evaluator", timeout=1.0)
        b2 = gate.acquire_slot(caller="ai_evaluator", timeout=1.0)
        b3 = gate.acquire_slot(caller="ai_evaluator", timeout=1.0)
        assert all(g is not None for g in (b1, b2, b3))

        # 前台占 1 + 批处理占 3 = 全局 4 满；上限 3 也已用尽 → 第 4 个批处理被拒
        b4 = gate.acquire_slot(caller="ai_scorer", timeout=0.2)
        assert b4 is None

        # 前台释放 → 上限回涨到 4，全局槽也让出 1 → 第 4 个批处理立即成功
        fg.release()
        assert gate.stats()["fg_demand"] == 0
        assert gate.stats()["batch_effective_cap"] == 4
        b4 = gate.acquire_slot(caller="ai_scorer", timeout=1.0)
        assert b4 is not None and b4.is_batch

        for g in (b1, b2, b3, b4):
            g.release()


def test_batch_cap_never_below_floor_under_heavy_fg_demand():
    """前台需求超过剩余余量：批处理上限触底 batch_max_concurrency，不低于保底。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "4", "LLM_BATCH_MAX_CONCURRENCY": "2"}):
        reset_llm_gate()
        gate = get_llm_gate()

        fgs = [gate.acquire_slot(caller="agent_map", timeout=1.0) for _ in range(3)]
        assert all(g is not None for g in fgs)
        assert gate.stats()["fg_demand"] == 3
        # clamp(4-3, 2, 4) = 2 → 保底生效
        assert gate.stats()["batch_effective_cap"] == 2

        for g in fgs:
            g.release()
        assert gate.stats()["batch_effective_cap"] == 4


def test_fg_slot_wait_counts_as_demand_and_releases_on_timeout():
    """前台等待全局槽期间就计入需求（批处理提前让位）；获取失败必须回落计数。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "4", "LLM_BATCH_MAX_CONCURRENCY": "2"}):
        reset_llm_gate()
        gate = get_llm_gate()

        # 占满全部全局槽
        holders = [gate.acquire_slot(caller="ai_scorer", timeout=1.0) for _ in range(4)]
        assert all(h is not None for h in holders)
        assert gate.stats()["fg_demand"] == 0

        # 前台等待超时 → 需求计数必须归零（泄漏会永久压低批处理上限）
        fg = gate.acquire_slot(caller="agent_map", timeout=0.2)
        assert fg is None
        assert gate.stats()["fg_demand"] == 0
        assert gate.stats()["batch_effective_cap"] == 4

        for h in holders:
            h.release()


def test_elastic_max_env_override():
    """LLM_BATCH_ELASTIC_MAX 可把弹性顶从全局 4 压到更小（运维规格优先）。"""
    with patch.dict(os.environ, {
        "LLM_MAX_CONCURRENCY": "4", "LLM_BATCH_MAX_CONCURRENCY": "2", "LLM_BATCH_ELASTIC_MAX": "3",
    }):
        reset_llm_gate()
        gate = get_llm_gate()
        assert gate.stats()["batch_elastic_max"] == 3
        assert gate.stats()["batch_effective_cap"] == 3
