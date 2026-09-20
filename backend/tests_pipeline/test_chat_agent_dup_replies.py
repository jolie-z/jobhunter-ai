"""ChatAgent「agent 反复重复回复」复核测试（diagnosing-bugs Phase 1 反馈回路）。

针对三个已定位的重复回复漏洞，各给一个 red-capable 断言：
1. confirm_and_render_materials 工具异常路径引用未定义的 logger → NameError
   → LangGraph 把异常回喂模型 → 模型重试工具 → 每次重试都重新渲染并重发物料（重复回复）。
2. handle_agent_message 无 per-chat 并发锁 → 同会话两条投递（卡片回调重放/重启后事件重投）
   并发跑两个 agent → 同一问题两条回复。
3. locate_job 多候选卡片 10s 节流（f6dec5a 已修）——验证该修复在本轮复核下仍然成立。
"""
import asyncio
import json
import time

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.services.chat_agent import agent as chat_agent
from app.services.chat_agent import tools as chat_tools
from app.services import resume_edit_chat


async def _async_ok(bucket):
    bucket.append(1)
    return True


# ==========================================
# 1) confirm_and_render_materials 异常路径不应 NameError
# ==========================================
def test_confirm_render_tool_error_returns_error_json_not_nameerror(monkeypatch):
    """_confirm_and_render 失败时，工具应返回 {"error": ...} JSON，而不是抛 NameError。

    NameError 会让 LangGraph 以异常回喂模型 → 模型重试 confirm_and_render_materials
    → 每次重试都重新渲染物料并重发聊天框 → 用户收到 N 份重复物料（复现「反复重复回复」）。
    """
    session = {
        "record_id": "recConfirm1",
        "stage": "confirm",
        "updated": json.dumps({"summary": "x"}, ensure_ascii=False),
        "orig": json.dumps({"summary": "x"}, ensure_ascii=False),
    }
    monkeypatch.setattr(resume_edit_chat, "_get_edit_session", lambda chat_id: session)

    async def boom(chat_id, sess):
        raise RuntimeError("render pipeline failed")

    monkeypatch.setattr(resume_edit_chat, "_confirm_and_render", boom)

    async def run():
        return await chat_tools.confirm_and_render_materials.ainvoke(
            {"record_id": "recConfirm1"}, config={"configurable": {"thread_id": "chat_confirm_test"}}
        )

    result = asyncio.run(run())

    payload = json.loads(result)
    assert "error" in payload, f"工具异常应折叠为 error JSON，实际返回: {result!r}"


# ==========================================
# 2) 同会话并发投递不应产生并发 agent 运行（重复回复源）
# ==========================================
class _FakeAgentApp:
    """模拟 agent 图：跑 0.4s，记录进入/退出时间，返回固定回复。"""

    def __init__(self, runs):
        self._runs = runs

    async def ainvoke(self, input, config=None, **kw):
        enter = time.monotonic()
        entry = {"enter": enter, "exit": None}
        self._runs.append(entry)
        await asyncio.sleep(0.4)
        entry["exit"] = time.monotonic()
        return {"messages": [AIMessage(content="回复内容")]}


def test_same_chat_concurrent_deliveries_do_not_overlap(monkeypatch):
    """卡片回调重放 / 重启后事件重投会绕过 message_id 防重锁。

    两次并发 handle_agent_message 必须被 per-chat 锁串行化，否则同一问题出现两条回复。
    """
    runs = []
    monkeypatch.setattr(chat_agent, "_agent_app", _FakeAgentApp(runs))

    from app.core import feishu_messaging as fm

    sent_cards, sent_texts = [], []
    monkeypatch.setattr(fm, "send_feishu_card", lambda *a, **kw: _async_ok(sent_cards))
    monkeypatch.setattr(fm, "send_feishu_message", lambda *a, **kw: _async_ok(sent_texts))

    async def run():
        await asyncio.gather(
            chat_agent.handle_agent_message("chat_dup_test", "查看该岗位的完整要求与JD原文"),
            asyncio.sleep(0.02),  # 模拟回调/重投稍晚到达
            chat_agent.handle_agent_message("chat_dup_test", "查看该岗位的完整要求与JD原文"),
        )

    asyncio.run(run())

    assert len(runs) == 2, "两次投递都应被处理（本测试关注是否重叠，不吞消息）"
    first, second = runs
    # 串行化判定：第二个运行不得在第一个运行结束前进入
    assert second["enter"] >= first["exit"], (
        "同会话两个 agent 运行发生了并发重叠 —— 并发投递（卡片回调重放/重启重投）"
        f"会各产出一条回复，形成重复回复。runs={runs}"
    )


