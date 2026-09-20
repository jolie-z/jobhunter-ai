"""JD 能力画像接口测试（纯离线：所有飞书/LLM 调用均在 service 边界 mock）。

注意：service 层的 update/get_global_jd_report 使用同步 requests + 直接导入的
get_tenant_access_token，因此必须 patch `app.strategy.service.requests` 和
`app.strategy.service.get_tenant_access_token`（patch 源模块无效）。
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_httpx_client():
    """generate 的第一步（搜索 A 级岗位）走 httpx.AsyncClient。"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_client_class.return_value.__aenter__.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_openai():
    with patch("app.strategy.service.get_openai_client") as mock:
        yield mock


@pytest.fixture
def mock_feishu_token():
    """generate 开头的异步 token（feishu_client）与 service 内同步 token 各一套。"""
    with patch("app.strategy.service.feishu_client.get_tenant_access_token", new_callable=AsyncMock) as mock_async:
        mock_async.return_value = "fake_token"
        with patch("app.strategy.service.get_tenant_access_token") as mock_sync:
            mock_sync.return_value = "fake_token"
            yield mock_async


@pytest.fixture
def mock_service_requests():
    """update/get_global_jd_report 的同步 requests 调用。"""
    with patch("app.strategy.service.requests") as mock_requests:
        mock_requests.post.return_value = MagicMock(
            status_code=200,
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={
                "code": 0,
                "data": {"items": [{"record_id": "res_rec_1", "fields": {}}]},
            }),
        )
        mock_requests.put.return_value = MagicMock(
            status_code=200,
            raise_for_status=MagicMock(),
            json=MagicMock(return_value={"code": 0}),
        )
        yield mock_requests


def test_generate_jd_report_success(
    mock_httpx_client, mock_openai, mock_feishu_token, mock_service_requests
):
    # httpx 搜索 A 级岗位
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "code": 0,
        "data": {
            "items": [
                {
                    "record_id": "rec123",
                    "fields": {
                        "岗位名称": "AI Engineer",
                        "岗位详情": "FastAPI, React, Pytest",
                    },
                }
            ]
        },
    }
    mock_httpx_client.post.return_value = mock_post_resp

    # LLM 生成
    mock_llm_resp = MagicMock()
    mock_llm_resp.choices = [MagicMock(message=MagicMock(content="Mocked JD Report"))]
    mock_openai.return_value.chat.completions.create.return_value = mock_llm_resp

    response = client.post("/api/strategy/generate_jd_report")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    # 修复回归点：service 曾丢失 return，导致接口 success 但 data 为 null
    assert data["data"] == "Mocked JD Report"
    assert mock_httpx_client.post.call_count == 1
    # update_global_jd_report：requests.post 找启用简历 + requests.put 回写
    assert mock_service_requests.post.call_count == 1
    assert mock_service_requests.put.call_count == 1
    assert mock_openai.return_value.chat.completions.create.call_count == 1


def test_get_jd_report_success(mock_feishu_token, mock_service_requests):
    mock_service_requests.post.return_value.json.return_value = {
        "code": 0,
        "data": {
            "items": [
                {
                    "record_id": "rec456",
                    "fields": {"全局A级JD能力画像": "Existing JD Report Content"},
                }
            ]
        },
    }

    response = client.get("/api/strategy/get_jd_report")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["data"] == "Existing JD Report Content"
    assert mock_service_requests.post.call_count == 1
    assert mock_service_requests.put.call_count == 0
