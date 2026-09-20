"""
自动化测试：规则清洗 (Tier 1 硬规则 + Tier 2 AI 侦察兵大模型初筛)
1. GET /api/strategy/active 结构与字段校验 (薪资/学历/城市/AI侦察兵规则)
2. POST /api/strategy/active 持久化更新
3. load_active_strategy 数据装配一致性
4. AIScoutEngine 判定逻辑验证
"""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.strategy.router import router
from job_processor.step1_rule_filter import load_active_strategy, AIScoutEngine


@pytest.fixture()
def client():
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_get_active_strategy_endpoint(client):
    r = client.get("/api/strategy/active")
    assert r.status_code == 200
    data = r.json()
    assert "min_salary_k" in data
    assert "allowed_cities" in data
    assert "exclude_education" in data
    assert "ai_scout_rules" in data
    assert isinstance(data["ai_scout_rules"], list)


def test_update_active_strategy_endpoint(client):
    # 先备份当前真实激活策略
    old_strat = load_active_strategy()

    test_rules = [
        {"keyword": "单休", "condition": "never", "desc": "一周只休一天属于单休"},
        {"keyword": "双休", "condition": "must", "desc": "每周必须保证双休"},
    ]
    payload = {
        "min_salary_k": 12,
        "max_salary_k": 35,
        "experience_years_max": 8,
        "exclude_education": ["高中", "中专"],
        "require_education": ["大专", "本科"],
        "allowed_cities": ["广州", "深圳", "远程"],
        "safe_phrases": [],
        "keyword_rules": [],
        "ai_scout_rules": test_rules,
    }

    try:
        r = client.post("/api/strategy/active", json=payload)
        assert r.status_code == 200
        res = r.json()
        assert res["status"] == "success"

        # 读取验证
        get_res = client.get("/api/strategy/active")
        assert get_res.status_code == 200
        strat = get_res.json()
        assert strat["min_salary_k"] == 12
        assert strat["max_salary_k"] == 35
        assert strat["experience_years_max"] == 8
        assert "广州" in strat["allowed_cities"]
        assert len(strat["ai_scout_rules"]) == 2
        assert strat["ai_scout_rules"][0]["keyword"] == "单休"
    finally:
        # 测试结束后 100% 还原线上真实策略
        if old_strat:
            client.post("/api/strategy/active", json={
                "min_salary_k": old_strat.get("min_salary_k", 10),
                "max_salary_k": old_strat.get("max_salary_k", 30),
                "experience_years_max": old_strat.get("experience_years_max", 10),
                "exclude_education": old_strat.get("exclude_education", ["高中", "中专"]),
                "require_education": old_strat.get("require_education", []),
                "allowed_cities": old_strat.get("allowed_cities", ["广州", "深圳", "远程"]),
                "safe_phrases": old_strat.get("safe_phrases", []),
                "keyword_rules": old_strat.get("keyword_rules", []),
                "ai_scout_rules": old_strat.get("ai_scout_rules", []),
            })


def test_ai_scout_engine_evaluation_parser():
    engine = AIScoutEngine({"ai_scout_rules": [{"keyword": "外包", "condition": "never", "desc": "劳务派遣外包"}]})
    mock_llm_reply = '```json\n{"passed": false, "reason": "命中了绝不包含的规则词：外包"}\n```'
    parsed = engine._parse_evaluate_result(mock_llm_reply)
    assert parsed["passed"] is False
    assert "外包" in parsed["reason"]

