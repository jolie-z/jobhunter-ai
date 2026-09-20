"""L1 失败分诊：持久性/暂时性故障分类与自动重试上限。

覆盖 2026-08-28 采纳的自愈体系 L1：
- 持久性故障（引擎执行失败/物料缺失/已下架）→ 波次不再自动发射，留在执行失败 Tab 待人工；
- 暂时性故障（登录态/浏览器/网络抖动）→ 保留自动重试，连续失败 MAX_AUTO_RETRIES 次后停手。
"""
from unittest.mock import AsyncMock

import pytest

import app.automation.scheduler as sched
import app.automation.run_snapshot as run_snapshot
from app.automation import failure_triage as triage
import app.services.feishu_service as feishu_service


# ---------------- 分类 classify_delivery_failure ----------------

def test_classify_persistent_engine_failure():
    assert triage.classify_delivery_failure("❌ 智联投递引擎执行失败，请检查相关日志") == "persistent"


def test_classify_persistent_missing_materials():
    assert triage.classify_delivery_failure("❌ 缺少 PDF 简历附件：该岗位为定制改写岗") == "persistent"
    assert triage.classify_delivery_failure("投递数据不全，缺少链接或打招呼语") == "persistent"
    assert triage.classify_delivery_failure("岗位已下架") == "persistent"


def test_classify_transient_session_and_browser():
    assert triage.classify_delivery_failure(
        "投递异常: The specified tab was not found (已自动修复微聊标签页捕获)") == "transient"
    assert triage.classify_delivery_failure("登录态失效，请重新登录") == "transient"
    assert triage.classify_delivery_failure("页面加载超时 timeout") == "transient"


def test_classify_unknown_defaults_retryable():
    assert triage.classify_delivery_failure("") == "unknown"
    assert triage.classify_delivery_failure("某个谁也没见过的错误") == "unknown"


def test_classify_persistent_wins_when_both_matched():
    # 同时命中两类关键词时按持久性处理：宁可停下等人工，不空转
    assert triage.classify_delivery_failure("登录失效且缺少 PDF 附件") == "persistent"


# ---------------- 分诊 should_skip_auto_delivery ----------------

def test_skip_persistent_failure_immediately():
    skip, reason = triage.should_skip_auto_delivery(
        {"error": "❌ 智联投递引擎执行失败", "failure_count": 1})
    assert skip and "持久性" in reason


def test_transient_below_cap_still_fires():
    skip, reason = triage.should_skip_auto_delivery(
        {"error": "登录态失效", "failure_count": 1})
    assert not skip and reason == ""


def test_transient_reaching_cap_skipped():
    skip, reason = triage.should_skip_auto_delivery(
        {"error": "登录态失效", "failure_count": triage.MAX_AUTO_RETRIES})
    assert skip and "连续失败" in reason


def test_unknown_counts_as_retryable_until_cap():
    skip, _ = triage.should_skip_auto_delivery({"error": "神秘错误", "failure_count": 1})
    assert not skip


# ---------------- 失败计数 failure_count ----------------

def test_record_failure_increments_count(monkeypatch):
    monkeypatch.setattr(run_snapshot, "_save_to_db", lambda: None)
    run_snapshot._delivery_failures.clear()

    # 15 秒纯时间窗防抖（办法 1）：同岗位窗口内重复失败视为同一次投递事件，failure_count 不虚增
    run_snapshot.record_delivery_failure("rec_a", error="登录态失效", job_name="岗位A")
    run_snapshot.record_delivery_failure("rec_a", error="登录态失效", job_name="岗位A")
    assert run_snapshot._delivery_failures["rec_a"]["failure_count"] == 1

    # 超出 15 秒时间窗后的真实再次失败，failure_count 正常累加
    from datetime import datetime, timedelta
    run_snapshot._delivery_failures["rec_a"]["failed_at"] = (
        datetime.now() - timedelta(seconds=16)
    ).strftime("%Y-%m-%d %H:%M:%S")
    run_snapshot.record_delivery_failure("rec_a", error="登录态失效", job_name="岗位A")
    assert run_snapshot._delivery_failures["rec_a"]["failure_count"] == 2

    # 登记被清除（投递成功/人工放弃）后，再次失败从 1 重新计数
    run_snapshot.remove_delivery_failure("rec_a")
    run_snapshot.record_delivery_failure("rec_a", error="登录态失效", job_name="岗位A")
    assert run_snapshot._delivery_failures["rec_a"]["failure_count"] == 1

    run_snapshot._delivery_failures.clear()


# ---------------- 波次接入（async 用例需 pytest-asyncio 才会执行） ----------------

@pytest.mark.asyncio
async def test_wave_skips_persistent_failed_jobs(monkeypatch):
    """波次发射前分诊：持久性失败的岗位不再自动发射，新岗位正常发射。"""
    monkeypatch.setattr(sched, "_delivery_guard_ok", lambda label: True)
    monkeypatch.setattr(sched, "pipeline_app", None)
    monkeypatch.setattr(sched, "get_autopilot_config",
                        lambda: {"auto_deliver_platforms": ["boss", "liepin", "51job", "zhilian"]})

    jobs = [
        {"job_id": "rec_bad", "job_name": "引擎挂了岗", "company_name": "甲", "platform": "boss"},
        {"job_id": "rec_fresh", "job_name": "新就绪岗", "company_name": "乙", "platform": "boss"},
    ]
    monkeypatch.setattr(feishu_service, "get_scheduled_delivery_jobs_from_feishu", lambda max_pages=5: jobs)
    monkeypatch.setattr(run_snapshot, "get_delivery_failures", lambda: {
        "rec_bad": {"error": "❌ 智联投递引擎执行失败", "failure_count": 1},
    })
    monkeypatch.setattr(run_snapshot, "remove_delivery_failure", lambda rid: None)
    monkeypatch.setattr(run_snapshot, "record_delivery_failure", lambda **kw: None)

    resumed: list = []

    async def _fake_resume(job_id: str):
        resumed.append(job_id)
        return True, "ok"

    mock_notifier = AsyncMock(return_value=True)
    monkeypatch.setattr(sched, "_resume_job_delivery", _fake_resume)
    monkeypatch.setattr("app.services.delivery_card_notifier.send_delivery_round_report", mock_notifier)

    await sched.scheduled_delivery_batch_task("分诊测试波次")

    assert resumed == ["rec_fresh"]
    mock_notifier.assert_awaited_once()
