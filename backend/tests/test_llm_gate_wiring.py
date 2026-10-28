"""
Phase 2 闸门接线与规范缺口回归测试 (backend/tests/test_llm_gate_wiring.py)

对照任务书 Phase 2 测试清单补齐（66576328 质检缺失项）：
1. 冷却窗每次发送前生效（含重试轮次，修复"仅首发检查"漏洞）
2. 等令牌期间并发槽未被占用（真实跨线程）
3. 流式未消费完直接 GC 时 __del__ 兜底释放槽位并记录 warning（GLM3-P2-4）
4. scout(5)+映射并发集成：全局上限与批量配额同时生效，交互调用不被饿死
5. BATCH_CALLERS 架构自检：集合内名字必须在生产代码有真实 caller= 引用（防死名字）
6. governed_llm_passage / GovernedChatOpenAI：拒绝不执行调用体、重入不重复占槽、
   LangChain 模型层每次 _generate/_agenerate 都过闸
7. 容量参数环境变量优先 + LLM_GATE_EXECUTOR_WORKERS 可配置（规范 §二.4）
8. settings.json mtime 缓存的热控失效语义
"""
import asyncio
import gc
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.llm_errors import LLMGateTimeoutError
from app.core.llm_gate import (
    BATCH_CALLERS,
    LLMGate,
    get_llm_gate,
    is_llm_gate_enabled,
    reset_llm_gate,
)
from app.core.llm_governed import (
    async_governed_llm_passage,
    govern_sync_call,
    governed_llm_passage,
)
from app.core.llm_retry import RetryPolicy


@pytest.fixture(autouse=True)
def reset_gate_fixture():
    reset_llm_gate()
    yield
    reset_llm_gate()


class _Mock429(Exception):
    """无 response / Retry-After 的上游 429（智谱 1302 无标头场景）。"""

    status_code = 429


def test_cooldown_checked_before_every_send():
    """【规范】冷却窗每次发送前生效：重试轮次也必须等完剩余冷却窗才能发出。"""
    with patch.dict(os.environ, {"LLM_429_COOLDOWN_SECONDS": "0.3"}):
        reset_llm_gate()
        gate = get_llm_gate()
        events: list[tuple[str, float]] = []

        def raw_create(*_a, **_k):
            events.append(("send", gate.get_cooldown_remaining()))
            if sum(1 for e in events if e[0] == "send") == 1:
                raise _Mock429("rate limit")
            return {"ok": True}

        def fake_sleep(delay):
            events.append(("sleep", round(delay, 2)))

        with patch("time.sleep", side_effect=fake_sleep):
            govern_sync_call(raw_create, (), {}, caller="agent_map",
                             policy=RetryPolicy(max_attempts=2, jitter=False))

    kinds = [e[0] for e in events]
    # 发送 -> 退避休眠(1.0s) -> 冷却窗等待(~0.3s) -> 才允许第 2 次发送
    assert kinds == ["send", "sleep", "sleep", "send"], f"事件序列异常: {events}"
    cooldown_waits = [d for kind, d in events if kind == "sleep" and d < 1.0]
    assert cooldown_waits and 0.2 <= cooldown_waits[0] <= 0.35, (
        f"第 2 次发送前必须等待剩余冷却窗: {events}"
    )


def test_token_wait_does_not_hold_slot_cross_thread():
    """【规范】等令牌期间并发槽未被占用——用真实线程验证。"""
    gate = LLMGate()
    gate._token_bucket.tokens = 0.0  # 令牌耗尽，触发等待

    token_wait_done = threading.Event()
    wait_thread = threading.Thread(
        target=lambda: (gate.wait_for_rpm_token(timeout=0.4), token_wait_done.set())
    )
    wait_thread.start()
    time.sleep(0.05)  # 确保等待线程已进入等令牌状态

    # 等令牌期间并发槽必须全量可用（等待不占槽）
    guards = [gate.acquire_slot(caller="interactive", timeout=0.3) for _ in range(gate.max_concurrency)]
    assert all(g is not None for g in guards), "等令牌期间并发槽被占用！"

    wait_thread.join(timeout=2.0)
    assert token_wait_done.is_set()
    for g in guards:
        g.release()


