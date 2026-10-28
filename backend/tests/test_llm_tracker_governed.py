"""
Phase 1 LLM 追踪代理与治理层集成单元测试 (tests/test_llm_tracker_governed.py)

覆盖规范：
1. TrackedClient 接入 govern 链路：非流式 create 自动受 govern_sync_call 统一策略保护
2. 重试权威交接：429 重试后成功，全链路 token 埋点记录完整
3. 异步客户端 govern_async_call：AsyncTrackedCompletions 协程重试
4. agent_mapper 手工循环删除回归：收编后全链路降级零回退
5. Phase 3 BOSS 规则降级与三平台平滑降级在重试耗尽后无缝承接
"""
import copy
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from app.core.llm_governed import current_llm_context, govern_async_call, govern_sync_call
from app.core.llm_retry import RetryPolicy
from app.core.llm_tracker import make_tracked_client
import resume_editor.agent_mapper as am
from app.core.llm_gate import reset_llm_gate
from common.config import _openai_client_cache, _async_openai_client_cache


@pytest.fixture(autouse=True)
def clean_gate_and_caches():
    _openai_client_cache.clear()
    _async_openai_client_cache.clear()
    yield
    _openai_client_cache.clear()
    _async_openai_client_cache.clear()


@pytest.fixture
def boss_gold_fields():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "boss_fields_sample.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def master_resume_fixture():
    return {
        "name": "张三",
        "phone": "13800138000",
        "email": "zhangsan@example.com",
        "wechat": "wx_zhangsan",
        "summary": "资深后端架构师，深耕分布式系统与高并发服务开发。",
        "experiences": [
            {
                "company": "阿里巴巴",
                "role": "高级技术专家",
                "start": "2021-03",
                "end": "至今",
                "desc": "负责淘系交易核心链路稳定性建设。",
            }
        ],
        "projects": [
            {
                "name": "千万级并发网关重构",
                "role": "架构负责人",
                "start": "2021-06",
                "end": "2022-12",
                "desc": "基于 Netty 与 Go 重构核心网关，降低 50% 延迟。",
            }
        ],
        "education": [
            {
                "school": "清华大学",
                "major": "计算机科学与技术",
                "degree": "硕士",
                "start": "2015-09",
                "end": "2018-07",
            }
        ],
        "skills": ["Go", "Python", "Kubernetes", "Redis"],
        "ok": True,
    }


def test_tracked_client_routes_through_govern_sync_and_logs():
    """验证 TrackedClient 挂载 govern_sync_call：429 重试后成功并安全记录埋点。"""
    class FakeRateLimit(Exception):
        status_code = 429

    mock_chat = MagicMock()
    mock_completions = MagicMock()
    mock_chat.completions = mock_completions

    raw_client = MagicMock()
    raw_client.chat = mock_chat
    raw_client._configured_max_retries = 2

    # 模拟第 1 次 429，第 2 次返回带有 usage 的 response
    fake_resp = MagicMock()
    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 100
    fake_usage.completion_tokens = 50
    fake_usage.total_tokens = 150
    fake_resp.usage = fake_usage
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = '{"test": "ok"}'

    call_count = 0

    def fake_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FakeRateLimit("Rate limit")
        return fake_resp

    mock_completions.create.side_effect = fake_create

    logged_usages = []

    def mock_safe_log(*args, **kwargs):
        logged_usages.append((args, kwargs))

    tracked_client = make_tracked_client(raw_client, caller="test_caller", client_for_policy=raw_client)

    def sample_business_caller():
        return tracked_client.chat.completions.create(model="test-model", messages=[{"role": "user", "content": "hi"}])

    with patch("time.sleep"), patch("app.core.llm_tracker._safe_log", side_effect=mock_safe_log):
        resp = sample_business_caller()

    assert resp is fake_resp
    assert call_count == 2, "应由策略层自动重试 1 次后成功"
    assert len(logged_usages) == 1
    assert "sample_business_caller" in logged_usages[0][0][0], "action 必须准确归因到业务函数帧"
    assert logged_usages[0][1].get("caller") == "test_caller"


