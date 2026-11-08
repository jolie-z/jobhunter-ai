"""第一批修复（2026-11-02 审计）后端单测：TOCTOU 占坑回滚 / greeting 闸门台账 / E 级白名单 / raw 回写幂等。

2026-11-06 补：autouse _no_background_escape 堵后台任务逃逸（智联 Edge 自动拉起事故根治），
见该 fixture docstring。
"""
import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.process_status import REJECT_AI


@pytest.fixture(autouse=True)
def _no_background_escape(monkeypatch):
    """堵后台任务逃逸（2026-11-06 智联 Edge 自动拉起事故根治）。

    病灶：run_full_auto_pipeline 经 _spawn_tracked(_run_pipeline_with_watchdog(...))
    发射真链路；用例返回后 patch 上下文（含 _execute_pipeline 的 mock）先撤，
    后台任务才被事件循环调度——真 _execute_pipeline 在 mock 缺位下执行，一路
    ensure_platforms_ready 真拉起 Edge（本次事故）/ 真写生产库。

    修法：_spawn_tracked 改为直接 close 协程（永不运行），只记录 name 供断言。
    协程 close 未启动的 coroutine 不产生 "never awaited" 警告，也不执行函数体。
    """
    import app.automation.pipeline_orchestrator as orch

    spawned: list[str] = []

    def _no_spawn(coro, *, name: str | None = None):
        spawned.append(name or getattr(coro, "__name__", "unnamed"))
        coro.close()
        return None

    monkeypatch.setattr(orch, "_spawn_tracked", _no_spawn)
    yield spawned


# ---------- 修 1：TOCTOU 占坑回滚 ----------

@pytest.mark.asyncio
async def test_start_pipeline_rollback_on_scheduled_probe_failure():
    """定时链路预检失败：占坑必须被回滚（running 复位 False），异常向上传播"""
    import app.automation.pipeline_orchestrator as orch_mod

    calls: list[tuple] = []
    prev_state = {"task_id": "pipeline_prev", "running": False}
    with patch.object(orch_mod.pb, "get_current_pipeline", return_value=dict(prev_state)), \
         patch.object(orch_mod.pb, "create_pipeline_queue", side_effect=lambda tid: calls.append(("create", tid))), \
         patch.object(orch_mod.pb, "set_current_pipeline", side_effect=lambda tid, running: calls.append(("set", tid, running))), \
         patch.object(orch_mod.pb, "discard_pipeline_queue", side_effect=lambda tid: calls.append(("discard", tid))), \
         patch("app.automation.llm_health.probe_llm", side_effect=lambda: calls.append(("probe",)) or {"ok": False, "message": "账号池全灭"}), \
         patch("app.automation.abort.begin_pipeline", side_effect=lambda tid: calls.append(("begin", tid))), \
         patch("app.automation.abort.end_pipeline", side_effect=lambda: calls.append(("abort_end",))), \
         patch.object(orch_mod, "_execute_pipeline", new=AsyncMock(return_value=None)):
        with pytest.raises(RuntimeError, match="LLM 网关不可用"):
            await orch_mod.run_full_auto_pipeline(trigger_source="scheduled")

    kinds = [c[0] for c in calls]
    # 占坑(begin) 先于预检(probe)：预检窗口内 /abort 可受理不被冲掉（CR-R1-P2）
    assert kinds.index("begin") < kinds.index("probe")
    sets = [c for c in calls if c[0] == "set"]
    # 占坑置新 task_id 为 True；回滚恢复「占坑前原值」而非幽灵 task_id（CR-R1-P1）
    assert sets[0][2] is True and sets[0][1] != "pipeline_prev"
    assert sets[-1] == ("set", "pipeline_prev", False)
    assert ("discard", calls[0][1]) in calls            # 未用队列已回收
    assert ("abort_end",) in calls                       # abort 登记已释放