# ==========================================
# 3) f6dec5a 已修：locate_job 多候选卡片 10s 节流
# ==========================================
def test_locate_job_card_throttle_holds_within_10s(monkeypatch):
    """f6dec5a 修复复核：10 秒内同一 chat_id 第二次 locate_job 不得重发候选卡片。"""
    chat_tools._locate_card_sent_ts.clear()
    resume_edit_chat._pending_locate.clear()

    cands = [
        {"record_id": "recA", "company": "甲公司", "title": "产品经理", "status": "新线索",
         "salary": "", "city": "", "platform": "", "grade": "", "score": 0.5},
        {"record_id": "recB", "company": "甲公司二", "title": "产品经理2", "status": "新线索",
         "salary": "", "city": "", "platform": "", "grade": "", "score": 0.45},
    ]

    async def fake_cands(query, top_n=5):
        return [dict(c) for c in cands]

    monkeypatch.setattr(resume_edit_chat, "find_job_candidates", fake_cands)

    cards_sent = []

    async def fake_card(chat_id, card, receive_id_type="chat_id"):
        cards_sent.append(card)
        return True

    import app.core.feishu_messaging as fm
    monkeypatch.setattr(fm, "send_feishu_card", fake_card)

    cfg = RunnableConfig(configurable={"thread_id": "chat_locate_throttle"})

    async def run():
        await chat_tools.locate_job.ainvoke({"company": "甲公司"}, config=cfg)
        await chat_tools.locate_job.ainvoke({"company": "甲公司"}, config=cfg)

    asyncio.run(run())

    assert len(cards_sent) == 1, (
        f"10 秒内重复 locate_job 不应重发候选卡片（f6dec5a 节流失效），实发 {len(cards_sent)} 张"
    )


# ==========================================
# 4) 循环熔断守卫（本轮新增根治层）
# ==========================================
def test_loop_guard_blocks_consecutive_identical_calls():
    """只读工具：同参数连续调用 2 次放行，第 3 次熔断；不同参数不受影响。"""
    from langchain_core.tools import tool as tool_decorator

    chat_tools.reset_loop_guard("chat_guard_1")

    @tool_decorator
    async def dummy_reader(query: str, config: RunnableConfig = None) -> str:
        """读取测试数据。"""
        return '{"ok": true}'

    guarded = chat_tools.guard_tool_loop(dummy_reader)
    cfg = {"configurable": {"thread_id": "chat_guard_1"}}

    async def run():
        r1 = await guarded.ainvoke({"query": "查卡尔"}, config=cfg)
        r2 = await guarded.ainvoke({"query": "查卡尔"}, config=cfg)
        r3 = await guarded.ainvoke({"query": "查卡尔"}, config=cfg)
        r4 = await guarded.ainvoke({"query": "查唯品会"}, config=cfg)
        return r1, r2, r3, r4

    r1, r2, r3, r4 = asyncio.run(run())

    assert '"loop_guarded"' not in r1 and '"loop_guarded"' not in r2, "前两次相同调用应放行"
    assert '"loop_guarded": true' in r3, "第 3 次相同调用必须被熔断"
    assert '"loop_guarded"' not in r4, "换参数后不应被误熔断"


def test_loop_guard_write_tool_blocked_on_second_call(monkeypatch):
    """写副作用工具（如 confirm_and_render_materials）：第 2 次相同调用即熔断，杜绝重复交付。"""
    from langchain_core.tools import tool as tool_decorator

    chat_tools.reset_loop_guard("chat_guard_w")
    monkeypatch.setattr(chat_tools, "_LOOP_TOOLS_WRITE", {"dummy_writer"})

    @tool_decorator
    async def dummy_writer(record_id: str, config: RunnableConfig = None) -> str:
        """写入测试数据。"""
        return '{"success": true}'

    guarded = chat_tools.guard_tool_loop(dummy_writer)
    cfg = {"configurable": {"thread_id": "chat_guard_w"}}

    async def run():
        r1 = await guarded.ainvoke({"record_id": "recX"}, config=cfg)
        r2 = await guarded.ainvoke({"record_id": "recX"}, config=cfg)
        return r1, r2

    r1, r2 = asyncio.run(run())

    assert '"loop_guarded"' not in r1, "写工具首次调用应放行"
    assert '"loop_guarded": true' in r2, "写工具第 2 次相同调用必须熔断（重复执行=重复交付）"


