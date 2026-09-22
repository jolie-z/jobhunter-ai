"""简历库七项修复（2026-09-23）后端单测：错误翻译 / 解析内容保真 / 排版缓存。

全部 mock，不触网。被测模块在用例内 import（与 test_resume_structurer_progress.py
同一理由：避免 collection 期改变全量回归的全局初始化顺序）。
"""
import asyncio
import json

import pytest


# ---------------------------------------------------------------------------
# friendly_error：上游裸报错 → 人话（双层咽喉点 + 幂等 + 防泄漏）
# ---------------------------------------------------------------------------

def test_friendly_error_maps_billing():
    from app.core.error_messages import friendly_error
    msg = friendly_error("Error code: 402 - {'error': {'message': 'Insufficient Balance'}}")
    assert "余额不足" in msg


def test_friendly_error_maps_auth_and_timeout():
    from app.core.error_messages import friendly_error
    assert "鉴权失败" in friendly_error("Error code: 401 - Invalid API key")
    assert "超时" in friendly_error("Request timed out: HTTPSConnectionPool")


def test_friendly_error_is_idempotent():
    from app.core.error_messages import friendly_error
    once = friendly_error("Error code: 402 - Insufficient Balance")
    assert friendly_error(once) == once  # 第二层出口再过一遍不改写


def test_friendly_error_never_leaks_raw_text():
    """R3 审查要求：未识别错误（含内网 URL/堆栈/错误码）不得把原文片段带回用户文案。"""
    from app.core.error_messages import friendly_error
    raw = "ValueError: request to https://internal-gw.corp.example.com/v1/xyz failed with status 9182 [req_id: abc123]"
    msg = friendly_error(raw)
    assert "internal-gw" not in msg
    assert "9182" not in msg
    assert "abc123" not in msg
    assert msg  # 且文案非空


def test_friendly_error_handles_empty():
    from app.core.error_messages import friendly_error
    assert friendly_error(None)
    assert friendly_error("")


# ---------------------------------------------------------------------------
# resume_structurer：skillOverview 承接 / extra 不静默丢弃 / bullet 渲染保真
# ---------------------------------------------------------------------------

def test_additional_skill_overview_rendered():
    from app.core.resume_structurer import json_to_markdown
    md = json_to_markdown({
        "moduleOrder": ["additional"],
        "moduleTitles": {"additional": "专业技能"},
        "additional": {
            "skillOverview": "八年后端开发经验，擅长高并发与稳定性建设。",
            "technicalSkills": ["Python", "Go"],
        },
    })
    assert "八年后端开发经验，擅长高并发与稳定性建设。" in md
    assert "Python / Go" in md


def test_additional_without_overview_keeps_legacy_render():
    """旧数据（无 skillOverview 字段）渲染不变。"""
    from app.core.resume_structurer import json_to_markdown
    md = json_to_markdown({
        "moduleOrder": ["additional"],
        "moduleTitles": {"additional": "专业技能"},
        "additional": {"technicalSkills": ["A", "B"]},
    })
    assert md.strip() == "# 专业技能\nA / B"


def test_render_desc_line_bullet_fidelity():
    from app.core.resume_structurer import _render_desc_line
    assert _render_desc_line("• 主导性能优化") == "- 主导性能优化"
    assert _render_desc_line("* 主导性能优化") == "- 主导性能优化"
    assert _render_desc_line("- 已有短横线") == "- 已有短横线"
    assert _render_desc_line("**加粗小标题**") == "**加粗小标题**"
    assert _render_desc_line("纯文本") == "- 纯文本"
    assert _render_desc_line("") == ""


def test_model_validate_preserves_extra_fields():
    """LLM 自带的未知字段不再被静默丢弃（extra=allow）。"""
    from app.core.resume_structurer import ResumeData
    data = ResumeData.model_validate({
        "summary": "s",
        "awards": [{"title": "x"}],  # schema 外字段
    })
    dumped = data.model_dump()
    assert dumped.get("awards") == [{"title": "x"}]


# ---------------------------------------------------------------------------
# format_markdown_service：同内容缓存命中不再重复调 LLM
# ---------------------------------------------------------------------------

