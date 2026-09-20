"""ChatAgent（工具循环 harness）测试。

覆盖：真 ReAct 循环（假模型脚本化 tool_calls → 真工具执行 → 最终回复）、
跨轮会话记忆（同 checkpointer 新实例恢复历史）、RunnableConfig 注入（工具拿到 chat_id）、
六件套工具的行为与回包格式。

外部边界（飞书读写、LLM、评估流水线）全部 Mock；循环与工具逻辑真实执行。
"""
import asyncio
import json

import aiosqlite
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.services.chat_agent import agent as chat_agent_mod
from app.services.chat_agent.tools import (
    check_evaluation_progress,
    edit_resume_json,
    locate_job,
    read_job_resume,
    start_evaluation,
    update_follow_status,
)


class FakeModel(GenericFakeChatModel):
    """脚本化模型：按序返回预设 AI 消息；bind_tools 原样返回自身（测试无需真绑定）。"""

    def bind_tools(self, tools, **kwargs):
        return self


def _tmp_saver():
    async def _make():
        import tempfile
        conn = await aiosqlite.connect(tempfile.mktemp(suffix=".db"))
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        return saver, conn
    return _make


def _run(coro):
    return asyncio.run(coro)


# ==========================================
# 真 ReAct 循环（假模型 + 真工具）
# ==========================================
def test_agent_loop_executes_tool_and_replies(monkeypatch):
    """模型发 tool_call → 工具真实执行（飞书写入被 Mock 捕获）→ 循环收敛出最终回复。"""
    written = []

    async def fake_update(table_id, record_id, fields):
        written.append((record_id, fields))

    from app.core import feishu_client as fcm
    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)

    model = FakeModel(messages=iter([
        AIMessage(content="", tool_calls=[{
            "name": "update_follow_status",
            "args": {"record_id": "recX", "status": "已投递", "set_delivery_date": True},
            "id": "c1",
        }]),
        AIMessage(content="已把岗位更新为「已投递」，投递日期已记录。"),
    ]))

    async def scenario():
        from langchain.agents import create_agent
        saver, conn = await _tmp_saver()()
        try:
            agent = create_agent(model=model, tools=[update_follow_status],
                                 system_prompt="test", checkpointer=saver)
            res = await agent.ainvoke(
                {"messages": [HumanMessage(content="唯品会那个岗位我投递完了，更新一下状态")]},
                config={"configurable": {"thread_id": "oc_loop"}},
            )
            return res, conn
        finally:
            await conn.close()

    res, _ = _run(scenario())

    assert written and written[0][0] == "recX", "工具应真实执行并触达 Mock 的写边界"
    assert written[0][1]["跟进状态"] == "已投递"
    assert isinstance(written[0][1]["投递日期"], int), "投递日期应为毫秒时间戳"
    assert "已投递" in res["messages"][-1].content, "循环应收敛出最终文本回复"


def test_cross_turn_memory_restored_from_checkpointer(monkeypatch):
    """同一 checkpointer、全新 agent 实例（模拟重启）：第二轮应看到第一轮历史。"""
    seen_history_lens = []

    class ProbingModel(FakeModel):
        def invoke(self, messages, **kw):
            seen_history_lens.append(len(messages))
            return super().invoke(messages, **kw)

    async def scenario():
        from langchain.agents import create_agent
        saver, conn = await _tmp_saver()()
        try:
            cfg = {"configurable": {"thread_id": "oc_mem"}}
            agent1 = create_agent(
                model=FakeModel(messages=iter([AIMessage(content="第一次的回答")])),
                tools=[], system_prompt="test", checkpointer=saver)
            await agent1.ainvoke({"messages": [HumanMessage(content="第一问")]}, config=cfg)

            agent2 = create_agent(
                model=ProbingModel(messages=iter([AIMessage(content="第二次的回答")])),
                tools=[], system_prompt="test", checkpointer=saver)
            res2 = await agent2.ainvoke({"messages": [HumanMessage(content="第二问")]}, config=cfg)
            return res2, conn
        finally:
            await conn.close()

    res2, _ = _run(scenario())
    human_texts = [m.content for m in res2["messages"] if isinstance(m, HumanMessage)]
    assert human_texts == ["第一问", "第二问"], "checkpointer 应恢复第一轮历史"


