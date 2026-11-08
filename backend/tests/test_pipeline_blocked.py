"""任务级 LLM 阻塞状态回归（2026-10-31 上游聚合网关 账号池全灭事故）。

锁定：
- AI 侦察兵 PRESERVE 路径（请求 503 / 解析失败）把错误按 classify_llm_error 分类上报，
  任务级阻塞登记置位；任一次真实成功即清除；
- 清洗泵在阻塞首次置位时广播 stage(status=blocked)；
- 编排器收尾 apply_outcome：存在阻塞且有「待AI初筛」遗留时 end 摘要打 outcome=blocked；
- 阻塞态随 stage 快照下发（dashboard-sync，刷新页面不丢）；
- /api/automation/llm-health 体检端点与 /api/automation/resume-cleaning 继续任务端点。
"""
import asyncio
import json
import sqlite3
import time

import pytest

from app.automation import abort as abort_mod
from app.automation import pipeline_blocked
from app.automation import pipeline_broadcast as pb
from app.automation.cleaning_pump import run_cleaning_pump
from job_processor import step1_rule_filter


class FakeUpstreamError(Exception):
    """模拟 上游聚合网关 网关 503（SDK 异常形态：带 status_code 属性）。"""

    def __init__(self, message: str = "Error code: 503 - no_healthy_account"):
        super().__init__(message)
        self.status_code = 503


