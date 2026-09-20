import pytest
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app

client = TestClient(app)


def test_get_rewrite_config():
    """测试获取简历改写阶段配置"""
    res = client.get("/api/pipeline/rewrite-config")
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == 0
    assert "skills" in data["data"]
    assert "current_skill_id" in data["data"]
    assert "include_diagnosis" in data["data"]
    assert "prompt_rules" in data["data"]
    assert isinstance(data["data"]["skills"], list)
    assert len(data["data"]["prompt_rules"]) >= 4


def test_save_rewrite_config():
    """测试更新简历改写阶段配置（切换 Skill 与协同开关）"""
    payload = {
        "skill_id": "resume_rewrite",
        "include_diagnosis": True
    }
    res = client.post("/api/pipeline/rewrite-config", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == 0

    # 再次读取验证
    res2 = client.get("/api/pipeline/rewrite-config")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["data"]["current_skill_id"] == "resume_rewrite"
    assert data2["data"]["include_diagnosis"] is True