def test_agent_message_entry_not_ready(monkeypatch):
    """未初始化时 handle_agent_message 返回 False（调用方回退老链路）。"""
    monkeypatch.setattr(chat_agent_mod, "_agent_app", None)
    assert _run(chat_agent_mod.handle_agent_message("oc_x", "你好")) is False


# ==========================================
# 工具单测（config 注入 + 回包格式）
# ==========================================
def test_locate_job_tool(monkeypatch):
    from app.services import resume_edit_chat

    # 1. 单命中
    async def fake_cands_single(q):
        assert "唯品会" in q
        return [{"record_id": "recA", "company": "唯品会", "title": "AI产品运营", "status": "新线索", "score": 0.9}]

    monkeypatch.setattr(resume_edit_chat, "find_job_candidates", fake_cands_single)
    out = json.loads(_run(locate_job.ainvoke({"company": "唯品会", "job_title": "AI产品运营"})))
    assert out["found"] == 1 and out["record_id"] == "recA" and out["candidates"][0]["record_id"] == "recA"

    # 2. 多命中（自动推候选卡）
    sent_cards = []

    async def fake_cands_multi(q):
        return [
            {"record_id": "recA1", "company": "唯品会", "title": "AI产品运营1", "status": "新线索", "score": 0.9, "salary": "25-35K", "city": "广州"},
            {"record_id": "recA2", "company": "唯品会", "title": "AI产品运营2", "status": "面试中", "score": 0.8, "salary": "30-40K", "city": "深圳"},
        ]

    async def fake_send_card(chat_id, card):
        sent_cards.append((chat_id, card))
        return "msg_123"

    from app.core import feishu_messaging as fmsg
    monkeypatch.setattr(resume_edit_chat, "find_job_candidates", fake_cands_multi)
    monkeypatch.setattr(fmsg, "send_feishu_card", fake_send_card)

    cfg = {"configurable": {"thread_id": "oc_test_chat"}}
    out_multi = json.loads(_run(locate_job.ainvoke({"company": "唯品会"}, config=cfg)))

    assert out_multi["found"] == 2
    assert out_multi["card_sent"] is True
    assert "点击上方卡片选择" in out_multi["hint"]
    assert len(sent_cards) == 1 and sent_cards[0][0] == "oc_test_chat"
    card_elem0 = sent_cards[0][1]["elements"][0]
    assert card_elem0["extra"]["value"]["record_id"] == "recA1"
    assert "oc_test_chat" in resume_edit_chat._pending_locate


def test_read_job_resume_tool(monkeypatch):
    from app.core import feishu_client as fcm
    from app.core.config import settings

    async def fake_fetch(table_id, record_id):
        assert table_id == settings.FEISHU_TABLE_ID_JOBS
        return {"fields": {"公司名称": "唯品会", "岗位名称": "AI产品运营", "跟进状态": "已投递",
                            "AI改写JSON": json.dumps({"summary": "x"}, ensure_ascii=False)}}

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    out = json.loads(_run(read_job_resume.ainvoke({"record_id": "recA"})))
    assert out["company"] == "唯品会" and out["follow_status"] == "已投递"
    assert "summary" in out["resume_json"]


def test_edit_resume_json_tool_registers_session(monkeypatch):
    from app.services import resume_edit_chat

    base = {"summary": "旧总结"}
    edited = {"summary": "新总结"}

    async def fake_load(record_id):
        assert record_id == "recA"
        return dict(base)

    async def fake_llm(b, instruction):
        assert "改成新总结" in instruction
        return dict(edited)

    monkeypatch.setattr(resume_edit_chat, "_load_resume_base", fake_load)
    monkeypatch.setattr(resume_edit_chat, "_llm_edit_resume", fake_llm)

    out = json.loads(_run(edit_resume_json.ainvoke(
        {"record_id": "recA", "instruction": "把总结改成新总结"},
        config={"configurable": {"thread_id": "oc_edit"}},
    )))

    assert "个人总结" in out["diff"] or "summary" in out["diff"].lower(), "应返回改动摘要"
    assert "确认生成" in out["next"]
    session = resume_edit_chat._get_edit_session("oc_edit")
    assert session and session["record_id"] == "recA", "应登记待确认编辑会话"
    assert json.loads(session["updated"])["summary"] == "新总结"


