"""全链路指挥中心实时状态同步回归（2026-10-30）。

覆盖三件事：
1. emit_job / emit_stage 会写入进程内实时登记表，stage_snapshot 能反映并发阶段运行数；
2. snapshot_service 的实时态覆盖只覆盖 running，不覆盖 Feishu 权威终态；
3. 待审批查询不再把「已完成初步评估 / 待投递」误当审批断点。
"""
import asyncio
import threading
import time

import pytest

from app.automation import pipeline_broadcast as pb
from app.automation.snapshot_service import apply_live_job_overlay
from app.services import feishu_service


@pytest.fixture(autouse=True)
def _reset_live_state():
    pb._live_jobs.clear()
    pb._live_stages.clear()
    pb._live_phases.clear()
    pb.set_current_pipeline(None, False)
    yield
    pb._live_jobs.clear()
    pb._live_stages.clear()
    pb._live_phases.clear()
    pb.set_current_pipeline(None, False)


def test_emit_job_tracks_live_state_and_running_counts():
    async def scenario():
        await pb.emit_job(
            "pipeline_test",
            job_id="rec_1",
            job_name="岗位1",
            node="evaluate_node",
            status="running",
            sub_status="ai_eval",
            grade="A",
        )
        snap = pb.get_stage_snapshot("pipeline_test")
        assert snap["running_counts"] == {"evaluating": 1}
        assert snap["active_stages"] == ["evaluating"]

        # 进入深评：初评运行数归零，深评运行数 +1；deep_eval_done 标记写入
        await pb.emit_job(
            "pipeline_test",
            job_id="rec_1",
            job_name="岗位1",
            node="deep_eval_node",
            status="running",
            sub_status="deep_eval",
            grade="A",
            deep_eval_done=True,
        )
        snap = pb.get_stage_snapshot("pipeline_test")
        assert snap["running_counts"] == {"deep_eval": 1}
        live = pb.get_live_jobs("pipeline_test")
        assert live["rec_1"]["deep_eval_done"] is True

        # 进入改写：深评运行数归零；deep_eval_done 跨事件保留
        await pb.emit_job(
            "pipeline_test",
            job_id="rec_1",
            job_name="岗位1",
            node="rewrite_node",
            status="running",
            sub_status="rewriting",
        )
        snap = pb.get_stage_snapshot("pipeline_test")
        assert snap["running_counts"] == {"rewriting": 1}
        live = pb.get_live_jobs("pipeline_test")
        assert live["rec_1"]["deep_eval_done"] is True

        # 终态不再计入运行数
        await pb.emit_job(
            "pipeline_test",
            job_id="rec_1",
            job_name="岗位1",
            node="manual_review_node",
            status="waiting",
            sub_status="waiting",
        )
        assert pb.get_stage_snapshot("pipeline_test")["running_counts"] == {}

    asyncio.run(scenario())


def test_emit_stage_and_phase_progress_snapshot():
    async def scenario():
        await pb.emit_stage("pipeline_test", "cleaning", "running")
        await pb.emit_stage("pipeline_test", "feishu_sync", "done")
    asyncio.run(scenario())
    pb.record_phase_progress("pipeline_test", "feishu_sync", 2, 5)
    # step1/step2 共用的 phase_progress 事件登记入口
    pb.record_phase_progress_event(
        "pipeline_test",
        {"type": "phase_progress", "phase": "hard_clean", "current": 1, "total": 4},
    )

    snap = pb.get_stage_snapshot("pipeline_test")
    assert snap["stage_status"]["cleaning"] == "running"
    assert snap["stage_status"]["feishu_sync"] == "done"
    assert snap["phases"]["feishu_sync"] == {"current": 2, "total": 5}
    assert snap["phases"]["hard_clean"] == {"current": 1, "total": 4}
    assert snap["current_stage"] == "cleaning"


def test_apply_live_overlay_overrides_snapshot_waiting_with_running():
    jobs = [
        {
            "job_id": "rec_1",
            "job_name": "岗位1",
            "status": "waiting",
            "node": "manual_review_node",
            "grade": "A",
            "score": 88,
        }
    ]
    live = {
        "rec_1": {
            "job_id": "rec_1",
            "status": "running",
            "node": "rewrite_node",
            "sub_status": "rewriting",
            "grade": "A",
            "score": 88,
            "deep_eval_done": True,
        }
    }
    out = apply_live_job_overlay(jobs, live)
    assert len(out) == 1
    assert out[0]["status"] == "running"
    assert out[0]["node"] == "rewrite_node"
    assert out[0]["sub_status"] == "rewriting"
    assert out[0]["deep_eval_done"] is True
    assert out[0]["failure_info"] is None


def test_apply_live_overlay_does_not_override_feishu_terminal():
    jobs = [
        {
            "job_id": "rec_1",
            "job_name": "岗位1",
            "status": "waiting",
            "node": "manual_review_node",
            "grade": "A",
        }
    ]
    live = {
        "rec_1": {
            "job_id": "rec_1",
            "status": "waiting",
            "node": "manual_review_node",
        }
    }
    out = apply_live_job_overlay(jobs, live)
    assert out[0]["status"] == "waiting"
    assert out[0]["node"] == "manual_review_node"


