"""2026-10-17：经历拷问切画像速览版 + 消息排布「稳定前缀优先」以命中网关前缀缓存。

网关前缀缓存只认字节级相同的消息前缀。本文件把这条约束固化为可回归的属性测试：
system 与首条 user 消息跨轮次、跨条目字节一致，历史只追加，轮次号不进前缀，
强制收束指令只在队尾。另验证 usage.cached_tokens 观测日志不因 usage 形态炸。
"""
import asyncio
import logging
from types import SimpleNamespace

from app.strategy import grill_service
from app.strategy.schemas import ChatMessage, GrillExperienceRequest

BRIEF = "- 硬技能：Python/SQL/LangChain\n- 软技能：跨部门协作\n- 业务经验：电商/医药\n- 加分项：RAG 落地"
HISTORY_T2 = [ChatMessage(role="assistant", content="Q1：这段经历的业务背景？"), ChatMessage(role="user", content="A1：给运营做周报自动化")]


def _payload(exp="做了个数据报表", history=None, turn=1, ctx=BRIEF, resume=None):
    return GrillExperienceRequest(
        original_experience=exp,
        chat_history=history or [],
        current_turn=turn,
        jd_report_context=ctx,
        full_resume_context=resume,
    )


def _messages(p: GrillExperienceRequest) -> list:
    return grill_service._build_grill_messages(p, grill_service._grill_system_prompt(grill_service._build_grill_context(p)))


# ---------- 前缀稳定性（缓存命中的充要条件） ----------

def test_first_two_messages_identical_across_turns():
    """同一条目：首轮与第二轮的 system + user 两条消息必须字节一致，历史只追加在其后。"""
    t1 = _messages(_payload())
    t2 = _messages(_payload(history=HISTORY_T2, turn=2))
    assert t1[:2] == t2[:2]
    assert len(t1) == 2, "首轮不得再追加「请开始」之类只出现一次的消息"
    assert t2[2:] == [{"role": m.role, "content": m.content} for m in HISTORY_T2]


def test_system_message_reused_across_items_sharing_profile():
    """不同经历条目共享同一画像时 system 消息完全相同——跨条目复用缓存；差异只落在 user 消息。"""
    a = _messages(_payload(exp="经历 A"))
    b = _messages(_payload(exp="经历 B"))
    assert a[0] == b[0]
    assert a[1] != b[1]


def test_turn_number_never_enters_prefix():
    """轮次号只用于触发收束，不得渗入前缀文本。"""
    assert _messages(_payload(turn=2)) == _messages(_payload(turn=3))


def test_forced_end_instruction_only_at_tail():
    t4 = _messages(_payload(history=HISTORY_T2, turn=4))
    assert t4[:2] == _messages(_payload())[:2]
    assert t4[-1]["role"] == "system" and "最高优先级强制指令" in t4[-1]["content"]
    assert sum("最高优先级强制指令" in m["content"] for m in t4) == 1


def test_system_prompt_carries_brief_and_opening_instruction():
    m = _messages(_payload())
    assert BRIEF in m[0]["content"]
    assert "直接抛出首个问题" in m[0]["content"], "开局指令必须固化在 system，才能让 user 消息跨轮一致"
    assert "请开始你的首次追问" not in m[1]["content"]
    assert m[1]["content"] == "这是我的原始经历：\n做了个数据报表"


def test_profile_absent_keeps_prefix_stable_too():
    """无画像时同样满足跨轮一致（简历库无画像的静默继续路径）。"""
    t1 = _messages(_payload(ctx=None))
    t2 = _messages(_payload(ctx=None, history=HISTORY_T2, turn=2))
    assert t1[:2] == t2[:2]
    assert "全局A级岗位能力报告" not in t1[0]["content"]


# ---------- 缓存命中观测 ----------

def test_cache_hit_logged_from_object_usage(caplog):
    usage = SimpleNamespace(prompt_tokens=1800, prompt_tokens_details=SimpleNamespace(cached_tokens=1536))
    with caplog.at_level(logging.INFO, logger="strategy_grill_service"):
        grill_service._log_prompt_cache_hit("t", usage, 2)
    assert "第 2 轮 prompt_tokens=1800 cached_tokens=1536" in caplog.text


def test_cache_hit_logged_from_dict_usage_and_tolerates_missing(caplog):
    with caplog.at_level(logging.INFO, logger="strategy_grill_service"):
        grill_service._log_prompt_cache_hit("t", {"prompt_tokens": 900, "prompt_tokens_details": {"cached_tokens": 0}}, 1)
        grill_service._log_prompt_cache_hit("t", {"prompt_tokens": 900}, 1)
        grill_service._log_prompt_cache_hit("t", SimpleNamespace(prompt_tokens=5), 1)
        grill_service._log_prompt_cache_hit("t", None, 1)
    assert caplog.text.count("cached_tokens=0") == 3


class _Chunk:
    def __init__(self, content=None, usage=None):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))] if content is not None else []
        self.usage = usage


class _Stream:
    def __init__(self, chunks):
        self._it = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._it)

    def close(self):
        self.closed = True


def test_stream_logs_cached_tokens_from_tail_chunk(monkeypatch, caplog):
    """网关在末块携带 usage 时，流式路径同样记录命中量；末块无 choices 不得炸。"""
    final = '{"question": "Q1", "suggested_options": ["a"], "is_finished": false, "blocks": []}'
    chunks = [_Chunk(final), _Chunk(usage=SimpleNamespace(prompt_tokens=2100, prompt_tokens_details=SimpleNamespace(cached_tokens=2048)))]
    completions = SimpleNamespace(create=lambda **kwargs: _Stream(chunks))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(grill_service, "_get_client", lambda: client)

    async def consume():
        events = []
        async for ev in grill_service.grill_experience_stream_service(_payload(history=HISTORY_T2, turn=2)):
            events.append(ev)
        return events

    with caplog.at_level(logging.INFO, logger="strategy_grill_service"):
        events = asyncio.run(consume())
    assert events[-1]["event"] == "final" and events[-1]["data"]["question"] == "Q1"
    assert "第 2 轮 prompt_tokens=2100 cached_tokens=2048" in caplog.text
