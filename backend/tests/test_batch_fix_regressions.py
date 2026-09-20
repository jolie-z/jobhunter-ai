"""批量任务修复回归测试（2026-09-12 质检修复批次）。

覆盖：
- B-3：_handle_mass_apply / _handle_approve 回写飞书失败必须按岗位失败抛出（不得虚报 success）
- B-12：_handle_approve 缺定制简历回落海投母本时必须发射明示提示
- B-5：批量删除拦截扩展——pending（排队）任务与投递 worker 台账中的岗位一并拦截
- B-15：定时波次海投轨双轨保底分支不再 NameError
- B-16：手动批量投递与定时波次 worker 级互斥
- P3：_handle_approve 自愈渲染失败必须中止入队；delivery_node 防重复发射守卫
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.cache import JobCache
from app.jobs.action_service import batch_delete_jobs
from app.tasks.executor import _handle_approve, _handle_mass_apply


@pytest.fixture(autouse=True)
def _isolate_job_cache_snapshot(monkeypatch, tmp_path):
    """全局隔离 JobCache 磁盘快照与内存态，杜绝任何用例踩踏生产快照 job_cache_snapshot.json。"""
    monkeypatch.setattr(JobCache, "_snapshot_path", tmp_path / "job_cache_snapshot_test.json")
    saved = (JobCache._data, JobCache._timestamp, JobCache._dirty, JobCache._last_disk_write)
    yield
    JobCache._data, JobCache._timestamp, JobCache._dirty, JobCache._last_disk_write = saved


def _drain_queue(queue: asyncio.Queue) -> list[dict]:
    events = []
    while not queue.empty():
        msg = queue.get_nowait()
        if isinstance(msg, str) and msg.startswith("data: "):
            events.append(json.loads(msg[6:].strip()))
    return events


@pytest.mark.asyncio
async def test_mass_apply_feishu_write_failure_raises():
    """B-3：海投回写飞书失败时必须抛错按岗位失败处理，不能返回 success 瞒报。"""
    queue = asyncio.Queue()
    mats = {"pdf_token": "tok_pdf", "img_token": "tok_img", "name": "海投简历"}

    with patch("app.automation.db.get_autopilot_config", return_value={"mass_apply_resume_id": "recResume1"}), \
         patch("app.automation.materials._render_mass_resume_materials_with_name", new_callable=AsyncMock) as mock_render, \
         patch("app.tasks.executor.update_feishu_record", MagicMock(return_value=False)), \
         patch("app.automation.routes.delivery_router._mark_approved_guarded", MagicMock(return_value=True)):

        mock_render.return_value = None  # 走 mats 兜底物料
        with pytest.raises(RuntimeError, match="回写飞书失败"):
            await _handle_mass_apply(
                record_id="recMass1",
                platform="智联招聘",
                fields={"公司名称": "测试公司", "岗位名称": "测试岗位"},
                mats=mats,
                greeting="您好",
                queue=queue,
                job_id="智联招聘-recMass1",
            )


@pytest.mark.asyncio
async def test_approve_feishu_write_failure_raises():
    """B-3：批准投递回写飞书失败时必须抛错按岗位失败处理，不能返回 success 瞒报。"""
    queue = asyncio.Queue()
    fields = {
        "公司名称": "测试公司",
        "岗位名称": "测试岗位",
        "招聘平台": "智联招聘",
        "PDF备份": [{"file_token": "tok_pdf", "name": "测试公司_测试岗位.pdf"}],
        "图片保存": [],
        "打招呼语": "您好",
    }

    with patch("app.tasks.executor.update_feishu_record", MagicMock(return_value=False)), \
         patch("app.automation.routes.delivery_router._mark_approved_guarded", MagicMock(return_value=True)):

        with pytest.raises(RuntimeError, match="回写飞书失败"):
            await _handle_approve(
                record_id="recApprove9",
                platform="智联招聘",
                fields=fields,
                queue=queue,
                job_id="智联招聘-recApprove9",
            )


@pytest.mark.asyncio
async def test_approve_mass_resume_fallback_emits_hint():
    """B-12：无定制简历 JSON 回落海投母本渲染时，SSE 必须有明示提示。"""
    queue = asyncio.Queue()
    fields = {
        "公司名称": "测试公司",
        "岗位名称": "测试岗位",
        "招聘平台": "智联招聘",
        "PDF备份": [],
        "图片保存": [],
        "打招呼语": "",
    }

    with patch("app.automation.materials._render_custom_resume_materials", new_callable=AsyncMock) as mock_custom, \
         patch("app.automation.materials._render_mass_resume_materials_with_name", new_callable=AsyncMock) as mock_mass, \
         patch("app.automation.db.get_autopilot_config", return_value={"mass_apply_resume_id": "recR", "mass_apply_greeting": "通用语"}), \
         patch("app.tasks.executor.update_feishu_record", MagicMock(return_value=True)), \
         patch("app.automation.routes.delivery_router._mark_approved_guarded", MagicMock(return_value=True)), \
         patch("app.core.cache.JobCache.patch_record_fields", MagicMock()):

        mock_custom.return_value = None
        mock_mass.return_value = {"pdf_token": "tok_pdf", "img_token": "tok_img", "name": "x.pdf"}

        result = await _handle_approve(
            record_id="recApprove10",
            platform="智联招聘",
            fields=fields,
            queue=queue,
            job_id="智联招聘-recApprove10",
        )
        assert result["status"] == "success"

        events = _drain_queue(queue)
        info_texts = " ".join(e.get("message", "") for e in events if e.get("type") == "info")
        assert "回落使用海投母本简历" in info_texts


@pytest.mark.asyncio
async def test_batch_delete_blocked_by_pending_task(monkeypatch):
    """B-5：排队中（pending）的批量任务持有的岗位同样禁止物理删除。"""
    from app.tasks import state as task_state

    monkeypatch.setattr(
        task_state,
        "task_status",
        {"t1": {"status": "pending", "job_ids": ["BOSS直聘-recPending1"]}},
    )

    with pytest.raises(HTTPException) as exc_info:
        await batch_delete_jobs(["BOSS直聘-recPending1"])
    assert exc_info.value.status_code == 409
    assert "recPending1" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_batch_delete_blocked_by_delivery_registry(monkeypatch):
    """B-5：投递 worker 台账中正在投递的岗位禁止物理删除。"""
    from app.automation.routes import delivery_router

    monkeypatch.setattr(
        delivery_router,
        "_ACTIVE_DELIVERY_RECORD_IDS",
        {"recDelivering1"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await batch_delete_jobs(["智联招聘-recDelivering1"])
    assert exc_info.value.status_code == 409
    assert "recDelivering1" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_resume_job_delivery_mass_track_no_nameerror(monkeypatch):
    """B-15：定时波次对无 LangGraph 断点的岗位（海投轨）走双轨保底分支，
    此前该分支引用已被重构删除的 raw_custom_md 直接 NameError，导致波次对海投岗必失败。
    回归：final_markdown 与精投判定同源（AI改写JSON），不再 NameError。"""
    import app.automation.delivery_tasks as dt

    liepin_mass_record = {
        "record_id": "recLiepinMass1",
        "fields": {
            "跟进状态": "待投递",
            "招聘平台": "猎聘",
            "公司名称": "星辰网络",
            "岗位名称": "AI 产品经理",
            "岗位链接": {"link": "https://www.liepin.com/job/123.shtml"},
            "PDF备份": [{"file_token": "tok_pdf", "name": "星辰网络_AI 产品经理.pdf"}],
            "打招呼语": "您好，对贵司 AI 产品岗很感兴趣",
            "综合评级": "D",
        },
    }

    captured: dict = {}

    async def fake_delivery_node(state):
        captured.update(state)
        return {"status": "已投递"}

    monkeypatch.setattr(dt, "get_pipeline_app", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.services.feishu_service.get_job_record_from_feishu",
        lambda rid, table_id=None: liepin_mass_record,
    )
    monkeypatch.setattr("app.automation.workflow.delivery_node", fake_delivery_node)

    ok, msg = await dt._resume_job_delivery("recLiepinMass1")
    assert ok is True, f"海投轨波次发射不应失败: {msg}"
    assert msg == "已投递"
    # final_markdown 无 raw_custom_md 残留引用，与精投判定同源取数
    assert captured.get("record_id") == "recLiepinMass1"
    assert captured.get("platform") == "猎聘"
    assert captured.get("is_custom") is False
    assert captured.get("final_markdown") == ""


@pytest.mark.asyncio
async def test_scheduled_wave_skips_when_manual_batch_running(monkeypatch):
    """B-16：手动批量投递持锁运行时，定时波次必须整轮跳过——
    双通道各自扫描「待投递」队列会对同一岗位重复打招呼/重复发简历。"""
    import asyncio as _asyncio

    import app.automation.delivery_tasks as dt
    from app.automation.routes import delivery_router

    busy_lock = _asyncio.Lock()
    await busy_lock.acquire()
    monkeypatch.setattr(delivery_router, "_deliver_worker_lock", busy_lock)

    impl_called = {"count": 0}

    async def fail_impl(*args, **kwargs):
        impl_called["count"] += 1
        raise AssertionError("手动批量运行中时波次不应进入发射实现")

    monkeypatch.setattr(dt, "_scheduled_delivery_batch_task_impl", fail_impl)
    try:
        await dt.scheduled_delivery_batch_task("上午波次")
        assert impl_called["count"] == 0
    finally:
        busy_lock.release()


@pytest.mark.asyncio
async def test_scheduled_wave_runs_and_holds_lock_when_idle(monkeypatch):
    """B-16 正向：锁空闲时波次正常发射，且发射全程持锁（手动批量此时触发会被 busy 拒绝）。"""
    import app.automation.delivery_tasks as dt
    from app.automation.routes import delivery_router

    lock_state = {"held_inside": None}

    async def fake_impl(window_label, pipeline_app=None):
        lock_state["held_inside"] = delivery_router._deliver_worker_lock.locked()

    monkeypatch.setattr(dt, "_scheduled_delivery_batch_task_impl", fake_impl)

    await dt.scheduled_delivery_batch_task("下午波次")
    assert lock_state["held_inside"] is True
    # 发射结束后锁必须释放，不阻塞下一轮手动触发
    assert delivery_router._deliver_worker_lock.locked() is False


@pytest.mark.asyncio
async def test_approve_self_heal_failure_blocks_enqueue():
    """P3：批准链路自愈渲染失败必须按岗位失败中止，不得让空物料岗位流入「待投递」。

    与 auto_heal_and_approve 的 422 中止口径对齐；此前空物料岗位会先入队、
    到投递网关才报错，白白浪费一次发射并污染失败台账。"""
    queue = asyncio.Queue()
    fields = {
        "公司名称": "测试公司",
        "岗位名称": "测试岗位",
        "招聘平台": "智联招聘",
        "PDF备份": [],
        "图片保存": [],
        "打招呼语": "",
    }

    with patch("app.automation.materials._render_custom_resume_materials", new_callable=AsyncMock) as mock_custom, \
         patch("app.automation.materials._render_mass_resume_materials_with_name", new_callable=AsyncMock) as mock_mass, \
         patch("app.automation.db.get_autopilot_config", return_value={"mass_apply_resume_id": "recR", "mass_apply_greeting": "通用语"}), \
         patch("app.tasks.executor.update_feishu_record", MagicMock(return_value=True)) as mock_update:

        mock_custom.return_value = None
        mock_mass.return_value = None  # 定制渲染与母本回落双双失败

        with pytest.raises(RuntimeError, match="自愈失败"):
            await _handle_approve(
                record_id="recApprove11",
                platform="智联招聘",
                fields=fields,
                queue=queue,
                job_id="智联招聘-recApprove11",
            )

        # 不得发生任何飞书写入（空物料岗位严禁入队）
        mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_delivery_node_blocks_duplicate_inflight(monkeypatch):
    """P3：同一岗位已在投递链路执行中时，delivery_node 必须拦截重复发射，
    且拦截方不得误清他人登记（否则第三条链路又会放行）。"""
    from app.automation import workflow

    monkeypatch.setattr(workflow, "_DELIVERY_INFLIGHT_RECORD_IDS", {"recDup1"})
    inner_calls = {"n": 0}

    async def fake_inner(state):
        inner_calls["n"] += 1
        return {"status": "已投递"}

    monkeypatch.setattr(workflow, "_delivery_node_inner", fake_inner)

    res = await workflow.delivery_node({"record_id": "BOSS直聘-recDup1"})
    assert "重复" in res.get("error", "")
    assert inner_calls["n"] == 0
    assert "recDup1" in workflow._DELIVERY_INFLIGHT_RECORD_IDS


@pytest.mark.asyncio
async def test_delivery_node_releases_inflight_after_finish(monkeypatch):
    """P3：正常投递完成后必须释放登记，不影响该岗位后续重试；执行期间登记在册。"""
    from app.automation import workflow

    registry: set = set()
    monkeypatch.setattr(workflow, "_DELIVERY_INFLIGHT_RECORD_IDS", registry)

    async def fake_inner(state):
        assert "recFresh1" in registry, "投递执行期间岗位必须登记在册"
        return {"status": "已投递"}

    monkeypatch.setattr(workflow, "_delivery_node_inner", fake_inner)

    res = await workflow.delivery_node({"record_id": "猎聘-recFresh1"})
    assert res == {"status": "已投递"}
    assert "recFresh1" not in registry
