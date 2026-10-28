"""LLM 超时配置单测（2026-10-13 画像 37 分钟超时马拉松事故的防回归闸）。

事故背景：共享 HTTP 客户端写死 timeout=180.0，用户切换慢思考模型（glm-5.3-flash，
画像负载单次 175~193s）后每次请求必超时，画像外层 3 次重试 × SDK max_retries=3
≈ 37 分钟锁死生成锁。修复：超时可配置（LLM_TIMEOUT_SECONDS，默认 360s）+ 画像链路
SDK 重试归零（见 jd_report_service._get_llm_client）。

覆盖：
1. get_llm_timeout_seconds 解析矩阵：缺失/数字/字符串/非法/非正数 → 默认或解析值
2. get_safe_httpx_client 超时参数生效（httpx 将 float 规范化为 httpx.Timeout 对象）
3. get_openai_client 缓存指纹必须含 timeout：改 settings 的 LLM_TIMEOUT_SECONDS
   后旧缓存客户端必须重建（否则就是「改了没生效」同族 bug）

运行口径：cd backend && .venv/bin/python -m pytest tests_pipeline/test_llm_timeout_config.py -q
"""
from unittest.mock import MagicMock

import pytest

from common import config

_SETTINGS: dict = {}


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch):
    """隔离 settings.json 与环境变量；用例前后清空客户端缓存做隔离——
    注意：清缓存只允许发生在 fixture 层，用例体内改配置前后绝不清缓存，
    否则会掩盖「指纹未感知配置变更」的真实缺陷。"""
    monkeypatch.setattr(config, "_load_settings_json", lambda: dict(_SETTINGS))
    for key in ("LLM_TIMEOUT_SECONDS", "OPENAI_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    _SETTINGS.clear()
    config._openai_client_cache.clear()
    yield
    config._openai_client_cache.clear()


def _set_settings(**kwargs):
    _SETTINGS.clear()
    _SETTINGS.update(kwargs)


class TestGetLlmTimeoutSeconds:
    def test_missing_returns_default(self):
        assert config.get_llm_timeout_seconds() == config.DEFAULT_LLM_TIMEOUT_SECONDS

    def test_settings_number_honored(self):
        _set_settings(LLM_TIMEOUT_SECONDS=240)
        assert config.get_llm_timeout_seconds() == 240.0

    def test_settings_numeric_string_parsed(self):
        _set_settings(LLM_TIMEOUT_SECONDS="240")
        assert config.get_llm_timeout_seconds() == 240.0

    @pytest.mark.parametrize("bad", ["abc", -5, 0, "", None, True, float("inf")])
    def test_invalid_or_non_positive_falls_back_to_default(self, bad):
        # 0/空串/None 被 _cfg 的 falsy 判空天然跳过；-5/"abc"/bool/inf 靠解析守卫回落
        if bad is not None:
            _set_settings(LLM_TIMEOUT_SECONDS=bad)
        assert config.get_llm_timeout_seconds() == config.DEFAULT_LLM_TIMEOUT_SECONDS

    def test_env_var_channel_parsed(self, monkeypatch):
        """settings.json 之外的 .env/环境变量通道同样生效（_cfg 双通道）。"""
        monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "240")
        assert config.get_llm_timeout_seconds() == 240.0


class TestSafeHttpxClient:
    def test_explicit_timeout_applied(self):
        client = config.get_safe_httpx_client(timeout=240.0)
        try:
            assert client.timeout.read == 240.0  # httpx 将 float 规范化为 Timeout 对象
        finally:
            client.close()

    def test_default_resolves_configured_timeout(self):
        _set_settings(LLM_TIMEOUT_SECONDS=480)
        client = config.get_safe_httpx_client()
        try:
            assert client.timeout.read == 480.0
        finally:
            client.close()


class TestOpenaiClientFingerprint:
    def test_timeout_change_rebuilds_cached_client(self, monkeypatch):
        """同配置两次调用命中缓存；仅改 LLM_TIMEOUT_SECONDS（之间不清缓存）必须重建。"""
        _set_settings(
            OPENAI_API_KEY="k-timeout-test",
            OPENAI_BASE_URL="http://localhost:9/v1",
            LLM_TIMEOUT_SECONDS=360,
        )
        constructed: list[dict] = []
        # 返回 MagicMock 而非裸 object()：get_openai_client 会挂 _configured_max_retries 属性
        monkeypatch.setattr("openai.OpenAI", MagicMock(side_effect=lambda **kw: constructed.append(kw) or MagicMock()))
        monkeypatch.setattr("app.core.llm_tracker.make_tracked_client", lambda raw, **kw: raw)

        first = config.get_openai_client(caller="t")
        second = config.get_openai_client(caller="t")
        assert first is second  # 同配置命中缓存，不重复建池
        assert constructed[0]["http_client"].timeout.read == 360.0

        _set_settings(
            OPENAI_API_KEY="k-timeout-test",
            OPENAI_BASE_URL="http://localhost:9/v1",
            LLM_TIMEOUT_SECONDS=480,
        )
        third = config.get_openai_client(caller="t")
        assert third is not second  # 指纹未感知 timeout 的话这里会命中旧缓存
        assert constructed[1]["http_client"].timeout.read == 480.0
