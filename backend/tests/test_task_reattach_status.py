import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.tasks.router import router
from app.tasks.state import GLOBAL_TASK_STATE, task_status


@pytest.fixture
def test_client():
    app = FastAPI()
    app.include_router(router, prefix="/api/tasks")
    return TestClient(app)


def test_task_status_idle(test_client):
    """验证空闲时 /api/tasks/status 返回 is_processing=False"""
    GLOBAL_TASK_STATE["is_processing"] = False
    GLOBAL_TASK_STATE["current_task_id"] = None
    res = test_client.get("/api/tasks/status")
    assert res.status_code == 200
    data = res.json()
    assert data["is_processing"] is False
    assert data.get("current_task_id") is None


def test_task_status_active_auto_recovery(test_client):
    """验证后台有任务在运行时，无参 GET /api/tasks/status 能自动返回正在执行的 task_id 和 job_ids"""
    task_id = "test-task-uuid-12345"
    GLOBAL_TASK_STATE["is_processing"] = True
    GLOBAL_TASK_STATE["current_task_id"] = task_id
    task_status[task_id] = {
        "status": "running",
        "task_type": "evaluate",
        "job_ids": ["rec_1", "rec_2", "rec_3"],
        "total": 3,
        "completed": 1,
    }

    try:
        res = test_client.get("/api/tasks/status")
        assert res.status_code == 200
        data = res.json()
        assert data["is_processing"] is True
        assert data["current_task_id"] == task_id
        assert "task" in data
        assert data["task"]["job_ids"] == ["rec_1", "rec_2", "rec_3"]
        assert data["task"]["completed"] == 1
    finally:
        # 清理现场
        GLOBAL_TASK_STATE["is_processing"] = False
        GLOBAL_TASK_STATE["current_task_id"] = None
        task_status.pop(task_id, None)


def test_task_status_recently_completed(test_client):
    """验证切回主页时若任务刚完结，能从 last_completed_task_id 探活到完成状态"""
    task_id = "test-task-completed-999"
    GLOBAL_TASK_STATE["is_processing"] = False
    GLOBAL_TASK_STATE["current_task_id"] = None
    GLOBAL_TASK_STATE["last_completed_task_id"] = task_id
    task_status[task_id] = {
        "status": "completed",
        "task_type": "evaluate",
        "total": 5,
        "completed": 5,
    }

    try:
        res = test_client.get("/api/tasks/status")
        assert res.status_code == 200
        data = res.json()
        assert data["is_processing"] is False
        assert data.get("task_id") == task_id
        assert data.get("task", {}).get("status") == "completed"
    finally:
        GLOBAL_TASK_STATE["last_completed_task_id"] = None
        task_status.pop(task_id, None)