def test_update_follow_status_tool(monkeypatch):
    from app.core import feishu_client as fcm

    written = []

    async def fake_update(table_id, record_id, fields):
        written.append(fields)

    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    out = json.loads(_run(update_follow_status.ainvoke(
        {"record_id": "recA", "status": "已投递", "set_delivery_date": True})))
    assert out["updated"] is True and out["delivery_date_set"] is True
    assert written[0]["跟进状态"] == "已投递"


def test_start_evaluation_tool(monkeypatch):
    from app.services import job_entry_chat as jec

    launched = []

    async def fake_launch(chat_id, record_id):
        launched.append((chat_id, record_id))

    monkeypatch.setattr(jec, "_launch_single_job_pipeline", fake_launch)

    async def scenario():
        out = await start_evaluation.ainvoke(
            {"record_id": "recEval"},
            config={"configurable": {"thread_id": "oc_eval"}},
        )
        for _ in range(5):  # 让 create_task 的后台任务跑起来
            await asyncio.sleep(0)
        return out

    out = json.loads(_run(scenario()))
    assert out["accepted"] is True
    assert launched == [("oc_eval", "recEval")], "评估应后台启动且带 chat_id"


def test_start_evaluation_rejects_duplicate(monkeypatch):
    from app.automation import inflight_registry as reg
    from app.services import job_entry_chat as jec

    launched = []

    async def fake_launch(chat_id, record_id):
        launched.append(record_id)

    monkeypatch.setattr(jec, "_launch_single_job_pipeline", fake_launch)
    reg.register("recBusy", chat_id="oc_x", card_msg_id="om_x")

    try:
        out = json.loads(_run(start_evaluation.ainvoke(
            {"record_id": "recBusy"},
            config={"configurable": {"thread_id": "oc_eval"}},
        )))
        assert out["accepted"] is False and "已有评估在跑" in out["reason"]
        assert launched == [], "重复评估不应启动"
    finally:
        reg.unregister("recBusy")


def test_check_evaluation_progress_tool(monkeypatch):
    from app.automation import inflight_registry as reg
    import time as _time
    from app.core import feishu_client as fcm

    reg.register("recProg", chat_id="oc_x", card_msg_id="om_x", started_epoch=_time.time() - 60)

    async def fake_fetch(table_id, record_id):
        return {"fields": {"跟进状态": "简历人工复核", "综合评级 (A-F)": "B"}}

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)

    try:
        out = json.loads(_run(check_evaluation_progress.ainvoke({"record_id": "recProg"})))
        assert out["stage"] == "评估中"
        assert 50 <= out["elapsed_seconds"] <= 120
        assert out["follow_status"] == "简历人工复核" and out["grade"] == "B"
    finally:
        reg.unregister("recProg")


# ==========================================
# 回复卡片化（interactive card + lark_md）
# ==========================================
def test_build_agent_reply_card():
    from app.services.chat_agent.card_builder import build_agent_reply_card

    text = "**唯品会** · AI产品运营\n- 薪资：25-35K\n- 城市：广州\n- 状态：新线索"
    card = build_agent_reply_card(text, title="🤖 测试助理")

    assert card["config"]["wide_screen_mode"] is True
    assert card["header"]["template"] == "blue"
    assert card["header"]["title"]["content"] == "🤖 测试助理"
    assert len(card["elements"]) == 1
    assert card["elements"][0]["tag"] == "div"
    assert card["elements"][0]["text"]["tag"] == "lark_md"
    assert card["elements"][0]["text"]["content"] == text


def test_build_agent_reply_card_splits_long_text():
    from app.services.chat_agent.card_builder import build_agent_reply_card

    # 制造 > 3500 字符的多行长文本
    long_text = "\n".join([f"第 {i} 行长文本描述..." * 20 for i in range(50)])
    card = build_agent_reply_card(long_text)

    assert len(card["elements"]) > 1
    for el in card["elements"]:
        assert el["tag"] == "div"
        assert el["text"]["tag"] == "lark_md"
        assert len(el["text"]["content"]) <= 3500


