"""
测试简历编辑器全量 API 在 FastAPI 主应用 (端口 8000 路由) 下的集成与连通性
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_01_resume_editor_platform_endpoints():
    """测试 /api/resume-editor/{platform} 获取各平台简历数据"""
    for platform in ["boss", "liepin", "51job", "zhilian"]:
        resp = client.get(f"/api/resume-editor/{platform}")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert isinstance(data.get("data"), dict)


def test_02_resume_editor_all_and_options():
    """测试 /api/resume-editor/all 和 /api/resume-editor/options/{platform}"""
    resp_all = client.get("/api/resume-editor/all")
    assert resp_all.status_code == 200
    assert resp_all.json().get("success") is True

    resp_opt = client.get("/api/resume-editor/options/liepin")
    assert resp_opt.status_code == 200
    assert resp_opt.json().get("success") is True

    resp_field = client.get("/api/resume-editor/options/zhilian/skills")
    assert resp_field.status_code == 200
    assert resp_field.json().get("success") is True


def test_03_platforms_status():
    """测试 /api/platforms/status 平台浏览器探测"""
    resp = client.get("/api/platforms/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert "platforms" in data
    assert "liepin" in data["platforms"]
    assert "boss" in data["platforms"]


def test_04_unified_batch_endpoints():
    """测试 /api/unified/collect 批量操作参数校验"""
    resp = client.post("/api/unified/collect", json={"platforms": []})
    assert resp.status_code == 400


def test_05_agent_map_endpoints():
    """测试 /api/agent-map/reports 与 /api/agent-map/resumes 路由"""
    resp_reports = client.get("/api/agent-map/reports")
    assert resp_reports.status_code == 200
    assert resp_reports.json().get("success") is True

    resp_resumes = client.get("/api/agent-map/resumes")
    assert resp_resumes.status_code == 200
    assert resp_resumes.json().get("success") is True
