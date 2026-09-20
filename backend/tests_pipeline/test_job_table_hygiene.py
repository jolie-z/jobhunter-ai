"""岗位表卫生（去重归档 + 存活积压规划）测试。

覆盖：分组与正主选取、四类保护过滤（受保护状态/进行中评估/白名单/会话指针）、
plan-execute 分离（未确认不执行）、归档写入字段、存活积压统计。

外部边界（飞书写入、岗位缓存）全部 Mock；分组/保护/统计逻辑真实执行。
"""
import asyncio
import json

import pytest

from app.services import job_table_hygiene as hyg


def _job(rid, company, title, status="新线索", resume="", fetch_time=""):
    return {"record_id": rid, "company_name": company, "job_name": title,
            "follow_status": status, "platform": "boss",
            "ai_rewrite_json": resume, "fetch_time": fetch_time,
            "grade": "B" if resume else ""}


JOBS = [
    _job("recLeader", "唯品会（中国）有限公司", "AI产品运营", resume="json串"),
    _job("recShadow1", "唯品会(中国)有限公司", "AI产品运营（客服方向）"),  # 注意：岗位名不同 → 不该与上面合并
    _job("recDup1", "唯品会（中国）有限公司", "AI产品运营"),
    _job("recDup2", "唯品会 中国 有限公司", "AI 产品运营"),
    _job("recSingle", "字节跳动", "后端开发工程师"),
]


@pytest.fixture
def mock_jobs(monkeypatch):
    from app.jobs import service as js

    async def fake_jobs(force=False):
        return [dict(j) for j in JOBS]

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)


def test_plan_groups_exact_dup_and_picks_richest_leader(mock_jobs):
    plan = _run(hyg.plan_dedup())

    # 唯品会 AI产品运营 3 条同键（去标点归一后同名），「AI产品运营（客服方向）」岗位名不同不合并
    assert plan["group_count"] == 1
    g = plan["groups"][0]
    assert g["leader_record_id"] == "recLeader", "有简历的正主应保留"
    assert {s["record_id"] for s in g["archivable"]} == {"recDup1", "recDup2"}
    assert plan["archivable_count"] == 2
    assert plan["total_jobs"] == len(JOBS)


def test_plan_protects_applied_and_whitelisted_and_pointer(mock_jobs, monkeypatch):
    from app.services import job_dedup_gate, resume_edit_chat

    # recDup1 = 已投递（状态保护）；recDup2 = 白名单 + 会话指针引用
    JOBS[2]["follow_status"] = "已投递"
    resume_edit_chat.record_delivered_context("oc_y", "recDup2")
    monkeypatch.setattr(job_dedup_gate, "load_overrides", lambda: {"recDup2"})

    try:
        plan = _run(hyg.plan_dedup())
    finally:
        JOBS[2]["follow_status"] = "新线索"
        resume_edit_chat._last_delivered.pop("oc_y", None)

    g = plan["groups"][0]
    reasons = {s["record_id"]: s["protected_reason"] for s in g["shadows"]}
    assert "状态受保护" in (reasons["recDup1"] or "")
    assert "白名单" in (reasons["recDup2"] or "")
    assert plan["archivable_count"] == 0, "两条影子都受保护时不应有可归档"


def test_execute_requires_confirmation(mock_jobs):
    out = _run(hyg.execute_dedup(confirmed=False))
    assert out["executed"] is False


def test_execute_archives_shadows_only(mock_jobs, monkeypatch):
    from app.core import feishu_client as fcm

    written = []

    async def fake_update(table_id, record_id, fields):
        written.append((record_id, fields))

    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(hyg.asyncio, "sleep", _nosleep)

    out = _run(hyg.execute_dedup(confirmed=True))

    assert out["executed"] is True and out["archived"] == 2 and out["failed"] == 0
    assert {r for r, _ in written} == {"recDup1", "recDup2"}
    assert all(f["跟进状态"] == hyg.ARCHIVE_STATUS for _, f in written)
    # 正主与无关岗位绝不能被写
    assert "recLeader" not in {r for r, _ in written} and "recSingle" not in {r for r, _ in written}


def test_liveness_backlog_counts_stale_active_only(mock_jobs, monkeypatch):
    import time as _time

    old = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(_time.time() - 40 * 86400))
    fresh = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime())
    JOBS[0]["fetch_time"] = old   # 唯品会正主：老 + 新线索 → 计入
    JOBS[3]["fetch_time"] = old   # recDup1：老 + 新线索 → 计入
    JOBS[4]["fetch_time"] = fresh  # 字节：新 → 不计

    try:
        out = _run(hyg.plan_liveness_backlog())
    finally:
        for j in JOBS:
            j["fetch_time"] = ""

    assert out["backlog_total"] == 2, "只有超龄且活跃态的计入积压"
    assert out["planned_batches"] == 1
    assert "boss" in out["by_platform"]


