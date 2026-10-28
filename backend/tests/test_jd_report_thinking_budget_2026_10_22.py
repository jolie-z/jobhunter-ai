"""
A级岗位画像「重新生成」空内容误报回归（2026-10-22 真机工单·问题四）

病灶：deepseek-v4.1-flash 为推理模型，思考计入 completion 预算。画像任务 prompt 万级
token、聚合 20 条 JD 输出全章节长报告，思考先烧尽 max_tokens=16384、正文一字未写即被
掐断（finish_reason=length、content 空），而 call_llm 只读 content → 误报「AI 返回空
内容」；同 prompt + temperature=0.3 重试确定性重演，3 次全灭。

修复锁定：
1. 默认携带顶层 extra_body={"thinking":{"type":"disabled"}} 关闭思考（本地网关实测
   生效；enable_thinking:false / reasoning.enabled:false 实测无效，勿改）。
2. content 为空且 finish_reason=length 时抛「输出预算被耗尽」专用归因，不再误报空内容。
3. 网关不认 thinking 参数（异常文本含 thinking）时降级去掉后重试，不锁死画像生成。
"""
from unittest.mock import MagicMock

import pytest

from app.strategy import jd_report_service as svc
from tests.api.test_strategy_jd_report import REPORT


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(svc, "_LLM_BACKOFF_SECONDS", (0, 0))


def _client_with(create_fn):
    client = MagicMock()
    client.chat.completions.create = create_fn
    return client


def _resp(content: str, finish_reason=None):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    return MagicMock(choices=[choice])


@pytest.mark.asyncio
async def test_thinking_disabled_by_default_on_success():
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _resp(REPORT, "stop")

    text = await svc._generate_report_text(_client_with(fake_create), "聚合 JD 文本", 6)
    assert text.strip() == REPORT.strip()
    assert len(calls) == 1
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}, "推理模型思考烧预算，聚合任务必须默认关思考"
    assert calls[0]["max_tokens"] == svc._LLM_MAX_TOKENS


@pytest.mark.asyncio
async def test_budget_exhaustion_reports_accurate_reason_not_empty_content():
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _resp("", finish_reason="length")  # 思考烧尽预算、正文为空、被长度掐断

    with pytest.raises(ValueError) as exc:
        await svc._generate_report_text(_client_with(fake_create), "聚合 JD 文本", 6)

    msg = str(exc.value)
    assert "输出预算被思考/正文耗尽" in msg and "finish_reason=length" in msg
    assert "AI 返回空内容" not in msg, "预算耗尽型截断不得再误报为「空内容」"
    assert len(calls) == svc._LLM_ATTEMPTS
    # 【P1 回归锁】预算耗尽文案若含 max_tokens/thinking 字面，会被重试循环的
    # 「网关拒参」子串启发式误命中，错误丢掉 16384 输出上限——此处锁定后续
    # 尝试必须始终携带 max_tokens 与关思考参数。
    for i, kwargs in enumerate(calls):
        assert kwargs.get("max_tokens") == svc._LLM_MAX_TOKENS, f"第 {i + 1} 次尝试不得因预算耗尽误删 max_tokens"
        assert kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}, f"第 {i + 1} 次尝试不得因预算耗尽误删关思考参数"


@pytest.mark.asyncio
async def test_gateway_rejecting_thinking_param_degrades_and_retries():
    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if "extra_body" in kwargs:
            raise Exception("400 Invalid parameter: 'thinking' not supported")
        return _resp(REPORT, "stop")

    text = await svc._generate_report_text(_client_with(fake_create), "聚合 JD 文本", 6)

    assert text.strip() == REPORT.strip()
    assert len(calls) == 2
    assert "extra_body" in calls[0], "首发必须带关思考参数"
    assert "extra_body" not in calls[1], "网关不认 thinking 时必须降级去掉，不得锁死画像生成"


@pytest.mark.asyncio
async def test_empty_content_with_other_finish_reason_keeps_old_semantics():
    """非 length 原因的空内容（如 content_filter）仍走原「AI 返回空内容」口径。"""

    def fake_create(**kwargs):
        return _resp("", finish_reason="content_filter")

    with pytest.raises(ValueError, match="AI 返回空内容"):
        await svc._generate_report_text(_client_with(fake_create), "聚合 JD 文本", 6)