def test_loop_guard_reset_between_turns():
    """每轮用户消息重置熔断历史：上一轮被熔断的调用，新轮次应重新放行。"""
    chat_tools.reset_loop_guard("chat_guard_r")
    sig = chat_tools._call_signature("read_job_resume", {"record_id": "rec1"})
    assert not chat_tools._loop_guard_should_block("chat_guard_r", "read_job_resume", sig)
    assert not chat_tools._loop_guard_should_block("chat_guard_r", "read_job_resume", sig)
    assert chat_tools._loop_guard_should_block("chat_guard_r", "read_job_resume", sig), "同轮第 3 次应熔断"

    chat_tools.reset_loop_guard("chat_guard_r")  # 新一轮
    assert not chat_tools._loop_guard_should_block("chat_guard_r", "read_job_resume", sig), "新一轮相同调用应重新放行"


# ==========================================
# 5) 卡片动作节流（send_prompt 双击/回调重放防重）
# ==========================================
def test_card_action_send_prompt_throttled(monkeypatch):
    """15 秒内同一 chat 同一 prompt 的 send_prompt 只放行一次，第二次直接忽略。"""
    from app.services import job_entry_chat

    job_entry_chat._CARD_ACTION_TS.clear()
    agent_calls = []

    async def fake_agent(chat_id: str, text: str):
        agent_calls.append(text)

    monkeypatch.setattr("app.services.chat_agent.agent.handle_agent_message", fake_agent)

    async def run():
        await job_entry_chat.handle_card_action(
            "chat_sp_throttle", {"action": "send_prompt", "record_id": "recSP1", "prompt": "查看该岗位的完整要求与JD原文"})
        await job_entry_chat.handle_card_action(
            "chat_sp_throttle", {"action": "send_prompt", "record_id": "recSP1", "prompt": "查看该岗位的完整要求与JD原文"})

    asyncio.run(run())

    assert len(agent_calls) == 1, f"重放/双击 send_prompt 不应二次触发 agent，实际触发 {len(agent_calls)} 次"


def test_card_action_update_status_throttled(monkeypatch):
    """10 秒内同一 chat 同一岗位同一目标状态的 update_status 只执行一次。"""
    from app.services import job_entry_chat

    job_entry_chat._CARD_ACTION_TS.clear()
    updates = []

    def fake_update(record_id, fields_update):
        updates.append(fields_update)
        return {"code": 0}

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", fake_update)

    async def fake_fetch(table_id, record_id):
        return {"fields": {"公司名称": "节流公司", "岗位名称": "节流岗位"}}

    monkeypatch.setattr("app.core.feishu_client.feishu_client.fetch_bitable_record_by_id", fake_fetch)

    cards_sent = []

    async def fake_card(receive_id, card, receive_id_type="chat_id"):
        cards_sent.append(card)
        return True

    monkeypatch.setattr("app.core.feishu_messaging.send_feishu_card", fake_card)

    value = {"action": "update_status", "record_id": "recUS1", "target_status": "已投递"}

    async def run():
        await job_entry_chat.handle_card_action("chat_us_throttle", value)
        await job_entry_chat.handle_card_action("chat_us_throttle", value)

    asyncio.run(run())

    assert len(updates) == 1, f"重放 update_status 不应二次写表，实际写 {len(updates)} 次"


# ==========================================
# 6) 防重锁持久化（重启后仍拦截飞书重投）
# ==========================================
def test_msg_dedup_survives_process_restart(tmp_path, monkeypatch):
    """模拟重启：清空内存态后从磁盘恢复，同一 message_id 仍应被拦截。"""
    from app.core import feishu_msg_dedup

    persist = tmp_path / "feishu_seen_msg_ids.json"
    monkeypatch.setattr(feishu_msg_dedup, "_PERSIST_PATH", persist)

    monkeypatch.setattr(feishu_msg_dedup, "_seen", feishu_msg_dedup.OrderedDict())
    monkeypatch.setattr(feishu_msg_dedup, "_loaded", False)
    assert feishu_msg_dedup.check_and_mark("om_restart_dup_1") is True
    assert persist.exists(), "标记后应落盘"

    # 模拟进程重启：内存态全失，仅磁盘留有记录
    monkeypatch.setattr(feishu_msg_dedup, "_seen", feishu_msg_dedup.OrderedDict())
    monkeypatch.setattr(feishu_msg_dedup, "_loaded", False)
    assert feishu_msg_dedup.check_and_mark("om_restart_dup_1") is False, "重启后飞书重投必须仍被拦截"
    assert feishu_msg_dedup.check_and_mark("om_restart_new_1") is True, "新消息不受影响"


