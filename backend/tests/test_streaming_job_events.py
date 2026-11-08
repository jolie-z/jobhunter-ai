"""清洗 / 飞书推送逐岗位流式事件回归（2026-10-30 流式改造）。

背景：清洗段与飞书推送段原本整段跑完才由编排器批量补发卡片，看板要等全部岗位
处理完才一起翻转。改造后 step1/step2 逐岗位广播 job 事件，本用例锁定：
- Tier1 淘汰/通过、Tier2 淘汰/通过、飞书推送开始/完成都逐岗位下发；
- 淘汰事件下发时数据库状态已经落盘（先落库后发事件，12 秒快照不会倒回旧态）。
"""
import json
import sqlite3

import pytest

from app.automation import pipeline_broadcast as pb
from job_processor import step1_rule_filter, step2_sync_feishu


def _make_clean_db(path):
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
            reject_reason TEXT,
            is_synced INTEGER DEFAULT 0,
            feishu_record_id TEXT DEFAULT ''
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
    rows = [
        # rowid=1：Tier1 薪资过低 → 硬规则淘汰
        ("https://jobs/1", "智联招聘", "低薪岗", "测试公司A", "5-8K", "广州", "岗位职责描述内容"),
        # rowid=2：Tier2 放行
        ("https://jobs/2", "智联招聘", "数据产品经理", "测试公司B", "15-25K", "广州", "岗位职责描述内容"),
        # rowid=3：Tier2 淘汰
        ("https://jobs/3", "智联招聘", "产品专员（淘汰）", "测试公司C", "15-25K", "广州", "岗位职责描述内容"),
    ]
    for link, plat, title, comp, salary, city, jd in rows:
        conn.execute(
            "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, salary, city, "
            "experience_req, education_req, jd_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (link, plat, title, comp, salary, city, "1-3年", "本科", jd),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def clean_db(tmp_path, monkeypatch):
    db = tmp_path / "clean_stream.db"
    _make_clean_db(db)
    monkeypatch.setattr(step1_rule_filter, "DB_PATH", str(db))
    step1_rule_filter.set_stop_flag(False)
    return db


async def test_clean_pipeline_emits_per_job_events(clean_db, monkeypatch):
    events = []

    def _db_status(job_id: str) -> str:
        conn = sqlite3.connect(clean_db)
        row = conn.execute(
            "SELECT process_status FROM raw_jobs WHERE 'raw_' || rowid = ?", (job_id,)
        ).fetchone()
        conn.close()
        return row[0] if row else ""

    async def fake_emit_job(task_id, job_id, job_name, node, status="running", **kwargs):
        events.append({
            "task_id": task_id, "job_id": job_id, "job_name": job_name,
            "node": node, "status": status, "db_status": _db_status(job_id), **kwargs,
        })

    async def fake_eval(self, job_title, jd_text, company_name="", sse_task_id=None):
        if "淘汰" in job_title:
            return {"status": "REJECT", "reject_reason": "触发 AI 侦察兵排雷: 触发绝不条件 [游戏]"}
        return {"status": "PASS", "reject_reason": None}

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)
    monkeypatch.setattr(step1_rule_filter.AIScoutEngine, "evaluate_job", fake_eval)

    streamed: list[str] = []

    async def fake_push(job):
        streamed.append(job.get("job_link"))

    passed = await step1_rule_filter._async_run_pipeline(
        sse_task_id="pipeline_stream_test", emit_job_events=True, on_job_passed=fake_push)
    # rowid=1 低薪岗（5-8K < 策略下限 10K）在 Tier1 被硬规则淘汰；
    # rowid=2 由 fake_eval 放行；rowid=3 被 Tier2 淘汰 → 仅 1 条进入待推送
    assert sorted(passed) == ["https://jobs/2"]
    # 流式推送回调：只对通过 Tier2 的岗位触发（过一个推一条）
    assert streamed == ["https://jobs/2"]

    by_job: dict[str, list[dict]] = {}
    for e in events:
        by_job.setdefault(e["job_id"], []).append(e)

    # Tier1 硬规则淘汰：只有一条 rejected 事件，且事件下发时 DB 已落「清洗淘汰」
    tier1_events = by_job["raw_1"]
    assert [e["node"] for e in tier1_events] == ["clean_rejected"]
    assert tier1_events[0]["status"] == "rejected"
    assert tier1_events[0]["reject_type"] == "rule"
    assert tier1_events[0]["reject_reason"] == "薪资区间不符"
    assert tier1_events[0]["db_status"] == "清洗淘汰"

    # Tier1 通过 → Tier2 评估中：两条通过岗位都先收到这两种事件
    for job_id in ("raw_2", "raw_3"):
        seq = by_job[job_id]
        assert seq[0]["node"] == "clean_rule_node"
        assert seq[0]["sub_status"] == "clean_rule_passed"
        assert seq[1]["node"] == "clean_ai_node"
        assert seq[1]["status"] == "running"

    # Tier2 放行：末条事件是 clean_ai_passed，且下发时 DB 已落「待推送至飞书」
    passed_events = by_job["raw_2"]
    assert passed_events[-1]["sub_status"] == "clean_ai_passed"
    assert passed_events[-1]["db_status"] == "待推送至飞书"

    # Tier2 淘汰：末条事件是 rejected；事件下发时 DB 已落「ai清洗淘汰」
    reject_events = by_job["raw_3"]
    assert reject_events[-1]["node"] == "clean_rejected"
    assert reject_events[-1]["status"] == "rejected"
    assert reject_events[-1]["reject_type"] == "ai"
    assert reject_events[-1]["db_status"] == "ai清洗淘汰"

    # 所有事件都带任务号，前端才能落到同一条链路的看板
    assert all(e["task_id"] == "pipeline_stream_test" for e in events)


