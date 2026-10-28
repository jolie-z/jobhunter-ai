"""
BOSS 平台简历映射及调用治理单测 (backend/tests/test_boss_agent_mapping.py)

Phase 0 验证目标：
1. 遭遇 429 RateLimitError 时按指数退避或 Retry-After 进行有界重试（上限 3 次）
2. 遭遇 AuthenticationError 等不可重试错误时立即 break（0 次重试）
3. 429 重试成功后正常产出映射报告
4. BOSS 在 LLM 持续 429 失败时返回可读的「速率限制」明确文案
5. 其他三平台在 LLM 持续 429 时平滑降级至规则映射 (success=True)
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch

from resume_editor.agent_mapper import map_platform
from tests.helpers.fake_llm_gateway import FakeLLMClient


@pytest.fixture(autouse=True)
def clear_client_caches():
    from common.config import _openai_client_cache, _async_openai_client_cache
    _openai_client_cache.clear()
    _async_openai_client_cache.clear()
    yield
    _openai_client_cache.clear()
    _async_openai_client_cache.clear()


@pytest.fixture
def sample_master_resume():
    return {
        "ok": True,
        "name": "张三",
        "phone": "13800138000",
        "email": "zhangsan@example.com",
        "summary": "资深全栈研发工程师，精通 Python 后端架构与大模型治理。",
        "experiences": [
            {
                "company": "未来科技",
                "role": "资深后端架构师",
                "start": "2021-06",
                "end": "至今",
                "desc": "主导全仓 LLM 限流网关与分布式调度系统。",
            }
        ],
        "projects": [
            {
                "name": "多平台简历同步中心",
                "role": "核心设计者",
                "desc": "实现了四平台字段映射与自动化回写链路。",
            }
        ],
        "education": [
            {
                "school": "北京大学",
                "major": "计算机科学与技术",
                "degree": "硕士",
                "start": "2015-09",
                "end": "2018-07",
            }
        ],
    }


@pytest.fixture
def boss_fields_dummy():
    return {
        "name": {"type": "input", "current_value": "旧姓名"},
        "personal_advantage": {"type": "textarea", "current_value": "旧优势"},
        "work_experience": {
            "type": "array",
            "current_value": [
                {
                    "company": "旧公司",
                    "position": "旧职位",
                    "start_date": "2020-01",
                    "end_date": "2021-05",
                    "description": "旧工作描述",
                }
            ],
        },
    }


@pytest.fixture
def job51_fields_dummy():
    return {
        "basic_info": {
            "type": "object",
            "current_value": {"name": "张三", "mobile": "13800000000", "email": "test@test.com"},
        },
        "self_intro": {"type": "textarea", "current_value": "旧介绍"},
    }


def test_boss_mapping_rate_limited_retry_cadence_with_header(boss_fields_dummy, sample_master_resume):
    """测试带 Retry-After 响应头时的退避重试时序与有界性。"""
    fake_client = FakeLLMClient(mode="rate_limit", retry_after=1.5)
    sleep_calls: list[float] = []

    with patch("openai.OpenAI", return_value=fake_client), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ):
        res = map_platform(
            "boss",
            boss_fields_dummy,
            sample_master_resume,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "glm-5-turbo"},
        )

    # 3 次尝试（第 1 次与第 2 次后休眠，第 3 次失败平滑降级至规则映射）
    assert len(fake_client.calls) == 3
    # 冷却窗每次发送前生效（Phase 2 规范约束）：每轮 = 退避休眠(Retry-After) + 闸内等待剩余冷却窗。
    # 真实时钟下退避已消化冷却窗、闸内等待为 0；此处 sleep 被打桩、时钟冻结，故闸内等待
    # 恒等于完整冷却窗（= Retry-After 1.5s）。
    assert sleep_calls == pytest.approx([1.5, 1.5, 1.5, 1.5], abs=0.05)
    assert res["success"] is True
    assert any("速率限制" in str(w) or "降级" in str(w) for w in res.get("warnings", []))


def test_boss_mapping_exponential_backoff_without_header(boss_fields_dummy, sample_master_resume):
    """测试无 Retry-After 头时采用指数退避 (1s, 2s)，且每次重发前等完全局冷却窗（默认 5s）。"""
    fake_client = FakeLLMClient(mode="rate_limit", retry_after=None)
    sleep_calls: list[float] = []

    with patch("openai.OpenAI", return_value=fake_client), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ), patch.dict(os.environ, {"LLM_429_COOLDOWN_SECONDS": "5.0"}):
        from app.core.llm_gate import reset_llm_gate
        reset_llm_gate()
        res = map_platform(
            "boss",
            boss_fields_dummy,
            sample_master_resume,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "glm-5-turbo"},
        )

    assert len(fake_client.calls) == 3
    # 无 Retry-After：退避 1s/2s 短于冷却窗 5s，重试轮必须补等冷却窗才能发送（66576328 质检 P1-3）。
    # 时钟冻结下序列为 [退避 1.0, 冷却 5.0, 退避 2.0, 冷却 5.0]。
    assert sleep_calls == pytest.approx([1.0, 5.0, 2.0, 5.0], abs=0.05)
    assert res["success"] is True
    assert any("速率限制" in str(w) or "降级" in str(w) for w in res.get("warnings", []))


def test_boss_mapping_auth_error_no_retry(boss_fields_dummy, sample_master_resume):
    """测试鉴权失败 (401) 时立即中断重试，总请求数为 1。"""
    fake_client = FakeLLMClient(mode="auth_error")
    sleep_calls: list[float] = []

    with patch("openai.OpenAI", return_value=fake_client), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ):
        res = map_platform(
            "boss",
            boss_fields_dummy,
            sample_master_resume,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "glm-5-turbo"},
        )

    assert len(fake_client.calls) == 1
    assert len(sleep_calls) == 0
    assert res["success"] is True
    assert any(("鉴权失败" in str(w)) or ("API Key" in str(w)) or ("降级" in str(w)) for w in res.get("warnings", []))


def test_boss_mapping_retry_then_success(boss_fields_dummy, sample_master_resume):
    """测试第 1 次 429 限流、第 2 次成功返回时的恢复能力。"""
    fake_client = FakeLLMClient(mode="rate_limit_then_success", fail_count=1, retry_after=0.5)
    sleep_calls: list[float] = []

    with patch("openai.OpenAI", return_value=fake_client), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ):
        res = map_platform(
            "boss",
            boss_fields_dummy,
            sample_master_resume,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "glm-5-turbo"},
        )

    assert len(fake_client.calls) == 2
    # 退避 0.5s（= Retry-After）；时钟冻结下重发前闸内冷却等待恒等于完整冷却窗 0.5s（真实时钟为 0）
    assert sleep_calls == pytest.approx([0.5, 0.5], abs=0.05)
    assert res["success"] is True
    assert "映射完成" in res["message"]


def test_other_platforms_degrade_on_rate_limit(job51_fields_dummy, sample_master_resume):
    """测试 51job 等平台在 LLM 持续 429 报错时，能正确降级至规则映射。"""
    fake_client = FakeLLMClient(mode="rate_limit")

    with patch("openai.OpenAI", return_value=fake_client), patch("time.sleep"):
        res = map_platform(
            "51job",
            job51_fields_dummy,
            sample_master_resume,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "glm-5-turbo"},
        )

    assert res["success"] is True
    assert res["platform"] == "51job"
    # 规则映射会包含降级警告或说明
    assert any("降级" in str(w) or "速率限制" in str(w) or "规则映射" in str(w) for w in res.get("warnings", [])) or "规则映射" in res.get("message", "")


def test_boss_mapping_429_then_invalid_json_does_not_report_rate_limit(boss_fields_dummy, sample_master_resume):
    """【P1-2 验证】测试第 1 次 429、后续 HTTP 成功但 JSON 解析失败时，错误信息正确上报为 JSON 无法解析，严禁误报为速率限制。"""
    fake_client = FakeLLMClient(
        mode="rate_limit_then_success",
        fail_count=1,
        success_content="This is plain text without any json structure",
    )

    with patch("openai.OpenAI", return_value=fake_client), patch("time.sleep"):
        res = map_platform(
            "boss",
            boss_fields_dummy,
            sample_master_resume,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "glm-5-turbo"},
        )

    assert res["success"] is True
    assert any("无法解析" in str(w) for w in res.get("warnings", []))
    assert not any("速率限制" in str(w) for w in res.get("warnings", []))


def test_llm_classify_titles_retry_on_429():
    """【P1-1 验证】测试 _llm_classify_titles 遇到 429 速率限制时能退避重试并成功恢复。"""
    from resume_editor.agent_mapper import _llm_classify_titles
    import json

    titles = ["工作经历", "专业技能"]
    success_json = json.dumps({"工作经历": "workExperience", "专业技能": "technicalSkills"})
    fake_client = FakeLLMClient(mode="rate_limit_then_success", fail_count=1, retry_after=0.2, success_content=success_json)
    sleep_calls = []

    with patch("openai.OpenAI", return_value=fake_client), patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        res = _llm_classify_titles(
            titles,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "gpt-4o-mini"},
        )

    assert len(fake_client.calls) == 2
    # 退避 0.2s（= Retry-After）+ 时钟冻结下的闸内冷却等待 0.2s（真实时钟为 0）
    assert sleep_calls == pytest.approx([0.2, 0.2], abs=0.05)
    assert res.get("工作经历") == "workExperience"


def test_classify_llm_error_structured_precision():
    """【P1-3 验证】测试错误分类对 400ms、insufficient arguments 等边界的精准分类。"""
    from app.core.llm_errors import classify_llm_error, LLMErrorKind
    import httpx

    # 包含 400ms 的超时错误：绝不能误判为 bad_request
    err1 = Exception("upstream connection timeout 400ms elapsed")
    kind1, _, _ = classify_llm_error(err1)
    assert kind1 == LLMErrorKind.timeout

    # 包含 insufficient arguments 的错误：绝不能误判为 quota (余额不足)
    err2 = Exception("Invalid input: insufficient arguments provided")
    kind2, _, _ = classify_llm_error(err2)
    assert kind2 != LLMErrorKind.quota

    # 真实的 insufficient_quota 错误
    err3 = Exception("Error code: 402, message: insufficient_quota")
    kind3, _, _ = classify_llm_error(err3)
    assert kind3 == LLMErrorKind.quota

    # 503 携带 Retry-After 标头：精准分类为 server 且带出 retry_after
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp_503 = httpx.Response(503, headers={"Retry-After": "4.5"}, request=req, text="Service Unavailable")
    err4 = Exception("503 Service Unavailable")
    setattr(err4, "response", resp_503)
    setattr(err4, "status_code", 503)
    kind4, _, ra4 = classify_llm_error(err4)
    assert kind4 == LLMErrorKind.server
    assert ra4 == 4.5


def test_classify_llm_error_malformed_body_defense():
    """【P1 核心防御】测试第三方网关返回异常 body 结构时，classify_llm_error 绝对不抛 AttributeError。"""
    from app.core.llm_errors import classify_llm_error, LLMErrorKind

    # Case 1: body 中 error 字段为 None ({"error": null})
    err1 = Exception("Gateway returned error")
    setattr(err1, "body", {"error": None, "code": "some_code"})
    kind1, _, _ = classify_llm_error(err1)
    assert isinstance(kind1, LLMErrorKind)

    # Case 2: body 中 error 字段为纯字符串 ({"error": "Internal Error"})
    err2 = Exception("Gateway returned text error")
    setattr(err2, "body", {"error": "Internal Error String", "status": 500})
    kind2, _, _ = classify_llm_error(err2)
    assert isinstance(kind2, LLMErrorKind)

    # Case 3: body 本身为非字典（如字符串）
    err3 = Exception("Gateway raw HTML")
    setattr(err3, "body", "<html>502 Bad Gateway</html>")
    kind3, _, _ = classify_llm_error(err3)
    assert isinstance(kind3, LLMErrorKind)

    # Case 4: body 中嵌套标准的 dict 且包含 code
    err4 = Exception("Standard OpenAI error")
    setattr(err4, "body", {"error": {"code": "insufficient_quota", "message": "You exceeded your quota"}})
    kind4, _, _ = classify_llm_error(err4)
    assert kind4 == LLMErrorKind.quota


def test_classify_llm_error_retry_after_non_zero_and_backoff_helper():
    """【P2 验证】测试 Retry-After 为 0 时的非零保底机制，以及 compute_backoff_delay 的统一退避计算。"""
    from app.core.llm_errors import classify_llm_error, compute_backoff_delay, LLMErrorKind
    import httpx

    # Retry-After 为 "0" 时，保底应返回 >= 1.0s，杜绝 0 秒无效休眠
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp_0 = httpx.Response(429, headers={"Retry-After": "0"}, request=req, text="Rate Limited")
    err = Exception("Rate limit with Retry-After: 0")
    setattr(err, "response", resp_0)
    setattr(err, "status_code", 429)

    kind, _, retry_after = classify_llm_error(err)
    assert kind == LLMErrorKind.rate_limited
    assert retry_after is not None
    assert retry_after >= 1.0

    # 验证 compute_backoff_delay 计算有界严格非零
    assert compute_backoff_delay(0, retry_after=retry_after) >= 1.0
    assert compute_backoff_delay(0, retry_after=None, kind=LLMErrorKind.rate_limited) == 1.0
    assert compute_backoff_delay(1, retry_after=None, kind=LLMErrorKind.rate_limited) == 2.0
    assert compute_backoff_delay(2, retry_after=None, kind=LLMErrorKind.rate_limited) == 4.0
    assert compute_backoff_delay(5, retry_after=None, kind=LLMErrorKind.rate_limited) == 10.0  # 封顶 10s
    assert compute_backoff_delay(0, retry_after=None, kind=LLMErrorKind.timeout) == 0.5        # 线性退避


def test_classify_llm_error_1302_word_boundary():
    """【P2 验证】测试智谱 1302 错误码正则单词边界匹配，杜绝类似 ID 串误判。"""
    from app.core.llm_errors import classify_llm_error, LLMErrorKind

    # 包含独立单词 1302：精准分类为 rate_limited
    err_hit = Exception("Zhipu AI error code 1302: concurrency limit reached")
    kind_hit, _, _ = classify_llm_error(err_hit)
    assert kind_hit == LLMErrorKind.rate_limited

    # 包含 1302 作为一个长数字的一部分（如任务号或毫秒）：绝不能误判为 rate_limited
    err_miss = Exception("Task_1302999 timeout after 5000ms")
    kind_miss, _, _ = classify_llm_error(err_miss)
    assert kind_miss != LLMErrorKind.rate_limited


def test_openai_client_constructor_zero_retries(boss_fields_dummy, sample_master_resume):
    """【P2 验证】测试 map_platform 构造底层 OpenAI client 时确切传入 max_retries=0 与全局配置 timeout。"""
    from common.config import get_llm_timeout_seconds
    captured_kwargs = {}

    def fake_openai_init(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeLLMClient(mode="rate_limit", fail_count=1)

    from common.config import get_setting as real_get_setting

    def fake_get_setting(key, default=None):
        if key == "LLM_RETRY_POLICY_ENABLED":
            return None
        return real_get_setting(key, default)

    with patch.dict(os.environ, {"LLM_RETRY_POLICY_ENABLED": "true"}), \
         patch("common.config.get_setting", side_effect=fake_get_setting), \
         patch("openai.OpenAI", side_effect=fake_openai_init), \
         patch("time.sleep"):
        map_platform(
            "boss",
            boss_fields_dummy,
            sample_master_resume,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "glm-5-turbo"},
        )

    assert captured_kwargs.get("max_retries") == 0
    assert captured_kwargs.get("timeout") == get_llm_timeout_seconds()


def test_all_three_platforms_degrade_on_429(sample_master_resume):
    """【P2 验证】测试 51job、liepin、zhilian 三大平台在 LLM 遭遇 429 异常时全部 100% 平滑降级至规则映射。"""
    dummy_fields = {
        "basic_info": {"type": "object", "current_value": {"name": "张三"}},
        "self_intro": {"type": "textarea", "current_value": "介绍"},
    }
    fake_client = FakeLLMClient(mode="rate_limit", retry_after=1.0)

    for platform in ("51job", "liepin", "zhilian"):
        with patch("openai.OpenAI", return_value=fake_client), patch("time.sleep"):
            res = map_platform(
                platform,
                dummy_fields,
                sample_master_resume,
                cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "gpt-4o-mini"},
            )

        assert res["success"] is True, f"{platform} 遇到 429 时应当降级成功"
        assert res["platform"] == platform
        assert any("降级" in w or "规则" in w or "LLM" in w for w in res.get("warnings", [])), (
            f"{platform} 应该在 warnings 中提示降级"
        )


