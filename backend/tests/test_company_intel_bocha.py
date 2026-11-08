"""博查（国内直连）公司情报引擎单测：请求格式、返回解析、缓存写入、失败兜底。"""
from unittest.mock import MagicMock, patch

import ai_agents.company_intel as ci


def _reset_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "_SERPER_CACHE_PATH", tmp_path / "bocha_cache.json")
    monkeypatch.setattr(ci, "_serper_cache", {})
    monkeypatch.setattr(ci, "get_bocha_api_key", lambda: "sk-bocha-test")
    # 限流治理状态复位：测试不做全局匀速节流、清空 429 冷却窗，避免用例间相互影响
    monkeypatch.setattr(ci, "_BOCHA_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(ci, "_bocha_next_slot_ts", 0.0)
    monkeypatch.setattr(ci, "_bocha_429_cooldown_until", 0.0)


def _webpages_payload():
    return {
        "value": [
            {"name": "标题 A", "summary": "摘要 A", "url": "https://example.com/a"},
            {"name": "标题 B", "snippet": "摘要 B", "url": "https://example.com/b"},
        ]
    }


def test_bocha_parses_live_data_envelope_and_caches(tmp_path, monkeypatch):
    """线上实际成功响应：HTTP 200 + {code:200, data:{webPages:{value:[...]}}}"""
    _reset_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ci, "_summarize_fragments", lambda company, fragments: ("### 🏢 测试公司简报", True)
    )

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "code": 200,
        "msg": None,
        "log_id": "test-log-id",
        "data": {
            "_type": "SearchResponse",
            "queryContext": {"originalQuery": "测试公司"},
            "webPages": _webpages_payload(),
        },
    }

    with patch.object(ci.requests, "post", return_value=fake_response) as mock_post:
        result = ci.search_company_bocha("测试公司")

    assert result == "### 🏢 测试公司简报"
    # 4 路并发侦察：每路一次请求
    assert mock_post.call_count == 4
    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer sk-bocha-test"
    assert kwargs["json"]["summary"] is True
    assert kwargs["json"]["count"] == 5
    assert kwargs["proxies"] == {"http": None, "https": None}
    # LLM 汇总成功才写缓存
    assert ci._serper_cache
    cached = list(ci._serper_cache.values())[0]
    assert cached["intel"] == "### 🏢 测试公司简报"


def test_bocha_parses_legacy_top_level_webpages(tmp_path, monkeypatch):
    """兼容官网示例/旧版顶层 {webPages:{value:[...]}} 形状"""
    _reset_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ci, "_summarize_fragments", lambda company, fragments: ("### 旧版形状简报", True)
    )

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"webPages": _webpages_payload()}

    with patch.object(ci.requests, "post", return_value=fake_response):
        result = ci.search_company_bocha("测试公司")

    assert result == "### 旧版形状简报"


def test_bocha_business_error_in_http_200_returns_none(tmp_path, monkeypatch):
    """HTTP 200 但 code 非成功值（如额度不足）→ 视为失败，触发降级"""
    _reset_cache(tmp_path, monkeypatch)
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"code": 403, "msg": "quota", "data": None}

    with patch.object(ci.requests, "post", return_value=fake_response):
        assert ci._fetch_bocha("bad-key", "测试查询") is None


def test_bocha_hits_cache_without_network(tmp_path, monkeypatch):
    _reset_cache(tmp_path, monkeypatch)
    import time

    name = "广州图灵科技有限公司"
    # 缓存键与线上一致（normalize_company 归一化后再查），避免短公司名模糊匹配不命中
    ci._serper_cache[ci._serper_cache_key(name)] = {"intel": "### 缓存简报", "ts": time.time()}

    with patch.object(ci.requests, "post") as mock_post:
        result = ci.search_company_bocha(name)

    mock_post.assert_not_called()
    assert result == "### 缓存简报"


def test_bocha_http_error_returns_none(tmp_path, monkeypatch):
    _reset_cache(tmp_path, monkeypatch)
    fake_response = MagicMock(status_code=401, text='{"code":"401","message":"invalid key"}')

    with patch.object(ci.requests, "post", return_value=fake_response):
        assert ci._fetch_bocha("bad-key", "测试查询") is None


def test_bocha_all_requests_failed_raises_for_fallback(tmp_path, monkeypatch):
    """4 路全部失败时必须抛错，让调度器降级 Serper/Tavily，而不是误报「未检索到」"""
    _reset_cache(tmp_path, monkeypatch)
    fake_response = MagicMock(status_code=401, text='{"code":"401","message":"invalid key"}')

    with patch.object(ci.requests, "post", return_value=fake_response):
        try:
            ci.search_company_bocha("测试公司")
        except RuntimeError as exc:
            assert str(exc) == "BOCHA_REQUEST_FAILED"
        else:  # pragma: no cover
            raise AssertionError("4 路全部失败时应抛 RuntimeError")