async def test_tier1_job_events_emit_rejected_and_passed(clean_db, monkeypatch):
    """Tier1 逐岗位事件：淘汰卡进回收站，通过卡显示排队 AI 排雷。"""
    events = []

    async def fake_emit_job(task_id, job_id, job_name, node, status="running", **kwargs):
        events.append({"job_id": job_id, "node": node, "status": status, **kwargs})

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)

    conn = sqlite3.connect(clean_db)
    conn.execute("UPDATE raw_jobs SET process_status = '清洗淘汰', reject_reason = '薪资区间不符' WHERE job_link = 'https://jobs/1'")
    conn.execute("UPDATE raw_jobs SET process_status = 'ai清洗淘汰', reject_reason = '触发 AI 侦察兵排雷' WHERE job_link = 'https://jobs/3'")
    conn.execute("UPDATE raw_jobs SET process_status = '待AI初筛' WHERE job_link = 'https://jobs/2'")
    conn.commit()
    cursor = conn.cursor()
    try:
        await step1_rule_filter._emit_tier1_job_events(
            "pipeline_stream_test", cursor, ["https://jobs/1", "https://jobs/2", "https://jobs/3"])
    finally:
        conn.close()

    by_job = {e["job_id"]: e for e in events}
    assert by_job["raw_1"]["node"] == "clean_rejected"
    assert by_job["raw_1"]["status"] == "rejected"
    assert by_job["raw_1"]["reject_type"] == "rule"
    assert by_job["raw_1"]["reject_reason"] == "薪资区间不符"
    assert by_job["raw_2"]["node"] == "clean_rule_node"
    assert by_job["raw_2"]["sub_status"] == "clean_rule_passed"
    assert by_job["raw_3"]["reject_type"] == "ai"


async def test_clean_pipeline_without_flag_keeps_legacy_protocol(clean_db, monkeypatch):
    """独立清洗任务不传 emit_job_events：不得多下发任何 job 事件。"""
    events = []

    async def fake_emit_job(*args, **kwargs):
        events.append(kwargs)

    async def fake_eval(self, job_title, jd_text, company_name="", sse_task_id=None):
        return {"status": "PASS", "reject_reason": None}

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)
    monkeypatch.setattr(step1_rule_filter.AIScoutEngine, "evaluate_job", fake_eval)

    await step1_rule_filter._async_run_pipeline(sse_task_id="clean_standalone_test")
    assert events == []


