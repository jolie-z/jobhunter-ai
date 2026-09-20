"""
自动化测试：第 9 阶段 自动投递 (delivery) 规则设置 API
1. GET /api/pipeline/delivery-config 验证字段结构（目标平台、双轨定时时间、超时熔断秒数、物料搭载审计流水）
2. POST /api/pipeline/delivery-config 验证更新持久化与还原
"""

import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router


import app.automation.db as adb


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


import time
from datetime import datetime


def test_delivery_config_roundtrip(client):
    now_ms = int(datetime.now().timestamp() * 1000)
    with patch("app.services.feishu_service.get_tenant_access_token", return_value="mock_token"), \
         patch("app.services.feishu_service.safe_feishu_request") as mock_post:
        mock_post.return_value.json.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "record_id": "rec_deliv_001",
                        "fields": {
                            "岗位名称": "AI算法专家",
                            "公司名称": "前沿科技",
                            "招聘平台": "BOSS直聘",
                            "综合等级": "A",
                            "薪资": "35-50K",
                            "图片保存": [{"file_token": "img_001"}],
                            "打招呼语": "您好，我对该岗位非常感兴趣！",
                            "跟进状态": "已投递",
                            "投递日期": now_ms,
                        },
                    }
                ],
                "has_more": False,
            },
        }

        # 1. GET 读取测试
        r = client.get("/api/pipeline/delivery-config")
        assert r.status_code == 200
        res = r.json()
        assert res["code"] == 0
        data = res["data"]
        assert "auto_deliver_platforms" in data
        assert "mass_deliver_time" in data
        assert "custom_deliver_mode" in data
        assert "custom_deliver_time" in data
        assert "delivery_timeout_sec" in data
        assert "batch_limit" in data
        assert "delivered_jobs" in data
        assert len(data["delivered_jobs"]) >= 1
        first_job = data["delivered_jobs"][0]
        assert first_job["has_image"] is True
        assert first_job["has_greeting"] is True
        assert first_job["status"] == "delivered"

        # 2. POST 保存测试
        payload = {
            "auto_deliver_platforms": ["boss", "liepin"],
            "mass_deliver_time": "10:00",
            "custom_deliver_mode": "scheduled",
            "custom_deliver_time": "14:30",
            "delivery_timeout_sec": 60,
            "batch_limit": 15,
        }
        post_r = client.post("/api/pipeline/delivery-config", json=payload)
        assert post_r.status_code == 200
        post_res = post_r.json()
        assert post_res["code"] == 0

        # 3. 再次 GET 验证保存生效
        r2 = client.get("/api/pipeline/delivery-config")
        assert r2.status_code == 200
        d2 = r2.json()["data"]
        assert d2["auto_deliver_platforms"] == ["boss", "liepin"]
        assert d2["mass_deliver_time"] == "10:00"
        assert d2["custom_deliver_mode"] == "scheduled"
        assert d2["custom_deliver_time"] == "14:30"
        assert d2["delivery_timeout_sec"] == 60
        assert d2["batch_limit"] == 15