@pytest.mark.asyncio
async def test_tracked_async_client_routes_through_govern_async():
    """验证异步 AsyncTrackedCompletions 挂载 govern_async_call 并支持重试与准确埋点归因。"""
    class FakeTimeout(Exception):
        status_code = 408

    mock_chat = MagicMock()
    mock_completions = MagicMock()
    mock_chat.completions = mock_completions

    raw_async_client = MagicMock()
    raw_async_client.chat = mock_chat
    raw_async_client._configured_max_retries = 1

    fake_resp = MagicMock()
    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 50
    fake_usage.completion_tokens = 20
    fake_usage.total_tokens = 70
    fake_resp.usage = fake_usage
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = '{"async": "ok"}'

    call_count = 0

    async def fake_async_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FakeTimeout("Timeout")
        return fake_resp

    mock_completions.create = fake_async_create

    # 模拟 _is_async_client 识别为异步客户端
    type(raw_async_client).__name__ = "AsyncOpenAI"

    tracked_async = make_tracked_client(raw_async_client, caller="test_async", client_for_policy=raw_async_client)

    logged_usages = []

    def mock_safe_log(*args, **kwargs):
        logged_usages.append((args, kwargs))

    async def sample_async_business_caller():
        return await tracked_async.chat.completions.create(model="async-model", messages=[])

    with patch("asyncio.sleep", return_value=None), patch("app.core.llm_tracker._safe_log", side_effect=mock_safe_log):
        resp = await sample_async_business_caller()

    assert resp is fake_resp
    assert call_count == 2
    assert len(logged_usages) == 1
    assert "sample_async_business_caller" in logged_usages[0][0][0], "异步 action 必须准确归因到业务协程函数帧"
    assert logged_usages[0][1].get("caller") == "test_async"


def test_agent_mapper_handover_boss_degrades_after_policy_exhaustion(boss_gold_fields, master_resume_fixture):
    """【重试权威交接核心用例】map_platform 在删除手工循环后，429 经策略层重试耗尽后平滑降级至 BOSS 规则映射。"""
    class Constant429Error(Exception):
        status_code = 429

    mock_raw_client = MagicMock()
    mock_chat = MagicMock()
    mock_completions = MagicMock()
    mock_chat.completions = mock_completions
    mock_raw_client.chat = mock_chat
    mock_raw_client._configured_max_retries = 2

    attempts_made = 0

    def mock_create_throws_429(*args, **kwargs):
        nonlocal attempts_made
        attempts_made += 1
        raise Constant429Error("Continuous 429 RateLimit")

    mock_completions.create.side_effect = mock_create_throws_429
    tracked = make_tracked_client(mock_raw_client, caller="agent_map", client_for_policy=mock_raw_client)

    cfg = {"OPENAI_API_KEY": "sk-test", "OPENAI_BASE_URL": "https://api.openai.com/v1"}

    with patch("common.config.get_openai_client", return_value=tracked), \
         patch("time.sleep"):

        report = am.map_platform("boss", boss_gold_fields, master_resume_fixture, cfg=cfg)

    # 1. 验证重试策略被完整执行 3 次 (1 次初始 + 2 次重试)
    assert attempts_made == 3, "重试权威交接后，策略层应统一执行 3 次尝试"

    # 2. 验证 BOSS 平滑降级成功
    assert report["success"] is True, "BOSS 规则降级开启时，429 耗尽应平滑降级返回 success=True"
    assert report["platform"] == "boss"
    assert any("确定性规则映射" in str(w) for w in report.get("warnings", []))
    assert len(report.get("fields", [])) > 0


def test_agent_mapper_handover_other_platforms_degrade_after_exhaustion(boss_gold_fields, master_resume_fixture):
    """验证其他平台（51job/zhilian/liepin）在删除手工循环后同样由策略层重试后平滑降级。"""
    class Constant503Error(Exception):
        status_code = 503

    mock_raw_client = MagicMock()
    mock_chat = MagicMock()
    mock_completions = MagicMock()
    mock_chat.completions = mock_completions
    mock_raw_client.chat = mock_chat
    mock_raw_client._configured_max_retries = 2

    mock_completions.create.side_effect = Constant503Error("Service Unavailable")
    tracked = make_tracked_client(mock_raw_client, caller="agent_map", client_for_policy=mock_raw_client)

    cfg = {"OPENAI_API_KEY": "sk-test"}

    with patch("common.config.get_openai_client", return_value=tracked), \
         patch("time.sleep"):

        for plat in ("51job", "zhilian", "liepin"):
            report = am.map_platform(plat, boss_gold_fields, master_resume_fixture, cfg=cfg)
            assert report["success"] is True, f"{plat} 遇到 503 重试耗尽后必须平滑降级成功"
            assert report["platform"] == plat


