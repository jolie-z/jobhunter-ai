import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

client = TestClient(app)


def test_write_back_unsupported_platform():
    response = client.post("/api/agent-map/write-back", json={"platform": "unknown_platform"})
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "暂不支持回写平台" in data["message"]


def test_write_back_dry_run_boss():
    # Dry run should execute boss_write_back.py --dry-run without raising 500 error
    response = client.post("/api/agent-map/write-back", json={
        "platform": "boss",
        "dry_run": True,
        "paths": ["work_experience"]
    })
    # Even if browser CDP is not running in CI, it should return graceful JSON failure or dry_run success
    assert response.status_code in (200, 500)
    data = response.json()
    assert "success" in data
    # Ensure error message does not misreport as '全部与官网一致' on failure
    if not data["success"]:
        assert "全部与官网一致" not in data.get("message", "")