class _FormatCompletions:
    def __init__(self, calls_ref):
        self._calls = calls_ref

    def create(self, **kwargs):
        self._calls["n"] += 1
        resp = type("R", (), {})()
        resp.choices = [type("C", (), {})()]
        resp.choices[0].message = type("M", (), {})()
        resp.choices[0].message.content = "**已排版**"
        return resp


@pytest.fixture
def fake_format_client(monkeypatch):
    """记录 LLM 调用次数并固定返回；每次用例重置模块级排版缓存。"""
    from app.strategy import format_service
    calls = {"n": 0}
    client = type("FakeClient", (), {})()
    client.chat = type("Chat", (), {})()
    client.chat.completions = _FormatCompletions(calls)
    monkeypatch.setattr(format_service, "_get_client", lambda: client)
    with format_service._format_cache_lock:
        format_service._format_cache.clear()
    return calls


def test_format_markdown_cache_hit(fake_format_client):
    from app.strategy import format_service
    from app.strategy.schemas import FormatMarkdownRequest
    payload = FormatMarkdownRequest(module_title="工作经历", current_content="- 负责核心系统开发")
    first = asyncio.run(format_service.format_markdown_service(payload))
    second = asyncio.run(format_service.format_markdown_service(payload))
    assert first["formatted_content"] == "**已排版**"
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["formatted_content"] == "**已排版**"
    assert fake_format_client["n"] == 1  # 第二次命中缓存，LLM 只被调一次


def test_format_markdown_cache_key_distinguishes_content(fake_format_client):
    """不同内容不命中彼此的缓存（键含 content）。"""
    from app.strategy import format_service
    from app.strategy.schemas import FormatMarkdownRequest
    p1 = FormatMarkdownRequest(module_title="工作经历", current_content="- 内容甲")
    p2 = FormatMarkdownRequest(module_title="工作经历", current_content="- 内容乙")
    asyncio.run(format_service.format_markdown_service(p1))
    second = asyncio.run(format_service.format_markdown_service(p2))
    assert second["cached"] is False
    assert fake_format_client["n"] == 2


# ---------------------------------------------------------------------------
# R1 审查修复回归：数字词边界 / prompt 版本绑定 / extra 模块兜底渲染 / grill SSE 事件序列
# ---------------------------------------------------------------------------

def test_friendly_error_digit_boundary_no_false_billing():
    """'requested 40251 tokens'（超长上下文 400 错）不得命中 '402' 误判成余额不足。"""
    from app.core.error_messages import friendly_error
    msg = friendly_error("This model's maximum context length is 32768 tokens, you requested 40251 tokens")
    assert "余额" not in msg
    msg2 = friendly_error("gateway error upstream returned 5003 after 1500ms retries")
    assert "余额" not in msg2
    from app.core.error_messages import _KNOWN_FRIENDLY
    assert msg2 in _KNOWN_FRIENDLY  # 未识别错误精确落到本模块固定兜底文案
    # 真正的状态码仍要命中
    assert "余额不足" in friendly_error("Error code: 402 - Insufficient Balance")
    assert "网关" in friendly_error("HTTP 502 Bad Gateway from upstream")


def test_format_prompt_version_binds_to_prompt_text():
    """FORMAT_PROMPT_VERSION 必须与排版 prompt 文本绑定：改 prompt 不 bump 版本会让
    缓存在 24h 内静默返回旧结果。本测试把 v1 与 prompt hash 锁死——改 prompt 时
    请同步 bump FORMAT_PROMPT_VERSION 并更新此处的 hash。"""
    import hashlib
    from app.strategy.format_service import FORMAT_PROMPT_VERSION, FORMAT_SYSTEM_PROMPT
    digest = hashlib.sha256(FORMAT_SYSTEM_PROMPT.encode()).hexdigest()
    if FORMAT_PROMPT_VERSION == "v1":
        assert digest == "e5b06eb574cbb47959aeac912fc243d5a4fab80aadf99807e6bf70b511c3a17d", (
            f"排版 prompt 已改动但 FORMAT_PROMPT_VERSION 仍为 v1（prompt 开头：{FORMAT_SYSTEM_PROMPT[:40]!r}）："
            "请 bump 版本并更新本测试 hash"
        )


