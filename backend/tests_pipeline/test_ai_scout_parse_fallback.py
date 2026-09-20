"""回归测试：AI 排雷异常状态 fail-preserve（Bug 3）。

事故模型（修复前）：
  - 模型返回非 JSON（格式偏离）→ _parse_evaluate_result 返回 {} →
    _check_ai_rules 把空 dict 当成「所有 must 条件都不满足」→ 大面积误杀
  - API 网络/配额异常 → evaluate_job 返回 PASS（fail-open）→
    不合格岗位整批漏进待推送池

修复后契约（fail-preserve）：
  - 解析失败 / 非法返回 / API 异常 → 状态 PRESERVE → 岗位保留「待AI初筛」
  - 正常 JSON + must 规则不满足 → 正常 REJECT（原逻辑不变）
  - 正常 JSON + 全部满足 → 正常 PASS（原逻辑不变）
"""
import asyncio
import sqlite3

import pytest

from job_processor import step1_rule_filter
from job_processor.step1_rule_filter import AIScoutEngine, _run_tier2_ai_scout


STRATEGY = {
    "ai_scout_rules": [
        {"keyword": "是销售岗", "desc": "是否为销售性质岗位", "condition": "never"},
        {"keyword": "有量化经验", "desc": "是否有可量化的项目成果", "condition": "must"},
    ],
}


@pytest.mark.asyncio
async def test_malformed_llm_output_preserves_job():
    """模型返回非 JSON：must 岗位不被误杀，保留待AI初筛（PRESERVE）。"""
    engine = AIScoutEngine(STRATEGY)
    with patch_llm("这是格式偏离的输出，不是 JSON"):
        res = await engine.evaluate_job("数据分析师", "负责数据平台建设", "测试公司")
    assert res["status"] == "PRESERVE"


@pytest.mark.asyncio
async def test_api_error_preserves_job():
    """API 网络/配额异常：fail-preserve 而非 fail-open 放行。"""
    engine = AIScoutEngine(STRATEGY)
    with patch_llm(None, raise_exc=RuntimeError("API quota exhausted")):
        res = await engine.evaluate_job("数据分析师", "负责数据平台建设", "测试公司")
    assert res["status"] == "PRESERVE"


@pytest.mark.asyncio
async def test_valid_llm_output_with_must_unsatisfied_still_rejects():
    """对照面：正常 JSON 且 must 不满足 → REJECT（保证修复没有误伤主逻辑）。"""
    engine = AIScoutEngine(STRATEGY)
    with patch_llm('{"是销售岗": false, "有量化经验": false}'):
        res = await engine.evaluate_job("数据分析师", "负责数据平台建设", "测试公司")
    assert res["status"] == "REJECT"
    assert "有量化经验" in res["reject_reason"]


@pytest.mark.asyncio
async def test_valid_llm_output_all_pass_still_passes():
    """对照面：正常 JSON 且全部满足 → PASS。"""
    engine = AIScoutEngine(STRATEGY)
    with patch_llm('{"是销售岗": false, "有量化经验": true}'):
        res = await engine.evaluate_job("数据分析师", "负责数据平台建设", "测试公司")
    assert res["status"] == "PASS"


def test_parse_result_returns_none_on_garbage():
    """空 dict 陷阱已拆除：解析失败返回 None 而非 {}。"""
    engine = AIScoutEngine(STRATEGY)
    assert engine._parse_evaluate_result("not json at all") is None
    assert engine._parse_evaluate_result("[1, 2, 3]") is None  # 合法 JSON 但非 dict


@pytest.mark.asyncio
async def test_tier2_preserved_jobs_stay_in_pending_pool(tmp_path):
    """集成面：_run_tier2_ai_scout 中 PRESERVE 岗位不被落库流转，保留「待AI初筛」。"""
    db_file = str(tmp_path / "ai_scout.db")
    link = "https://example.com/job/1"
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                job_link TEXT PRIMARY KEY, job_title TEXT, jd_text TEXT,
                company_name TEXT, process_status TEXT, reject_reason TEXT
            )
        """)
        conn.execute(
            "INSERT INTO raw_jobs VALUES (?, '数据分析师', 'JD 内容', '测试公司', '待AI初筛', NULL)",
            (link,),
        )
        conn.commit()

    with patch_db(db_file), patch_llm("模型今天状态不佳，返回了一段散文"):
        conn = sqlite3.connect(db_file)
        try:
            await _run_tier2_ai_scout(
                conn.cursor(), conn, STRATEGY, sse_task_id=None,
                limit=None, target_links=[link],
            )
        finally:
            conn.close()

    with sqlite3.connect(db_file) as conn:
        status = conn.execute(
            "SELECT process_status, reject_reason FROM raw_jobs WHERE job_link = ?", (link,)
        ).fetchone()
    assert status == ("待AI初筛", None), "PRESERVE 岗位必须原样保留在待AI初筛池"


# ---------- 测试工具 ----------

from unittest.mock import patch


class _FakeCompletion:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def patch_llm(content, raise_exc=None):
    """mock get_cleaner_client 的 create；content=None 且 raise_exc 时抛异常。"""
    async def fake_create(**kwargs):
        if raise_exc:
            raise raise_exc
        return _FakeCompletion(content)
    client = type("Client", (), {})()
    client.chat = type("Chat", (), {})()
    client.chat.completions = type("Comp", (), {})()
    client.chat.completions.create = fake_create
    return patch.object(step1_rule_filter, "get_cleaner_client", return_value=client)


def patch_db(db_path):
    """_run_tier2_ai_scout 直接用传入的 conn，此 patch 仅为未来实现切换预留。"""
    from contextlib import contextmanager
    @contextmanager
    def _noop(*a, **kw):
        yield
    return _noop()