@pytest.mark.asyncio
async def test_start_pipeline_manual_probe_failure_still_launches(_no_background_escape):
    """手动链路预检失败只告警不拦截：占坑保留（无回滚 False），返回 task_id"""
    import app.automation.pipeline_orchestrator as orch_mod

    sets: list[bool] = []
    with patch.object(orch_mod.pb, "get_current_pipeline", return_value={"running": False, "task_id": None}), \
         patch.object(orch_mod.pb, "create_pipeline_queue"), \
         patch.object(orch_mod.pb, "set_current_pipeline", side_effect=lambda tid, running: sets.append(running)), \
         patch("app.automation.llm_health.probe_llm", return_value={"ok": False, "message": "慢"}), \
         patch("app.automation.abort.begin_pipeline"), \
         patch("app.automation.pipeline_orchestrator.get_autopilot_config", return_value={}), \
         patch.object(orch_mod, "_derive_search_from_config", return_value={"keyword": "k", "city": "c", "salary": "", "target_jobs": 5, "platforms": []}), \
         patch.object(orch_mod, "_execute_pipeline", new=AsyncMock(return_value=None)):
        task_id = await orch_mod.run_full_auto_pipeline(trigger_source="manual")

    assert task_id.startswith("pipeline_")
    assert sets == [True]  # 占坑未被回滚，running 所有权移交 _execute_pipeline
    # 逃逸哨兵（2026-11-06 事故）：链路只允许经 _spawn_tracked 发射且被本 fixture 拦截，
    # 绝不允许真 _execute_pipeline 在 mock 撤除后于后台任务里执行
    assert _no_background_escape == ["_run_pipeline_with_watchdog"]


@pytest.mark.asyncio
async def test_start_pipeline_probe_ok_launches_and_keeps_running(_no_background_escape):
    """预检通过：正常发射，running 保持 True（Opus R1-P2 断言）"""
    import app.automation.pipeline_orchestrator as orch_mod

    sets: list[bool] = []
    with patch.object(orch_mod.pb, "get_current_pipeline", return_value={"running": False, "task_id": None}), \
         patch.object(orch_mod.pb, "create_pipeline_queue"), \
         patch.object(orch_mod.pb, "set_current_pipeline", side_effect=lambda tid, running: sets.append(running)), \
         patch("app.automation.llm_health.probe_llm", return_value={"ok": True}), \
         patch("app.automation.abort.begin_pipeline"), \
         patch("app.automation.pipeline_orchestrator.get_autopilot_config", return_value={}), \
         patch.object(orch_mod, "_derive_search_from_config", return_value={"keyword": "k", "city": "c", "salary": "", "target_jobs": 5, "platforms": []}), \
         patch.object(orch_mod, "_execute_pipeline", new=AsyncMock(return_value=None)):
        task_id = await orch_mod.run_full_auto_pipeline(trigger_source="manual")

    assert sets == [True]
    assert _no_background_escape == ["_run_pipeline_with_watchdog"]


# ---------- 修 2：greeting 闸门与失败台账 ----------

@pytest.mark.asyncio
async def test_wave3_invalid_greeting_records_failure_ledger():
    """打招呼语为 ❌ 错误文本：与简历闸门同等强度判失败，且登记当日台账（step=STEP_RESUME_GREETING）"""
    from app.tasks import wave_pipeline as wp

    job_ids = ["boss-greet1"]
    queue = asyncio.Queue()
    prefetched = {
        "greet1": {
            "fields": {
                "公司名称": "招呼语故障公司", "岗位名称": "AI产品经理",
                "岗位详情": "详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字",
                "薪资": "20K", "城市": "广州", "经验要求": "3年", "学历要求": "本科",
            }
        }
    }
    mock_res = {
        "success": True, "ai_score": 90, "grade": "A",
        "update_data": {"综合评级 (A-F)": "A", "初评总分": 90}, "usage": {},
    }

    ledger_calls: list[dict] = []

    def fake_ledger(job_id, error="", step="", company="", job_name="", platform="", job_url="", grade=""):
        ledger_calls.append({"job_id": job_id, "step": step, "error": error})

    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", return_value=mock_res), \
         patch("app.tasks.wave_pipeline.deep_evaluate_resume", return_value=({"dream_picture": "画像"}, {})), \
         patch("app.tasks.wave_pipeline.process_resume_rewrite", MagicMock(return_value=("# 正常简历", {}))), \
         patch("app.tasks.wave_pipeline.process_greeting_generation", MagicMock(return_value=("❌ AI 服务未配置 (api_key)", {}))), \
         patch("app.tasks.wave_pipeline.record_delivery_failure", side_effect=fake_ledger), \
         patch("app.tasks.wave_pipeline.convert_and_stitch_resume", return_value="{}") as mock_stitch, \
         patch("app.tasks.wave_pipeline.update_feishu_record", return_value=True) as mock_write:

        success, failed, _ = await wp.run_wave_evaluation_pipeline(
            job_ids=job_ids, task_id="test-greet-gate", resume_text="母本", preferences_text="偏好",
            queue=queue, prefetched=prefetched,
        )

    assert success == 0
    assert failed == 1
    assert len(ledger_calls) == 1
    assert ledger_calls[0]["step"] == wp.STEP_RESUME_GREETING
    assert "打招呼语: ❌" in ledger_calls[0]["error"]
    # 错误文本绝不写回飞书
    mock_stitch.assert_not_called()
    for call in mock_write.call_args_list:
        fields = call.args[1] if call.args else {}
        assert "打招呼语" not in fields


