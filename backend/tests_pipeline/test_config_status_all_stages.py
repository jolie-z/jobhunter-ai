"""
全链路 9 阶段就绪检测与强阻断规则测试 (/api/pipeline/config-status)
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.automation.db as adb
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()
    return TestClient(app)


def test_config_status_contains_all_nine_stages(client):
    """测试 /api/pipeline/config-status 返回全量 9 大阶段状态"""
    resp = client.get("/api/pipeline/config-status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    modules = data["modules"]
    
    expected_stages = [
        "scraping",
        "cleaning",
        "feishu_sync",
        "evaluating",
        "deep_eval",
        "rewriting",
        "greeting",
        "review",
        "delivering",
    ]
    for stage in expected_stages:
        assert stage in modules, f"Stage {stage} should be present in config-status modules"
    
    assert "required_keys" in data
    assert "greeting" in data["required_keys"]
    assert "review" in data["required_keys"]
    assert "all_configured" in data


def test_greeting_and_review_readiness_logic(client):
    """测试打招呼语（通用话术非空）与待审批（大公司门槛人数>0）在 config-status 中的判定"""
    from app.automation.db import get_autopilot_config, update_autopilot_config
    orig_cfg = get_autopilot_config()

    try:
        # 1. 保存打招呼语
        client.post(
            "/api/pipeline/greeting-config",
            json={
                "mass_apply_greeting": orig_cfg.get("mass_apply_greeting") or "您好，认真看了贵公司岗位JD...",
                "greeting_platforms": {"boss": True, "liepin": True},
            },
        )
        # 2. 保存待审批
        client.post(
            "/api/pipeline/review-config",
            json={"mass_apply_max_headcount": 500},
        )
        
        resp = client.get("/api/pipeline/config-status")
        assert resp.status_code == 200
        modules = resp.json()["data"]["modules"]
        assert modules["greeting"] is True
        assert modules["review"] is True
    finally:
        # 恢复原配置，防止污染真实数据库
        update_autopilot_config(
            cron_time=orig_cfg.get("cron_time", "09:00"),
            auto_deliver_grades=orig_cfg.get("auto_deliver_grades", ["C", "D", "E", "F"]),
            auto_deliver_platforms=orig_cfg.get("auto_deliver_platforms", ["boss", "liepin", "51job", "zhilian"]),
            is_enabled=orig_cfg.get("is_enabled", True),
            platform_configs=orig_cfg.get("platform_configs", {}),
            batch_limit=orig_cfg.get("batch_limit", 20),
            mass_apply_resume_id=orig_cfg.get("mass_apply_resume_id", ""),
            rewrite_base_resume_id=orig_cfg.get("rewrite_base_resume_id", ""),
            mass_apply_max_headcount=orig_cfg.get("mass_apply_max_headcount", 1000),
            mass_apply_greeting=orig_cfg.get("mass_apply_greeting", ""),
            greeting_platforms=orig_cfg.get("greeting_platforms"),
            eval_concurrency=orig_cfg.get("eval_concurrency", 5),
            enable_company_search=orig_cfg.get("enable_company_search", True),
        )