def test_send_agent_reply_with_fallback(monkeypatch):
    from app.core import feishu_messaging as fmsg
    from app.services.chat_agent.agent import send_agent_reply

    sent_cards = []
    sent_texts = []

    async def fake_card_fail(cid, card, **kw):
        sent_cards.append((cid, card))
        raise RuntimeError("Card syntax error")

    async def fake_text(cid, text, *args, **kw):
        sent_texts.append((cid, text))
        return True

    monkeypatch.setattr(fmsg, "send_feishu_card", fake_card_fail)
    monkeypatch.setattr(fmsg, "send_feishu_message", fake_text)

    _run(send_agent_reply("oc_fallback", "这是一条测试回复"))

    # 新契约：失败后先同幂等键重试一次（防超时双发），重试仍被拒绝才降级，且文字恰好一条
    assert len(sent_cards) == 2 and all(c[0] == "oc_fallback" for c in sent_cards)
    assert len(sent_texts) == 1 and sent_texts[0] == ("oc_fallback", "这是一条测试回复"), "重试仍失败时应降级为普通文本且不双发"


def test_handle_agent_message_sends_card(monkeypatch):
    from app.core import feishu_messaging as fmsg
    from app.services.chat_agent import agent as chat_agent_mod

    sent_cards = []
    sent_texts = []

    async def fake_card(cid, card, **kw):
        sent_cards.append((cid, card))
        return "msg_123"

    async def fake_text(cid, text, *args, **kw):
        sent_texts.append((cid, text))
        return True

    monkeypatch.setattr(fmsg, "send_feishu_card", fake_card)
    monkeypatch.setattr(fmsg, "send_feishu_message", fake_text)

    class MockApp:
        async def ainvoke(self, inp, config=None):
            return {"messages": [AIMessage(content="**唯品会** 岗位已找到，薪资 25-35K")]}

    monkeypatch.setattr(chat_agent_mod, "_agent_app", MockApp())

    res = _run(chat_agent_mod.handle_agent_message("oc_test_reply", "查一下唯品会"))

    assert res is True
    assert len(sent_cards) == 1
    assert sent_cards[0][0] == "oc_test_reply"
    assert "**唯品会**" in sent_cards[0][1]["elements"][0]["text"]["content"]


# ==========================================
# 状态驱动动作卡片测试
# ==========================================
def test_status_action_recommendations_coverage():
    from app.services.chat_agent.action_config import get_actions_for_status, STATUS_ACTION_RECOMMENDATIONS

    expected_statuses = [
        "新线索", "已完成初步评估", "已完成深度评估", "简历人工复核", "海投人工复核",
        "待投递", "已投递", "一面", "二面", "三面", "Offer"
    ]
    for st in expected_statuses:
        actions = get_actions_for_status(st)
        assert len(actions) >= 2, f"状态 [{st}] 应至少包含2个推荐动作"
        for act in actions:
            assert "label" in act and "action" in act


def test_build_status_action_elements():
    from app.services.chat_agent.action_config import build_status_action_elements

    elements = build_status_action_elements("一面", "recJob123")
    assert any(el.get("tag") == "hr" for el in elements)
    action_rows = [el for el in elements if el.get("tag") == "action"]
    assert len(action_rows) >= 1
    all_buttons = [b for row in action_rows for b in row.get("actions", [])]
    assert any("高频面试题预测" in b["text"]["content"] for b in all_buttons)
    assert any(b["value"].get("target_status") == "二面" for b in all_buttons)


def test_build_job_selected_card():
    from app.services.chat_agent.card_builder import build_job_selected_card

    job_info = {
        "company": "唯品会",
        "title": "AI产品运营",
        "salary": "25-35K",
        "city": "广州",
        "status": "简历人工复核",
        "platform": "BOSS直聘",
        "grade": "A",
    }
    card = build_job_selected_card(job_info, record_id="recVip01")
    assert card["header"]["title"]["content"] == "🎯 目标岗位已选定"
    content = card["elements"][0]["text"]["content"]
    assert "唯品会 · AI产品运营" in content
    assert "25-35K" in content and "广州" in content and "简历人工复核" in content
    
    # 验证挂载了对应的按钮（发送简历、微调、审批通过、手动投递）
    action_rows = [el for el in card["elements"] if el.get("tag") == "action"]
    all_buttons = [b for row in action_rows for b in row.get("actions", [])]
    assert any("发送简历" in b["text"]["content"] for b in all_buttons)
    assert any(b["value"].get("target_status") == "待投递" for b in all_buttons)


