"""中断评估恢复链路测试。

覆盖三层：
1. LangGraph checkpoint 续跑语义（真实 AsyncSqliteSaver + 迷你图：节点中途炸 ≈ 进程被硬杀，
   astream(None) 应只重跑中断节点，不重跑已完成节点）；
2. 恢复执行器决策表：超时标红 / 无检查点标红 / 图中断复用旧卡续跑补投物料 / 物料已交付跳过补发；
3. 防重与生命周期：跑动中登记在案、正常与异常路径注销、登记未注销时拒绝重复点击。

外部边界（飞书卡片/消息/物料交付/流水线本体）全部 Mock，决策与状态流转真实执行。
"""
import asyncio
import json
import time
from types import SimpleNamespace
from typing import TypedDict

import pytest

from app.automation import inflight_registry as reg
from app.automation import scheduler as scheduler_mod
from app.services import job_entry_chat
from app.services import eval_pipeline_feedback as epf


@pytest.fixture(autouse=True)
def _tmp_registry(tmp_path, monkeypatch):
    reg.reset_for_test(tmp_path / "inflight.json")
    monkeypatch.setattr(epf, "_inflight_pipelines", set())
    yield
    reg.reset_for_test()


@pytest.fixture
def patched_feishu(monkeypatch):
    """替换聊天录入链路的全部飞书边界，返回记录器。"""
    sent, cards_sent, card_updates = [], [], []

    async def fake_send_card(receive_id, card, receive_id_type="chat_id"):
        cards_sent.append((receive_id, card))
        return f"om_card_{len(cards_sent)}"

    async def fake_update_card(message_id, card):
        card_updates.append((message_id, card))
        return True

    async def fake_send(receive_id, text, receive_id_type="chat_id", **kw):
        sent.append((receive_id, text))
        return True

    async def fake_deliver(chat_id, record_id, company="", job=""):
        sent.append((chat_id, f"__delivered__{record_id}"))
        return True  # 新契约：交付函数返回真实成败

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "测试公司", "岗位名称": "测试岗位"}}

    monkeypatch.setattr(epf, "send_feishu_card", fake_send_card)
    monkeypatch.setattr(epf, "update_feishu_card", fake_update_card)
    monkeypatch.setattr(epf, "send_feishu_message", fake_send)
    monkeypatch.setattr(epf, "_deliver_materials_to_chat", fake_deliver)

    from app.core.feishu_client import feishu_client
    monkeypatch.setattr(feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    return SimpleNamespace(sent=sent, cards_sent=cards_sent, card_updates=card_updates)


# ==========================================
# 1. LangGraph checkpoint 续跑语义
# ==========================================
def test_langgraph_resume_only_reruns_interrupted_node(tmp_path):
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    import aiosqlite

    calls = {"n1": 0, "n2": 0}
    fail_n2 = {"active": True}

    class _S(TypedDict):
        n1: str
        n2: str

    async def node1(state):
        calls["n1"] += 1
        return {"n1": "done"}

    async def node2(state):
        calls["n2"] += 1
        if fail_n2["active"]:
            raise RuntimeError("模拟进程死在节点执行中")
        return {"n2": "done"}

    builder = StateGraph(_S)
    builder.add_node("n1", node1)
    builder.add_node("n2", node2)
    builder.add_edge(START, "n1")
    builder.add_edge("n1", "n2")
    builder.add_edge("n2", END)

    async def scenario():
        conn = await aiosqlite.connect(tmp_path / "ckpt.db")
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": "t1"}}

        # 第一跑：n1 完成落 checkpoint，n2 中途炸（等价于进程被硬杀）
        with pytest.raises(RuntimeError):
            async for _ in graph.astream({"n1": "", "n2": ""}, config):
                pass
        state = await graph.aget_state(config)
        assert state.next == ("n2",), "断点应停在 n2 等待执行"

        # 恢复：astream(None) 续跑，n1 不重跑
        fail_n2["active"] = False
        async for _ in graph.astream(None, config):
            pass
        final = await graph.aget_state(config)
        assert final.values["n1"] == "done"
        assert final.values["n2"] == "done"
        assert calls["n1"] == 1, "已完成的节点不应重跑"
        assert calls["n2"] == 2, "中断节点应恰好重跑一次"
        await conn.close()

    asyncio.run(scenario())


# ==========================================
# 2. 恢复执行器决策表
# ==========================================
def test_stale_entry_not_resumed_but_marked_red(patched_feishu, monkeypatch):
    from app.automation import full_auto

    launches = []

    async def fake_launch(**kw):
        launches.append(kw)
        return {}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    monkeypatch.setattr(epf, "_RESUME_STALE_SECONDS", 3600)
    reg.register("recOld", chat_id="oc1", card_msg_id="om_old",
                 company="旧公司", job="旧岗位", started_epoch=time.time() - 7200)

    asyncio.run(job_entry_chat.resume_inflight_evaluations())

    assert launches == [], "超时登记不应触发续跑"
    assert patched_feishu.card_updates, "旧进度卡应被标红"
    _, card = patched_feishu.card_updates[-1]
    assert card["header"]["template"] == "red"
    body = json.dumps(card, ensure_ascii=False)
    assert "请重新点击" in body
    assert not reg.has("recOld"), "处理完的登记应注销（让用户能重新点击）"


def test_resume_without_checkpoint_marks_red(patched_feishu, monkeypatch):
    from app.automation import full_auto

    launches = []

    async def fake_launch(**kw):
        launches.append(kw)
        return {}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    monkeypatch.setattr(scheduler_mod, "pipeline_app", None)
    reg.register("recNock", chat_id="oc1", card_msg_id="om_1")

    asyncio.run(job_entry_chat.resume_inflight_evaluations())

    assert launches == []
    _, card = patched_feishu.card_updates[-1]
    assert card["header"]["template"] == "red"
    assert "检查点" in json.dumps(card, ensure_ascii=False)
    assert not reg.has("recNock")


def test_midgraph_resume_rebinds_card_and_delivers(patched_feishu, monkeypatch):
    from app.automation import full_auto

    launches = []

    async def fake_launch(**kw):
        launches.append(kw)
        return {"outcome": "stopped", "status": "简历人工复核", "grade": "A"}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)

    class _FakeState:
        values = {"grade": "A", "score": 89.0}
        next = ("rewrite_node",)

    class _FakeApp:
        async def aget_state(self, config):
            assert config["configurable"]["thread_id"] == "recMid"
            return _FakeState()

    monkeypatch.setattr(scheduler_mod, "pipeline_app", _FakeApp())

    reg.register("recMid", chat_id="oc1", card_msg_id="om_live",
                 company="公司A", job="岗位B", started_epoch=time.time() - 120)

    asyncio.run(job_entry_chat.resume_inflight_evaluations())

    assert len(launches) == 1
    kw = launches[0]
    assert kw["record_id"] == "recMid"
    assert kw["resume"] is True
    assert kw["stop_at_review"] is True
    assert callable(kw["on_node_done"])

    assert patched_feishu.cards_sent == [], "恢复模式应复用旧卡，不发新卡"
    assert all(mid == "om_live" for mid, _ in patched_feishu.card_updates)
    first_note = json.dumps(patched_feishu.card_updates[0][1], ensure_ascii=False)
    assert "断点恢复" in first_note
    assert "✅ AI 初评 + 深度评估" in first_note, "已完成的评估阶段应按 checkpoint 重建为 ✅"
    last_card = patched_feishu.card_updates[-1][1]
    assert last_card["header"]["template"] == "green"
    assert "已送达下方消息" in json.dumps(last_card, ensure_ascii=False)
    assert any("__delivered__recMid" in t for _, t in patched_feishu.sent), "物料应补投递"
    assert not reg.has("recMid")


