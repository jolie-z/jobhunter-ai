import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_jobs_snapshot_returns_dynamic_delivery_schedule(monkeypatch):
    """测试 jobs-snapshot 接口动态回传配置的发射时刻"""
    monkeypatch.setattr(
        "app.automation.db.get_autopilot_config",
        lambda: {"mass_deliver_time": "10:15", "custom_deliver_time": "15:45"}
    )
    
    # 模拟 run_snapshot
    monkeypatch.setattr(
        "app.automation.run_snapshot.current_runtime",
        lambda: {"started": True, "start_rowid": 100, "record_ids": ["rec_1"], "task_id": "test_task"}
    )

    # 模拟飞书数据
    monkeypatch.setattr(
        "app.services.feishu_service.get_pending_review_jobs_from_feishu",
        lambda: []
    )
    monkeypatch.setattr(
        "app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu",
        lambda: [
            {"job_id": "rec_1", "job_name": "AI工程师", "company_name": "测试公司", "platform": "boss", "grade": "A"}
        ]
    )
    monkeypatch.setattr(
        "app.services.feishu_service.get_delivered_jobs_from_feishu",
        lambda: []
    )

    res = client.get("/api/automation/jobs-snapshot")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["delivery_schedule"]["mass_time"] == "10:15"
    assert data["delivery_schedule"]["custom_time"] == "15:45"
    
    # 待投递岗位全量返回且 is_current_run 为 True
    ready_jobs = [j for j in data["data"] if j.get("status") == "ready_to_deliver"]
    assert len(ready_jobs) == 1
    assert ready_jobs[0]["is_current_run"] is True


def test_jobs_snapshot_only_returns_current_run_records(monkeypatch):
    """测试 jobs-snapshot 仅返回当前任务岗位，彻底隔离历史存量"""
    monkeypatch.setattr(
        "app.automation.run_snapshot.current_runtime",
        lambda: {"started": True, "start_rowid": 50, "record_ids": ["rec_current_1"], "task_id": "task_2"}
    )

    # 模拟飞书待审批：包含当前任务岗位与历史未审批岗位
    monkeypatch.setattr(
        "app.services.feishu_service.get_pending_review_jobs_from_feishu",
        lambda: [
            {"job_id": "rec_current_1", "job_name": "本轮高级开发", "company_name": "公司A", "platform": "boss", "grade": "A", "follow_status": "简历人工复核"},
            {"job_id": "rec_history_2", "job_name": "历史待审开发", "company_name": "公司B", "platform": "zhilian", "grade": "B", "follow_status": "简历人工复核"},
        ]
    )
    monkeypatch.setattr(
        "app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu",
        lambda: [
            {"job_id": "rec_ready_3", "job_name": "历史放行待发射", "company_name": "公司C", "platform": "boss", "grade": "C"}
        ]
    )
    monkeypatch.setattr(
        "app.services.feishu_service.get_delivered_jobs_from_feishu",
        lambda: []
    )

    res = client.get("/api/automation/jobs-snapshot")
    assert res.status_code == 200
    data = res.json()
    jobs_map = {j["job_id"]: j for j in data["data"]}

    # 本轮待审批岗位应存在
    assert "rec_current_1" in jobs_map
    assert jobs_map["rec_current_1"]["status"] == "waiting"
    
    # 历史未审批岗位（未在本轮 record_ids 登记者）不应出现在指挥中心大盘中
    assert "rec_history_2" not in jobs_map
    # 待投递岗位（统一投递发射池）应正常展示在待投递列表中，且 is_current_run 为 False（非本轮岗位）
    assert "rec_ready_3" in jobs_map
    assert jobs_map["rec_ready_3"]["status"] == "ready_to_deliver"
    assert jobs_map["rec_ready_3"]["is_current_run"] is False