def test_handle_card_action_send_prompt(monkeypatch):
    from app.services import job_entry_chat as jec
    from app.services.chat_agent import agent as chat_agent_mod

    received_prompts = []

    async def fake_handle_agent_msg(cid, text):
        received_prompts.append((cid, text))
        return True

    monkeypatch.setattr(chat_agent_mod, "handle_agent_message", fake_handle_agent_msg)

    _run(jec.handle_card_action("oc_user", {
        "action": "send_prompt",
        "prompt": "查看该岗位的完整要求与JD原文",
        "record_id": "recPrompt01"
    }))

    assert len(received_prompts) == 1
    assert received_prompts[0] == ("oc_user", "查看该岗位的完整要求与JD原文")


def test_handle_card_action_update_status(monkeypatch):
    from app.services import job_entry_chat as jec
    from app.core import feishu_client as fcm
    from app.core import feishu_messaging as fmsg

    updated_records = []
    sent_cards = []

    def fake_update(rid, updates):
        updated_records.append((rid, updates))
        return True

    async def fake_fetch(tid, rid):
        return {"fields": {"公司名称": "广汽集团", "岗位名称": "数据分析", "跟进状态": "二面"}}

    async def fake_card(cid, card, **kw):
        sent_cards.append((cid, card))
        return "msg_ok"

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", fake_update)
    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(jec, "send_feishu_card", fake_card)
    monkeypatch.setattr(fmsg, "send_feishu_card", fake_card)

    _run(jec.handle_card_action("oc_user", {
        "action": "update_status",
        "target_status": "二面",
        "record_id": "recGAC"
    }))

    assert len(updated_records) == 1
    assert updated_records[0] == ("recGAC", {"跟进状态": "二面"})
    assert len(sent_cards) == 1
    assert "广汽集团" in sent_cards[0][1]["elements"][0]["text"]["content"]


def test_handle_card_action_send_materials_on_demand(monkeypatch):
    from app.services import job_entry_chat as jec
    from app.core import feishu_client as fcm

    sent_messages = []
    sent_images = []
    sent_files = []
    updated_records = []

    async def fake_fetch(tid, rid):
        return {
            "fields": {
                "公司名称": "谷雨护肤品",
                "岗位名称": "AI大模型运营",
                "打招呼语": "您好，我对该岗位很感兴趣",
                "AI改写JSON": json.dumps({"summary": "5年AI大模型电商运营", "workExperience": []}),
            }
        }

    async def fake_load_base(rid):
        return {"summary": "5年AI大模型电商运营", "workExperience": []}

    async def fake_merge_privacy(base):
        base["personalInfo"] = {"name": "张三", "phone": "13800138000"}
        return True

    async def fake_render(data, name):
        return {"pdf_token": "tok_pdf_1", "img_token": "tok_img_1", "name": name}

    async def fake_update_record(tid, rid, fields):
        updated_records.append((rid, fields))
        return {"code": 0}

    def fake_download(token, path):
        from pathlib import Path
        Path(path).write_bytes(b"dummy_bytes")
        return True

    async def fake_upload_img(b):
        return "img_key_123"

    async def fake_upload_file(b, n):
        return "file_key_123"

    async def fake_msg(cid, text, *a, **k):
        sent_messages.append((cid, text))
        return True

    async def fake_send_img(cid, ikey, *a, **k):
        sent_images.append((cid, ikey))
        return True

    async def fake_send_file(cid, fkey, *a, **k):
        sent_files.append((cid, fkey))
        return True

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update_record)
    monkeypatch.setattr("app.services.resume_edit_chat._load_resume_base", fake_load_base)
    monkeypatch.setattr("app.services.resume_edit_chat._merge_privacy", fake_merge_privacy)
    monkeypatch.setattr("app.automation.materials._render_custom_resume_materials", fake_render)
    monkeypatch.setattr("app.core.feishu_utils.download_feishu_file", fake_download)
    monkeypatch.setattr("app.core.feishu_messaging.upload_image_to_feishu", fake_upload_img)
    monkeypatch.setattr("app.core.feishu_messaging.upload_file_to_feishu", fake_upload_file)
    monkeypatch.setattr("app.core.feishu_messaging.send_feishu_image", fake_send_img)
    monkeypatch.setattr("app.core.feishu_messaging.send_feishu_file", fake_send_file)
    monkeypatch.setattr(jec, "send_feishu_message", fake_msg)

    _run(jec.handle_card_action("oc_user", {
        "action": "send_materials",
        "record_id": "recGuyu01"
    }))

    # 1. 验证打招呼语已发送
    assert any("打招呼语" in m[1] for m in sent_messages)
    # 2. 验证多维表格缺失物料时触发了自动回写与即时渲染
    assert len(updated_records) == 1
    assert updated_records[0][1]["PDF备份"][0]["file_token"] == "tok_pdf_1"
    # 3. 验证图片与 PDF 均已成功推送到飞书聊天
    assert len(sent_images) == 1 and sent_images[0] == ("oc_user", "img_key_123")
    assert len(sent_files) == 1 and sent_files[0] == ("oc_user", "file_key_123")


