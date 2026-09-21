"""LLM 链路诊断（diagnose_llm）与 readiness 测试。

全部 mock，不发起真实 LLM 调用。报错翻译矩阵直接测 _explain_llm_fail 纯函数。
注意：①被测模块在用例内 import；②本文件不起 TestClient（lifespan 会启动 APScheduler
并绑定事件循环，先于 tests/api 执行会引爆 test_automation 的 loop-closed 顺序污染），
一律直调 service 层函数。
"""
import httpx as _httpx
import pytest


# ============================================================
# _explain_llm_fail 报错翻译矩阵
# ============================================================

def _fake_response(status: int = 401):
    """openai 异常构造要求真实 httpx.Response（内部取 response.request）。"""
    request = _httpx.Request("POST", "https://fake.example/v1/chat/completions")
    return _httpx.Response(status, request=request)


def test_explain_auth_error():
    import openai
    from app.settings import diagnostics

    exc = openai.AuthenticationError(message="401 invalid", response=_fake_response(401), body=None)
    detail, fix = diagnostics._explain_llm_fail(exc)
    assert "Key" in detail
    assert fix


def test_explain_model_not_found():
    import openai
    from app.settings import diagnostics

    exc = openai.NotFoundError(message="model gpt-x not found", response=_fake_response(404), body=None)
    detail, _ = diagnostics._explain_llm_fail(exc)
    assert "模型名" in detail


def test_explain_base_url_not_found():
    import openai
    from app.settings import diagnostics

    exc = openai.NotFoundError(message="url not found", response=_fake_response(404), body=None)
    detail, _ = diagnostics._explain_llm_fail(exc)
    assert "Base URL" in detail


def test_explain_rate_limit():
    import openai
    from app.settings import diagnostics

    exc = openai.RateLimitError(message="429 too many", response=_fake_response(429), body=None)
    detail, _ = diagnostics._explain_llm_fail(exc)
    assert "429" in detail or "限流" in detail


def test_explain_timeout():
    import openai
    from app.settings import diagnostics

    detail, _ = diagnostics._explain_llm_fail(openai.APITimeoutError(request=None))
    assert "超时" in detail


def test_explain_fallback():
    from app.settings import diagnostics

    detail, fix = diagnostics._explain_llm_fail(RuntimeError("weird gateway error"))
    assert "weird gateway error" in detail
    assert fix


# ============================================================
# diagnose_llm 结构（mock 配置与客户端，零网络）
# ============================================================

class _FakeCompletions:
    def __init__(self, content="OK", stream_chunks=None, exc: Exception | None = None):
        self._content = content
        self._stream_chunks = stream_chunks
        self._exc = exc

    def create(self, **kwargs):
        if self._exc:
            raise self._exc
        if kwargs.get("stream"):
            return iter(self._stream_chunks or [])
        resp = type("R", (), {})()
        resp.choices = [type("C", (), {})()]
        resp.choices[0].message = type("M", (), {})()
        resp.choices[0].message.content = self._content
        return resp


class _FakeClient:
    def __init__(self, completions):
        self.chat = type("Chat", (), {})()
        self.chat.completions = completions
        self.closed = False

    def close(self):
        self.closed = True


def test_diagnose_llm_missing_main_keys(monkeypatch):
    """主通道 Key 缺失：credentials 不通过、不做真实探活；vision 标选填。"""
    from app.settings import diagnostics

    monkeypatch.setattr(diagnostics, "get_missing_llm_keys", lambda: ["OPENAI_API_KEY", "OPENAI_MODEL"])
    monkeypatch.setattr(diagnostics, "get_missing_vision_keys", lambda: ["VISION_MODEL"])

    import asyncio
    data = asyncio.run(diagnostics.diagnose_llm())["data"]

    assert data["all_ok"] is False
    by_key = {c["key"]: c for c in data["checks"]}
    assert by_key["main_credentials"]["ok"] is False
    assert "OPENAI_API_KEY" in by_key["main_credentials"]["detail"]
    assert by_key["vision"]["optional"] is True
    assert "main_chat" not in by_key  # 未配置时不做真实调用


def test_diagnose_llm_all_pass(monkeypatch):
    """配置齐全 + 探活成功：main_chat/vision 均 ok。"""
    from app.settings import diagnostics

    monkeypatch.setattr(diagnostics, "get_missing_llm_keys", lambda: [])
    monkeypatch.setattr(diagnostics, "get_missing_vision_keys", lambda: [])
    monkeypatch.setattr(diagnostics, "get_configured_value", lambda key: "fake")

    fake = _FakeClient(_FakeCompletions())
    monkeypatch.setattr(diagnostics, "_short_client", lambda key, url: fake)

    import asyncio
    data = asyncio.run(diagnostics.diagnose_llm())["data"]

    assert data["all_ok"] is True
    by_key = {c["key"]: c for c in data["checks"]}
    assert by_key["main_credentials"]["ok"] is True
    assert by_key["main_chat"]["ok"] is True
    assert by_key["vision"]["ok"] is True


def test_diagnose_llm_chat_fail_vision_optional(monkeypatch):
    """探活失败 → main_chat 不 ok（带修复建议）；vision 缺失仅为选填提示，不拖垮 all_ok。"""
    import openai
    from app.settings import diagnostics

    monkeypatch.setattr(diagnostics, "get_missing_llm_keys", lambda: [])
    monkeypatch.setattr(diagnostics, "get_missing_vision_keys", lambda: ["VISION_MODEL"])
    monkeypatch.setattr(diagnostics, "get_configured_value", lambda key: "fake")

    fake = _FakeClient(_FakeCompletions(
        exc=openai.AuthenticationError(message="401", response=_fake_response(401), body=None)
    ))
    monkeypatch.setattr(diagnostics, "_short_client", lambda key, url: fake)

    import asyncio
    data = asyncio.run(diagnostics.diagnose_llm())["data"]

    by_key = {c["key"]: c for c in data["checks"]}
    assert by_key["main_chat"]["ok"] is False
    assert by_key["main_chat"]["fix"]
    # vision 未配置 → optional；main_chat 失败决定 all_ok=False
    assert by_key["vision"]["optional"] is True
    assert data["all_ok"] is False


# ============================================================
# readiness / settings service 层
# ============================================================

def test_readiness_service(monkeypatch):
    from app.settings import service as settings_service

    monkeypatch.setattr("common.config.get_missing_llm_keys", lambda: ["OPENAI_API_KEY"])
    monkeypatch.setattr("common.config.get_missing_vision_keys", lambda: [])
    monkeypatch.setattr("common.config.get_missing_feishu_min_keys", lambda: ["FEISHU_APP_TOKEN"])

    import asyncio
    data = asyncio.run(settings_service.get_readiness())["data"]
    assert data["main_llm_ready"] is False
    assert data["vision_ready"] is True
    assert data["feishu_min_ready"] is False
    assert data["missing"]["llm"] == ["OPENAI_API_KEY"]


def test_settings_payload_includes_required_flag():
    """GET /api/settings 每字段下发 required 标注，且恰好 8 个必填。"""
    from app.settings import service as settings_service

    import asyncio
    groups = asyncio.run(settings_service.get_system_settings())["groups"]
    required_keys = {
        f["key"]
        for g in groups
        for f in g["fields"]
        if f.get("required")
    }
    assert required_keys == {
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
        "FEISHU_TABLE_ID_JOBS", "FEISHU_TABLE_ID_RESUMES",
    }
