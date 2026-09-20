import pytest
from fastapi.testclient import TestClient
import app.automation.db as adb

def test_save_and_get_autopilot_config(tmp_path, monkeypatch, client: TestClient):
    # 隔离测试数据库，禁止写入生产 autopilot.db
    test_db = str(tmp_path / "autopilot.db")
    monkeypatch.setattr(adb, "DB_PATH", test_db)
    adb.init_autopilot_db()

    # Test data representing all platforms
    payload = {
        "cron_time": "10:30",
        "auto_deliver_grades": ["A", "B"],
        "is_enabled": True,
        "platform_configs": {
            "boss": {"limit": 10, "keyword": "前端", "city": "北京", "salary": "20K-30K"},
            "xiaohongshu": {"limit": 5, "keyword": "产品", "sort_by": "time_descending"},
            "liepin": {"limit": 8, "keyword": "后端", "city": "上海", "salary": "30K-50K"},
            "zhilian": {"limit": 2, "keyword": "测试", "city": "广州", "salary": "10K-15K"},
            "51job": {"limit": 1, "keyword": "运维", "city": "深圳", "salary": "15K-20K"}
        }
    }

    # 1. POST config
    response = client.post("/api/automation/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"

    # 2. GET config to verify persistence
    response = client.get("/api/automation/config")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    
    config = data["data"]
    assert config["cron_time"] == "10:30"
    assert "A" in config["auto_deliver_grades"]
    assert config["is_enabled"] is True
    
    platforms = config["platform_configs"]
    
    # Verify all platforms
    assert platforms["boss"]["salary"] == "20K-30K"
    assert platforms["boss"]["limit"] == 10
    
    assert platforms["xiaohongshu"]["sort_by"] == "time_descending"
    assert platforms["xiaohongshu"]["limit"] == 5
    
    assert platforms["liepin"]["city"] == "上海"
    assert platforms["liepin"]["salary"] == "30K-50K"
    
    assert platforms["zhilian"]["salary"] == "10K-15K"
    assert platforms["zhilian"]["keyword"] == "测试"
    
    assert platforms["51job"]["city"] == "深圳"
    assert platforms["51job"]["limit"] == 1


def test_save_config_partial_preserves_greeting(tmp_path, monkeypatch, client: TestClient):
    """验证 PATCH 防覆盖回归：只传部分字段保存时，未传入的打招呼语与海投白名单绝不得被清空。"""
    test_db = str(tmp_path / "autopilot.db")
    monkeypatch.setattr(adb, "DB_PATH", test_db)
    adb.init_autopilot_db()

    # 1. 预先设置好打招呼语和投递等级
    original_greeting = "您好，这是现有的通用海投打招呼语。"
    adb.update_autopilot_config(
        mass_apply_greeting=original_greeting,
        auto_deliver_grades=["C", "D", "F"],
    )

    # 2. 模拟前端仅更新定时任务，未传 mass_apply_greeting
    partial_payload = {
        "cron_time": "08:30",
        "is_enabled": True,
    }
    resp = client.post("/api/automation/config", json=partial_payload)
    assert resp.status_code == 200

    # 3. 校验打招呼语与投递等级依然完好
    cfg = adb.get_autopilot_config()
    assert cfg["cron_time"] == "08:30"
    assert cfg["mass_apply_greeting"] == original_greeting
    assert cfg["auto_deliver_grades"] == ["C", "D", "F"]