def test_read_job_resume_returns_full_fields(monkeypatch):
    from app.services.chat_agent import tools
    from app.core import feishu_client as fcm

    async def fake_fetch(tid, rid):
        return {
            "fields": {
                "公司名称": "谷雨护肤品",
                "岗位名称": "AI大模型运营",
                "岗位链接": "https://www.zhipin.com/job_detail/xyz.html",
                "招聘平台": "BOSS直聘",
                "薪资": "15-25K",
                "城市": "广州",
                "工作地址": "天河区珠江新城天盈广场",
                "公司规模": "500-999人",
                "所属行业": "美妆/日化",
                "综合评级 (A-F)": "A",
                "核心-角色匹配": "95",
                "高杠杆匹配点": "5年美妆电商客服大模型运营",
                "致命硬伤与毒点": "无明显硬伤",
                "破局行动计划": "突出多渠道知识库中台落地经验",
                "AI改写JSON": json.dumps({"summary": "5年经验"}),
            }
        }

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)

    res_str = _run(tools.read_job_resume.ainvoke({"record_id": "recGuyu01"}))
    res = json.loads(res_str)

    assert res["company"] == "谷雨护肤品"
    assert res["job_title"] == "AI大模型运营"
    assert res["job_link"] == "https://www.zhipin.com/job_detail/xyz.html"
    assert res["platform"] == "BOSS直聘"
    assert res["work_address"] == "天河区珠江新城天盈广场"
    assert res["company_scale"] == "500-999人"
    assert res["grade"] == "A"
    assert res["scores_8_dimensions"]["核心-角色匹配"] == "95"
    assert "多渠道知识库" in res["action_plan"]


def test_handle_agent_message_injects_focus_context(monkeypatch):
    from app.services.chat_agent import agent
    from app.core import feishu_client as fcm

    invoked_messages = []

    class FakeAgentApp:
        async def ainvoke(self, payload, config=None):
            invoked_messages.append(payload["messages"][0]["content"])
            class FakeMsg:
                content = "这是岗位的链接：https://www.zhipin.com/job/123"
            return {"messages": [FakeMsg()]}

    monkeypatch.setattr(agent, "_agent_app", FakeAgentApp())
    monkeypatch.setattr(agent, "send_agent_reply", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr("app.core.feishu_messaging.send_feishu_message", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr("app.services.resume_edit_chat._resolve_context_target", lambda cid: "recGuyu01")

    async def fake_fetch(tid, rid):
        return {
            "fields": {
                "公司名称": "谷雨护肤品",
                "岗位名称": "AI大模型运营",
                "跟进状态": "简历人工复核",
            }
        }

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)

    ok = _run(agent.handle_agent_message("oc_user", "给我这个岗位的链接"))
    assert ok is True
    assert len(invoked_messages) == 1
    # 验证系统焦点岗位上下文已成功注入给大模型
    assert "【当前焦点岗位上下文】" in invoked_messages[0]
    assert "谷雨护肤品 · AI大模型运营" in invoked_messages[0]
    assert "recGuyu01" in invoked_messages[0]
    assert "给我这个岗位的链接" in invoked_messages[0]


def test_query_company_intel_from_cache(monkeypatch):
    from app.services.chat_agent import tools
    from app.core import feishu_client as fcm

    async def fake_fetch(tid, rid):
        return {
            "fields": {
                "公司名称": "唯品会",
                "公司业务情报": "【唯品会 深度情报】\n1. 商业模式：特卖电商龙头\n2. AI应用：智能客服与精准选品",
            }
        }

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)

    res_str = _run(tools.query_company_intel.ainvoke({"record_id": "recVip01"}))
    res = json.loads(res_str)

    assert res["company"] == "唯品会"
    assert res["source"] == "bitable_cached"
    assert "特卖电商龙头" in res["intelligence"]