def test_get_openai_client_real_path_make_tracked_client_no_type_error():
    """【P0 闭环】真实路径验证：不 stub make_tracked_client，真实调用 get_openai_client 与 get_async_openai_client，
    确保参数绑定无 TypeError（如 multiple values for argument 'client'），TrackedClient 成功封装且挂载 policy_client。"""
    from common.config import get_openai_client, get_async_openai_client, _openai_client_cache, _async_openai_client_cache
    from app.core.llm_tracker import TrackedClient

    _openai_client_cache.clear()
    _async_openai_client_cache.clear()

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-test-key", "OPENAI_BASE_URL": "https://api.openai.com/v1"}):
        # 1. 同步客户端真实实例化路径（未命中缓存走 make_tracked_client）
        sync_client = get_openai_client(caller="agent_map", max_retries=2)
        assert isinstance(sync_client, TrackedClient), "同步工厂必须成功返回 TrackedClient"
        assert getattr(sync_client._client, "_configured_max_retries", None) == 2, "策略客户端必须挂载 _configured_max_retries"

        # 2. 异步客户端真实实例化路径
        async_client = get_async_openai_client(caller="test_async", max_retries=1)
        assert isinstance(async_client, TrackedClient), "异步工厂必须成功返回 TrackedClient"
        assert getattr(async_client._client, "_configured_max_retries", None) == 1


def test_retry_policy_disabled_straight_through_single_invocation_zero_sleep():
    """【回滚开关闭环】验证 LLM_RETRY_POLICY_ENABLED=false 时：
    1. is_enabled() 判定为 False；
    2. govern_sync_call 与 TrackedClient 短路直通 raw_create；
    3. create 恰好仅调用 1 次；
    4. time.sleep 调用 0 次；
    5. 原装异常立即上抛，绝不发起策略重试。"""
    class Mock429Error(Exception):
        status_code = 429

    mock_chat = MagicMock()
    mock_completions = MagicMock()
    mock_chat.completions = mock_completions
    raw_client = MagicMock()
    raw_client.chat = mock_chat
    raw_client._configured_max_retries = 2

    call_count = 0

    def mock_create_fail(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise Mock429Error("Direct 429 RateLimit")

    mock_completions.create.side_effect = mock_create_fail
    tracked_client = make_tracked_client(raw_client, caller="test_caller", client_for_policy=raw_client)

    with patch.dict(os.environ, {"LLM_RETRY_POLICY_ENABLED": "false"}), \
         patch("common.config.get_setting", return_value=None), \
         patch("time.sleep") as mock_sleep, \
         patch("app.core.llm_tracker._safe_log"):

        with pytest.raises(Mock429Error) as exc_info:
            tracked_client.chat.completions.create(model="test-model", messages=[])

        assert "Direct 429 RateLimit" in str(exc_info.value)
        assert call_count == 1, "回滚开关关闭时，底层 create 必须恰好调用 1 次（零重试直通）"
        mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_async_retry_policy_disabled_straight_through_single_invocation_zero_sleep():
    """【异步回滚开关闭环】验证异步场景下 LLM_RETRY_POLICY_ENABLED=false 时：
    短路直通 raw_create、恰好调用 1 次、asyncio.sleep 零调用、原装异常立即上抛。"""
    class MockAsync503Error(Exception):
        status_code = 503

    mock_chat = MagicMock()
    mock_completions = MagicMock()
    mock_chat.completions = mock_completions
    raw_async_client = MagicMock()
    raw_async_client.chat = mock_chat
    raw_async_client._configured_max_retries = 2

    call_count = 0

    async def mock_async_create_fail(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise MockAsync503Error("Direct 503 Service Unavailable")

    mock_completions.create = mock_async_create_fail
    type(raw_async_client).__name__ = "AsyncOpenAI"
    tracked_async = make_tracked_client(raw_async_client, caller="test_async", client_for_policy=raw_async_client)

    with patch.dict(os.environ, {"LLM_RETRY_POLICY_ENABLED": "false"}), \
         patch("common.config.get_setting", return_value=None), \
         patch("asyncio.sleep") as mock_async_sleep, \
         patch("app.core.llm_tracker._safe_log"):

        with pytest.raises(MockAsync503Error) as exc_info:
            await tracked_async.chat.completions.create(model="async-model", messages=[])

        assert "Direct 503 Service Unavailable" in str(exc_info.value)
        assert call_count == 1, "异步回滚开关关闭时，底层 create 必须恰好调用 1 次（零重试直通）"
        mock_async_sleep.assert_not_called()


