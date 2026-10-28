"""
全链路「终止任务」静默失效回归（2026-10-23 真机工单）

病灶三层（本文件锁定第 1、3 层的可测语义；第 2 层前端取权威 ID 由 tsc/联测保障）：
1. request_abort 对不匹配 task_id 静默 return False，接口照返 200+success 且无日志——
   用户点终止「看似受理、实际无效」。真机实录：两次终止全部没生效，链路继续跑到真实投递。
2. 前端 handleAbort 直接吃 store 陈旧僵尸 ID（上一轮未收尾任务的 ID）。
3. 进程被杀时 automation_logs 的 finally 终态不执行 → status=running/finished_at=NULL 永久残留。

修复语义锁定：
- 后端方案 B：ID 不匹配降级终止当前登记任务，响应带实际 task_id + degraded 标记；
  无登记任务 + 非空 ID → 409 显式失败；空串必生效语义原样保留。
- request_abort 守卫原语义（匹配/空串生效）不变。
- reconcile_stale_running_logs：启动清账僵尸 running，幂等，已完结行不动。
"""
import asyncio
import sqlite3
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.automation import abort as abort_mod
from app.automation import db as autopilot_db
from app.automation.routes import control_router


@pytest.fixture(autouse=True)
def _clean_abort_state():
    abort_mod._state.update({"aborted": False, "pipeline_task_id": ""})
    abort_mod._platform_aborted.clear()
    yield
    abort_mod._state.update({"aborted": False, "pipeline_task_id": ""})
    abort_mod._platform_aborted.clear()


def _call_abort(task_id: str):
    req = control_router.AbortRequest(task_id=task_id)
    return asyncio.run(control_router.abort_pipeline(req))


# ───────────────── request_abort 守卫原语义锁定 ─────────────────

def test_request_abort_guard_semantics_unchanged():
    abort_mod.begin_pipeline("pipeline_a33da56a")
    assert abort_mod.current_pipeline_task_id() == "pipeline_a33da56a"
    assert abort_mod.request_abort("pipeline_83571e16") is False, "不匹配 ID 必须拒绝（守卫语义不变）"
    assert not abort_mod.is_aborted(), "被拒的终止请求不得置位 aborted"
    assert abort_mod.request_abort("pipeline_a33da56a") is True
    assert abort_mod.is_aborted()


def test_request_abort_empty_string_always_takes_effect():
    abort_mod.begin_pipeline("pipeline_a33da56a")
    assert abort_mod.request_abort("") is True, "空串必生效语义保留"
    assert abort_mod.is_aborted()


# ───────────────── 终止接口：降级 / 409 / 假受理根治 ─────────────────

def test_abort_endpoint_degrades_to_current_registered_task():
    """真机场景复刻：store 持有僵尸旧 ID，登记任务是另一个 → 降级终止登记任务。"""
    abort_mod.begin_pipeline("pipeline_a33da56a")
    with patch("app.api.routes.crawlers.stop_platform") as mock_stop:
        res = _call_abort("pipeline_83571e16")

    assert res["aborted"] is True
    assert res["task_id"] == "pipeline_a33da56a", "必须返回实际终止的登记任务 ID"
    assert res["degraded"] is True
    assert abort_mod.is_aborted(), "降级终止必须真实置位"
    assert mock_stop.call_count == len(abort_mod.KNOWN_PLATFORMS), "平台急刹链路照常执行"


def test_abort_endpoint_matching_id_not_degraded():
    abort_mod.begin_pipeline("pipeline_a33da56a")
    with patch("app.api.routes.crawlers.stop_platform"):
        res = _call_abort("pipeline_a33da56a")
    assert res["aborted"] is True and res["degraded"] is False
    assert res["task_id"] == "pipeline_a33da56a"


def test_abort_endpoint_empty_id_reports_registered_task():
    abort_mod.begin_pipeline("pipeline_a33da56a")
    with patch("app.api.routes.crawlers.stop_platform"):
        res = _call_abort("")
    assert res["aborted"] is True and res["degraded"] is False
    assert res["task_id"] == "pipeline_a33da56a", "空串终止响应须回带登记任务 ID 供前端对账"


