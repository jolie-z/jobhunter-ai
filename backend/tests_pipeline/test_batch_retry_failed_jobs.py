"""执行失败岗位批量重试与批量放弃端到端接口测试。

测试覆盖：
1. 400 Bad Request: 空列表与全在途岗位去重拦截
2. 409 Conflict: 批量投递锁冲突保护
3. 批量重试: 成功调用标准投递编排引擎，飞书与 raw 分流，finally 释放在途标记
4. 批量放弃: 在途互斥保护、持久化先行原则与失败补偿
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.automation import run_snapshot as _rs
from app.automation.routes.delivery_router import _deliver_worker_lock

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_snapshot_and_lock(monkeypatch):
    """每次测试前后清理在途标记与锁状态，并隔离飞书网络请求"""
    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", lambda *args, **kwargs: True)
    _rs._retrying_jobs.clear()
    _rs._delivery_failures.clear()
    _rs._dismissed_jobs.clear()
    if _deliver_worker_lock.locked():
        _deliver_worker_lock.release()
    yield
    _rs._retrying_jobs.clear()
    _rs._delivery_failures.clear()
    _rs._dismissed_jobs.clear()
    if _deliver_worker_lock.locked():
        _deliver_worker_lock.release()


def test_batch_retry_empty_request_returns_400():
    """空列表直接返回 400"""
    res = client.post("/api/automation/batch-retry-failed-jobs", json={"job_ids": []})
    # Pydantic Field(min_length=1) 触发 422 或业务 400
    assert res.status_code in (400, 422)


def test_batch_retry_all_retrying_returns_400():
    """所有岗位均已在途时返回 400 防重"""
    _rs.mark_job_retrying("rec_test_busy_1")
    _rs.mark_job_retrying("rec_test_busy_2")

    res = client.post("/api/automation/batch-retry-failed-jobs", json={
        "job_ids": ["rec_test_busy_1", "rec_test_busy_2"]
    })
    assert res.status_code == 400
    assert "均已在重试中" in res.json()["detail"]


@pytest.mark.asyncio
async def test_batch_retry_deduplicates_same_request_ids(monkeypatch):
    """验证同一次请求内的重复 job_id 能够被正确去重，只投递一次"""
    from app.automation.services.batch_retry_service import batch_retry_failed_jobs_service, _BATCH_BG_TASKS
    dispatched_ids = []
    async def fake_orchestrator(ids):
        dispatched_ids.extend(ids)
        return None

    monkeypatch.setattr(
        "app.automation.services.batch_retry_service._deliver_approved_worker",
        fake_orchestrator,
    )

    data = await batch_retry_failed_jobs_service(["rec_dup_1", "rec_dup_1", "rec_dup_1"])
    assert data["retried_count"] == 1
    assert data["ignored_count"] == 2

    if _BATCH_BG_TASKS:
        await asyncio.gather(*list(_BATCH_BG_TASKS))

    assert dispatched_ids == ["rec_dup_1"]


@pytest.mark.asyncio
async def test_batch_retry_lock_conflict_returns_409():
    """锁被占用时，批量重试直接返回 409 Conflict"""
    await _deliver_worker_lock.acquire()
    try:
        res = client.post("/api/automation/batch-retry-failed-jobs", json={
            "job_ids": ["rec_test_1", "rec_test_2"]
        })
        assert res.status_code == 409
        assert "当前已有投递任务正在执行中" in res.json()["detail"]
    finally:
        _deliver_worker_lock.release()


@pytest.mark.asyncio
async def test_batch_retry_dispatches_to_standard_orchestrator(monkeypatch):
    """批量重试成功分流：飞书岗送入标准编排器，并在后台任务执行完毕后释放在途标记"""
    from app.automation.services.batch_retry_service import batch_retry_failed_jobs_service, _BATCH_BG_TASKS
    retrying_during_execution = {}
    mock_raw_runner = AsyncMock(return_value=None)
    async def fake_orchestrator(ids):
        retrying_during_execution["rec_feishu_1"] = _rs.is_job_retrying("rec_feishu_1")
        retrying_during_execution["raw_99"] = _rs.is_job_retrying("raw_99")
        return None

    monkeypatch.setattr(
        "app.automation.services.batch_retry_service._deliver_approved_worker",
        fake_orchestrator,
    )
    monkeypatch.setattr(
        "app.automation.full_auto.run_single_job_pipeline_async",
        mock_raw_runner,
    )

    data = await batch_retry_failed_jobs_service(["rec_feishu_1", "rec_feishu_2", "raw_99"])
    assert data["status"] == "success"
    assert data["retried_count"] == 2
    assert data["raw_count"] == 1

    # 等待后台协程执行完毕
    if _BATCH_BG_TASKS:
        await asyncio.gather(*list(_BATCH_BG_TASKS))

    # 验证执行过程中，在途标记必须为 True
    assert retrying_during_execution.get("rec_feishu_1") is True
    assert retrying_during_execution.get("raw_99") is True

    # 验证后台批次结束后，finally 成功清空在途标记
    assert _rs.is_job_retrying("rec_feishu_1") is False
    assert _rs.is_job_retrying("rec_feishu_2") is False
    assert _rs.is_job_retrying("raw_99") is False


@pytest.mark.asyncio
async def test_batch_dismiss_with_busy_guard_and_persistence_first(monkeypatch):
    """批量放弃验证：在途岗位互斥拦截；持久化先行；持久化失败时不操作内存快照"""
    # 模拟在途岗位
    _rs.mark_job_retrying("rec_busy_delivering")

    # 模拟飞书更新：rec_ok 成功，rec_fail 失败
    def mock_update_feishu(job_id, patch_data):
        if job_id == "rec_ok":
            return True
        return False

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update_feishu)

    res = client.post("/api/automation/batch-dismiss-failed-jobs", json={
        "job_ids": ["rec_busy_delivering", "rec_ok", "rec_fail"]
    })
    assert res.status_code == 200
    data = res.json()
    assert data["dismissed_count"] == 1
    assert data["busy_count"] == 1
    assert data["failed_count"] == 1

    # rec_ok 成功持久化并移出
    assert "rec_ok" in _rs._dismissed_jobs
    # rec_busy 正在投递，被拦截，未被放弃
    assert "rec_busy_delivering" not in _rs._dismissed_jobs
    # rec_fail 持久化失败，未被写入内存放弃集合（保障下次轮询仍可重新处置）
    assert "rec_fail" not in _rs._dismissed_jobs


@pytest.mark.asyncio
async def test_batch_retry_feishu_status_compensation(monkeypatch):
    """验证批量重试触发时，顺手将飞书表格状态由「已放弃」重新平账回「待投递」"""
    reconciled_calls = []

    def mock_update(job_id, patch_data):
        reconciled_calls.append((job_id, patch_data))
        return True

    monkeypatch.setattr("app.services.feishu_service.update_feishu_record", mock_update)

    async def fake_orchestrator(ids):
        return None

    monkeypatch.setattr(
        "app.automation.services.batch_retry_service._deliver_approved_worker",
        fake_orchestrator,
    )

    from app.automation.services.batch_retry_service import batch_retry_failed_jobs_service, _BATCH_BG_TASKS
    data = await batch_retry_failed_jobs_service(["rec_reconcile_1", "rec_reconcile_2"])
    assert data["status"] == "success"

    if _BATCH_BG_TASKS:
        await asyncio.gather(*list(_BATCH_BG_TASKS))

    assert len(reconciled_calls) == 2
    assert ("rec_reconcile_1", {"跟进状态": "待投递"}) in reconciled_calls
    assert ("rec_reconcile_2", {"跟进状态": "待投递"}) in reconciled_calls

