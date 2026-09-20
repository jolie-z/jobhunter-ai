import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router
import app.automation.db as adb
from ai_agents.skill_greeting import run_skill_based_greeting


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()
    
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_greeting_config_endpoint_roundtrip(client):
    # 1. GET 默认配置
    res = client.get("/api/pipeline/greeting-config")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["greeting_platforms"] == {"boss": True, "liepin": True, "zhilian": True, "51job": False}
    assert len(data["prompt_rules"]) >= 4
    assert "核心胜任力我是全覆盖的" in data["opening_template"]
    assert "期待和您有关于岗位的深度沟通" in data["closing_template"]
    assert data["prompt_mode"] == "official"
    assert "CRITICAL" in data["official_prompt"]
    assert data["custom_prompt"] == ""

    # 2. POST 保存自定义 Prompt 与平台配置
    custom_text = "你是一个专业猎头顾问，请用极为精炼的3句话输出开场白。"
    new_payload = {
        "greeting_platforms": {"boss": True, "liepin": False, "51job": True, "zhilian": False},
        "mass_apply_greeting": "您好，这是我的通用海投话术测试...",
        "prompt_mode": "custom",
        "custom_prompt": custom_text,
    }
    save_res = client.post("/api/pipeline/greeting-config", json=new_payload)
    assert save_res.status_code == 200
    assert save_res.json()["code"] == 0

    # 3. GET 再次读取验证持久化成功
    res2 = client.get("/api/pipeline/greeting-config")
    assert res2.status_code == 200
    data2 = res2.json()["data"]
    assert data2["greeting_platforms"] == {"boss": True, "liepin": False, "51job": True, "zhilian": False}
    assert data2["mass_apply_greeting"] == "您好，这是我的通用海投话术测试..."
    assert data2["prompt_mode"] == "custom"
    assert data2["custom_prompt"] == custom_text


def test_review_config_patch_preserves_greeting(client):
    """严格 PATCH 回归：待审批面板保存只写自己的字段，不得用旧快照覆盖打招呼语。

    对应 2026-09 QA 排查批次：历史实现里各面板保存会把全量字段现读现写回库，
    存在跨面板互相覆盖隐患；现改为各面板只传自己负责的字段。
    """
    greeting = "您好，这是需要被跨面板保存保护住的通用海投话术。"
    save_res = client.post("/api/pipeline/greeting-config", json={"mass_apply_greeting": greeting})
    assert save_res.status_code == 200
    assert save_res.json()["code"] == 0

    review_res = client.post("/api/pipeline/review-config", json={"mass_apply_max_headcount": 888})
    assert review_res.status_code == 200

    data = client.get("/api/pipeline/greeting-config").json()["data"]
    assert data["mass_apply_greeting"] == greeting
    assert adb.get_autopilot_config()["mass_apply_max_headcount"] == 888


def test_dashboard_sync_aggregates_stage_payloads(client):
    """dashboard-sync 聚合接口：四个子 payload 与原离散轮询接口响应体同构。"""
    from fastapi.testclient import TestClient as _TC

    from app.automation.router import router as automation_router

    auto_api = FastAPI()
    auto_api.include_router(automation_router, prefix="/api/automation")
    auto_client = _TC(auto_api)

    res = auto_client.get("/api/automation/dashboard-sync")
    assert res.status_code == 200
    payload = res.json()["data"]

    # 配置状态：与 /api/pipeline/config-status 同构
    assert payload["config_status"]["code"] == 0
    assert "greeting" in payload["config_status"]["data"]["modules"]

    # 当前链路 / 抓取台账：与 /api/automation/current-pipeline、/run-snapshot 同构
    assert "data" in payload["current_pipeline"]
    assert "data" in payload["run_snapshot"]

    # 岗位快照：与 /api/automation/jobs-snapshot 同构（data 为数组 + task_id/delivery_schedule）
    jobs_payload = payload["jobs_snapshot"]
    assert isinstance(jobs_payload["data"], list)
    assert "task_id" in jobs_payload
    assert "delivery_schedule" in jobs_payload