def test_summarize_report_is_human_readable(mock_jobs):
    report = _run(hyg.hygiene_report())
    text = hyg.summarize_report(report)
    assert "重复岗位" in text and "归档" in text
    assert "绝不物理删除" in text


def _nosleep(*a, **k):
    async def _f():
        return None
    return _f()


def _run(coro):
    return asyncio.run(coro)


# ==========================================
# 疑似重复复核（母本案卷 + AI意见 + 放行）
# ==========================================
def _suspect(rid, company, title, sim, status="疑似重复"):
    """贴近真实案卷格式的疑似重复岗位（综合相似度 + 母本岗位/链接）。"""
    return {"record_id": rid, "company_name": company, "job_name": title,
            "follow_status": status, "platform": "BOSS直聘",
            "salary": "15-20K", "city": "上海",
            "job_link": f"https://example.com/{rid}",
            "ai_evaluation_detail": (f"⚠️ 疑似重复岗位（综合相似度 {sim}%，JD 重合({sim}%)且岗位名沾边）\n"
                                      f"母本岗位：AI产品经理（BOSS直聘）\n母本链接：https://example.com/parent"),
            "ai_rewrite_json": "", "fetch_time": ""}


def test_review_three_tier_funnel(monkeypatch):
    """三层漏斗：铁证自动维持不进决策；放行建议单列；只有边界条目需要拍板（含母本对比）。"""
    from app.jobs import service as js

    jobs = [
        _suspect("recIron", "甲公司", "AI产品经理", 99),    # 铁证：真重复 + 相似度≥90 → 自动维持
        _suspect("recBorder", "乙公司", "AI产品经理", 72),  # 边界：真重复但相似度<90 → 需拍板
        _suspect("recRelease", "丙公司", "AI产品经理", 69),  # 放行建议
        _job("recNormal", "丁公司", "后端开发"),
    ]

    async def fake_jobs(force=False):
        return [dict(j) for j in jobs]

    async def fake_verdicts(suspects):
        assert {s["record_id"] for s in suspects} == {"recIron", "recBorder", "recRelease"}
        return {"recIron": {"verdict": "真重复", "reason": "完全一致"},
                "recBorder": {"verdict": "真重复", "reason": "名称相近但需人工确认"},
                "recRelease": {"verdict": "建议放行", "reason": "职能方向明显不同"}}

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)
    monkeypatch.setattr(hyg, "_llm_verdicts", fake_verdicts)

    out = _run(hyg.review_duplicate_suspects())

    assert out["auto_kept_count"] == 1 and out["auto_kept"][0]["record_id"] == "recIron"
    assert out["suggest_approve"] == ["recRelease"]
    assert [it["record_id"] for it in out["need_decision"]] == ["recBorder"], "只有边界条目需要拍板"
    border = out["need_decision"][0]
    assert border["parent"]["parent_title"] == "AI产品经理"
    assert border["parent"]["parent_platform"] == "BOSS直聘", "贪婪正则应取最后一对括号里的平台"
    assert border["job_link"].startswith("https://")
    text = out["summary"]
    assert "铁证重复" in text and "无需操作" in text
    assert "建议放行" in text
    assert "边界条目" in text and "【母本】" in text and "【本条】" in text
    assert "recNormal" not in text, "非重复岗位不应出现在报告里"


def test_review_suspects_llm_failure_degrades_to_boundary(monkeypatch):
    from app.jobs import service as js

    jobs = [_suspect("recS1", "甲公司", "AI产品经理", 95)]

    async def fake_jobs(force=False):
        return [dict(j) for j in jobs]

    async def boom(suspects):
        raise RuntimeError("LLM 超时")

    monkeypatch.setattr(js, "fetch_and_clean_all_jobs", fake_jobs)
    monkeypatch.setattr(hyg, "_llm_verdicts", boom)

    out = _run(hyg.review_duplicate_suspects())

    assert out["count"] == 1
    assert out["items"][0]["ai_verdict"] == "无法判断"
    assert out["suggest_approve"] == [], "AI 意见不可用时不应自动建议放行"
    assert out["auto_kept_count"] == 0, "无法判断不应进铁证层（保守交人工）"
    assert [it["record_id"] for it in out["need_decision"]] == ["recS1"], "无法判断按边界交人工拍板"


def test_approve_suspects_updates_status_and_whitelist(monkeypatch):
    from app.core import feishu_client as fcm
    from app.services import job_dedup_gate

    written, whitelisted = [], []

    async def fake_update(table_id, record_id, fields):
        written.append((record_id, fields))

    def fake_override(record_id):
        whitelisted.append(record_id)

    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(job_dedup_gate, "record_dedup_override", fake_override)

    out = _run(hyg.approve_suspects(["recS2", "recS5"]))

    assert out["approved"] == 2 and out["failed"] == 0
    assert {r for r, _ in written} == {"recS2", "recS5"}
    assert all(f["跟进状态"] == "新线索" for _, f in written), "放行应改回新线索"
    assert set(whitelisted) == {"recS2", "recS5"}, "放行必须记入去重白名单（否则会被查重再拦）"
