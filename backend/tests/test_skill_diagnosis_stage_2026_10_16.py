"""2026-10-16 复核修复：异步 Skill 改写通道「诊断阶段」SSE 文案四态 + 单轮引擎 usage 事件。

背景：worker 此前无条件推「🩺 岗位深度诊断上下文就绪」，简历库模式/纯净模式/未诊断岗位
三种情形都在说假话；单轮引擎的 usage 事件因 usage_dict 先用后定义被 except 静默吞掉从未发出。
"""
from types import SimpleNamespace

from ai_agents.skill_rewrite import (
    diagnosis_has_content,
    format_diagnosis_context,
    run_skill_based_rewrite,
)
from app.strategy.routes.skill_agent_router import _diagnosis_stage_message

_EMPTY_SIX_FIELDS = {
    "dream_picture": "",
    "ats_ability_analysis": "",
    "resume_audit": "",
    "strong_fit_assessment": "",
    "risk_red_flags": "",
    "deep_action_plan": "",
}


# ---------- 判空口径（Prompt 注入侧与 SSE 文案侧同源） ----------

def test_diagnosis_has_content_strip_semantics():
    assert diagnosis_has_content(None) is False
    assert diagnosis_has_content({}) is False
    assert diagnosis_has_content(_EMPTY_SIX_FIELDS) is False, "未诊断岗位退回的 6 空串字段必须判空"
    assert diagnosis_has_content({"dream_picture": "   \n"}) is False, "纯空白不算内容"
    assert diagnosis_has_content({"dream_picture": None, "risk_red_flags": "  "}) is False
    assert diagnosis_has_content({**_EMPTY_SIX_FIELDS, "risk_red_flags": "忌空话"}) is True
    assert diagnosis_has_content({"custom": {"nested": "x"}}) is True, "合成报告 JSON 的嵌套值视为有内容"


def test_format_diagnosis_context_whitespace_only_not_injected():
    """旧口径 any(bool(v)) 对纯空白值判「有」，再因各节 strip 为空走兜底 JSON dump——
    把一坨空白注入 Prompt。新口径与 diagnosis_has_content 同源，直接返回空串。"""
    assert format_diagnosis_context({"dream_picture": "   "}) == ""
    assert format_diagnosis_context(_EMPTY_SIX_FIELDS) == ""
    assert "忌空话" in format_diagnosis_context({"risk_red_flags": "忌空话"})


# ---------- 四态文案 ----------

def test_stage_message_resume_library_mode():
    msg = _diagnosis_stage_message("recResume123", True, {"risk_red_flags": "有内容也不该说就绪"})
    assert msg.startswith("📄 简历库模式")
    assert "就绪" not in msg


def test_stage_message_resume_mode_precedes_pure_mode():
    """简历库模式根本不加载诊断，优先级高于纯净模式开关。"""
    assert _diagnosis_stage_message("recResume123", False, {}).startswith("📄 简历库模式")


def test_stage_message_pure_mode():
    msg = _diagnosis_stage_message(None, False, {"risk_red_flags": "有内容但未注入"})
    assert msg.startswith("🧪 纯净模式")
    assert "就绪" not in msg


def test_stage_message_ready_only_when_populated():
    msg = _diagnosis_stage_message("", True, {**_EMPTY_SIX_FIELDS, "risk_red_flags": "忌空话"})
    assert msg.startswith("🩺 岗位深度诊断上下文就绪")
    assert "已注入" in msg


def test_stage_message_empty_or_failed_read():
    for diag in ({}, None, _EMPTY_SIX_FIELDS, {"dream_picture": "  "}):
        msg = _diagnosis_stage_message(None, True, diag)
        assert msg.startswith("⚠️ 未读到岗位深度诊断"), f"diag={diag!r} 不该说就绪: {msg}"


# ---------- 单轮引擎 usage 事件 ----------

def _fake_openai_client(content: str, prompt_tokens: int = 1200, completion_tokens: int = 300):
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        prompt_tokens_details=SimpleNamespace(cached_tokens=256),
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, reasoning_content=""))],
        usage=usage,
    )
    create = lambda **kwargs: response  # noqa: E731
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_single_turn_rewrite_emits_usage_event(monkeypatch):
    """usage 事件必须在引擎返回前发出，且与返回的 usage_dict 同值（看板 token 计数不再等 complete）。"""
    import ai_agents.skill_rewrite as sr

    monkeypatch.setattr(
        sr, "get_openai_client",
        lambda: _fake_openai_client("<FINAL_RESUME>\n# 张三\n- 主导 **RAG** 搭建\n</FINAL_RESUME>"),
    )
    events: list[tuple[str, dict]] = []

    final_md, usage = run_skill_based_rewrite(
        original_resume="{}",
        jd_text="岗位 JD",
        diagnosis_dict={},
        job_name="单测岗位",
        skill_id="",
        include_diagnosis=True,
        on_event=lambda t, d: events.append((t, d)),
    )

    assert not final_md.startswith("❌"), final_md
    usage_events = [d for t, d in events if t == "usage"]
    assert len(usage_events) == 1, f"单轮路径应恰好发出一次 usage 事件，实际事件序列: {[t for t, _ in events]}"
    ev = usage_events[0]
    assert ev["prompt_tokens"] == 1200
    assert ev["completion_tokens"] == 300
    assert ev["total_tokens"] == 1500
    assert ev["cached_tokens"] == 256
    assert usage["total_tokens"] == 1500 and usage["cached_tokens"] == 256
    # usage 必须晚于「大模型响应完成」思考事件（usage_dict 此时才可用），早于引擎返回
    types_seq = [t for t, _ in events]
    assert types_seq.index("usage") > max(i for i, t in enumerate(types_seq) if t == "thinking")
