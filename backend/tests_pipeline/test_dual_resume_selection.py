"""
自动化测试：双简历独立选择体系 (全链路基准简历 vs 海投专属简历)
1. GET /api/pipeline/eval-config 返回基准简历与海投简历元数据
2. POST /api/pipeline/set-mass-apply-resume 设置海投专属简历并持久化
3. POST /api/pipeline/activate-resume 激活全链路基准简历
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router
from app.automation.db import get_autopilot_config, update_autopilot_config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.automation.db as adb
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()

    from app.services import feishu_service
    from app.strategy import service as strat_service

    mock_resumes = [
        {"record_id": "rec_base_001", "title": "通用产品经理基准版", "word_count": 5800, "status": "启用"},
        {"record_id": "rec_mass_002", "title": "海投通用版-精简", "word_count": 4200, "status": "草稿"},
    ]

    def _mock_get_active():
        return mock_resumes[0]

    def _mock_get_all():
        return list(mock_resumes)

    def _mock_activate(rec_id):
        for r in mock_resumes:
            r["status"] = "启用" if r["record_id"] == rec_id else "草稿"

    monkeypatch.setattr(feishu_service, "get_active_resume_meta", _mock_get_active)
    monkeypatch.setattr(feishu_service, "get_all_resumes_meta", _mock_get_all)
    monkeypatch.setattr(strat_service, "activate_target_resume", _mock_activate)

    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_eval_config_dual_resume(client):
    # 预设海投简历 ID
    update_autopilot_config(mass_apply_resume_id="rec_mass_002")

    r = client.get("/api/pipeline/eval-config")
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    data = res["data"]
    
    assert "active_resume" in data
    assert data["active_resume"]["record_id"] == "rec_base_001"
    
    assert "mass_apply_resume_id" in data
    assert data["mass_apply_resume_id"] == "rec_mass_002"
    assert "mass_apply_resume" in data
    assert data["mass_apply_resume"]["title"] == "海投通用版-精简"


def test_set_mass_apply_resume_endpoint(client):
    r = client.post("/api/pipeline/set-mass-apply-resume", json={"record_id": "rec_mass_002"})
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    assert res["data"]["mass_apply_resume_id"] == "rec_mass_002"
    assert res["data"]["mass_apply_resume"]["title"] == "海投通用版-精简"

    # 验证底层数据库持久化
    cfg = get_autopilot_config()
    assert cfg.get("mass_apply_resume_id") == "rec_mass_002"


def test_activate_base_resume_endpoint(client):
    r = client.post("/api/pipeline/activate-resume", json={"record_id": "rec_base_001"})
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    assert res["data"]["active_resume"]["record_id"] == "rec_base_001"