def test_governed_stream_gc_releases_slot_with_warning(caplog):
    """【GLM3-P2-4】流式未消费完直接 GC：__del__ 兜底释放槽位并记录 warning。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "1"}):
        reset_llm_gate()
        gate = get_llm_gate()

        def stream_create(*_a, **_k):
            def _g():
                yield "c1"
                yield "c2"
            return _g()

        with caplog.at_level(logging.WARNING, logger="llm_governed"):
            s = govern_sync_call(stream_create, (), {"stream": True}, caller="x")
            assert gate.stats()["active_slots"] == 1
            del s
            gc.collect()

        assert gate.stats()["active_slots"] == 0, "GC 后槽位未归还"
        assert any("GC 回收" in r.message for r in caplog.records), "兜底释放必须记录 warning 日志"


def test_scout_and_agent_map_integration_batch_quota_protects_interactive():
    """【规范集成】scout(5)+映射并发：全局并发上限与批量配额同时生效，交互调用不被饿死。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "4", "LLM_BATCH_MAX_CONCURRENCY": "2"}):
        reset_llm_gate()
        gate = get_llm_gate()

        lock = threading.Lock()
        in_flight = {"global": 0, "batch": 0}
        peak = {"global": 0, "batch": 0}

        def make_raw(is_batch: bool):
            def raw(*_a, **_k):
                with lock:
                    in_flight["global"] += 1
                    if is_batch:
                        in_flight["batch"] += 1
                    peak["global"] = max(peak["global"], in_flight["global"])
                    peak["batch"] = max(peak["batch"], in_flight["batch"])
                time.sleep(0.03)
                with lock:
                    in_flight["global"] -= 1
                    if is_batch:
                        in_flight["batch"] -= 1
                return {"ok": True}
            return raw

        results: dict[str, list] = {"scout": [], "map": []}

        def run(caller: str, is_batch: bool, bucket: str):
            try:
                govern_sync_call(make_raw(is_batch), (), {}, caller=caller,
                                 policy=RetryPolicy(max_attempts=1))
                results[bucket].append("ok")
            except Exception as e:  # noqa: BLE001
                results[bucket].append(e)

        threads = [threading.Thread(target=run, args=("step1_rule_filter", True, "scout")) for _ in range(5)]
        threads += [threading.Thread(target=run, args=("agent_map", False, "map")) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(results["map"]) == 2 and all(r == "ok" for r in results["map"]), results["map"]
        assert len(results["scout"]) == 5 and all(r == "ok" for r in results["scout"]), results["scout"]
        assert peak["global"] <= 4, f"全局并发越界: {peak}"
        assert peak["batch"] <= 2, f"批量配额越界: {peak}"
        assert gate.stats()["active_slots"] == 0


def test_batch_callers_architecture_self_check():
    """【架构自检】BATCH_CALLERS 每个名字必须在生产代码有真实 caller=/gate_caller= 引用。

    防止 66576328 式缺陷：名单名字与真实 caller 脱节导致双通道隔离整体失效。
    """
    backend_root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r"""(?:caller|gate_caller)\s*=\s*["']([A-Za-z0-9_]+)["']""")
    found: set[str] = set()
    for entry in backend_root.iterdir():
        if entry.name.startswith(".") or entry.name in ("tests", "test_scripts", "node_modules"):
            continue
        files = [entry] if entry.suffix == ".py" else (entry.rglob("*.py") if entry.is_dir() else [])
        for p in files:
            try:
                found.update(pattern.findall(p.read_text(encoding="utf-8")))
            except Exception:
                continue

    dead = BATCH_CALLERS - found
    assert not dead, f"BATCH_CALLERS 存在生产代码零引用的死名字（双通道隔离失效）: {dead}"
    # 已知真实批量链路点名验证
    gate = LLMGate()
    for name in ("step1_rule_filter", "ai_evaluator", "ai_scorer", "job_table_hygiene"):
        assert gate.is_batch_caller(name) is True, name


def test_governed_passage_rejects_without_running_body():
    """显式过闸被拒绝时严禁执行调用体（LangChain 站点防裸发）。"""
    gate = get_llm_gate()
    body_ran = False
    with patch("app.core.llm_governed.is_llm_gate_enabled", return_value=True), \
         patch.object(gate, "wait_if_global_cooldown", return_value=False), \
         patch.object(gate, "get_cooldown_remaining", return_value=120.0):
        with pytest.raises(LLMGateTimeoutError):
            with governed_llm_passage(caller="agent_router"):
                body_ran = True
    assert body_ran is False
    assert gate.stats()["active_slots"] == 0


def test_governed_passage_reentrant_does_not_double_book():
    """重入护栏：同一调用链嵌套进入只占一次槽、只扣一次令牌。"""
    gate = get_llm_gate()
    with governed_llm_passage(caller="chat_agent"):
        assert gate.stats()["active_slots"] == 1
        with governed_llm_passage(caller="chat_agent"):
            assert gate.stats()["active_slots"] == 1
    assert gate.stats()["active_slots"] == 0


@pytest.mark.asyncio
async def test_async_governed_passage_holds_and_releases():
    """异步显式过闸：占槽 -> 成功计数 -> 释放。"""
    gate = get_llm_gate()
    async with async_governed_llm_passage(caller="job_table_hygiene"):
        assert gate.stats()["active_slots"] == 1
        assert gate.is_batch_caller("job_table_hygiene")
    assert gate.stats()["active_slots"] == 0
    assert gate.stats()["total_successes"] == 1


def test_capacity_params_env_overrides_settings():
    """【规范 §二.4】容量参数：环境变量 > settings.json；熔断开关仍 settings.json 优先。"""
    with patch.dict(os.environ, {"LLM_MAX_CONCURRENCY": "2"}), \
         patch("common.config.get_setting", side_effect=lambda k: 8 if k == "LLM_MAX_CONCURRENCY" else None):
        gate = LLMGate()
        assert gate.max_concurrency == 2, "容量参数必须环境变量优先"

    with patch.dict(os.environ, {"LLM_GATE_ENABLED": "true"}), \
         patch("common.config.get_setting", side_effect=lambda k: False if k == "LLM_GATE_ENABLED" else None):
        assert is_llm_gate_enabled() is False, "熔断开关必须 settings.json 热控优先"


