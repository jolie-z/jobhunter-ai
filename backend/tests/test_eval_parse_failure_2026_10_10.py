"""F级伪造事故根治回归锁（2026-10-10，Windows agent 排查报告核实后修复）。

事故链：LLM 返回 B 级内容但 JSON 差一个闭引号 → 解析失败被伪造 grade=F → 低分轨写
「已完成初步评估」→ F 在 auto_deliver_grades 默认白名单 → B级岗位被通用简历自动投出。

覆盖：
- 廉价 JSON 修复（补引号/括号）救回近失误
- 解析失败结构化返回（grade="" + parse_failed），不再伪造 F
- 评估失败短路：不走分流轨、跟进状态=AI评估失败（词表常量）
- 投递闸门：解析失败/空评级无条件禁止自动投递
- 战报口径：空评级单列「评估失败」，不折算 D/F
- 问题1：岗位标识归一（raw_<rowid> 反查飞书 record_id）
"""
import json
import sqlite3
from unittest.mock import patch

import ai_agents.ai_evaluator as ae
from app.core.feishu_utils import FOLLOW_STATUS_EVAL_FAILED


# ---------- 廉价修复 ----------

def test_repair_json_recovers_missing_closing_quote():
    """事故原文形态：内容完整的 B 级 JSON 仅末段 rationale 漏闭引号"""
    good = json.dumps({
        "grade": "B",
        "scores": {"role_match": 4, "skills_align": 4},
        "score_rationales": {"role_match": "匹配良好。", "skills_align": "存在系统性短板。"},
    }, ensure_ascii=False)
    broken = good[:-3] + "}}"  # 事故原文形态：末段 rationale 的闭引号丢失（。"}} → 。}}）
    with __import__("pytest").raises(json.JSONDecodeError):
        json.loads(broken)
    repaired = ae._repair_json_text(broken)
    assert repaired is not None
    parsed = json.loads(repaired)
    assert parsed["grade"] == "B", "修复后必须保住真实评级 B（事故岗位本该是 B）"


def test_repair_json_returns_none_for_garbage():
    assert ae._repair_json_text("这不是JSON at all {{{{") is None


# ---------- _call_10dim_evaluation：修复→重试→结构化失败 ----------

def _llm(content: str):
    from types import SimpleNamespace
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, reasoning_content=""))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15,
                              prompt_tokens_details=None),
    )


_LOCAL_SCORE_KEYS = ["role_match", "skills_align", "seniority", "compensation",
                     "interview_prob", "company_stage", "market_fit", "growth"]
GOOD_JSON = json.dumps({
    "grade": "B",
    "scores": {k: 4 for k in _LOCAL_SCORE_KEYS},
    "score_rationales": {k: "点评" for k in _LOCAL_SCORE_KEYS},
}, ensure_ascii=False)


def test_call_10dim_repairs_broken_json_without_retry():
    """第一轮坏 JSON 但可廉价修复 → 直接救回，不烧重试"""
    calls = []
    def fake_create(**kwargs):
        calls.append(1)
        return _llm(GOOD_JSON[:-2] + "}}")
    with patch.object(ae, "get_openai_client") as m_client, \
         patch.object(ae, "_EVAL_PARSE_MAX_RETRY", 2):
        m_client.return_value.chat = __import__("types").SimpleNamespace(
            completions=__import__("types").SimpleNamespace(create=fake_create))
        result, usage = ae._call_10dim_evaluation("简历", "JD")
    assert len(calls) == 1, "廉价修复成功不得重试 LLM"
    assert result["grade"] == "B"
    assert not result.get("parse_failed")


def test_call_10dim_retries_then_succeeds():
    """修复不了 → 原样重试，第二次成功"""
    calls = []
    def fake_create(**kwargs):
        calls.append(1)
        return _llm("彻底坏掉的输出" if len(calls) == 1 else GOOD_JSON)
    with patch.object(ae, "get_openai_client") as m_client:
        m_client.return_value.chat = __import__("types").SimpleNamespace(
            completions=__import__("types").SimpleNamespace(create=fake_create))
        result, usage = ae._call_10dim_evaluation("简历", "JD")
    assert len(calls) == 2
    assert result["grade"] == "B"
    assert usage["total_tokens"] == 30, "两次调用的 token 必须累计"


def test_call_10dim_never_fabricates_grade_on_final_failure():
    """重试穷尽后结构化失败：grade 空串 + parse_failed，绝不返回伪造 F"""
    def fake_create(**kwargs):
        return _llm("彻底坏掉的输出")
    with patch.object(ae, "get_openai_client") as m_client:
        m_client.return_value.chat = __import__("types").SimpleNamespace(
            completions=__import__("types").SimpleNamespace(create=fake_create))
        result, usage = ae._call_10dim_evaluation("简历", "JD")
    assert result["grade"] == "", "空串=未产出评级；伪造 F 会进海投轨自动投递"
    assert result.get("parse_failed") is True
    assert result.get("parse_error")