def test_apply_live_overlay_injects_missing_running_job():
    live = {
        "rec_2": {
            "job_id": "rec_2",
            "job_name": "岗位2",
            "company_name": "公司2",
            "status": "running",
            "node": "evaluate_node",
            "sub_status": "ai_eval",
        }
    }
    out = apply_live_job_overlay([], live)
    assert len(out) == 1
    assert out[0]["job_id"] == "rec_2"
    assert out[0]["status"] == "running"
    assert out[0]["is_current_run"] is True


def test_apply_live_overlay_removes_raw_card_when_rec_exists():
    jobs = [
        {"job_id": "raw_1", "job_name": "岗位1", "status": "scraped", "node": "scrape_node", "job_url": "https://x/1"},
        {"job_id": "rec_1", "job_name": "岗位1", "status": "waiting", "node": "manual_review_node", "job_url": "https://x/1"},
    ]
    live = {
        "rec_1": {
            "job_id": "rec_1",
            "raw_job_id": "raw_1",
            "status": "running",
            "node": "rewrite_node",
            "sub_status": "rewriting",
        }
    }
    out = apply_live_job_overlay(jobs, live)
    assert len(out) == 1
    assert out[0]["job_id"] == "rec_1"
    assert out[0]["status"] == "running"
    assert out[0]["node"] == "rewrite_node"


def test_apply_live_overlay_upgrades_raw_card_when_no_rec():
    jobs = [{"job_id": "raw_1", "job_name": "岗位1", "status": "scraped", "node": "scrape_node"}]
    live = {
        "rec_1": {
            "job_id": "rec_1",
            "raw_job_id": "raw_1",
            "status": "running",
            "node": "evaluate_node",
            "sub_status": "ai_eval",
        }
    }
    out = apply_live_job_overlay(jobs, live)
    assert len(out) == 1
    assert out[0]["job_id"] == "rec_1"


def test_live_registry_snapshot_thread_safe():
    """step2 worker thread 写 phase_progress 时，dashboard-sync 读快照不得因 dict 变长崩溃。"""
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set() and i < 2000:
            pb.record_phase_progress_event(
                "pipeline_thread",
                {"type": "phase_progress", "phase": f"phase_{i}", "current": i, "total": 2000},
            )
            i += 1

    def reader():
        for _ in range(500):
            try:
                pb.get_stage_snapshot("pipeline_thread")
            except Exception as e:  # pragma: no cover - 失败时给出明确证据
                errors.append(e)
                return

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        reader()
    finally:
        stop.set()
        thread.join()

    assert not errors


def test_node_action_desc_is_single_source():
    assert pb.node_action_desc("evaluate_node", "ai_eval_queued") == "AI初评排队中"
    assert pb.node_action_desc("deep_eval_node", "deep_eval") == "深度画像评估中"
    assert pb.node_action_desc("rewrite_node", "rewriting") == "定制简历改写中"
    assert pb.node_action_desc("delivery_node") == "正在自动投递中"


def test_emit_job_includes_last_action_desc():
    async def scenario():
        q = pb.create_pipeline_queue("pipeline_desc")
        await pb.emit_job(
            "pipeline_desc",
            job_id="rec_desc",
            job_name="岗位",
            node="rewrite_node",
            status="running",
            sub_status="rewriting",
        )
        msg = await asyncio.wait_for(q.get(), timeout=1)
        assert "定制简历改写中" in msg

    asyncio.run(scenario())


def test_apply_live_overlay_skips_feishu_terminal_target():
    for terminal in ("delivered", "error"):
        jobs = [{"job_id": "rec_1", "job_name": "岗位1", "status": terminal, "node": "delivery_node"}]
        live = {
            "rec_1": {
                "job_id": "rec_1",
                "status": "running",
                "node": "rewrite_node",
                "sub_status": "rewriting",
                "updated_at": time.time(),
            }
        }
        out = apply_live_job_overlay(jobs, live)
        assert out[0]["status"] == terminal


def test_apply_live_overlay_skips_stale_running():
    jobs = [{"job_id": "rec_1", "job_name": "岗位1", "status": "waiting", "node": "manual_review_node"}]
    live = {
        "rec_1": {
            "job_id": "rec_1",
            "status": "running",
            "node": "rewrite_node",
            "sub_status": "rewriting",
            "updated_at": time.time() - 3600,
        }
    }
    out = apply_live_job_overlay(jobs, live)
    assert out[0]["status"] == "waiting"


def test_pending_review_query_excludes_done_and_ready(monkeypatch):
    captured = {}

    class _Resp:
        def json(self):
            return {"code": 0, "data": {"items": [], "has_more": False}}

    def _fake_request(method, url, headers=None, json=None, **kwargs):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr(feishu_service, "get_tenant_access_token", lambda: "token")
    monkeypatch.setattr(feishu_service, "safe_feishu_request", _fake_request)

    feishu_service.get_pending_review_jobs_from_feishu()

    values = [c["value"][0] for c in captured["payload"]["filter"]["conditions"]]
    assert "简历人工复核" in values
    assert "海投人工复核" in values
    assert "已完成初步评估" not in values
    assert "待投递" not in values