def test_query_company_intel_live_search_and_writeback(monkeypatch):
    from app.services.chat_agent import tools
    from app.core import feishu_client as fcm

    updated_records = []

    async def fake_fetch(tid, rid):
        return {
            "fields": {
                "公司名称": "小红书",
                "公司业务情报": "",  # 无缓存
            }
        }

    def fake_fetch_intel(cname):
        return f"【{cname} 商业情报】\n社区电商与大模型内容分发"

    def fake_update(rid, fields):
        updated_records.append((rid, fields))
        return True

    monkeypatch.setattr(fcm.feishu_client, "fetch_bitable_record_by_id", fake_fetch)
    monkeypatch.setattr("ai_agents.company_intel.fetch_company_intel", fake_fetch_intel)
    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", fake_update)

    res_str = _run(tools.query_company_intel.ainvoke({"record_id": "recXhs01"}))
    res = json.loads(res_str)

    assert res["company"] == "小红书"
    assert res["source"] == "live_web_search"
    assert "社区电商与大模型" in res["intelligence"]
    # 验证新搜到的情报自动回写多维表格
    assert len(updated_records) == 1
    assert "社区电商与大模型" in updated_records[0][1]["公司业务情报"]


def test_confirm_and_render_materials_tool(monkeypatch):
    from app.services.chat_agent import tools
    from app.services import resume_edit_chat

    # 预设一个待确认的编辑草案
    session_data = {
        "record_id": "recTest01",
        "stage": "confirm",
        "updated": json.dumps({"name": "张三", "summary": "强化PRD的总结"}, ensure_ascii=False),
        "orig": json.dumps({"name": "张三", "summary": "旧总结"}, ensure_ascii=False),
    }
    resume_edit_chat._set_edit_session("chat_test_01", session_data)

    rendered_calls = []

    async def fake_confirm_render(chat_id, session):
        rendered_calls.append((chat_id, session))

    monkeypatch.setattr(resume_edit_chat, "_confirm_and_render", fake_confirm_render)

    res_str = _run(tools.confirm_and_render_materials.ainvoke(
        {"record_id": "recTest01"},
        config={"configurable": {"chat_id": "chat_test_01"}},
    ))
    res = json.loads(res_str)

    assert res["success"] is True
    assert res["record_id"] == "recTest01"
    assert len(rendered_calls) == 1
    assert rendered_calls[0][0] == "chat_test_01"
    assert "强化PRD" in rendered_calls[0][1]["updated"]


def test_cancel_resume_edit_tool(monkeypatch):
    from app.services.chat_agent import tools
    from app.services import resume_edit_chat

    resume_edit_chat._set_edit_session("chat_test_02", {
        "record_id": "recTest02",
        "stage": "confirm",
        "updated": "{}",
        "orig": "{}",
    })

    res_str = _run(tools.cancel_resume_edit.ainvoke(
        {},
        config={"configurable": {"chat_id": "chat_test_02"}},
    ))
    res = json.loads(res_str)

    assert res["cancelled"] is True
    assert res["had_pending_session"] is True
    # 验证会话已被清除
    assert resume_edit_chat._get_edit_session("chat_test_02") is None



