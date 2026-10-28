"""2026-10-17：ATS 对齐接入「稳定前缀优先」缓存观测 + 共享 llm_usage 工具。

ATS 保持注入画像完整版（用户决定），缓存收益来自跨经历条目复用 system 前缀：
同一 jd_report_context 下 system 消息字节一致，按条目变化的简历 AST 与目标经历落在 user。
"""
import asyncio
import logging
from types import SimpleNamespace

from app.core import llm_usage
from app.strategy import ai_diagnosis_service as ats
from app.strategy.schemas import AtsAlignRequest

PROFILE = "## 一、硬技能\n**Python**（18/20 岗位）…（完整版画像）"


# ---------- 共享 usage 工具：四种形态 ----------

def test_extract_usage_object_shape():
    usage = SimpleNamespace(prompt_tokens=1800, prompt_tokens_details=SimpleNamespace(cached_tokens=1536))
    assert llm_usage.extract_prompt_cache_usage(usage) == (1800, 1536)


def test_extract_usage_dict_shape():
    assert llm_usage.extract_prompt_cache_usage({"prompt_tokens": 900, "prompt_tokens_details": {"cached_tokens": 512}}) == (900, 512)


def test_extract_usage_object_with_dict_details():
    """对象 usage 嵌 dict details（异构网关形态）也要取到 cached_tokens。"""
    usage = SimpleNamespace(prompt_tokens=700, prompt_tokens_details={"cached_tokens": 256})
    assert llm_usage.extract_prompt_cache_usage(usage) == (700, 256)


def test_extract_usage_missing_or_garbage_degrades_to_zero():
    assert llm_usage.extract_prompt_cache_usage(SimpleNamespace(prompt_tokens=5)) == (5, 0)
    assert llm_usage.extract_prompt_cache_usage({"prompt_tokens": "abc", "prompt_tokens_details": {"cached_tokens": "x"}}) == (None, 0)
    assert llm_usage.extract_prompt_cache_usage({}) == (None, 0)


def test_log_prompt_cache_hit_formats_with_and_without_turn(caplog):
    usage = {"prompt_tokens": 1200, "prompt_tokens_details": {"cached_tokens": 1024}}
    with caplog.at_level(logging.INFO, logger="llm_usage"):
        llm_usage.log_prompt_cache_hit("f", usage, 3)
        llm_usage.log_prompt_cache_hit("g", usage)
        llm_usage.log_prompt_cache_hit("h", None)
    assert "[Func: f] 第 3 轮 prompt_tokens=1200 cached_tokens=1024" in caplog.text
    assert "[Func: g] prompt_tokens=1200 cached_tokens=1024" in caplog.text
    assert "[Func: h]" not in caplog.text


# ---------- ATS 消息排布：稳定前缀属性 ----------

def test_ats_messages_system_reused_across_items():
    sys_prompt = f"规则…\n【全局A级岗位核心能力画像】：\n{PROFILE}\n\n格式…"
    a = ats._ats_messages(sys_prompt, '{"workExperience": []}', "经历 A")
    b = ats._ats_messages(sys_prompt, '{"workExperience": []}', "经历 B")
    assert a[0] == b[0] and a[0]["role"] == "system"
    assert a[1] != b[1] and a[1]["role"] == "user"
    assert "经历 A" in a[1]["content"] and "经历 B" in b[1]["content"]
    assert len(a) == 2


# ---------- ATS 服务：真实装配 + 命中观测 ----------

class _Completions:
    def __init__(self):
        self.calls: list[list] = []

    def create(self, **kwargs):
        self.calls.append(kwargs["messages"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"is_modified": false, "blocks": [], "injected_keywords": [], "surgeon_rationale": ""}'
            ))],
            usage=SimpleNamespace(prompt_tokens=3200, prompt_tokens_details=SimpleNamespace(cached_tokens=2816)),
        )


def _run_ats(monkeypatch, completions: _Completions, experience: str, profile: str = PROFILE):
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(ats, "_get_client", lambda: client)

    async def fake_parse(_text: str):
        return {"workExperience": [{"company": "X"}], "personalProjects": []}

    monkeypatch.setattr(ats, "parse_resume_to_json", fake_parse)
    payload = AtsAlignRequest(
        original_experience=experience,
        jd_report_context=profile,
        full_resume_context="非 JSON 的 Markdown 底稿",
    )
    return asyncio.run(ats.ats_align_experience_service(payload))


def test_ats_service_keeps_system_prefix_stable_across_items(monkeypatch, caplog):
    completions = _Completions()
    with caplog.at_level(logging.INFO, logger="llm_usage"):
        data_a = _run_ats(monkeypatch, completions, "做了个数据报表")
        data_b = _run_ats(monkeypatch, completions, "搭了套监控告警")
    assert data_a["is_modified"] is False and data_b["is_modified"] is False
    assert len(completions.calls) == 2
    m_a, m_b = completions.calls
    assert m_a[0] == m_b[0], "同一画像下 system 必须字节一致，才能跨条目命中前缀缓存"
    assert PROFILE in m_a[0]["content"]
    assert [m["role"] for m in m_a] == ["system", "user"]
    assert "做了个数据报表" in m_a[1]["content"] and "搭了套监控告警" in m_b[1]["content"]
    assert caplog.text.count("[Func: ats_align_experience_service] prompt_tokens=3200 cached_tokens=2816") == 2


def test_ats_service_system_changes_only_with_profile(monkeypatch):
    completions = _Completions()
    _run_ats(monkeypatch, completions, "经历", profile=PROFILE)
    _run_ats(monkeypatch, completions, "经历", profile="- 硬技能：Python（速览版）")
    assert completions.calls[0][0] != completions.calls[1][0]
    assert completions.calls[0][1] == completions.calls[1][1]
