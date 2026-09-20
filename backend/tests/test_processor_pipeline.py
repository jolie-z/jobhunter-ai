import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app

client = TestClient(app)

def test_processor_stats_returns_full_pipeline_metrics():
    response = client.get("/api/v1/processor/stats")
    assert response.status_code == 200
    data = response.json()
    assert "raw_pending" in data
    assert "ai_pending" in data
    assert "global_pending" in data
    assert "ready_to_sync" in data
    assert "synced_count" in data
    assert "rejected_count" in data
    assert "xhs_pending" in data
    assert "global_breakdown" in data
    assert isinstance(data["raw_pending"], int)
    assert isinstance(data["ai_pending"], int)
    assert isinstance(data["ready_to_sync"], int)
    assert isinstance(data["synced_count"], int)
    assert isinstance(data["rejected_count"], int)

def test_processor_sync_feishu_endpoint():
    with patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu") as mock_sync:
        mock_sync.return_value = []
        response = client.post("/api/v1/processor/sync-feishu", json={"limit": 10})
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "success"
        assert res_data["task_id"].startswith("sync_feishu_")

def test_processor_run_global_endpoint():
    with patch("job_processor.step1_rule_filter._async_run_pipeline") as mock_clean, \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu") as mock_sync:
        async def mock_clean_coro(*args, **kwargs):
            return ["http://test.com/job1"]
        mock_clean.side_effect = mock_clean_coro
        mock_sync.return_value = []

        response = client.post("/api/v1/processor/run-global", json={"limit": 5})
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "success"
        assert res_data["task_id"].startswith("clean_global_")

def test_processor_run_hard_filter_endpoint():
    with patch("job_processor.step1_rule_filter._async_run_hard_filter_only") as mock_hard:
        async def mock_coro(*args, **kwargs):
            return {"total": 5, "passed": 3, "rejected": 2}
        mock_hard.side_effect = mock_coro

        response = client.post("/api/v1/processor/run-hard-filter", json={"limit": 5})
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "success"
        assert res_data["task_id"].startswith("clean_hard_")

def test_processor_run_ai_scout_endpoint():
    with patch("job_processor.step1_rule_filter._async_run_ai_scout_only") as mock_ai:
        async def mock_coro(*args, **kwargs):
            return ["http://test.com/job1"]
        mock_ai.side_effect = mock_coro

        response = client.post("/api/v1/processor/run-ai-scout", json={"limit": 5})
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "success"
        assert res_data["task_id"].startswith("clean_ai_")

def test_processor_skip_ai_sync_endpoint():
    with patch("job_processor.step1_rule_filter._async_skip_ai_to_feishu") as mock_skip, \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu") as mock_sync:
        async def mock_coro(*args, **kwargs):
            return ["http://test.com/job1"]
        mock_skip.side_effect = mock_coro
        mock_sync.return_value = []

        response = client.post("/api/v1/processor/skip-ai-sync", json={"limit": 5})
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "success"
        assert res_data["task_id"].startswith("skip_ai_")
