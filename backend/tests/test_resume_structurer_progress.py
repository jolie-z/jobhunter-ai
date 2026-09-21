"""简历结构化器改造测试：流式进度回调 / strict 诚实报错 / 流式失败回退非流式。

全部 mock OpenAI client，不触网。
注意：被测模块在 fixture/用例内 import，避免 collection 期 import app.* 改变
全量回归的全局初始化顺序（scheduler loop 绑定顺序污染已实证）。
"""
import json

import pytest


_VALID_JSON = {
    "moduleOrder": ["summary"],
    "moduleTitles": {"summary": "个人总结"},
    "summary": "hello",
    "personalInfo": {"name": "张三"},
}


class _Delta:
    def __init__(self, content):
        self.content = content


class _Chunk:
    def __init__(self, content):
        self.choices = [type("C", (), {})()]
        self.choices[0].delta = _Delta(content)


class _StreamCompletions:
    """stream=True 返回分片；非流式按配置返回内容或抛错。"""

    def __init__(self, pieces, non_stream_reply=None, stream_exc: Exception | None = None):
        self._pieces = pieces
        self._non_stream_reply = non_stream_reply
        self._stream_exc = stream_exc

    def create(self, **kwargs):
        if kwargs.get("stream"):
            if self._stream_exc:
                raise self._stream_exc
            return iter([_Chunk(p) for p in self._pieces])
        if self._non_stream_reply is not None:
            resp = type("R", (), {})()
            resp.choices = [type("C", (), {})()]
            resp.choices[0].message = type("M", (), {})()
            resp.choices[0].message.content = self._non_stream_reply
            return resp
        raise AssertionError("非流式通道不应被调用")


class _FakeClient:
    def __init__(self, completions):
        self.chat = type("Chat", (), {})()
        self.chat.completions = completions


@pytest.fixture
def fake_llm(monkeypatch):
    def _install(completions):
        from app.core import resume_structurer
        monkeypatch.setattr(resume_structurer, "get_openai_client", lambda: _FakeClient(completions))
    return _install


def test_progress_cb_reports_streaming_chars(fake_llm):
    """流式路径：progress_cb 按累计字符数回调，最终解析成功。"""
    from app.core import resume_structurer
    long_summary = "a" * 200
    raw = json.dumps({
        "moduleOrder": ["summary"],
        "moduleTitles": {"summary": "个人总结"},
        "summary": long_summary,
    })
    third = len(raw) // 3
    pieces = [raw[:third], raw[third:2 * third], raw[2 * third:]]
    fake_llm(_StreamCompletions(pieces))

    import asyncio
    reports: list[int] = []
    result = asyncio.run(
        resume_structurer.parse_resume_to_json("MD", progress_cb=reports.append)
    )

    assert result["summary"] == long_summary
    assert reports == sorted(reports)  # 单调递增
    # 节流口径：每累计 ≥150 字回调一次（100+100+100 的分片只触发 200 那一次）
    assert reports == [200]


def test_stream_failure_falls_back_to_non_stream(fake_llm):
    """流式建立失败（网关不支持 stream+json）→ 自动回退非流式，行为不变。"""
    from app.core import resume_structurer
    fake_llm(_StreamCompletions(
        pieces=[],
        non_stream_reply=json.dumps(_VALID_JSON),
        stream_exc=RuntimeError("stream unsupported"),
    ))

    import asyncio
    result = asyncio.run(resume_structurer.parse_resume_to_json("MD", progress_cb=lambda n: None))
    assert result["summary"] == "hello"


def test_strict_raises_on_invalid_json(fake_llm):
    """strict=True：模型返回非 JSON → 诚实抛错（上传链路），不再静默空简历。"""
    from app.core import resume_structurer
    fake_llm(_StreamCompletions(pieces=[], non_stream_reply="这不是 JSON"))

    import asyncio
    with pytest.raises(ValueError) as exc_info:
        asyncio.run(resume_structurer.parse_resume_to_json("MD", strict=True))
    assert "无法解析" in str(exc_info.value)


def test_non_strict_keeps_empty_fallback(fake_llm):
    """strict=False（默认）：保持旧行为返回空结构，ATS 诊断等既有调用方不受影响。"""
    from app.core import resume_structurer
    fake_llm(_StreamCompletions(pieces=[], non_stream_reply="这不是 JSON"))

    import asyncio
    result = asyncio.run(resume_structurer.parse_resume_to_json("MD"))
    assert result["summary"] == ""
    assert isinstance(result["workExperience"], list)