def test_bocha_partial_failure_with_no_results_raises_for_fallback(tmp_path, monkeypatch):
    """2 路失败 + 2 路成功但零结果：必须抛错降级，不能误报「未检索到」"""
    _reset_cache(tmp_path, monkeypatch)

    def fake_fetch(api_key, query, freshness="oneYear"):
        # 按查询词固定失败两路，避免线程调度导致计数不确定
        return None if ("核心业务" in query or "竞品" in query) else {}

    monkeypatch.setattr(ci, "_fetch_bocha", fake_fetch)

    try:
        ci.search_company_bocha("测试公司")
    except RuntimeError as exc:
        assert str(exc) == "BOCHA_PARTIAL_FAILED"
    else:  # pragma: no cover
        raise AssertionError("部分请求失败且零结果时应抛 RuntimeError")


def test_bocha_all_success_no_results_returns_not_found(tmp_path, monkeypatch):
    """4 路全部成功且确实无结果：才返回「未检索到」"""
    _reset_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(ci, "_fetch_bocha", lambda *args, **kwargs: {})

    result = ci.search_company_bocha("测试公司")
    assert result.startswith("未检索到该公司")


def test_bocha_not_configured_raises(monkeypatch):
    monkeypatch.setattr(ci, "get_bocha_api_key", lambda: None)

    try:
        ci.search_company_bocha("测试公司")
    except RuntimeError as exc:
        assert str(exc) == "BOCHA_NOT_CONFIGURED"
    else:  # pragma: no cover
        raise AssertionError("未配置 BOCHA_API_KEY 时应抛 RuntimeError")


def test_bocha_429_retries_with_backoff_then_succeeds(tmp_path, monkeypatch):
    """429 → 退避后重试成功：不浪费请求，退避等待按梯度执行"""
    _reset_cache(tmp_path, monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(ci.time, "sleep", lambda s: sleeps.append(s))

    resp_429 = MagicMock(status_code=429, text='{"code":"429","message":"You have reached the request limit"}')
    resp_ok = MagicMock(status_code=200)
    resp_ok.json.return_value = {"code": 200, "data": {"webPages": _webpages_payload()}}

    with patch.object(ci.requests, "post", side_effect=[resp_429, resp_ok]) as mock_post:
        result = ci._fetch_bocha("sk-bocha-test", "测试查询")

    assert result is not None and result.get("webPages")
    assert mock_post.call_count == 2
    assert sleeps == [2.0]


def test_bocha_429_exhausted_opens_global_cooldown(tmp_path, monkeypatch):
    """连续退避仍 429：耗尽后返回 None 并打开全进程冷却窗，后续请求零网络快速失败"""
    _reset_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(ci.time, "sleep", lambda s: None)

    resp_429 = MagicMock(status_code=429, text='{"code":"429","message":"You have reached the request limit"}')

    with patch.object(ci.requests, "post", return_value=resp_429) as mock_post:
        assert ci._fetch_bocha("sk-bocha-test", "测试查询") is None
        assert mock_post.call_count == ci._BOCHA_429_RETRIES + 1
        # 冷却窗已打开，且同一调用内不再重试
        assert ci._bocha_429_cooldown_active()
        # 冷却窗内的下一个请求快速失败，不发网络请求
        assert ci._fetch_bocha("sk-bocha-test", "后续查询") is None
        assert mock_post.call_count == ci._BOCHA_429_RETRIES + 1


def test_search_company_bocha_failfast_during_cooldown(tmp_path, monkeypatch):
    """冷却期内 search_company_bocha 直接抛 BOCHA_REQUEST_FAILED 降级 Serper，不扇出"""
    _reset_cache(tmp_path, monkeypatch)
    import time as _time
    monkeypatch.setattr(ci, "_bocha_429_cooldown_until", _time.time() + 60)

    with patch.object(ci.requests, "post") as mock_post:
        try:
            ci.search_company_bocha("测试公司")
        except RuntimeError as exc:
            assert str(exc) == "BOCHA_REQUEST_FAILED"
        else:  # pragma: no cover
            raise AssertionError("冷却窗内应快速失败以降级 Serper")
        mock_post.assert_not_called()


def test_bocha_non_429_http_error_never_retries(tmp_path, monkeypatch):
    """401 等非 429 错误保持原契约：打日志立即返回 None，不做退避重试"""
    _reset_cache(tmp_path, monkeypatch)
    resp_401 = MagicMock(status_code=401, text='{"code":"401","message":"invalid key"}')

    with patch.object(ci.requests, "post", return_value=resp_401) as mock_post:
        assert ci._fetch_bocha("bad-key", "测试查询") is None
    assert mock_post.call_count == 1
