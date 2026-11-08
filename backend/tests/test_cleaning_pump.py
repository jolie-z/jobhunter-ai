"""抓取期流式清洗泵回归（2026-10-30 抓取→清洗流式改造）。

锁定：
- 抓取尚未结束（scraping_done 未置位）时，泵就能把已入库岗位清洗并推进到待推送；
- 新行入库 + 唤醒信号能触发增量清洗；
- 终止信号让泵立即退出，不吞掉岗位状态；
- 抓取结束且无待清洗行时泵立即收口。
"""
import asyncio
import sqlite3
import time

import pytest

from app.automation import abort as abort_mod
from app.automation import pipeline_broadcast as pb
from app.automation.cleaning_pump import run_cleaning_pump
from job_processor import step1_rule_filter


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
    conn.execute(
        "INSERT INTO job_strategies (is_active, min_salary_k, max_salary_k, experience_years_max) "
        "VALUES (1, 10, 25, 99)"
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


def _insert_row(path, i):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, salary, city, "
        "experience_req, education_req, jd_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (f"https://jobs/late-{i}", "猎聘", f"AI产品经理{i}", f"后到公司{i}",
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


async def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.fixture
def pump_db(tmp_path, monkeypatch):
    db = tmp_path / "pump.db"
    _make_db(db)
    monkeypatch.setattr(step1_rule_filter, "DB_PATH", str(db))
    step1_rule_filter.set_stop_flag(False)

    async def fake_eval(self, job_title, jd_text, company_name="", sse_task_id=None):
        return {"status": "PASS", "reject_reason": None}

    monkeypatch.setattr(step1_rule_filter.AIScoutEngine, "evaluate_job", fake_eval)
    return db


async def test_pump_drains_while_scraping_still_running(pump_db, monkeypatch):
    events = []

    async def fake_emit_job(task_id, job_id, job_name, node, status="running", **kwargs):
        events.append({"job_id": job_id, "node": node, "status": status})

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)

    scraping_done = asyncio.Event()
    wake = asyncio.Event()
    task = asyncio.create_task(run_cleaning_pump(
        "pipeline_pump_test", str(pump_db), 0, scraping_done, wake))
    try:
        # 抓取还没结束，泵已经把这批岗位洗完并推进到待推送
        assert await _wait_until(lambda: _count_status(pump_db, "待推送至飞书") == 2)
        assert not scraping_done.is_set()
        assert any(e["node"] == "clean_ai_node" for e in events)
    finally:
        scraping_done.set()
        wake.set()

    result = await asyncio.wait_for(task, timeout=5)
    assert result["passes"] >= 1
    assert result["cleaned"] >= 2
    assert result["progress"]["total"] == 2
    assert result["progress"]["ai_passed"] == 2


async def test_pump_wakes_on_new_rows(pump_db, monkeypatch):
    async def fake_emit_job(*args, **kwargs):
        return None

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)
    # 清空初始行，模拟「抓取刚开始还没有新行」
    conn = sqlite3.connect(pump_db)
    conn.execute("DELETE FROM raw_jobs")
    conn.commit()
    conn.close()

    scraping_done = asyncio.Event()
    wake = asyncio.Event()
    task = asyncio.create_task(run_cleaning_pump(
        "pipeline_pump_test", str(pump_db), 0, scraping_done, wake))
    try:
        await asyncio.sleep(0.1)
        assert _count_status(pump_db, "待推送至飞书") == 0

        _insert_row(pump_db, 1)
        wake.set()
        assert await _wait_until(lambda: _count_status(pump_db, "待推送至飞书") == 1)
    finally:
        scraping_done.set()
        wake.set()

    result = await asyncio.wait_for(task, timeout=5)
    assert result["cleaned"] >= 1


async def test_pump_exits_immediately_on_abort(pump_db, monkeypatch):
    monkeypatch.setattr(abort_mod, "is_aborted", lambda: True)

    scraping_done = asyncio.Event()
    wake = asyncio.Event()
    result = await asyncio.wait_for(
        run_cleaning_pump("pipeline_pump_test", str(pump_db), 0, scraping_done, wake),
        timeout=2)
    assert result["passes"] == 0
    assert _count_status(pump_db, "已存入数据") == 2


async def test_pump_exits_when_done_and_no_pending(pump_db, monkeypatch):
    conn = sqlite3.connect(pump_db)
    conn.execute("DELETE FROM raw_jobs")
    conn.commit()
    conn.close()

    scraping_done = asyncio.Event()
    scraping_done.set()
    wake = asyncio.Event()
    result = await asyncio.wait_for(
        run_cleaning_pump("pipeline_pump_test", str(pump_db), 0, scraping_done, wake),
        timeout=2)
    assert result["passes"] == 0
    assert result["cleaned"] == 0