async def test_streamed_push_survives_gather_writeback(clean_db, monkeypatch):
    """P0 回归：流式推送已把行改成「已同步 + is_synced=1」后，
    gather 之后的批量回写不得把它打回「待推送至飞书」（否则批量兜底永久跳过、行永久卡死）。"""
    async def fake_emit_job(*args, **kwargs):
        pass

    async def fake_eval(self, job_title, jd_text, company_name="", sse_task_id=None):
        return {"status": "PASS", "reject_reason": None}

    async def fake_push(job):
        # 模拟 sync_one_link 成功后的落库：已同步 + is_synced=1
        conn = sqlite3.connect(clean_db)
        conn.execute(
            "UPDATE raw_jobs SET process_status='已同步', is_synced=1, feishu_record_id='rec_stream' "
            "WHERE job_link=?", (job["job_link"],))
        conn.commit()
        conn.close()

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)
    monkeypatch.setattr(step1_rule_filter.AIScoutEngine, "evaluate_job", fake_eval)

    await step1_rule_filter._async_run_pipeline(
        sse_task_id="pipeline_stream_test", emit_job_events=True, on_job_passed=fake_push)

    conn = sqlite3.connect(clean_db)
    rows = conn.execute(
        "SELECT process_status, is_synced FROM raw_jobs WHERE job_link IN ('https://jobs/2','https://jobs/3')"
    ).fetchall()
    conn.close()
    assert rows, "流式通过的岗位应存在"
    for status, is_synced in rows:
        assert status == "已同步", f"流式推送成功后状态被回写覆盖为 {status}"
        assert is_synced == 1


def _make_sync_db(path):
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
            process_status TEXT DEFAULT '待推送至飞书',
            reject_reason TEXT,
            is_synced INTEGER DEFAULT 0,
            feishu_record_id TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, salary, city, jd_text) "
        "VALUES ('https://jobs/1', '智联招聘', 'AIGC产品经理', '广信通信', '15-25K', '广州', 'jd')"
    )
    conn.commit()
    conn.close()


def test_feishu_sync_emits_per_job_events(tmp_path, monkeypatch):
    db = tmp_path / "sync_stream.db"
    _make_sync_db(db)
    step1_rule_filter.set_stop_flag(False)

    messages = []
    monkeypatch.setattr(step2_sync_feishu, "_push_sse_threadsafe", lambda tid, msg: messages.append((tid, msg)))
    monkeypatch.setattr(step2_sync_feishu, "get_tenant_access_token", lambda: "token")
    monkeypatch.setattr(step2_sync_feishu, "check_job_exists", lambda *a, **k: False)
    monkeypatch.setattr(step2_sync_feishu, "push_single_record_to_feishu", lambda token, fields: "rec_test_1")

    created = step2_sync_feishu.sync_sqlite_to_feishu(
        str(db), table_name="raw_jobs", sse_task_id="pipeline_stream_test")
    assert created == ["rec_test_1"]

    job_events = []
    for tid, msg in messages:
        assert tid == "pipeline_stream_test"
        if not msg.startswith("data: "):
            continue
        payload = json.loads(msg[len("data: "):].strip())
        if payload.get("type") == "job":
            job_events.append(payload)

    assert [e["status"] for e in job_events] == ["running", "done"]
    assert job_events[0]["node"] == "feishu_sync"
    assert job_events[0]["job_id"] == "raw_1"
    assert job_events[0]["last_action_desc"] == "正在推送飞书多维表格"
    assert job_events[1]["sub_status"] == "feishu_synced"
    assert job_events[1]["last_action_desc"] == "已推送飞书，等待评估"