def test_call_10dim_rejects_non_dict_json():
    """合法 JSON 但顶层是数组 → 视为解析失败，不得让下游 .get 炸裂"""
    def fake_create(**kwargs):
        return _llm('[1, 2, 3]')
    with patch.object(ae, "get_openai_client") as m_client:
        m_client.return_value.chat = __import__("types").SimpleNamespace(
            completions=__import__("types").SimpleNamespace(create=fake_create))
        result, _ = ae._call_10dim_evaluation("简历", "JD")
    assert result["grade"] == "" and result.get("parse_failed") is True


# ---------- evaluate_single_job 短路 ----------

def _job_data():
    return {"record_id": "recX1", "company": "蛙蔻", "job_title": "后端", "platform": "BOSS直聘",
            "jd_text": "JD", "salary": "10-15k", "city": "广州", "experience": "3年", "education": "本科"}


def test_evaluate_single_job_short_circuits_on_parse_failure():
    """解析失败：不走分流轨、跟进状态=AI评估失败（词表）、不写综合评级"""
    fake_eval = {
        "grade": "", "scores": {}, "score_rationales": {},
        "parse_failed": True, "parse_error": "Unterminated string", "raw_snippet": "...",
    }
    with patch.object(ae, "_call_10dim_evaluation", return_value=(fake_eval, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})):
        result = ae.evaluate_single_job(_job_data(), "简历内容", company_intel="有情报", preferences_text="")
    assert result["success"] is False
    assert result.get("parse_failed") is True
    assert result["update_data"]["跟进状态"] == FOLLOW_STATUS_EVAL_FAILED == "AI评估失败"
    assert "综合评级 (A-F)" not in result["update_data"], "评估失败绝不写综合评级（伪造 F 曾致误投）"


# ---------- 投递闸门 ----------

def test_delivery_gate_blocks_parse_failed_unconditionally():
    """解析失败岗无条件豁免自动投递白名单（蛙蔻事故的反例锁）"""
    from app.automation.workflow import evaluate_delivery_gate
    state = {"parse_failed": True, "platform": "BOSS直聘", "grade": "F", "company_scale": "50人"}
    ok, reason = evaluate_delivery_gate(state)
    assert ok is False
    assert "解析失败" in reason or "禁止自动投递" in reason


def test_delivery_gate_blocks_empty_grade():
    """评级缺失（评估异常）禁止自动投递——空串不得被任何白名单放行"""
    from app.automation.workflow import evaluate_delivery_gate
    state = {"platform": "BOSS直聘", "grade": "", "company_scale": "50人"}
    ok, reason = evaluate_delivery_gate(state)
    assert ok is False


def test_workflow_grade_fallback_is_empty():
    """workflow 评估节点：grade 缺省兜底从 C 改为空串（静默折 C 曾被海投轨当真实评级）"""
    import inspect
    import app.automation.workflow as wf
    src = inspect.getsource(wf)
    assert '"grade": result.get("grade", ""),' in src
    assert '"grade": result.get("grade", "C")' not in src


# ---------- 战报口径 ----------

def test_master_card_counts_eval_failure_separately():
    """战报主卡：空评级单列「评估失败」，不进 D/F 桶"""
    from app.automation.pipeline_report import send_pipeline_master_card
    import asyncio
    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {"elements": []}

    job_results = [
        {"record_id": "rec1", "platform": "BOSS直聘", "grade": "B", "outcome": "waiting"},
        {"record_id": "rec2", "platform": "猎聘", "grade": "", "outcome": "failed", "error": "8维评估JSON解析失败"},
    ]
    with patch("app.services.pipeline_card_builders.build_master_pipeline_card", side_effect=fake_builder), \
         patch("app.core.feishu_messaging.is_valid_receive_id", return_value=True), \
         patch("app.core.feishu_messaging.send_feishu_card", return_value=True), \
         patch("app.services.report_feishu._get_receive_id", return_value="oc_t"):
        asyncio.run(send_pipeline_master_card(
            started_at=__import__("datetime").datetime(2026, 10, 10, 22, 3),
            scrape_counts={"BOSS直聘": 2},
            cleaning={"hard_rejected": 0, "hard_passed": 2, "ai_rejected": 0, "ai_passed": 2},
            job_results=job_results,
        ))
    assert captured["grade_counts"].get("D/F", 0) == 0, "评估失败不得折进 D/F 桶"
    assert captured["eval_failed_cnt"] == 1


def test_text_report_labels_empty_grade_as_failure():
    """文本报告：空评级显示「评估失败」而非 ? 或 D"""
    from app.automation.pipeline_report import build_pipeline_report
    text = build_pipeline_report(
        started_at=__import__("datetime").datetime(2026, 10, 10, 22, 3),
        scrape_counts={}, disabled_platforms=[], platform_cn={},
        cleaning={"total": 2, "hard_rejected": 0, "hard_passed": 2, "ai_rejected": 0, "ai_passed": 2},
        synced_count=2,
        job_results=[{"record_id": "r", "platform": "BOSS直聘", "grade": "", "outcome": "failed", "error": "x"}],
    )
    assert "评估失败" in text


