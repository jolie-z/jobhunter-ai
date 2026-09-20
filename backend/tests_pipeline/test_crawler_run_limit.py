import pytest
from unittest.mock import patch
from pydantic import ValidationError
from app.api.routes.crawlers import SpiderRunRequest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_spider_run_request_pydantic_validation():
    """测试 SpiderRunRequest 模型的 target_jobs 50 边界验证"""
    # 50 应该正常通过
    req_50 = SpiderRunRequest(
        platform="boss",
        keyword="产品经理",
        target_jobs=50
    )
    assert req_50.target_jobs == 50

    # 1 应该正常通过
    req_1 = SpiderRunRequest(
        platform="boss",
        keyword="产品经理",
        target_jobs=1
    )
    assert req_1.target_jobs == 1

    # 51 必须抛出 ValidationError
    with pytest.raises(ValidationError) as exc_info:
        SpiderRunRequest(
            platform="boss",
            keyword="产品经理",
            target_jobs=51
        )
    assert "target_jobs" in str(exc_info.value)

    # 500 必须抛出 ValidationError
    with pytest.raises(ValidationError) as exc_info:
        SpiderRunRequest(
            platform="boss",
            keyword="产品经理",
            target_jobs=500
        )
    assert "target_jobs" in str(exc_info.value)

def test_crawler_endpoint_rejects_over_50():
    """测试 /api/v1/crawlers/run 接口拒绝大于 50 的抓取目标数（返回 422）"""
    resp = client.post("/api/v1/crawlers/run", json={
        "platform": "boss",
        "keyword": "测试工程师",
        "city": "广州",
        "salary": "不限",
        "start_page": 1,
        "target_jobs": 51,
    })
    assert resp.status_code == 422
    assert "target_jobs" in str(resp.json())