def test_unconsumed_extra_modules_rendered_as_fallback():
    """extra=allow 保留的 schema 外顶层模块要有兜底渲染，不能只烂在 JSON 里。"""
    from app.core.resume_structurer import json_to_markdown
    md = json_to_markdown({
        "moduleOrder": ["summary"],
        "moduleTitles": {"summary": "个人总结", "awards": "获奖经历"},
        "summary": "s",
        "awards": [{"title": "最佳员工", "years": "2024"}],
    })
    assert "# 获奖经历" in md
    assert "最佳员工" in md


# ---------------------------------------------------------------------------
# grill SSE 事件序列（跨线程流式 + 取消贯通）
# ---------------------------------------------------------------------------

class _StreamChunk:
    def __init__(self, content):
        self.choices = [type("C", (), {})()]
        self.choices[0].delta = type("D", (), {})()
        self.choices[0].delta.content = content


class _FakeStream:
    """带 close 标记的假流：可断言取消路径真的调用了 stream.close()（R2 审查 H3）。"""
    def __init__(self, pieces):
        self._iter = iter(pieces)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)

    def close(self):
        self.closed = True


class _StreamCompletionsForGrill:
    def __init__(self, pieces, calls_ref):
        self._pieces = pieces
        self._calls = calls_ref
        self.last_stream = None

    def create(self, **kwargs):
        self._calls["n"] += 1
        assert kwargs.get("stream") is True
        self.last_stream = _FakeStream([_StreamChunk(p) for p in self._pieces])
        return self.last_stream


@pytest.fixture
def fake_grill_stream(monkeypatch):
    from app.strategy import grill_service
    calls = {"n": 0}
    completions = _StreamCompletionsForGrill(
        ['{"question": "Q1", "suggested_options": ["a"], "is_finished": false, "blocks": []}'],
        calls,
    )
    client = type("FakeClient", (), {})()
    client.chat = type("Chat", (), {})()
    client.chat.completions = completions
    monkeypatch.setattr(grill_service, "_get_client", lambda: client)
    return {"calls": calls, "completions": completions}


def test_grill_stream_emits_final_event(fake_grill_stream):
    """正常路径：线程流式输出 → 生成器收到 final 事件（数据与 REST 版一致）→ 迭代自然终止。"""
    from app.strategy import grill_service
    from app.strategy.schemas import GrillExperienceRequest
    payload = GrillExperienceRequest(
        original_experience="经历原文",
        chat_history=[],
        current_turn=1,
        jd_report_context="",
        full_resume_context="",
    )

    async def consume():
        events = []
        async for ev in grill_service.grill_experience_stream_service(payload):
            events.append(ev)
        return events

    events = asyncio.run(consume())
    finals = [e for e in events if e["event"] == "final"]
    assert len(finals) == 1
    assert finals[0]["data"]["question"] == "Q1"
    assert fake_grill_stream["calls"]["n"] == 1
    assert fake_grill_stream["completions"].last_stream.closed is True  # 正常结束也关闭上游流


def test_grill_stream_cancel_stops_iteration(fake_grill_stream):
    """取消贯通：生成器被提前关闭（客户端断开）→ finally 置位 cancel_event →
    上游流被 close（停止计费）。限 5 秒防回归成永挂（R2 审查 H3 可证伪化）。"""
    from app.strategy import grill_service
    from app.strategy.schemas import GrillExperienceRequest
    payload = GrillExperienceRequest(
        original_experience="经历原文",
        chat_history=[],
        current_turn=1,
        jd_report_context="",
        full_resume_context="",
    )

    async def consume_and_close():
        agen = grill_service.grill_experience_stream_service(payload)
        await anext(agen)      # 拿首个事件（stage 或 final）
        await agen.aclose()    # 模拟客户端断开触发 finally

    asyncio.run(asyncio.wait_for(consume_and_close(), timeout=5.0))
    assert fake_grill_stream["completions"].last_stream.closed is True