def test_abort_endpoint_409_when_no_registered_task_with_stale_id():
    """无登记任务 + 陈旧非空 ID：旧语义假受理（aborted=True 实则无对象），现须显式 409。"""
    with patch("app.api.routes.crawlers.stop_platform"):
        with pytest.raises(HTTPException) as exc:
            _call_abort("pipeline_83571e16")
    assert exc.value.status_code == 409
    assert not abort_mod.is_aborted(), "无对象的终止请求不得置位全局 aborted"


def test_abort_endpoint_empty_id_without_task_keeps_force_semantics():
    """无任务 + 空串：防御性强制终止语义保留（仅置标志，下一轮 begin 自然清除）。"""
    with patch("app.api.routes.crawlers.stop_platform"):
        res = _call_abort("")
    assert res["aborted"] is True


def test_abort_endpoint_degrade_race_fails_explicitly(monkeypatch):
    """【R1-P1-2】降级路径竞态：读 current_tid 与降级置位之间任务恰好收尾/切换，
    降级调用返回 False——必须显式 409，绝不返回 degraded=True 的假受理。"""
    abort_mod.begin_pipeline("pipeline_a33da56a")

    def always_rejected(task_id: str = "") -> bool:
        return False  # 原始调用与降级调用全部被拒（模拟竞态窗口内登记被清/切换）

    monkeypatch.setattr(abort_mod, "request_abort", always_rejected)
    with patch("app.api.routes.crawlers.stop_platform"):
        with pytest.raises(HTTPException) as exc:
            _call_abort("pipeline_83571e16")
    assert exc.value.status_code == 409


def test_current_pipeline_endpoint_response_shape():
    """【R1-P1-1】前端 handleAbort 依赖 /current-pipeline 的字段路径
    （data.running / data.task_id）——用断言钉死响应形状，契约漂移即测试失败。"""
    from app.automation import pipeline_broadcast as pb
    pb.set_current_pipeline("pipeline_a33da56a", True)
    try:
        res = asyncio.run(control_router.current_pipeline())
        assert res["status"] == "success"
        assert res["data"] == {"task_id": "pipeline_a33da56a", "running": True}
    finally:
        pb.set_current_pipeline(None, False)
    # 复位态（链路收尾后）：前端 running !== true 判断依赖 false 为布尔假值而非 undefined
    res_idle = asyncio.run(control_router.current_pipeline())
    assert res_idle["data"] == {"task_id": None, "running": False}


# ───────────────── automation_logs 重启清账 ─────────────────

def test_reconcile_stale_running_marks_zombies_and_is_idempotent(tmp_path, monkeypatch):
    db_file = tmp_path / "autopilot.db"
    monkeypatch.setattr(autopilot_db, "DB_PATH", str(db_file))
    autopilot_db.init_autopilot_db()

    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO automation_logs (task_id, started_at, status, jobs_processed, details) "
        "VALUES ('pipeline_83571e16', '2026-10-22T14:00:00', 'running', 0, '定时发射')")
    conn.execute(
        "INSERT INTO automation_logs (task_id, started_at, finished_at, status, jobs_processed, details) "
        "VALUES ('pipeline_done', '2026-10-21T10:00:00', '2026-10-21T10:20:00', 'success', 3, 'ok')")
    conn.commit()
    conn.close()

    assert autopilot_db.reconcile_stale_running_logs() == 1

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    zombie = conn.execute(
        "SELECT * FROM automation_logs WHERE task_id='pipeline_83571e16'").fetchone()
    done = conn.execute(
        "SELECT * FROM automation_logs WHERE task_id='pipeline_done'").fetchone()
    conn.close()

    assert zombie["status"] == "interrupted_on_restart"
    assert zombie["finished_at"], "僵尸行必须补写 finished_at"
    assert "进程重启自动结账" in zombie["details"]
    assert done["status"] == "success" and done["task_id"] == "pipeline_done", "已完结行不得被改写"

    assert autopilot_db.reconcile_stale_running_logs() == 0, "清账幂等：二次执行无残留"


def test_reconcile_stale_running_survives_missing_db(tmp_path, monkeypatch):
    """库不存在/表缺失等异常不得阻断启动（吞异常返回 0）。"""
    monkeypatch.setattr(autopilot_db, "DB_PATH", str(tmp_path / "nonexistent" / "x.db"))
    assert autopilot_db.reconcile_stale_running_logs() == 0