def _make_db(path, n=2):
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE raw_jobs (
            job_link TEXT PRIMARY KEY,
            platform TEXT,
            job_title TEXT,
            company_name TEXT,
            salary TEXT,
            city TEXT,
            experience_req TEXT,
            education_req TEXT,
            jd_text TEXT,
            publish_date TEXT,
            process_status TEXT DEFAULT '已存入数据',
            reject_reason TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE job_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            is_active INTEGER,
            min_salary_k REAL,
            max_salary_k REAL,
            experience_years_max INTEGER,
            exclude_education TEXT DEFAULT '[]',
            allowed_cities TEXT DEFAULT '[]',
            safe_phrases TEXT DEFAULT '[]',
            keyword_rules TEXT DEFAULT '[]',
            ai_scout_rules TEXT DEFAULT '[]'
        )"""
    )
    # ai_scout_rules 必须非空：空规则时 evaluate_job 直接放行，根本不会发起 LLM 调用
    conn.execute(
        "INSERT INTO job_strategies (is_active, min_salary_k, max_salary_k, experience_years_max, ai_scout_rules) "
        "VALUES (1, 10, 25, 99, ?)",
        (json.dumps([{"keyword": "双休", "condition": "must", "desc": "每周双休"}]),),
    )
    for i in range(n):
        conn.execute(
            "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, salary, city, "
            "experience_req, education_req, jd_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"https://jobs/{i}", "智联招聘", f"数据产品经理{i}", f"测试公司{i}",
             "15-25K", "广州", "1-3年", "本科", "岗位职责描述内容"),
        )
    conn.commit()
    conn.close()


def _count_status(path, status):
    conn = sqlite3.connect(path)
    n = conn.execute(
        "SELECT COUNT(*) FROM raw_jobs WHERE process_status = ?", (status,)).fetchone()[0]
    conn.close()
    return n


def _mark_all_pending(path):
    """把全部行翻到「待AI初筛」：_async_run_ai_scout_only 只扫该状态池（模拟硬规则已完成）。"""
    conn = sqlite3.connect(path)
    conn.execute("UPDATE raw_jobs SET process_status = '待AI初筛'")
    conn.commit()
    conn.close()


@pytest.fixture
def scout_db(tmp_path, monkeypatch):
    db = tmp_path / "blocked.db"
    _make_db(db)
    monkeypatch.setattr(step1_rule_filter, "DB_PATH", str(db))
    step1_rule_filter.set_stop_flag(False)
    return db


async def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


# ── 登记表单元行为 ──────────────────────────────────────────────────────────

def test_report_failure_then_success_clears():
    pipeline_blocked.reset_all()
    state = pipeline_blocked.report_llm_failure(
        "pipeline_unit_t", kind="server", model="m-1",
        message="模型服务端异常（503）", gateway_hint="503 no_healthy_account")
    assert state["blocked"] is True
    assert state["kind"] == "server"
    assert state["failed_count"] == 1
    assert state["model"] == "m-1"
    # 重复失败累计并刷新为最近一次根因
    state = pipeline_blocked.report_llm_failure("pipeline_unit_t", kind="rate_limited", message="频控")
    assert state["failed_count"] == 2
    assert state["kind"] == "rate_limited"

    pipeline_blocked.attach_scope("pipeline_unit_t", min_rowid=42)
    assert pipeline_blocked.get_blocked_state("pipeline_unit_t")["min_rowid"] == 42

    pipeline_blocked.report_llm_success("pipeline_unit_t")
    assert pipeline_blocked.get_blocked_state("pipeline_unit_t") is None


def test_apply_outcome_requires_preserved_rows():
    pipeline_blocked.reset_all()
    pipeline_blocked.report_llm_failure("pipeline_outcome_t", kind="server", message="x")
    summary = pipeline_blocked.apply_outcome({"jobs": 6}, "pipeline_outcome_t", 6)
    assert summary["outcome"] == "blocked"
    assert summary["blocked"]["kind"] == "server"
    assert summary["blocked"]["task_id"] == "pipeline_outcome_t"

    # 遗留为 0（已自愈/无遗留）不打阻塞标记
    summary2 = pipeline_blocked.apply_outcome({"jobs": 6}, "pipeline_outcome_t", 0)
    assert "outcome" not in summary2
    # 无阻塞登记时不改动摘要
    assert pipeline_blocked.apply_outcome({"jobs": 1}, "pipeline_no_block_t", 9) == {"jobs": 1}


def test_stage_snapshot_carries_blocked_for_dashboard_sync():
    pipeline_blocked.reset_all()
    pb.set_current_pipeline("pipeline_snap_t", False)
    pipeline_blocked.report_llm_failure(
        "pipeline_snap_t", kind="server", model="wb-model",
        message="模型服务端异常（503）", gateway_hint="503 no_healthy_account")
    try:
        snap = pb.get_stage_snapshot()
        assert snap["task_id"] == "pipeline_snap_t"
        assert snap["blocked"]["kind"] == "server"
        assert snap["blocked"]["model"] == "wb-model"
    finally:
        pipeline_blocked.reset_all()
        pb.set_current_pipeline(None, False)


# ── AI 侦察兵 PRESERVE 路径上报 ─────────────────────────────────────────────

async def test_ai_scout_503_sets_blocked_and_preserves_rows(scout_db, monkeypatch):
    _mark_all_pending(scout_db)
    pipeline_blocked.reset_all()
    pb.create_pipeline_queue("pipeline_503_t")

    def raise_503():
        raise FakeUpstreamError()

    monkeypatch.setattr(step1_rule_filter, "get_cleaner_client", raise_503)
    passed = await step1_rule_filter._async_run_ai_scout_only(sse_task_id="pipeline_503_t")
    assert passed == []
    # fail-preserve 语义不变：岗位留在待AI初筛
    assert _count_status(scout_db, "待AI初筛") == 2

    state = pipeline_blocked.get_blocked_state("pipeline_503_t")
    assert state is not None
    assert state["kind"] == "server"
    assert state["failed_count"] == 2
    assert state["model"]
    assert "503" in state["gateway_hint"]
    pipeline_blocked.reset_all()


async def test_ai_scout_parse_failure_sets_unknown_blocked(scout_db, monkeypatch):
    _mark_all_pending(scout_db)
    pipeline_blocked.reset_all()
    pb.create_pipeline_queue("pipeline_parse_t")

    class MockMessage:
        content = "这不是 JSON"

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]

    mock_client = type("C", (), {})()
    mock_client.chat = type("Chat", (), {})()
    mock_client.chat.completions = type("Completions", (), {})()

    async def mock_create(*_args, **_kwargs):
        return MockResponse()

    mock_client.chat.completions.create = mock_create
    monkeypatch.setattr(step1_rule_filter, "get_cleaner_client", lambda: mock_client)

    await step1_rule_filter._async_run_ai_scout_only(sse_task_id="pipeline_parse_t")
    state = pipeline_blocked.get_blocked_state("pipeline_parse_t")
    assert state is not None
    assert state["kind"] == "unknown"
    assert "格式异常" in state["message"]
    pipeline_blocked.reset_all()


async def test_ai_scout_success_clears_blocked(scout_db, monkeypatch):
    _mark_all_pending(scout_db)
    pipeline_blocked.reset_all()
    pb.create_pipeline_queue("pipeline_recover_t")
    pipeline_blocked.report_llm_failure("pipeline_recover_t", kind="server", message="旧故障")

    class MockMessage:
        content = '{"双休": true}'

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]

    mock_client = type("C", (), {})()
    mock_client.chat = type("Chat", (), {})()
    mock_client.chat.completions = type("Completions", (), {})()

    async def mock_create(*_args, **_kwargs):
        return MockResponse()

    mock_client.chat.completions.create = mock_create
    monkeypatch.setattr(step1_rule_filter, "get_cleaner_client", lambda: mock_client)

    passed = await step1_rule_filter._async_run_ai_scout_only(sse_task_id="pipeline_recover_t")
    assert len(passed) == 2
    assert _count_status(scout_db, "待推送至飞书") == 2
    # 任一次真实成功即清除阻塞
    assert pipeline_blocked.get_blocked_state("pipeline_recover_t") is None
    pipeline_blocked.reset_all()


async def test_pump_announces_blocked_stage_once(scout_db, monkeypatch):
    pipeline_blocked.reset_all()
    channel = pb.create_pipeline_queue("pipeline_pump_block_t")

    def raise_503():
        raise FakeUpstreamError()

    monkeypatch.setattr(step1_rule_filter, "get_cleaner_client", raise_503)

    scraping_done = asyncio.Event()
    wake = asyncio.Event()
    task = asyncio.create_task(
        run_cleaning_pump("pipeline_pump_block_t", str(scout_db), 0, scraping_done, wake))
    try:
        assert await _wait_until(
            lambda: '"status": "blocked"' in "".join(channel._history))
        history = "".join(channel._history)
        # 人话摘要 + 只广播一次（不随批次重复刷屏）
        assert "AI 排雷持续失败" in history
        blocked_stage_count = history.count('"status": "blocked"')
        await asyncio.sleep(0.2)
        assert history.count('"status": "blocked"') == blocked_stage_count
    finally:
        scraping_done.set()
        wake.set()
    await asyncio.wait_for(task, timeout=10)
    pipeline_blocked.reset_all()


# ── 「继续任务」端点与后台体 ────────────────────────────────────────────────

def test_llm_health_endpoint_ok(client, monkeypatch):
    from app.automation import llm_health as lh

    def fake_probe():
        return {"ok": True, "latency_ms": 12, "model": "wb-model",
                "error_kind": None, "message": "LLM 网关可用", "hint": None,
                "checked_at": "2026-10-31 12:00:00"}

    monkeypatch.setattr(lh, "probe_llm", fake_probe)
    res = client.get("/api/automation/llm-health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["data"]["ok"] is True
    assert data["data"]["model"] == "wb-model"


def test_llm_health_endpoint_failure_keeps_kind(client, monkeypatch):
    from app.automation import llm_health as lh

    def fake_probe():
        return {"ok": False, "latency_ms": 30, "model": "wb-model",
                "error_kind": "server", "message": "模型服务端异常（503）",
                "hint": "503 no_healthy_account", "checked_at": "2026-10-31 12:00:00"}

    monkeypatch.setattr(lh, "probe_llm", fake_probe)
    res = client.get("/api/automation/llm-health")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["ok"] is False
    assert data["error_kind"] == "server"


def test_resume_endpoint_rejects_when_pipeline_running(client):
    pipeline_blocked.reset_all()
    pb.set_current_pipeline("pipeline_busy_t", True)
    try:
        res = client.post("/api/automation/resume-cleaning", json={"task_id": "pipeline_busy_t"})
        assert res.status_code == 409
    finally:
        pb.set_current_pipeline(None, False)


def test_resume_endpoint_rejects_without_task(client):
    """无阻塞登记一律 409 拒绝（外审 R2-P1-2：旧逻辑回退 cur.get("task_id") 放行，
    worker 端 min_rowid 退化为 0 → 全库历史行拉进 AI 排雷并自动投递）"""
    pipeline_blocked.reset_all()
    pb.set_current_pipeline(None, False)
    res = client.post("/api/automation/resume-cleaning", json={"task_id": ""})
    assert res.status_code == 409


async def test_resume_worker_reruns_pending_rows_scoped_by_min_rowid(scout_db, monkeypatch):
    """min_rowid 圈定重洗范围：本轮遗留行重洗，范围外行不动；跑完 outcome=resumed 收口。"""
    pipeline_blocked.reset_all()
    task_id = "pipeline_resume_scope_t"
    _mark_all_pending(scout_db)
    channel = pb.create_pipeline_queue(task_id)
    # 模拟阻塞登记：本轮从 rowid 1 之后开始（rowid 1 是范围外的历史遗留）
    pipeline_blocked.report_llm_failure(task_id, kind="server", message="x")
    pipeline_blocked.attach_scope(task_id, min_rowid=1)

    class MockMessage:
        content = '{"双休": true}'

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]

    mock_client = type("C", (), {})()
    mock_client.chat = type("Chat", (), {})()
    mock_client.chat.completions = type("Completions", (), {})()

    async def mock_create(*_args, **_kwargs):
        return MockResponse()

    mock_client.chat.completions.create = mock_create
    monkeypatch.setattr(step1_rule_filter, "get_cleaner_client", lambda: mock_client)

    async def fake_sync(*_args, **_kwargs):
        return ["rec_1"]

    from job_processor import step2_sync_feishu
    monkeypatch.setattr(step2_sync_feishu, "sync_sqlite_to_feishu_async", fake_sync)

    from app.automation.routes import control_router
    try:
        await control_router._run_resume_cleaning_worker(task_id)
        history = "".join(channel._history)
        assert '"outcome": "resumed"' in history
        # 只有 rowid=2（本轮回合内）被重洗，rowid=1 的历史遗留保持原状
        conn = sqlite3.connect(scout_db)
        rows = dict(conn.execute(
            "SELECT rowid, process_status FROM raw_jobs ORDER BY rowid").fetchall())
        conn.close()
        assert rows[1] == "待AI初筛"
        assert rows[2] == "待推送至飞书"
        # 链路继续向下走：飞书推送阶段被点亮并收口
        assert '"stage": "feishu_sync", "status": "running"' in history
    finally:
        pipeline_blocked.reset_all()
        abort_mod.end_pipeline()


async def test_resume_worker_reports_blocked_again_when_llm_still_down(scout_db, monkeypatch):
    """LLM 未恢复时继续任务不得伪装成功：按同一规则 outcome=blocked 收口。"""
    pipeline_blocked.reset_all()
    task_id = "pipeline_resume_still_t"
    _mark_all_pending(scout_db)
    channel = pb.create_pipeline_queue(task_id)
    pipeline_blocked.report_llm_failure(task_id, kind="server", message="x")
    pipeline_blocked.attach_scope(task_id, min_rowid=1)

    def raise_503():
        raise FakeUpstreamError()

    monkeypatch.setattr(step1_rule_filter, "get_cleaner_client", raise_503)

    from app.automation.routes import control_router
    try:
        await control_router._run_resume_cleaning_worker(task_id)
        history = "".join(channel._history)
        assert '"outcome": "blocked"' in history
        assert _count_status(scout_db, "待AI初筛") == 2
    finally:
        pipeline_blocked.reset_all()
        abort_mod.end_pipeline()