def test_resume_skips_delivery_when_materials_already_sent(patched_feishu, monkeypatch):
    from app.automation import full_auto

    async def fake_launch(**kw):
        return {"outcome": "stopped", "status": "简历人工复核"}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)

    class _FakeState:
        values = {"grade": "A", "final_markdown": "md", "greeting": "hi"}
        next = ()

    class _FakeApp:
        async def aget_state(self, config):
            return _FakeState()

    monkeypatch.setattr(scheduler_mod, "pipeline_app", _FakeApp())

    reg.register("recDone", chat_id="oc1", card_msg_id="om_d", started_epoch=time.time() - 60)
    reg.mark_materials_delivered("recDone")

    asyncio.run(job_entry_chat.resume_inflight_evaluations())

    assert not any("__delivered__" in t for _, t in patched_feishu.sent), "物料已交付过就不应补发"
    last = patched_feishu.card_updates[-1][1]
    assert last["header"]["template"] == "green"
    assert "无需重复发送" in json.dumps(last, ensure_ascii=False)
    assert not reg.has("recDone")


# ==========================================
# 3. 防重与生命周期
# ==========================================
def test_fresh_run_registers_during_and_cleans_after(patched_feishu, monkeypatch):
    from app.automation import full_auto

    seen = {}

    async def fake_launch(**kw):
        seen["registered_during_run"] = reg.has(kw["record_id"])
        seen["resume_kwarg"] = kw.get("resume")
        seen["chat_id"] = (reg.get(kw["record_id"]) or {}).get("chat_id")
        seen["card_msg_id"] = (reg.get(kw["record_id"]) or {}).get("card_msg_id")
        return {"outcome": "stopped", "status": "简历人工复核"}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)

    asyncio.run(job_entry_chat._run_pipeline_with_feedback("oc1", "recX"))

    assert seen == {
        "registered_during_run": True,
        "resume_kwarg": False,
        "chat_id": "oc1",
        "card_msg_id": "om_card_1",
    }
    assert not reg.has("recX"), "正常结束后登记应注销"


