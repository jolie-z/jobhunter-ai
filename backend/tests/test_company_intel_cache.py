import os
import time
from pathlib import Path
from unittest.mock import patch
import pytest

import ai_agents.company_intel as ci
from ai_agents.company_intel import (
    search_company_ai_news,
    _load_serper_cache,
    _save_serper_cache,
    _serper_cache_lookup,
    _serper_cache_key,
)


def test_serper_cache_load_save(tmp_path):
    """验证 Serper 磁盘缓存读写原子性与 TTL 机制"""
    cache_file = tmp_path / "test_serper_cache.json"
    ci._SERPER_CACHE_PATH = cache_file
    ci._serper_cache = {}

    # 写入一条缓存
    now = time.time()
    ci._serper_cache["测试公司"] = {"ts": now, "intel": "### 🏢 【测试公司】商业情报简报\n核心业务发展迅速"}
    _save_serper_cache()

    # 清空内存，重新 load
    ci._serper_cache = {}
    _load_serper_cache()
    assert "测试公司" in ci._serper_cache
    assert "核心业务发展迅速" in ci._serper_cache["测试公司"]["intel"]

    # 验证 lookup 命中
    hit = _serper_cache_lookup("测试公司", now)
    assert hit is not None
    assert "核心业务发展迅速" in hit["intel"]

    # 验证模糊匹配 (>=4 字符)
    hit_fuzzy = _serper_cache_lookup("测试公司集团", now)
    assert hit_fuzzy is not None

    # 验证过期失效
    hit_expired = _serper_cache_lookup("测试公司", now + (15 * 86400))
    assert hit_expired is None


def test_search_company_ai_news_hits_cache(tmp_path):
    """验证 search_company_ai_news 在命中缓存时不发起任何网络请求"""
    cache_file = tmp_path / "test_serper_cache.json"
    ci._SERPER_CACHE_PATH = cache_file
    ci._serper_cache = {
        "广州图灵科技有限公司": {
            "ts": time.time(),
            "intel": "### 🏢 【广州图灵科技有限公司】商业情报简报\n核心聚焦人工智能 Agent 平台研发与行业解决方案。",
        }
    }

    with patch("ai_agents.company_intel.requests.post") as mock_post:
        result = search_company_ai_news("广州图灵科技有限公司")
        mock_post.assert_not_called()
        assert "广州图灵科技有限公司" in result
        assert "核心聚焦人工智能 Agent" in result