def test_msg_dedup_lru_eviction_no_full_clear(tmp_path, monkeypatch):
    """超限淘汰只逐出最旧条目，绝不整表清空（旧实现的防重真空期已消除）。"""
    from app.core import feishu_msg_dedup

    monkeypatch.setattr(feishu_msg_dedup, "_PERSIST_PATH", tmp_path / "feishu_seen_lru.json")
    monkeypatch.setattr(feishu_msg_dedup, "_seen", feishu_msg_dedup.OrderedDict())
    monkeypatch.setattr(feishu_msg_dedup, "_loaded", False)
    monkeypatch.setattr(feishu_msg_dedup, "_MAX_SEEN", 3)

    assert feishu_msg_dedup.check_and_mark("om_lru_1") is True
    feishu_msg_dedup.check_and_mark("om_lru_2")
    feishu_msg_dedup.check_and_mark("om_lru_3")
    feishu_msg_dedup.check_and_mark("om_lru_4")  # 触发淘汰，只逐出最旧的 om_lru_1

    assert feishu_msg_dedup.check_and_mark("om_lru_2") is False, "未逐出的条目必须仍被防重保护"
    assert feishu_msg_dedup.check_and_mark("om_lru_3") is False
    assert feishu_msg_dedup.check_and_mark("om_lru_4") is False
    # 注意：上面 check 未命中不会改淘汰顺序；重新标记 om_lru_1 会按 LRU 逐出 om_lru_2
    assert feishu_msg_dedup.check_and_mark("om_lru_1") is True, "最旧条目被逐出后可重新处理"


# ==========================================
# 7) 回复发送幂等：卡片超时重试不双发，明确拒绝才降级文字
# ==========================================
def test_agent_reply_card_timeout_retries_same_key_no_double(monkeypatch):
    """卡片首次发送超时（飞书可能已收下）：必须用同一幂等键重试同一张卡，
    成功后不得再发降级文字——否则用户收到「卡+文」双份。"""
    from app.core import feishu_messaging as fm

    card_calls, text_calls = [], []

    async def flaky_card(receive_id, card, receive_id_type="chat_id", idempotency_key=None):
        card_calls.append(idempotency_key)
        if len(card_calls) == 1:
            raise TimeoutError("simulated read timeout after feishu accepted")
        return "om_fake_1"

    async def fake_text(receive_id, text, receive_id_type="open_id", **kw):
        text_calls.append(text)
        return True

    monkeypatch.setattr(fm, "send_feishu_card", flaky_card)
    monkeypatch.setattr(fm, "send_feishu_message", fake_text)

    asyncio.run(chat_agent.send_agent_reply("chat_idem_1", "答案内容"))

    assert len(card_calls) == 2, f"超时后应恰好重试一次，实际调用 {len(card_calls)} 次"
    assert card_calls[0] and card_calls[0] == card_calls[1], "两次尝试必须携带同一幂等键（uuid）"
    assert text_calls == [], "重试成功后严禁再发降级文字（卡+文双份）"


def test_agent_reply_card_rejected_falls_back_to_text_once(monkeypatch):
    """卡片被飞书明确拒绝（重试同样拒绝）：降级为恰好一条纯文本。"""
    from app.core import feishu_messaging as fm

    card_calls, text_calls = [], []

    async def reject_card(receive_id, card, receive_id_type="chat_id", idempotency_key=None):
        card_calls.append(idempotency_key)
        raise RuntimeError("simulated card rejected: invalid card format")

    async def fake_text(receive_id, text, receive_id_type="open_id", **kw):
        text_calls.append(text)
        return True

    monkeypatch.setattr(fm, "send_feishu_card", reject_card)
    monkeypatch.setattr(fm, "send_feishu_message", fake_text)

    asyncio.run(chat_agent.send_agent_reply("chat_idem_2", "答案内容"))

    assert len(card_calls) == 2, "拒绝后应先同幂等键重试一次再降级"
    assert card_calls[0] == card_calls[1]
    assert len(text_calls) == 1, f"降级文字必须恰好一条，实际 {len(text_calls)} 条"


def test_message_send_url_includes_uuid_param():
    """发消息 URL 的幂等参数拼装：带键时追加 uuid=，不带键时保持原样。"""
    from app.core.feishu_messaging import _message_send_url

    base = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
    assert _message_send_url("chat_id") == base
    url = _message_send_url("chat_id", "abc-123")
    assert url == f"{base}&uuid=abc-123"