# ---------- 修 3（方向反转）：五档契约 —— E 为已退役幽灵档 ----------

@pytest.mark.asyncio
async def test_delivery_config_keeps_five_grade_contract():
    """五档契约（commit 29aca7f6，A/B/C/D/F）：后端白名单剔除 E 与非法值是设计内行为；
    真正的修复在前端下架 E 选项/默认值（本测试守护后端契约不被再度放宽）"""
    from app.pipeline.routes.delivery_config_router import DeliveryConfigBody, save_delivery_config_endpoint

    captured: dict = {}

    def fake_update(**kwargs):
        captured.update(kwargs)
        return True

    with patch("app.automation.db.update_autopilot_config", side_effect=fake_update), \
         patch("app.automation.scheduler.get_autopilot_config", return_value={}), \
         patch("app.services.feishu_service.get_delivered_jobs_from_feishu", return_value=[]):
        body = DeliveryConfigBody(auto_deliver_grades=["C", "E", "X"])
        resp = await save_delivery_config_endpoint(body)

    assert resp["code"] == 0
    assert captured["auto_deliver_grades"] == ["C"]  # E 与 X 均按契约剔除


# ---------- 修 6：raw 回写服务幂等 ----------

def _make_tmp_db(tmp_path, rows: list[tuple]):
    db = tmp_path / "raw_test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE raw_jobs (job_link TEXT, process_status TEXT, reject_reason TEXT)")
    conn.executemany("INSERT INTO raw_jobs VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db


def test_sync_eval_reject_to_raw_updates_synced_row(tmp_path, monkeypatch):
    from app.automation.services import reject_sync_service as svc

    db = _make_tmp_db(tmp_path, [("https://example.com/job1", "已同步", "")])
    monkeypatch.setattr(svc, "job_hunter_db_path", lambda default: db)

    # 服务返回实际回写行数（rowcount），非布尔
    assert svc.sync_eval_reject_to_raw("https://example.com/job1", "初评F级淘汰(41分)") == 1
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT process_status, reject_reason FROM raw_jobs WHERE job_link='https://example.com/job1'").fetchone()
    conn.close()
    assert row[0] == REJECT_AI
    assert "F级" in row[1]


def test_sync_eval_reject_to_raw_idempotent_for_already_rejected(tmp_path, monkeypatch):
    from app.automation.services import reject_sync_service as svc

    db = _make_tmp_db(tmp_path, [("https://example.com/job2", REJECT_AI, "旧结论")])
    monkeypatch.setattr(svc, "job_hunter_db_path", lambda default: db)

    assert svc.sync_eval_reject_to_raw("https://example.com/job2", "再次淘汰") == 0


def test_sync_eval_reject_to_raw_missing_row_or_empty_link(tmp_path, monkeypatch):
    from app.automation.services import reject_sync_service as svc

    db = _make_tmp_db(tmp_path, [])
    monkeypatch.setattr(svc, "job_hunter_db_path", lambda default: db)

    assert svc.sync_eval_reject_to_raw("https://example.com/none", "x") == 0
    assert svc.sync_eval_reject_to_raw("", "x") == 0


# ---------- 修 6 运行时：wave1 F 档归档触发 raw 回写 ----------

@pytest.mark.asyncio
async def test_wave1_f_grade_archives_sync_raw_writeback():
    """初评 F 档就地归档时：按岗位链接字段提取的 URL（extract_feishu_text 对 url 型
    字段提取 link，与 raw_jobs.job_link 同款键）调用回写服务；E 档在五档契约下不产出、
    不触发（CR-R1-P2 口径统一）"""
    from app.tasks import wave_pipeline as wp

    job_ids = ["liepin-rawsync1"]
    queue = asyncio.Queue()
    prefetched = {
        "rawsync1": {
            "fields": {
                "公司名称": "回写验证公司", "岗位名称": "AI工程师",
                "岗位详情": "详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字详细岗位职责内容超过五十个字",
                "薪资": "10K", "城市": "广州", "经验要求": "3年", "学历要求": "本科",
                "岗位链接": [{"link": "https://www.liepin.com/job/999.shtml", "text": "点击查看岗位", "type": "url"}],
            }
        }
    }
    mock_res = {
        "success": True, "ai_score": 38, "grade": "F",
        "update_data": {"综合评级 (A-F)": "F", "初评总分": 38}, "usage": {},
    }
    sync_calls: list[tuple] = []
    with patch("app.tasks.wave_pipeline.research_company_serper", AsyncMock(return_value="")), \
         patch("app.tasks.wave_pipeline.evaluate_single_job", return_value=mock_res), \
         patch("app.tasks.wave_pipeline.sync_eval_reject_to_raw",
               side_effect=lambda link, reason: sync_calls.append((link, reason)) or True), \
         patch("app.tasks.wave_pipeline.update_feishu_record", return_value=True):

        success, failed, _ = await wp.run_wave_evaluation_pipeline(
            job_ids=job_ids, task_id="test-raw-sync", resume_text="母本", preferences_text="偏好",
            queue=queue, prefetched=prefetched,
        )

    assert success == 1  # F 档就地归档计入成功
    assert len(sync_calls) == 1
    assert sync_calls[0][0] == "https://www.liepin.com/job/999.shtml"
    assert "F级" in sync_calls[0][1]


# ---------- CR-R2 补强：真实状态回滚 + 预检期 abort 行为 ----------

@pytest.mark.asyncio
async def test_start_pipeline_real_state_rollback_restores_previous():
    """不 mock getter/setter 的真实状态用例：回滚后 get_current_pipeline 恢复占坑前原值"""
    import app.automation.pipeline_orchestrator as orch_mod
    import app.automation.pipeline_broadcast as pb_real
    from app.automation import abort as abort_real

    pb_real.set_current_pipeline("pipeline_prev_real", False)
    try:
        with patch("app.automation.llm_health.probe_llm", return_value={"ok": False, "message": "断网"}), \
             patch.object(orch_mod, "_execute_pipeline", new=AsyncMock(return_value=None)):
            with pytest.raises(RuntimeError, match="LLM 网关不可用"):
                await orch_mod.run_full_auto_pipeline(trigger_source="scheduled")

        cur = pb_real.get_current_pipeline()
        assert cur == {"task_id": "pipeline_prev_real", "running": False}
        assert not abort_real.is_aborted()
    finally:
        pb_real.set_current_pipeline(None, False)
        abort_real.end_pipeline()


@pytest.mark.asyncio
async def test_start_pipeline_abort_during_probe_survives_launch():
    """行为用例（CR-R2-P2）：预检窗口内受理的 /abort，begin 上移后不再被冲掉——
    预检通过发射后，终止标记仍在（链路首个安全边界即收尾）"""
    import app.automation.pipeline_orchestrator as orch_mod
    import app.automation.pipeline_broadcast as pb_real
    from app.automation import abort as abort_real

    pb_real.set_current_pipeline(None, False)
    registered: list[str] = []
    original_begin = abort_real.begin_pipeline  # patch 前保存原函数，避免递归

    def fake_begin(task_id):
        registered.append(task_id)
        original_begin(task_id)

    def probe_during_window():
        # 模拟「预检进行中，用户点终止」：对已登记的当前任务发起终止
        if registered:
            abort_real.request_abort(registered[-1])
        return {"ok": True}

    try:
        with patch.object(orch_mod.pb, "get_current_pipeline", return_value={"task_id": None, "running": False}), \
             patch.object(orch_mod.pb, "create_pipeline_queue"), \
             patch.object(orch_mod.pb, "set_current_pipeline"), \
             patch.object(orch_mod.pb, "discard_pipeline_queue"), \
             patch("app.automation.abort.begin_pipeline", side_effect=fake_begin), \
             patch("app.automation.llm_health.probe_llm", side_effect=probe_during_window), \
             patch("app.automation.pipeline_orchestrator.get_autopilot_config", return_value={}), \
             patch.object(orch_mod, "_derive_search_from_config", return_value={"keyword": "k", "city": "c", "salary": "", "target_jobs": 5, "platforms": []}), \
             patch.object(orch_mod, "_execute_pipeline", new=AsyncMock(return_value=None)):
            task_id = await orch_mod.run_full_auto_pipeline(trigger_source="manual")

        assert registered == [task_id]
        assert abort_real.is_aborted() is True  # 终止标记未被后续流程冲掉
        assert abort_real.current_pipeline_task_id() == task_id
    finally:
        abort_real.end_pipeline()
        pb_real.set_current_pipeline(None, False)


# ---------- reject_sync 白名单：投递后段绝不改写 ----------

def test_sync_eval_reject_to_raw_never_overwrites_delivery_stage(tmp_path, monkeypatch):
    from app.automation.services import reject_sync_service as svc

    db = _make_tmp_db(tmp_path, [("https://example.com/d1", "待投递", "")])
    monkeypatch.setattr(svc, "job_hunter_db_path", lambda default: db)

    assert svc.sync_eval_reject_to_raw("https://example.com/d1", "误标尝试") == 0
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT process_status FROM raw_jobs WHERE job_link='https://example.com/d1'").fetchone()[0] == "待投递"
    conn.close()


# ---------- CR-R4 补强：回填主循环按行口径单测（首行已淘汰、其余行仍待回写） ----------

def test_run_backfill_per_row_semantics_with_dup_records(tmp_path, monkeypatch):
    """同链接多行 raw（首行已被老链路淘汰、第二行仍 SYNCED）+ 同链接重复 record：
    dry-run 按行统计待回写行；apply 经真实服务写库且重复 record 去重跳过"""
    import importlib.util
    from app.automation.services import reject_sync_service as svc

    db = tmp_path / "bf.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE raw_jobs (job_link TEXT, process_status TEXT, reject_reason TEXT)")
    # 同链接两行：首行已被老链路标 ai清洗淘汰，第二行仍 SYNCED（待回写）
    conn.execute("INSERT INTO raw_jobs VALUES ('https://x/job1', 'ai清洗淘汰', '老链路结论')")
    conn.execute("INSERT INTO raw_jobs VALUES ('https://x/job1', '已同步', '')")
    conn.commit()

    spec = importlib.util.spec_from_file_location("backfill", Path(__file__).resolve().parents[1] / "scripts" / "backfill_reject_raw.py")
    bf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf)

    monkeypatch.setattr(svc, "job_hunter_db_path", lambda default: db)
    jobs = [
        {"record_id": "rec1", "company": "X", "job_name": "岗1", "grade": "F", "job_link": "https://x/job1"},
        {"record_id": "rec2", "company": "X", "job_name": "岗1", "grade": "F", "job_link": "https://x/job1"},  # 同链接重复
    ]

    # dry-run：按行统计（不写库）
    stats = bf.run_backfill(jobs, conn, apply_mode=False, service=svc.sync_eval_reject_to_raw, quiet=True)
    assert stats["matched_links"] == 1
    assert stats["writable_rows"] == 1  # 首行淘汰态不计入，仅第二行待回写
    assert stats["skipped_dup"] == 1
    assert stats["written_rows"] == 0

    # apply：真实服务写库（monkeypatch 后指向 tmp db），仅第二行被改写
    stats = bf.run_backfill(jobs, conn, apply_mode=True, service=svc.sync_eval_reject_to_raw, quiet=True)
    assert stats["written_rows"] == 1
    rows = conn.execute("SELECT process_status, reject_reason FROM raw_jobs WHERE job_link='https://x/job1' ORDER BY rowid").fetchall()
    assert rows[0][0] == "ai清洗淘汰" and rows[0][1] == "老链路结论"  # 首行不动
    assert rows[1][0] == REJECT_AI and "存量回填" in rows[1][1]  # 第二行回写
    conn.close()
