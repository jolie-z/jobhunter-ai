import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router
import app.automation.db as adb


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()
    
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_review_config_endpoint_roundtrip(client, monkeypatch):
    # Mock feishu_service get_pending_review_jobs_from_feishu
    mock_jobs = [
        {
            "job_id": "rec_test_1",
            "job_name": "高级前端工程师",
            "company_name": "腾讯",
            "platform": "boss",
            "grade": "A",
            "salary": "30-50K",
            "city": "深圳",
            "has_image": True,
            "has_pdf": False,
            "has_greeting": True,
            "greeting_text": "您好，认真看了贵公司岗位JD...",
            "is_custom": True,
            "status": "waiting",
            "node": "manual_review_node",
        },
        {
            "job_id": "rec_test_2",
            "job_name": "架构师",
            "company_name": "阿里巴巴",
            "platform": "liepin",
            "grade": "B",
            "salary": "40-70K",
            "city": "杭州",
            "has_image": False,
            "has_pdf": True,
            "has_greeting": True,
            "greeting_text": "您好，认真看了贵公司岗位JD...",
            "is_custom": True,
            "status": "waiting",
            "node": "manual_review_node",
        },
    ]

    import app.services.feishu_service as fs
    monkeypatch.setattr(fs, "get_pending_review_jobs_from_feishu", lambda: mock_jobs)

    # 1. GET 默认配置
    res = client.get("/api/pipeline/review-config")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["mass_apply_max_headcount"] == 1000
    assert len(data["pending_jobs"]) == 2
    assert data["pending_jobs"][0]["has_image"] is True
    assert data["pending_jobs"][1]["has_pdf"] is True

    # 2. POST 保存大公司门槛
    save_res = client.post("/api/pipeline/review-config", json={"mass_apply_max_headcount": 2000})
    assert save_res.status_code == 200
    assert save_res.json()["code"] == 0

    # 3. GET 验证持久化
    res2 = client.get("/api/pipeline/review-config")
    assert res2.status_code == 200
    assert res2.json()["data"]["mass_apply_max_headcount"] == 2000
