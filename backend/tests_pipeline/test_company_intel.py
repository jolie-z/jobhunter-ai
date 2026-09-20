"""
自动化测试：公司情报统一调度器 fetch_company_intel
验证点：
1. Serper 主引擎成功 → 直接采用，不触发 Tavily
2. 未配置 SERPER_API_KEY → 自动降级 Tavily
3. Serper 请求异常 → 自动降级 Tavily
4. 匿名/未知公司 → 直接返回 ⚠️ 占位，不发起任何网络请求
"""

from unittest.mock import MagicMock

from ai_agents.company_intel import fetch_company_intel


def test_serper_success_short_circuits_tavily(monkeypatch):
    """Serper 主引擎成功时直接采用，Tavily 不应被调用"""
    mock_serper = MagicMock(return_value="### 🏢 【测试科技】商业情报简报\n**1. 核心业务与市场地位**\n企业级大模型应用。")
    mock_tavily = MagicMock(return_value="【不应该被调用】")
    monkeypatch.setattr("ai_agents.company_intel.search_company_ai_news", mock_serper)
    monkeypatch.setattr("ai_agents.company_intel.search_company_info_tavily", mock_tavily)

    intel = fetch_company_intel("测试科技股份有限公司")

    mock_serper.assert_called_once_with("测试科技股份有限公司")
    mock_tavily.assert_not_called()
    assert "商业情报简报" in intel


def test_falls_back_to_tavily_when_serper_not_configured(monkeypatch):
    """未配置 SERPER_API_KEY（RuntimeError）时降级 Tavily"""
    def _raise_no_key(company):
        raise RuntimeError("SERPER_NOT_CONFIGURED")

    mock_tavily = MagicMock(return_value="【测试科技 公司情报】\n· 来自 Tavily 的情报。")
    monkeypatch.setattr("ai_agents.company_intel.search_company_ai_news", _raise_no_key)
    monkeypatch.setattr("ai_agents.company_intel.search_company_info_tavily", mock_tavily)

    intel = fetch_company_intel("测试科技股份有限公司")

    mock_tavily.assert_called_once_with("测试科技股份有限公司")
    assert "Tavily 的情报" in intel


def test_falls_back_to_tavily_when_serper_errors(monkeypatch):
    """Serper 网络异常时降级 Tavily"""
    def _raise_network(company):
        raise ConnectionError("timeout")

    mock_tavily = MagicMock(return_value="【测试科技 公司情报】\n· 来自 Tavily 的情报。")
    monkeypatch.setattr("ai_agents.company_intel.search_company_ai_news", _raise_network)
    monkeypatch.setattr("ai_agents.company_intel.search_company_info_tavily", mock_tavily)

    intel = fetch_company_intel("测试科技股份有限公司")

    mock_tavily.assert_called_once()
    assert intel.startswith("【测试科技")


def test_anonymous_company_skips_all_engines(monkeypatch):
    """匿名/未知公司直接返回 ⚠️ 占位，两个引擎都不触发"""
    mock_serper = MagicMock(return_value="【不应该被调用】")
    mock_tavily = MagicMock(return_value="【不应该被调用】")
    monkeypatch.setattr("ai_agents.company_intel.search_company_ai_news", mock_serper)
    monkeypatch.setattr("ai_agents.company_intel.search_company_info_tavily", mock_tavily)

    for company in ("未知公司", "某科技公司", "", "保密"):
        intel = fetch_company_intel(company)
        assert intel.startswith("⚠️"), f"{company!r} 应返回 ⚠️ 占位"

    mock_serper.assert_not_called()
    mock_tavily.assert_not_called()
