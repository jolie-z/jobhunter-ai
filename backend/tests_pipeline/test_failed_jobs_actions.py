import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_feishu_manual_rejected(monkeypatch):
    monkeypatch.setattr("app.services.feishu_service.get_manual_rejected_jobs_from_feishu", lambda: [])


def test_dismiss_failed_job_removes_from_snapshot(monkeypatch):
    """测试放弃失败岗位后：飞书门牌先落「已放弃投递」（唯一事实源），岗位被移出 snapshot 数据集合"""
    feishu_writes = {}
    def mock_update(rid, patch_dict):
        feishu_writes[rid] = dict(patch_dict)
        return True
    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update)

    from app.automation.run_snapshot import undismiss_job
    undismiss_job("raw_999")
    undismiss_job("rec_fail_1")

    # 1. 发起放弃请求
    res = client.post("/api/automation/dismiss-failed-job", json={
        "job_id": "rec_fail_1",
        "job_url": "https://test.com/job/fail_1"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert feishu_writes.get("rec_fail_1", {}).get("跟进状态") == "已放弃投递"

    # 2. 模拟 jobs-snapshot
    monkeypatch.setattr(
        "app.automation.run_snapshot.current_runtime",
        lambda: {"started": True, "start_rowid": 99999, "record_ids": ["rec_fail_1", "rec_ok_2"], "task_id": "test_dismiss"}
    )
    monkeypatch.setattr(
        "app.services.feishu_service.get_pending_review_jobs_from_feishu",
        lambda: [
            {"job_id": "rec_fail_1", "job_name": "失败岗位", "platform": "boss", "grade": "C"},
            {"job_id": "rec_ok_2", "job_name": "正常岗位", "platform": "boss", "grade": "B"}
        ]
    )
    monkeypatch.setattr("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", lambda: [])
    monkeypatch.setattr("app.services.feishu_service.get_delivered_jobs_from_feishu", lambda: [])

    snap_res = client.get("/api/automation/jobs-snapshot")
    assert snap_res.status_code == 200
    job_ids = [j["job_id"] for j in snap_res.json()["data"]]
    assert "rec_fail_1" not in job_ids
    assert "rec_ok_2" in job_ids


def test_retry_failed_job_triggers_async_pipeline(monkeypatch):
    """测试重试失败岗位会调用异步流水线并恢复状态"""
    called_args = {}

    async def mock_run_single(record_id="", raw_rowid=None, pipeline_task_id=None, stop_at_review=False):
        called_args["record_id"] = record_id
        called_args["raw_rowid"] = raw_rowid
        called_args["task_id"] = pipeline_task_id

    monkeypatch.setattr("app.automation.full_auto.run_single_job_pipeline_async", mock_run_single)

    res = client.post("/api/automation/retry-failed-job", json={
        "job_id": "raw_888",
        "job_url": "https://test.com/job/888",
        "pipeline_task_id": "task_123"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "重新拉起" in res.json()["message"]


def test_retry_failed_job_feishu_delivery(monkeypatch):
    """测试重试飞书待投递异常岗位会唤起投递引擎"""
    called_thread_id = None

    async def mock_resume_delivery(thread_id):
        nonlocal called_thread_id
        called_thread_id = thread_id
        return True, "已投递"

    monkeypatch.setattr("app.automation.scheduler._resume_job_delivery", mock_resume_delivery)

    res = client.post("/api/automation/retry-failed-job", json={
        "job_id": "rec_test_fail",
        "job_url": "https://test.com/job/fail",
        "pipeline_task_id": "task_123"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert "自动投递引擎" in res.json()["message"]


def test_dismiss_ghost_failed_job_fallback(monkeypatch):
    """测试幽灵/脏数据岗位（飞书不存在或回写失败）：降级保证本地正常销账移出"""
    # 模拟飞书回写失败（例如 1254043 RecordIdNotFound）
    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", lambda *args, **kwargs: False)

    from app.automation import run_snapshot as _rs
    _rs.record_delivery_failure("rec_ghost_999", error="测试异常")
    assert "rec_ghost_999" in _rs.get_delivery_failures()

    res = client.post("/api/automation/dismiss-failed-job", json={
        "job_id": "rec_ghost_999",
        "job_url": "https://ghost.com"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    # 确保本地异常台账与看板名单中已销账
    assert "rec_ghost_999" not in _rs.get_delivery_failures()
    assert "rec_ghost_999" in _rs.get_dismissed_job_ids()


def test_retrying_job_locked_as_running_in_snapshot(monkeypatch):
    """测试重试中岗位在 jobs-snapshot 轮询中被固化为 running，不会被老快照和旧失败台账冲刷回执行失败"""
    from app.automation import run_snapshot as _rs

    # 1. 模拟一个失败记录
    test_id = "rec_retry_lock_123"
    _rs.record_delivery_failure(test_id, error="微聊受阻")
    assert test_id in _rs.get_delivery_failures()

    # 2. 模拟点击重试后打上常驻锁
    _rs.mark_job_retrying(test_id)
    assert test_id in _rs.get_retrying_job_ids()

    # 3. 模拟飞书与 runtime
    monkeypatch.setattr(
        "app.automation.run_snapshot.current_runtime",
        lambda: {"started": True, "start_rowid": 1, "record_ids": [test_id], "task_id": "test_retry_lock"}
    )
    monkeypatch.setattr(
        "app.services.feishu_service.get_pending_review_jobs_from_feishu",
        lambda: [{"job_id": test_id, "job_name": "高级产品经理", "company_name": "中望软件", "platform": "zhilian", "grade": "A"}]
    )
    monkeypatch.setattr("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", lambda: [])
    monkeypatch.setattr("app.services.feishu_service.get_delivered_jobs_from_feishu", lambda: [])

    # 4. 获取 snapshot
    snap_res = client.get("/api/automation/jobs-snapshot")
    assert snap_res.status_code == 200
    snap_data = snap_res.json()["data"]

    # 5. 断言：在返回的岗位列表中，该重试中岗位状态强制为 running，无 failure_info
    matched = [j for j in snap_data if j["job_id"] == test_id]
    assert len(matched) == 1
    job_snap = matched[0]
    assert job_snap["status"] == "running"
    assert job_snap["node"] == "delivery_node"
    assert job_snap["sub_status"] == "delivering"
    assert job_snap.get("failure_info") is None

    # 6. 断言：delivery_failures 中已被剔除
    res_failures = snap_res.json().get("delivery_failures", {})
    assert test_id not in res_failures

    # 7. 解除锁后，恢复可标记
    _rs.unmark_job_retrying(test_id)
    assert test_id not in _rs.get_retrying_job_ids()


def test_active_delivering_job_locked_as_running_in_snapshot(monkeypatch):
    """测试待投递岗位点击立即投递后：在飞书仍为待投递期间，快照中被固化为 running/delivering，绝不回到待投递"""
    from app.automation import run_snapshot as _rs

    test_id = "rec_delivering_456"
    # 1. 模拟进入投递队列
    _rs.mark_job_delivering(test_id)
    assert test_id in _rs.get_active_inflight_job_ids()

    # 2. 模拟飞书待投递接口仍返回该岗位
    monkeypatch.setattr(
        "app.automation.run_snapshot.current_runtime",
        lambda: {"started": True, "start_rowid": 1, "record_ids": [test_id], "task_id": "test_deliver_lock"}
    )
    monkeypatch.setattr(
        "app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu",
        lambda: [{"job_id": test_id, "job_name": "产品经理/产品负责人", "company_name": "广州方图科技有限公司", "platform": "zhilian", "grade": "C"}]
    )
    monkeypatch.setattr("app.services.feishu_service.get_pending_review_jobs_from_feishu", lambda: [])
    monkeypatch.setattr("app.services.feishu_service.get_delivered_jobs_from_feishu", lambda: [])

    # 3. 请求 snapshot
    snap_res = client.get("/api/automation/jobs-snapshot")
    assert snap_res.status_code == 200
    snap_data = snap_res.json()["data"]

    # 4. 断言：岗位状态强制为 running，node 为 delivery_node，绝不是 ready_to_deliver
    matched = [j for j in snap_data if j["job_id"] == test_id]
    assert len(matched) == 1
    job_snap = matched[0]
    assert job_snap["status"] == "running"
    assert job_snap["node"] == "delivery_node"
    assert job_snap["sub_status"] == "delivering"

    # 5. 投递完成后解除锁
    _rs.unmark_job_delivering(test_id)
    assert test_id not in _rs.get_active_inflight_job_ids()



