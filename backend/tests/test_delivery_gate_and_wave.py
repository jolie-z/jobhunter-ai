"""海投投递闸门与定时发射双保险的回归测试。

覆盖 2026-08 修复的两个问题：
1. quick_greeting_node 在安检判定前预写「待投递」门牌，导致定时波次误捞未审批岗位（方案A：门牌跟随安检结果）；
2. 定时发射波次对停在校验断点、无老板放行标记的岗位缺少兜底拦截（方案B：波次双保险）。
"""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from langgraph.graph import END

import app.automation.workflow as wf
import app.automation.scheduler as sched
import app.automation.db as automation_db
import app.automation.run_snapshot as run_snapshot
import app.services.feishu_service as feishu_service


BASE_CFG = {
    "mass_apply_max_headcount": 1000,
    "auto_deliver_platforms": ["boss", "liepin", "51job", "zhilian"],
    "auto_deliver_grades": ["C", "D", "F"],
    "mass_apply_greeting": "你好呀",
}


def _patch_config(monkeypatch, cfg=None):
    monkeypatch.setattr(wf, "get_autopilot_config", lambda: dict(cfg or BASE_CFG))


# ---------------- 安检闸门 evaluate_delivery_gate ----------------

def test_gate_small_company_mass_passes(monkeypatch):
    _patch_config(monkeypatch)
    ok, reason = wf.evaluate_delivery_gate(
        {"grade": "C", "platform": "boss", "feishu_fields": {"公司规模": "50-150人"}}
    )
    assert ok and reason == ""


def test_gate_big_company_mass_blocked(monkeypatch):
    _patch_config(monkeypatch)
    ok, reason = wf.evaluate_delivery_gate(
        {"grade": "C", "platform": "boss", "feishu_fields": {"公司规模": "1000-5000人"}}
    )
    assert not ok and "门槛" in reason


def test_gate_grade_not_in_whitelist_blocked(monkeypatch):
    _patch_config(monkeypatch)
    ok, reason = wf.evaluate_delivery_gate(
        {"grade": "A", "platform": "boss", "feishu_fields": {}}
    )
    assert not ok and "白名单" in reason


def test_gate_platform_disabled_blocked(monkeypatch):
    _patch_config(monkeypatch)
    ok, reason = wf.evaluate_delivery_gate(
        {"grade": "C", "platform": "xiaohongshu", "feishu_fields": {}}
    )
    assert not ok and "平台" in reason


def test_gate_custom_track_skips_size_check(monkeypatch):
    _patch_config(monkeypatch)
    ok, reason = wf.evaluate_delivery_gate(
        {"grade": "C", "platform": "boss", "final_markdown": "# 定制简历",
         "feishu_fields": {"公司规模": "5000-10000人"}}
    )
    assert ok and reason == ""


# ---------------- 路由 route_before_delivery ----------------

def test_route_pass_scheduled_goes_end(monkeypatch):
    _patch_config(monkeypatch)
    state = {"grade": "C", "platform": "boss", "feishu_fields": {"公司规模": "50人"},
             "stop_at_review": True, "job_name": "测试岗"}
    assert wf.route_before_delivery(state) == END


def test_route_pass_manual_goes_delivery(monkeypatch):
    _patch_config(monkeypatch)
    state = {"grade": "C", "platform": "boss", "feishu_fields": {"公司规模": "50人"},
             "stop_at_review": False, "job_name": "测试岗"}
    assert wf.route_before_delivery(state) == "delivery_node"


def test_route_big_company_blocked_to_review(monkeypatch):
    _patch_config(monkeypatch)
    state = {"grade": "C", "platform": "boss", "feishu_fields": {"公司规模": "5000人"},
             "stop_at_review": True, "job_name": "测试岗"}
    assert wf.route_before_delivery(state) == "manual_review_node"


def test_route_error_ends(monkeypatch):
    _patch_config(monkeypatch)
    assert wf.route_before_delivery({"error": "评估失败"}) == END


# ---------------- 方案A：quick_greeting_node 门牌跟随安检结果 ----------------

class _FakeFeishuTool:
    def __init__(self, captured: dict):
        self._captured = captured

    async def ainvoke(self, inp: dict):
        self._captured.update(inp["updates"])


@pytest.mark.asyncio
async def test_quick_greeting_writes_ready_label_when_gate_passes(monkeypatch):
    # 配置带海投母本 ID，避免按需挂载时回退真实飞书查激活简历
    _patch_config(monkeypatch, {**BASE_CFG, "mass_apply_resume_id": "rec_mass_base"})
    captured: dict = {}
    monkeypatch.setattr(wf, "update_feishu_status", _FakeFeishuTool(captured))
    monkeypatch.setattr(wf, "_emit_node_running", _noop_emit)
    # BOSS 岗缺长图会触发按需挂载：单测环境必须 Mock 渲染器，否则命中「不拉起 Playwright」的安全跳过路径，
    # material_ready 恒为 False，门牌永远是「海投人工复核」
    monkeypatch.setattr(
        "app.automation.materials._render_mass_resume_materials",
        AsyncMock(return_value={"pdf_token": "tok_pdf", "img_token": "tok_img", "name": "海投简历"}),
    )

    state = {"record_id": "rec1", "job_name": "小厂岗", "grade": "C", "platform": "boss",
             "feishu_fields": {"PDF备份": [{"file_token": "x"}]}}
    await wf.quick_greeting_node(state)
    assert captured["跟进状态"] == "待投递"
    # 缺的长图被实际挂载回写，而非只改门牌
    assert captured["图片保存"][0]["file_token"] == "tok_img"