def test_gate_executor_workers_configurable():
    """【规范 §二.4】LLM_GATE_EXECUTOR_WORKERS 可配置。"""
    with patch.dict(os.environ, {"LLM_GATE_EXECUTOR_WORKERS": "3", "LLM_MAX_CONCURRENCY": "4"}):
        gate = LLMGate()
        assert gate._executor._max_workers == 3


def test_governed_chat_openai_wraps_generate_and_agenerate(monkeypatch):
    """GovernedChatOpenAI：模型层每次 _generate/_agenerate 都过闸，并透传 gate_caller。"""
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    import app.core.llm_langchain as llc

    entered: list[str] = []

    @contextmanager
    def recording_passage(caller: str = "", _timeout: float = 60.0):
        entered.append(caller)
        yield

    @asynccontextmanager
    async def recording_async_passage(caller: str = "", _timeout: float = 60.0):
        entered.append(caller)
        yield

    monkeypatch.setattr(llc, "governed_llm_passage", recording_passage)
    monkeypatch.setattr(llc, "async_governed_llm_passage", recording_async_passage)

    def fake_generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ARG001
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def fake_agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ARG001
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    # 打补丁到 MRO 中真正定义 _generate/_agenerate 的父类，避免覆盖子类包装
    for klass in llc.GovernedChatOpenAI.__mro__[1:]:
        if "_generate" in klass.__dict__:
            monkeypatch.setattr(klass, "_generate", fake_generate)
            break
    for klass in llc.GovernedChatOpenAI.__mro__[1:]:
        if "_agenerate" in klass.__dict__:
            monkeypatch.setattr(klass, "_agenerate", fake_agenerate)
            break

    model = llc.GovernedChatOpenAI(
        model="test-model", api_key="k", base_url="http://localhost:9/v1",
        gate_caller="agent_router",
    )
    assert model.invoke("hi").content == "ok"
    assert entered == ["agent_router"]

    entered.clear()
    assert asyncio.run(model.ainvoke("hi")).content == "ok"
    assert entered == ["agent_router"]


def test_governed_chat_openai_stream_lifecycle(monkeypatch):
    """GovernedChatOpenAI 流式路径：迭代期间真实持槽，读完/中途关闭后释放（真实闸门非打桩）。"""
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk

    import app.core.llm_langchain as llc

    def fake_stream(self, *args, **kwargs):  # noqa: ARG001
        yield ChatGenerationChunk(message=AIMessageChunk(content="a"))

    async def fake_astream(self, *args, **kwargs):  # noqa: ARG001
        yield ChatGenerationChunk(message=AIMessageChunk(content="b"))

    for klass in llc.GovernedChatOpenAI.__mro__[1:]:
        if "_stream" in klass.__dict__:
            monkeypatch.setattr(klass, "_stream", fake_stream)
            break
    for klass in llc.GovernedChatOpenAI.__mro__[1:]:
        if "_astream" in klass.__dict__:
            monkeypatch.setattr(klass, "_astream", fake_astream)
            break

    gate = get_llm_gate()
    model = llc.GovernedChatOpenAI(
        model="test-model", api_key="k", base_url="http://localhost:9/v1",
        gate_caller="agent_router",
    )

    # 完整消费：结束后槽位归还
    chunks = list(model.stream("hi"))
    assert chunks and chunks[0].content == "a"
    assert gate.stats()["active_slots"] == 0

    # 中途关闭：生成器关闭（含 CPython 引用计数即时回收内层生成器）必须触发 finally 释放
    it = model.stream("hi")
    next(it)
    assert gate.stats()["active_slots"] == 1, "流迭代期间必须持有并发槽"
    it.close()
    gc.collect()
    assert gate.stats()["active_slots"] == 0, "流关闭后必须释放并发槽"

    async def consume_async():
        return [c async for c in model.astream("hi")]

    got = asyncio.run(consume_async())
    assert got and got[0].content == "b"
    assert gate.stats()["active_slots"] == 0


def test_settings_mtime_cache_invalidates_on_write(tmp_path, monkeypatch):
    """settings.json mtime 缓存：文件变更后读取立即可见（热控语义不变）。"""
    import common.config as cc

    f = tmp_path / "settings.json"
    f.write_text('{"LLM_GATE_ENABLED": true}', encoding="utf-8")
    monkeypatch.setattr(cc, "SETTINGS_JSON_PATH", f)
    monkeypatch.setattr(cc, "_settings_cache", {"mtime_ns": None, "data": {}})

    assert cc.get_setting("LLM_GATE_ENABLED") is True

    f.write_text('{"LLM_GATE_ENABLED": false}', encoding="utf-8")
    # 强制 mtime 前进，规避文件系统时间戳粒度
    os.utime(f, ns=(1, time.time_ns() + 1_000_000))
    assert cc.get_setting("LLM_GATE_ENABLED") is False