def test_sync_one_link_streams_single_job(tmp_path, monkeypatch):
    """流式单岗推送：通过清洗即刻推一条，且只动目标岗位。"""
    db = tmp_path / "sync_one.db"
    _make_sync_db(db)
    step1_rule_filter.set_stop_flag(False)

    messages = []
    monkeypatch.setattr(step2_sync_feishu, "_push_sse_threadsafe", lambda tid, msg: messages.append((tid, msg)))
    monkeypatch.setattr(step2_sync_feishu, "get_tenant_access_token", lambda: "token")
    monkeypatch.setattr(step2_sync_feishu, "check_job_exists", lambda *a, **k: False)
    monkeypatch.setattr(step2_sync_feishu, "push_single_record_to_feishu", lambda token, fields: "rec_stream_1")

    created = step2_sync_feishu.sync_one_link(
        str(db), "raw_jobs", "pipeline_stream_test", "https://jobs/1")
    assert created == ["rec_stream_1"]

    conn = sqlite3.connect(db)
    status, rec_id = conn.execute(
        "SELECT process_status, feishu_record_id FROM raw_jobs WHERE job_link = 'https://jobs/1'"
    ).fetchone()
    conn.close()
    assert status == "已同步"
    assert rec_id == "rec_stream_1"

    job_events = []
    for _tid, msg in messages:
        if not msg.startswith("data: "):
            continue
        payload = json.loads(msg[len("data: "):].strip())
        if payload.get("type") == "job":
            job_events.append(payload)
    assert [e["status"] for e in job_events] == ["running", "done"]
    assert job_events[0]["job_id"] == "raw_1"


async def test_streaming_push_result_not_reverted_by_final_batch(clean_db, monkeypatch):
    """P0 回归：流式推送写成「已同步」后，Tier2 收尾批量写不得把它倒回「待推送至飞书」。"""
    async def fake_eval(self, job_title, jd_text, company_name="", sse_task_id=None):
        if "淘汰" in job_title:
            return {"status": "REJECT", "reject_reason": "触发 AI 侦察兵排雷: 触发绝不条件 [游戏]"}
        return {"status": "PASS", "reject_reason": None}

    monkeypatch.setattr(step1_rule_filter.AIScoutEngine, "evaluate_job", fake_eval)

    async def fake_push(job):
        # 模拟 step2 单岗推送成功：独立连接写入「已同步 + is_synced」
        conn = sqlite3.connect(clean_db)
        conn.execute(
            "UPDATE raw_jobs SET process_status = '已同步', is_synced = 1 WHERE job_link = ?",
            (job.get("job_link"),),
        )
        conn.commit()
        conn.close()

    reports = []

    async def fake_event(task_id, event_data):
        if event_data.get("type") == "cleaning_report":
            reports.append(event_data.get("data"))

    monkeypatch.setattr(step1_rule_filter, "push_sse_event", fake_event)

    await step1_rule_filter._async_run_pipeline(
        sse_task_id="pipeline_stream_test", emit_job_events=True, on_job_passed=fake_push)

    conn = sqlite3.connect(clean_db)
    statuses = dict(conn.execute("SELECT job_link, process_status FROM raw_jobs").fetchall())
    conn.close()
    # jobs/1 低薪岗在 Tier1 被硬规则淘汰；jobs/2 流式推送写成已同步，
    # 收尾写不得把它倒回「待推送至飞书」；jobs/3 被 Tier2 淘汰。
    assert statuses["https://jobs/1"] == "清洗淘汰"
    assert statuses["https://jobs/2"] == "已同步"
    assert statuses["https://jobs/3"] == "ai清洗淘汰"
    # 清洗报告必须把「已同步」计入通过，否则流式链路会报 0 通过
    assert reports and reports[-1]["passed"] == 1
    assert reports[-1]["hard_rejected"] == 1 and reports[-1]["ai_rejected"] == 1


async def test_stop_flag_skips_tier2_events_and_push(clean_db, monkeypatch):
    """终止信号：Tier2 不发事件、不触发流式推送、DB 保持原状。"""
    events = []
    pushed = []

    async def fake_emit_job(task_id, job_id, job_name, node, status="running", **kwargs):
        events.append(node)

    async def fake_push(job):
        pushed.append(job.get("job_link"))

    monkeypatch.setattr(pb, "emit_job", fake_emit_job)

    conn = sqlite3.connect(clean_db)
    cursor = conn.cursor()
    cursor.execute("UPDATE raw_jobs SET process_status = '待AI初筛'")
    conn.commit()
    step1_rule_filter.set_stop_flag(True)
    try:
        await step1_rule_filter._run_tier2_ai_scout(
            cursor, conn, {"ai_scout_rules": []}, "pipeline_stream_test", None,
            target_links=["https://jobs/1", "https://jobs/2", "https://jobs/3"],
            emit_job_events=True, on_job_passed=fake_push,
        )
    finally:
        step1_rule_filter.set_stop_flag(False)
        conn.close()

    assert events == []
    assert pushed == []
    conn = sqlite3.connect(clean_db)
    statuses = {r[0] for r in conn.execute("SELECT process_status FROM raw_jobs").fetchall()}
    conn.close()
    assert statuses == {"待AI初筛"}


