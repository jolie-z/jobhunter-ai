import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.automation import scheduler

client = TestClient(app)


def test_resume_approve_moves_to_ready_to_deliver():
    """测试审批放行后，岗位进入「待投递」队列，飞书更新为「待投递」而非直接标记为已投递"""
    fake_state = MagicMock()
    fake_state.next = ["manual_review_node"]

    mock_pipeline_app = MagicMock()
    mock_pipeline_app.aget_state = AsyncMock(return_value=fake_state)

    with patch.object(scheduler, "pipeline_app", mock_pipeline_app):
        with patch("app.services.feishu_service.update_feishu_record") as mock_update_feishu:
            with patch("app.automation.router.get_autopilot_config", return_value={"custom_deliver_mode": "immediate"}):
                res = client.post("/api/automation/resume", json={"thread_id": "rec_test_123", "action": "approve"})
                assert res.status_code == 200
                data = res.json()
                assert data["status"] == "approved"
                assert data["node"] == "ready_to_deliver"
                mock_update_feishu.assert_called_once_with("rec_test_123", {"跟进状态": "待投递"})


def test_resume_batch_approve_moves_all_to_ready_to_deliver():
    """测试批量审批放行后，所有岗位均更新为「待投递」并进入就绪池"""
    fake_state = MagicMock()
    fake_state.next = ["manual_review_node"]

    mock_pipeline_app = MagicMock()
    mock_pipeline_app.aget_state = AsyncMock(return_value=fake_state)

    with patch.object(scheduler, "pipeline_app", mock_pipeline_app):
        with patch("app.services.feishu_service.update_feishu_record") as mock_update_feishu:
            with patch("app.automation.router.get_autopilot_config", return_value={"custom_deliver_mode": "immediate"}):
                res = client.post(
                    "/api/automation/resume_batch",
                    json={"thread_ids": ["rec_1", "rec_2"], "action": "approve"}
                )
                assert res.status_code == 200
                data = res.json()
                assert data["status"] == "success"
                assert data["data"]["success"] == 2
                for detail in data["data"]["details"]:
                    assert detail["status"] == "approved"
                    assert detail["node"] == "ready_to_deliver"
                assert mock_update_feishu.call_count == 2


def test_resume_scheduled_mode():
    """测试定时模式下，审批放行后 status 为 scheduled，node 为 ready_to_deliver"""
    fake_state = MagicMock()
    fake_state.next = ["manual_review_node"]

    mock_pipeline_app = MagicMock()
    mock_pipeline_app.aget_state = AsyncMock(return_value=fake_state)

    with patch.object(scheduler, "pipeline_app", mock_pipeline_app):
        with patch("app.services.feishu_service.update_feishu_record") as mock_update_feishu:
            with patch("app.automation.router.get_autopilot_config", return_value={"custom_deliver_mode": "scheduled", "custom_deliver_time": "14:00"}):
                res = client.post("/api/automation/resume", json={"thread_id": "rec_test_456", "action": "approve"})
                assert res.status_code == 200
                data = res.json()
                assert data["status"] == "scheduled"
                assert data["node"] == "ready_to_deliver"
                mock_update_feishu.assert_called_once_with("rec_test_456", {"跟进状态": "待投递"})


def test_deliver_approved_endpoint():
    """测试 /api/automation/deliver_approved 能够成功接收入参并启动投递任务"""
    with patch("app.automation.router._deliver_approved_worker", new_callable=AsyncMock) as mock_worker:
        res = client.post("/api/automation/deliver_approved", json={"thread_ids": ["rec_1", "rec_2"]})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["data"]["count"] == 2
        assert data["data"]["thread_ids"] == ["rec_1", "rec_2"]