async def test_pump_stops_after_consecutive_failures(pump_db, monkeypatch):
    """连续 3 批失败后退出，交回抓取结束后的兜底清洗（不死循环）。"""
    from app.automation import cleaning_pump as cp
    monkeypatch.setattr(cp, "RETRY_BACKOFF_BASE_SECONDS", 0.01)

    calls = {"n": 0}

    async def failing_drain():
        calls["n"] += 1
        raise RuntimeError("LLM 网关 502")

    scraping_done = asyncio.Event()
    wake = asyncio.Event()
    result = await asyncio.wait_for(
        run_cleaning_pump(
            "pipeline_pump_test", str(pump_db), 0, scraping_done, wake,
            drain_once=failing_drain, count_pending=lambda: 2),
        timeout=5)
    assert calls["n"] == cp.MAX_CONSECUTIVE_FAILURES
    assert result["passes"] == 0


async def test_pump_done_recheck_catches_late_rows(pump_db):
    """scraping_done 置位后的二次确认：第一次看似无行、二次确认发现迟到行，仍会清洗。"""
    sequence = iter([0, 2, 2, 0])
    drained = []

    async def drain_once():
        drained.append(1)

    scraping_done = asyncio.Event()
    scraping_done.set()
    wake = asyncio.Event()
    result = await asyncio.wait_for(
        run_cleaning_pump(
            "pipeline_pump_test", str(pump_db), 0, scraping_done, wake,
            drain_once=drain_once, count_pending=lambda: next(sequence, 0)),
        timeout=5)
    assert len(drained) == 1
    assert result["passes"] == 1
    assert result["cleaned"] == 2


def test_count_pending_rows_returns_unknown_on_db_error():
    """查库失败返回 -1（未知），绝不返回 0 让兜底清洗被静默跳过。"""
    from app.automation.cleaning_pump import count_pending_rows
    assert count_pending_rows("/nonexistent-dir/no-such.db", 0) == -1


def test_collect_progress_excludes_pending_and_preserved(pump_db):
    """累计进度：未处理行与 PRESERVE 残留不得计入完成数。"""
    from app.automation.cleaning_pump import collect_progress

    conn = sqlite3.connect(pump_db)
    conn.execute("DELETE FROM raw_jobs")
    rows = [
        ("https://jobs/p1", "已存入数据"),      # 未处理
        ("https://jobs/p2", "清洗中"),          # 未处理（僵尸）
        ("https://jobs/r1", "待AI初筛"),        # PRESERVE 残留
        ("https://jobs/ok", "待推送至飞书"),    # Tier1+Tier2 通过
        ("https://jobs/ai-rej", "ai清洗淘汰"),  # Tier2 淘汰
        ("https://jobs/hard-rej", "清洗淘汰"),  # Tier1 淘汰
    ]
    for link, status in rows:
        conn.execute(
            "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, process_status) "
            "VALUES (?, '智联招聘', '岗位', '公司', ?)",
            (link, status),
        )
    conn.commit()
    conn.close()

    progress = collect_progress(str(pump_db), 0)
    assert progress["total"] == 6
    assert progress["pending"] == 2
    assert progress["hard_done"] == 4
    assert progress["hard_rejected"] == 1
    assert progress["ai_total"] == 3
    assert progress["ai_preserved"] == 1
    assert progress["ai_done"] == 2
    assert progress["ai_passed"] == 1
    assert progress["ai_rejected"] == 1


async def test_preserved_job_not_recleaned_and_progress_accurate(pump_db, monkeypatch):
    """PRESERVE 岗位留在待AI初筛：不会被下一批重复清洗，进度不计完成。"""
    eval_calls = {"n": 0}

    async def fake_eval(self, job_title, jd_text, company_name="", sse_task_id=None):
        eval_calls["n"] += 1
        return {"status": "PRESERVE", "reject_reason": None}

    monkeypatch.setattr(step1_rule_filter.AIScoutEngine, "evaluate_job", fake_eval)

    async def fake_emit_job(*args, **kwargs):
        return None

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)

    scraping_done = asyncio.Event()
    wake = asyncio.Event()
    task = asyncio.create_task(run_cleaning_pump(
        "pipeline_pump_test", str(pump_db), 0, scraping_done, wake))
    try:
        # 两个岗位都评估过一次后进入保留态
        assert await _wait_until(lambda: eval_calls["n"] == 2)
        assert _count_status(pump_db, "待AI初筛") == 2
    finally:
        scraping_done.set()
        wake.set()

    result = await asyncio.wait_for(task, timeout=5)
    # 不得重复清洗（每个岗位只评估一次）
    assert eval_calls["n"] == 2
    assert result["progress"]["ai_preserved"] == 2
    assert result["progress"]["ai_done"] == 0
    assert result["progress"]["ai_total"] == 2