def test_sync_one_link_failure_paths_keep_pending(tmp_path, monkeypatch):
    """单岗推送三种失败路径：返回 [] 且行保持「待推送至飞书」，交给批量段兜底。"""
    db = tmp_path / "sync_fail.db"
    _make_sync_db(db)
    step1_rule_filter.set_stop_flag(False)

    def _status():
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT process_status, is_synced FROM raw_jobs WHERE job_link = 'https://jobs/1'"
        ).fetchone()
        conn.close()
        return row

    # 1) Token 获取异常
    monkeypatch.setattr(step2_sync_feishu, "get_tenant_access_token",
                        lambda: (_ for _ in ()).throw(RuntimeError("token boom")))
    assert step2_sync_feishu.sync_one_link(str(db), "raw_jobs", "t", "https://jobs/1") == []
    assert _status() == ("待推送至飞书", 0)

    # 2) 查重未知态（fail-closed）
    monkeypatch.setattr(step2_sync_feishu, "get_tenant_access_token", lambda: "token")
    monkeypatch.setattr(step2_sync_feishu, "check_job_exists", lambda *a, **k: None)
    assert step2_sync_feishu.sync_one_link(str(db), "raw_jobs", "t", "https://jobs/1") == []
    assert _status() == ("待推送至飞书", 0)

    # 3) 建档失败
    monkeypatch.setattr(step2_sync_feishu, "check_job_exists", lambda *a, **k: False)
    monkeypatch.setattr(step2_sync_feishu, "push_single_record_to_feishu", lambda token, fields: False)
    assert step2_sync_feishu.sync_one_link(str(db), "raw_jobs", "t", "https://jobs/1") == []
    assert _status() == ("待推送至飞书", 0)


def test_sync_one_link_skips_already_synced(tmp_path, monkeypatch):
    """已同步行不得被单岗推送再次捞起（防重复建档）。"""
    db = tmp_path / "sync_done.db"
    _make_sync_db(db)
    step1_rule_filter.set_stop_flag(False)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE raw_jobs SET process_status = '已同步', is_synced = 1, feishu_record_id = 'rec_done' "
        "WHERE job_link = 'https://jobs/1'"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(step2_sync_feishu, "get_tenant_access_token", lambda: "token")
    monkeypatch.setattr(step2_sync_feishu, "check_job_exists", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应查重")))
    monkeypatch.setattr(step2_sync_feishu, "push_single_record_to_feishu", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应推送")))

    assert step2_sync_feishu.sync_one_link(str(db), "raw_jobs", "t", "https://jobs/1") == []


def test_feishu_done_event_is_emitted_after_db_commit(tmp_path, monkeypatch):
    """批量同步：done 事件下发时 DB 必须已经是「已同步」（先落库后发事件）。"""
    db = tmp_path / "sync_order.db"
    _make_sync_db(db)
    step1_rule_filter.set_stop_flag(False)

    event_db_status = []

    def _capture(tid, msg):
        if not msg.startswith("data: "):
            return
        payload = json.loads(msg[len("data: "):].strip())
        if payload.get("type") == "job" and payload.get("status") == "done":
            conn = sqlite3.connect(db)
            event_db_status.append(
                conn.execute("SELECT process_status FROM raw_jobs WHERE job_link = 'https://jobs/1'").fetchone()[0])
            conn.close()

    monkeypatch.setattr(step2_sync_feishu, "_push_sse_threadsafe", _capture)
    monkeypatch.setattr(step2_sync_feishu, "get_tenant_access_token", lambda: "token")
    monkeypatch.setattr(step2_sync_feishu, "check_job_exists", lambda *a, **k: False)
    monkeypatch.setattr(step2_sync_feishu, "push_single_record_to_feishu", lambda token, fields: "rec_order_1")

    step2_sync_feishu.sync_sqlite_to_feishu(
        str(db), table_name="raw_jobs", sse_task_id="pipeline_stream_test")
    assert event_db_status == ["已同步"]