def test_pipeline_exception_marks_red_and_unregisters(patched_feishu, monkeypatch):
    from app.automation import full_auto

    async def fake_launch(**kw):
        raise RuntimeError("LLM 超时")

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)

    asyncio.run(job_entry_chat._run_pipeline_with_feedback("oc1", "recErr"))

    reds = [c for _, c in patched_feishu.card_updates if c["header"]["template"] == "red"]
    assert reds, "异常应把进度卡标红"
    assert "LLM 超时" in json.dumps(reds[-1], ensure_ascii=False)
    assert not reg.has("recErr"), "异常路径也应注销登记，允许用户重试"


def test_launch_rejected_while_registered_in_registry(patched_feishu, monkeypatch):
    from app.automation import full_auto

    launches = []

    async def fake_launch(**kw):
        launches.append(kw)
        return {}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    monkeypatch.setattr(scheduler_mod, "pipeline_app", None)

    reg.register("recY", chat_id="oc1", card_msg_id="om1")
    asyncio.run(job_entry_chat._launch_single_job_pipeline("oc1", "recY"))

    assert launches == [], "登记未注销（如重启遗留）时不应启动第二次评估"
    assert any("自动恢复" in t for _, t in patched_feishu.sent)


def test_launch_rejected_while_inflight_in_process(patched_feishu, monkeypatch):
    from app.automation import full_auto

    launches = []

    async def fake_launch(**kw):
        launches.append(kw)
        return {}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)
    epf._inflight_pipelines.add("recZ")
    try:
        asyncio.run(job_entry_chat._launch_single_job_pipeline("oc1", "recZ"))
    finally:
        epf._inflight_pipelines.discard("recZ")

    assert launches == []
    assert any("正在进行中" in t for _, t in patched_feishu.sent)


def test_launch_pipeline_card_contains_actual_company_and_job(patched_feishu, monkeypatch):
    from app.automation import full_auto

    async def fake_launch(**kw):
        return {"outcome": "stopped", "status": "简历人工复核"}

    monkeypatch.setattr(full_auto, "run_single_job_pipeline_async", fake_launch)

    asyncio.run(job_entry_chat._launch_single_job_pipeline("oc1", "recVip01"))

    # 验证首发的进度卡标题包含真实的“测试公司 · 测试岗位”，绝非“未知公司 · 未知岗位”
    assert len(patched_feishu.cards_sent) >= 1
    card_title = patched_feishu.cards_sent[0][1]["header"]["title"]["content"]
    assert "测试公司 · 测试岗位" in card_title
    assert "未知公司" not in card_title