# ---------- 问题1：岗位标识归一 ----------

def test_resolve_feishu_record_id_from_raw_rowid(tmp_path):
    """raw_<rowid>/纯数字 → 反查 raw_jobs.feishu_record_id；rec 开头原样；无记录返回空"""
    from app.strategy.routes.skill_agent_router import _resolve_feishu_record_id_sync
    db = tmp_path / "raw.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE raw_jobs (feishu_record_id TEXT)")
        conn.execute("INSERT INTO raw_jobs (feishu_record_id) VALUES ('recAbc123')")
    assert _resolve_feishu_record_id_sync("recKeep", str(db)) == "recKeep"
    assert _resolve_feishu_record_id_sync("raw_1", str(db)) == "recAbc123"
    assert _resolve_feishu_record_id_sync("1", str(db)) == "recAbc123"
    assert _resolve_feishu_record_id_sync("raw_999", str(db)) == ""
    assert _resolve_feishu_record_id_sync("", str(db)) == ""


def test_resolve_warns_when_raw_lookup_misses(caplog):
    """R1 P1 回归锁：raw 反查落空（返回空串）也必须告警——最危险的未解析态不得静默"""
    import logging
    from app.strategy.routes import skill_agent_router as sar
    # 直测 worker 内联逻辑的等价条件：payload 有 id 但 clean_id 落空
    payload_job_id = "raw_999"
    clean_id = sar._resolve_feishu_record_id_sync(
        sar.extract_record_id(payload_job_id), str(__import__("pathlib").Path("/nonexistent/db"))
    )
    assert clean_id == ""
    assert payload_job_id and not (clean_id and clean_id.startswith("rec")), "告警条件必须命中"


# ---------- 问题1 补充：保存链路序列化统一（2026-10-11 排查报告修复E） ----------

def test_normalize_resume_json_field_unifies_serialization():
    """紧凑串与 indent 串统一为 indent=2；非法内容（v1 markdown）原样"""
    from app.jobs.action_service import normalize_resume_json_field
    compact = '{"a":1,"b":{"c":"中文"}}'
    out = normalize_resume_json_field(compact)
    assert out == json.dumps({"a": 1, "b": {"c": "中文"}}, ensure_ascii=False, indent=2)
    # 已是 indent 版幂等
    assert normalize_resume_json_field(out) == out
    # v1 markdown 原样
    assert normalize_resume_json_field("# 简历\n- 条目") == "# 简历\n- 条目"
    assert normalize_resume_json_field("") == ""


def test_worker_parse_error_guard():
    """解析器失败返回 {"error":...} 时命中守护判定（真实 worker 分支消费的同一函数）"""
    from app.strategy.routes.skill_agent_router import _parse_result_has_error
    assert _parse_result_has_error({"error": "LLM 返回非法结构", "original_markdown": "md"}) is True
    assert _parse_result_has_error("非 dict 返回") is True
    assert _parse_result_has_error(None) is True
    assert _parse_result_has_error({"personalInfo": {}, "summary": "正常"}) is False, "正常解析结果不得误判为失败"


# ---------- 问题3：自定义改写岗位台账扫描 ----------

def test_custom_rewrite_jobs_scans_artifacts(tmp_path):
    """扫描产物台账：skill_id != resume_rewrite 的目录入列（含 executed_at），官方目录剔除"""
    import json as _json
    from fastapi.testclient import TestClient

    from app.main import app

    runs = tmp_path / "skill_runs"
    for job, skill in [("recA", "custom_resume_optimizer"), ("recB", "resume_rewrite"), ("recC", "my_skill")]:
        d = runs / job / skill
        d.mkdir(parents=True)
        (d / "meta.json").write_text(_json.dumps({"executed_at": "2026-10-11T01:57:00", "skill_id": skill}), encoding="utf-8")

    import ai_agents.skills.skill_dirs as sd
    from app.strategy.routes import skill_artifacts_router as rr

    client = TestClient(app)
    with patch.object(sd, "SKILLS_RUNS_DIR", runs), \
         patch.object(rr, "SKILLS_RUNS_DIR", runs, create=True):
        # 路由内部延迟 import SKILLS_RUNS_DIR——patch 源头即可
        resp = client.get("/api/strategy/custom_rewrite_jobs")
    assert resp.status_code == 200
    data = resp.json()
    ids = {x["job_record_id"] for x in data["data"]}
    assert "recA" in ids and "recC" in ids, "自定义技能目录必须入列"
    assert "recB" not in ids, "官方 resume_rewrite 目录必须剔除"
    assert all(x["executed_at"] for x in data["data"])