@pytest.mark.asyncio
async def test_quick_greeting_writes_review_label_when_gate_blocked(monkeypatch):
    _patch_config(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(wf, "update_feishu_status", _FakeFeishuTool(captured))
    monkeypatch.setattr(wf, "_emit_node_running", _noop_emit)

    state = {"record_id": "rec2", "job_name": "大厂岗", "grade": "C", "platform": "boss",
             "feishu_fields": {"PDF备份": [{"file_token": "x"}], "公司规模": "5000-10000人"}}
    await wf.quick_greeting_node(state)
    assert captured["跟进状态"] == "海投人工复核"


async def _noop_emit(state, node_name, sub_status):
    return None


# ---------------- 方案B：定时发射波次双保险 ----------------

class _FakePipelineApp:
    def __init__(self, parked_ids):
        self._parked = set(parked_ids)

    async def aget_state(self, config):
        tid = config["configurable"]["thread_id"]
        if tid in self._parked:
            return SimpleNamespace(next=("manual_review_node",), values={})
        return SimpleNamespace(next=(), values={})


@pytest.mark.asyncio
async def test_wave_skips_unapproved_parked_jobs(monkeypatch):
    monkeypatch.setattr(sched, "_delivery_guard_ok", lambda label: True)
    monkeypatch.setattr(sched, "pipeline_app",
                        _FakePipelineApp(parked_ids={"rec_parked", "rec_ok_parked"}))
    monkeypatch.setattr(sched, "get_autopilot_config", lambda: dict(BASE_CFG))

    jobs = [
        {"job_id": "rec_parked", "job_name": "未审批大厂岗", "company_name": "大厂", "platform": "boss"},
        {"job_id": "rec_ok_parked", "job_name": "已审批岗", "company_name": "中厂", "platform": "boss"},
        {"job_id": "rec_direct", "job_name": "免审直入岗", "company_name": "小厂", "platform": "boss"},
    ]
    monkeypatch.setattr(feishu_service, "get_scheduled_delivery_jobs_from_feishu", lambda max_pages=5: jobs)

    flipped: dict = {}
    monkeypatch.setattr(feishu_service, "update_feishu_record",
                        lambda rid, updates: flipped.update({rid: updates.get("跟进状态")}))
    monkeypatch.setattr(automation_db, "has_approval_mark", lambda rid: rid == "rec_ok_parked")

    resumed: list = []
    monkeypatch.setattr(sched, "_resume_job_delivery",
                        _fake_resume(resumed))
    monkeypatch.setattr(run_snapshot, "remove_delivery_failure", lambda rid: None)
    monkeypatch.setattr(run_snapshot, "record_delivery_failure", lambda **kw: None)
    mock_notifier = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.delivery_card_notifier.send_delivery_round_report", mock_notifier)

    await sched.scheduled_delivery_batch_task("测试波次")

    # 无放行标记的断点岗被拦截并回写门牌；已审批断点岗与免审直入岗正常发射
    assert resumed == ["rec_ok_parked", "rec_direct"]
    assert flipped == {"rec_parked": "海投人工复核"}
    mock_notifier.assert_awaited_once()


def _fake_resume(resumed: list):
    async def _inner(job_id: str):
        resumed.append(job_id)
        return True, "ok"
    return _inner


# ---------------- 放行标记表 ----------------

def test_approval_mark_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(automation_db, "DB_PATH", tmp_path / "autopilot_test.db")
    with sqlite3.connect(automation_db.DB_PATH) as conn:
        conn.execute("CREATE TABLE boss_approvals (record_id TEXT PRIMARY KEY, approved_at TEXT NOT NULL)")

    assert automation_db.has_approval_mark("rec_x") is False
    assert automation_db.mark_job_approved("rec_x") is True
    assert automation_db.has_approval_mark("rec_x") is True


# ---------------- 幽灵 E 级清理契约 ----------------

def test_default_whitelist_has_no_ghost_e(tmp_path, monkeypatch):
    """评估器只产出 A/B/C/D/F，各处默认免审白名单必须与之一致（E 是永不触发的幽灵等级）。"""
    monkeypatch.setattr(automation_db, "DB_PATH", tmp_path / "autopilot_init.db")
    automation_db.init_autopilot_db()
    with sqlite3.connect(automation_db.DB_PATH) as conn:
        grades = json.loads(conn.execute(
            "SELECT auto_deliver_grades FROM automation_configs WHERE id = 1"
        ).fetchone()[0])
    assert grades == ["C", "D", "F"]


def test_no_ghost_e_defaults_in_source():
    """源码契约：默认白名单清单不得再出现幽灵 E 档。"""
    backend = Path(__file__).resolve().parents[1]
    offenders = [
        str(p.relative_to(backend.parent))
        for p in list((backend / "app").rglob("*.py")) + list((backend / "ai_agents").rglob("*.py"))
        if '"C", "D", "E", "F"' in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"默认白名单仍含幽灵 E: {offenders}"
