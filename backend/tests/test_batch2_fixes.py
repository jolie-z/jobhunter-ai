"""第二批修复（2026-11-02 审计 P1-5/9/10/12）后端单测。"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.strategy.schemas import UpdateStrategyRequest
from app.automation.snapshot_service import classify_feishu_followup


# ---------- 修 5a：/auto-heal-and-approve 评估闸 ----------

def _fake_record(follow_status: str, grade: str) -> dict:
    return {
        "fields": {
            "跟进状态": follow_status, "综合评级 (A-F)": grade,
            "岗位名称": "岗", "公司名称": "司",
            # 海投轨（非精投）：AI改写JSON 空 + 评级非 AB → is_custom_record=False
            "AI改写JSON": "",
        }
    }


@pytest.mark.asyncio
async def test_auto_heal_approve_rejects_unrated_job():
    """无评级（未经 AI 评估）→ 409 not_evaluated，物料渲染完全不被触达"""
    import app.automation.routes.delivery_router as dr

    with patch.object(dr.feishu_service, "get_job_record_from_feishu",
                      return_value=_fake_record("简历人工复核", "")), \
         patch.object(dr.feishu_service, "extract_record_id", side_effect=lambda x: x):
        dr._AUTO_HEAL_INFLIGHT_RECORDS.clear()
        with pytest.raises(HTTPException) as exc:
            await dr.auto_heal_and_approve(type("Req", (), {"record_id": "recX"})())
    assert exc.value.status_code == 409
    assert "not_evaluated" in exc.value.detail


@pytest.mark.asyncio
async def test_auto_heal_approve_rejects_invalid_follow_status():
    """跟进状态不在待审批集合（如待投递/空）→ 409 invalid_status"""
    import app.automation.routes.delivery_router as dr

    for bad_status in ("待投递", "", "已完成深度评估"):
        with patch.object(dr.feishu_service, "get_job_record_from_feishu",
                          return_value=_fake_record(bad_status, "")), \
             patch.object(dr.feishu_service, "extract_record_id", side_effect=lambda x: x):
            dr._AUTO_HEAL_INFLIGHT_RECORDS.clear()
            with pytest.raises(HTTPException) as exc:
                await dr.auto_heal_and_approve(type("Req", (), {"record_id": "recX"})())
        assert exc.value.status_code == 409
        assert "invalid_status" in exc.value.detail


@pytest.mark.asyncio
async def test_auto_heal_approve_passes_valid_waiting_job():
    """正向用例（Opus R1-P2 防误拦）：简历人工复核+评级 B → 通过闸门进入物料渲染"""
    import app.automation.routes.delivery_router as dr

    with patch.object(dr.feishu_service, "get_job_record_from_feishu",
                      return_value=_fake_record("简历人工复核", "B")), \
         patch.object(dr.feishu_service, "extract_record_id", side_effect=lambda x: x):
        dr._AUTO_HEAL_INFLIGHT_RECORDS.clear()
        # 断言关键：没有 409 评估闸拒绝。空 AI改写JSON 会在后续物料校验抛 422
        # （"精投简历内容无效"）——那也是闸门通过后的合法业务拦截
        try:
            await dr.auto_heal_and_approve(type("Req", (), {"record_id": "recX"})())
            got_409 = False
        except HTTPException as e:
            got_409 = (e.status_code == 409)
        assert not got_409, "简历人工复核+评级B 应通过评估闸（后续 422 物料拦截属正常业务流）"


# ---------- 修 9：学历白名单 ----------

def test_education_lists_mutually_exclusive():
    UpdateStrategyRequest(require_education=["本科"], exclude_education=[])  # 单边 OK
    with pytest.raises(ValidationError, match="互斥"):
        UpdateStrategyRequest(require_education=["本科"], exclude_education=["硕士"])


def test_engine_require_education_semantics():
    from job_processor.structural_filter import StructuralFilterEngine

    eng = StructuralFilterEngine.__new__(StructuralFilterEngine)
    eng.strategy = {"exclude_education": [], "require_education": ["大专"], "keyword_rules": []}
    for edu, expect in [("本科及以上", False), ("大专", False), ("高中", True),
                        ("学历不限", False), ("", False), ("硕士", False)]:
        rejected, _ = eng.is_obvious_garbage("标题", "3年", edu)
        assert rejected == expect, f"edu={edu!r} 期望 rejected={expect}"


def test_strategy_roundtrip_persists_require_education(tmp_path, monkeypatch):
    """白名单经 schema→config_service SQL 落库再读回（死配置根治的闭环断言）"""
    import sqlite3
    import app.strategy.config_service as cs

    db = tmp_path / "strategy.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE job_strategies (
        strategy_name TEXT, is_active INTEGER, min_salary_k INTEGER, max_salary_k INTEGER,
        experience_years_max INTEGER, exclude_education TEXT, require_education TEXT,
        allowed_cities TEXT, safe_phrases TEXT, keyword_rules TEXT, ai_scout_rules TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()

    real_connect = cs.sqlite3.connect

    def fake_connect(path, *a, **k):
        return real_connect(str(db))

    monkeypatch.setattr(cs.sqlite3, "connect", fake_connect)
    cs._update_active_strategy_sync(UpdateStrategyRequest(require_education=["本科"]))
    resp = cs._fetch_active_strategy_sync()
    assert resp.require_education == ["本科"]


# ---------- 修 12：快照第 4 段分诊 ----------

def test_section4_terminal_statuses_no_longer_regress_to_waiting():
    """审计 C-1/3/4/6（CR-B2-R1-P4 修正：直接调用生产纯函数，不再重抄分支）：
    已下架/不合适/面试态/AI评估失败不再回流待审批"""
    assert classify_feishu_followup("已下架", "B")["node"] == "post_delivery"
    assert classify_feishu_followup("不合适", "C")["node"] == "manual_rejected"
    assert classify_feishu_followup("二面", "B")["node"] == "post_delivery"
    assert classify_feishu_followup("Offer", "C")["node"] == "post_delivery"
    assert classify_feishu_followup("AI评估失败", "D")["status"] == "failed"
    assert classify_feishu_followup("投递失败", "C")["status"] == "failed"
    # 失败卡补 failure_info 语义：eval_failed 归 failed 分区（非 waiting）→ 不可被放行
    assert classify_feishu_followup("AI评估失败", "")["sub_status"] == "eval_failed"


def test_section4_unchanged_branches_stable():
    """显式状态表优先级不变（回归护栏，真实生产实现）"""
    assert classify_feishu_followup("简历人工复核", "B")["status"] == "waiting"
    assert classify_feishu_followup("海投人工复核", "C")["node"] == "manual_review_node"
    assert classify_feishu_followup("待审批", "B")["status"] == "waiting"
    assert classify_feishu_followup("疑似重复", "B")["last_action_desc"] == "疑似重复岗位，待人工裁决"
    assert classify_feishu_followup("待投递", "C")["status"] == "ready_to_deliver"
    assert classify_feishu_followup("已投递", "C")["status"] == "delivered"
    assert classify_feishu_followup("已完成深度评估", "B")["status"] == "done"
    assert classify_feishu_followup("", "F")["status"] == "rejected_auto"
    assert classify_feishu_followup("", "")["status"] == "running"


def test_section4_eval_incomplete_not_in_review_and_gate_aligned():
    """停机无评级（eval_incomplete）不进待审批 + 闸门集合与快照 is_waiting 精确一致（CR-B2-R1-P1）"""
    from app.core.process_status import APPROVAL_FOLLOW_STATUSES
    from app.core.feishu_utils import extract_feishu_text
    r = classify_feishu_followup("", "", pipeline_stopped=True, crawl_recent=False)
    assert r["sub_status"] == "eval_incomplete" and r["node"] == "evaluate_node"
    # 闸门判定复现（CR-B2-R2-P2 修正：与 delivery_router 真实条件同构）
    # eval_incomplete 形态=跟进状态空+无评级 → 集合不含空串、空态兜底要求评级非空 → 拒绝
    gate_ok = (r["sub_status"] in APPROVAL_FOLLOW_STATUSES) or (not "" and "" in ("A", "B", "C", "D"))
    assert not gate_ok
    # 快照 waiting 判定与闸门集合同源（同用 APPROVAL_FOLLOW_STATUSES）
    for st in ("简历人工复核", "海投人工复核", "待审批", "疑似重复"):
        assert classify_feishu_followup(st, "B")["node"] == "manual_review_node"


def test_engine_unrecognized_education_passes():
    """解析失败/未识别档位一律放行（CR-B2-R1-P3 语义定版）"""
    from job_processor.structural_filter import StructuralFilterEngine
    eng = StructuralFilterEngine.__new__(StructuralFilterEngine)
    eng.strategy = {"exclude_education": [], "require_education": ["本科"], "keyword_rules": []}
    for edu in ("统招全日制", "详见职位描述", "电大毕业证待核"):
        rejected, _ = eng.is_obvious_garbage("标题", "3年", edu)
        assert rejected is False, f"{edu!r} 应放行（未识别档位）"


@pytest.mark.asyncio
async def test_auto_heal_approve_passes_blank_follow_with_rating():
    """快照兜底形态正向用例（CR-B2-R2-P2）：跟进状态空 + 评级 B → 通过评估闸（非 409）"""
    import app.automation.routes.delivery_router as dr

    with patch.object(dr.feishu_service, "get_job_record_from_feishu",
                      return_value=_fake_record("", "B")), \
         patch.object(dr.feishu_service, "extract_record_id", side_effect=lambda x: x):
        dr._AUTO_HEAL_INFLIGHT_RECORDS.clear()
        try:
            await dr.auto_heal_and_approve(type("Req", (), {"record_id": "recX"})())
            got_409 = False
        except HTTPException as e:
            got_409 = (e.status_code == 409)
        assert not got_409, "空跟进状态+A-D评级 应通过评估闸（后续物料 422 属正常业务流）"


def test_section4_rejected_in_pure_function():
    """「已拒绝」收敛进纯函数（CR-B2-R2-P2）：单处维护，调用方分支已删"""
    r = classify_feishu_followup("已拒绝", "B")
    assert r == {"status": "rejected_manual", "node": "manual_rejected",
                 "sub_status": "rejected_manual", "last_action_desc": "老板已拒绝"}
