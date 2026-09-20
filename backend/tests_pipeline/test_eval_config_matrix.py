"""
自动化测试：AI 初评矩阵 (模型/并发通道/8维权重/流转阀门/偏好矩阵)
1. GET /api/pipeline/eval-config 结构完整性与8维度校验
2. POST /api/pipeline/eval-config 权重与流转阈值更新与持久化
3. POST /api/pipeline/eval-preferences 新增/状态切换与 DELETE 删除偏好项
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router


@pytest.fixture()
def client(monkeypatch):
    import app.strategy.service as strat_service
    
    _mock_prefs = [{"record_id": "rec_thresh_1", "type": "自动化阈值", "rule": "A", "status": "启用"}]
    
    async def _mock_get_prefs():
        return list(_mock_prefs)
        
    async def _mock_upsert_pref(req):
        for p in _mock_prefs:
            if p.get("record_id") == req.record_id or (req.type == "自动化阈值" and p.get("type") == "自动化阈值"):
                p["rule"] = req.rule
                p["status"] = req.status
                return p["record_id"]
        rec_id = f"rec_new_{len(_mock_prefs)+1}"
        _mock_prefs.append({"record_id": rec_id, "type": req.type, "rule": req.rule, "status": req.status})
        return rec_id

    async def _mock_delete_pref(rec_id):
        nonlocal _mock_prefs
        _mock_prefs = [p for p in _mock_prefs if p.get("record_id") != rec_id]
        return True

    monkeypatch.setattr(strat_service, "get_preferences_service", _mock_get_prefs)
    monkeypatch.setattr(strat_service, "upsert_preference_service", _mock_upsert_pref)
    monkeypatch.setattr(strat_service, "delete_preference_service", _mock_delete_pref)

    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_get_eval_config_endpoint(client):
    r = client.get("/api/pipeline/eval-config")
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    data = res["data"]
    assert "model_name" in data
    assert "concurrency" in data
    assert "threshold" in data
    assert "weights" in data
    assert "enable_company_search" in data
    assert "tavily_configured" in data
    weights = data["weights"]
    for dim in ["role_match", "skills_align", "seniority", "compensation", "interview_prob", "market_fit", "growth", "company_stage"]:
        assert dim in weights


def test_save_eval_config_endpoint(client):
    payload = {
        "concurrency": 8,
        "threshold": "B",
        "enable_company_search": False,
        "weights": {
            "role_match": 1.0,
            "skills_align": 0.9,
            "seniority": 0.8,
            "compensation": 1.0,
            "interview_prob": 0.8,
            "market_fit": 0.6,
            "growth": 0.7,
            "company_stage": 0.3,
        }
    }
    r = client.post("/api/pipeline/eval-config", json=payload)
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    assert "已保存" in res["msg"]

    # 验证读取
    check_r = client.get("/api/pipeline/eval-config")
    d = check_r.json()["data"]
    assert d["concurrency"] == 8
    assert d["threshold"] == "B"
    assert d["enable_company_search"] is False
    assert d["weights"]["compensation"] == 1.0

    # 恢复 enable_company_search 为 True
    client.post("/api/pipeline/eval-config", json={"enable_company_search": True})


def test_eval_preferences_lifecycle(client):
    # 1. 新增
    r1 = client.post("/api/pipeline/eval-preferences", json={
        "type": "核心加分",
        "rule": "测试自动化偏好：熟悉 LangGraph 框架",
        "status": "启用"
    })
    assert r1.status_code == 200
    rec_id = r1.json()["data"]["record_id"]
    assert rec_id is not None

    # 2. 状态更新
    r2 = client.post("/api/pipeline/eval-preferences", json={
        "record_id": rec_id,
        "type": "核心加分",
        "rule": "测试自动化偏好：熟悉 LangGraph 框架",
        "status": "停用"
    })
    assert r2.status_code == 200

    # 3. 删除
    r3 = client.delete(f"/api/pipeline/eval-preferences/{rec_id}")
    assert r3.status_code == 200
    assert r3.json()["code"] == 0
