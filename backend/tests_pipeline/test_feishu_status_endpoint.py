"""
自动化测试：飞书多维表格推送配置与连通性探针
1. GET /api/pipeline/feishu-status 返回状态与多维表格元数据
2. POST /api/pipeline/feishu-test 测试鉴权
3. POST /api/pipeline/feishu-config 更新推送与风控参数
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router
from app.core.feishu_client import feishu_client


@pytest.fixture()
def client():
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_feishu_status_endpoint(client):
    r = client.get("/api/pipeline/feishu-status")
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    data = res["data"]
    assert "is_configured" in data
    assert "total_records" in data
    assert "bitable_url" in data
    assert "batch_limit" in data


def test_feishu_test_connection_endpoint(client, monkeypatch):
    async def mock_token():
        return "t-mock-token-123456"

    monkeypatch.setattr(feishu_client, "get_tenant_access_token", mock_token)

    r = client.post("/api/pipeline/feishu-test")
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    assert "鉴权成功" in res["msg"]


def test_feishu_config_save_endpoint(client):
    r = client.post("/api/pipeline/feishu-config", json={"batch_limit": 60, "enable_report": True})
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    assert "已保存" in res["msg"]

    # 读取验证
    status_r = client.get("/api/pipeline/feishu-status")
    assert status_r.json()["data"]["batch_limit"] == 60
