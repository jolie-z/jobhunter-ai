"""召回自动复评链路回归（改动：report_card_actions._batch_recall_rejected_jobs 三步链路 + 守卫 + 防重入）。

链路（用户裁决语义）：召回 = 人工否决 AI 初筛 → 推送飞书（如需）→ run_single_job_pipeline_async
（入口即初评、无排雷）→ 按评级走既有精投/海投流转，stop_at_review=True 本动作不投递。
"""
import pytest
import sqlite3
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

from app.services import report_card_actions as rca
from app.services import feishu_service
from app.services import job_action_service as jas


@pytest.fixture()
def recall_db(tmp_path):
    """召回场景专用库：1 条阶段2排雷淘汰岗（无飞书记录）+ 1 条带飞书记录的已确认淘汰岗。"""
    db = str(tmp_path / "recall.db")
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT, job_title TEXT, company_name TEXT,
                salary TEXT, city TEXT, education_req TEXT, experience_req TEXT,
                jd_text TEXT, job_link TEXT, process_status TEXT, reject_reason TEXT,
                crawl_time TEXT DEFAULT '', publish_date TEXT DEFAULT '',
                is_synced INTEGER DEFAULT 0, feishu_record_id TEXT DEFAULT ''
            )
        """)
        conn.execute(
            "INSERT INTO raw_jobs (rowid, platform, job_title, company_name, job_link, "
            "process_status, reject_reason) "
            "VALUES (1, 'BOSS直聘', 'AI大客户经理', '测试公司A', 'https://zhipin.com/job/1', "
            "'ai清洗淘汰', '触发 AI 侦察兵排雷: 触发绝不条件 [销售]')"
        )
        conn.execute(
            "INSERT INTO raw_jobs (rowid, platform, job_title, company_name, job_link, "
            "process_status, feishu_record_id) "
            "VALUES (2, '猎聘', '产品经理', '测试公司B', 'https://liepin.com/job/2', "
            "'已确认淘汰', 'recEXIST1')"
        )
        conn.commit()
    return db


def _feishu_record(follow_status: str):
    return {"record_id": "recX", "fields": {"跟进状态": {"text": follow_status}}}


@pytest.fixture()
def patched_feishu():
    """飞书查询/更新打桩：get 返回可配置状态，update 记录调用。"""
    with patch.object(feishu_service, "get_job_record_from_feishu", return_value=_feishu_record("新线索")) as m_get, \
         patch.object(feishu_service, "update_feishu_record", return_value=True) as m_upd:
        yield m_get, m_upd


@pytest.fixture(autouse=True)
def clear_set():
    import app.automation.delivery_tasks as _dt
    # 复评链路内部会 init 真实图并 set_pipeline_app；进入前记下现场，退出时还原，
    # 否则真实 CompiledStateGraph 残留在模块全局，后续文件的 scheduler.pipeline_app 打桩被短路
    _prev_pipeline_app = _dt.pipeline_app
    jas._recall_evaluating.clear()
    rca._recall_background_tasks.clear()
    yield
    jas._recall_evaluating.clear()
    rca._recall_background_tasks.clear()
    _dt.pipeline_app = _prev_pipeline_app


@pytest.mark.asyncio
async def test_rowid_recall_without_record_pushes_and_runs_engine(recall_db, patched_feishu):
    """阶段2淘汰岗（无飞书记录）召回：标记待推送 → 推送建档 → 引擎以非空 record_id + stop_at_review=True 拉起。"""
    engine = AsyncMock(return_value={})
    created = {}

    def fake_sync(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
        # 模拟 sync 行为：按 link 命中后回写 record_id 与已同步
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE raw_jobs SET is_synced = 1, process_status = '已同步', feishu_record_id = 'recNEW1' "
                "WHERE job_link IN (%s)" % ",".join("?" * len(target_links)), list(target_links)
            )
        created["links"] = list(target_links)
        created["db"] = db_path
        return ["recNEW1"]

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", side_effect=fake_sync), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["1"])
        # 等待后台复评任务跑完再断言
        if rca._recall_background_tasks:
            await asyncio.gather(*list(rca._recall_background_tasks), return_exceptions=True)

    assert created["links"] == ["https://zhipin.com/job/1"]
    engine.assert_awaited_once()
    args, kwargs = engine.call_args
    assert args[0] == "recNEW1"          # record_id 非空（推送建档成功）
    assert args[1] == "raw_1"            # raw_rowid 透传
    assert kwargs.get("stop_at_review") is True
    with sqlite3.connect(recall_db) as conn:
        status = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 1").fetchone()[0]
    assert status == "召回待初评"         # 推送后的"已同步"被覆盖回召回态


@pytest.mark.asyncio
async def test_rec_recall_with_flow_status_is_rejected(recall_db, patched_feishu):
    """rec 路径守卫：飞书跟进状态为「已投递」的岗位拒召，引擎不拉起、状态不被改写、防重入集合释放。"""
    m_get, m_upd = patched_feishu
    m_get.return_value = _feishu_record("已投递")
    engine = AsyncMock(return_value={})

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["recEXIST1"])

    m_upd.assert_not_called()
    engine.assert_not_awaited()
    assert rca._raw_rowid_str(2) not in jas._recall_evaluating  # 归一键（raw_2）必须已释放（不得永久锁死）
    with sqlite3.connect(recall_db) as conn:
        status = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 2").fetchone()[0]
    assert status == "已确认淘汰"         # 本地状态未被污染


@pytest.mark.asyncio
async def test_rec_recall_allowed_status_hands_off_and_runs_engine(recall_db, patched_feishu):
    """rec 路径放行（白名单「已淘汰」）：引擎收到 raw_ 前缀 raw_rowid + record_id，防重入所有权移交协程。"""
    m_get, _ = patched_feishu
    m_get.return_value = _feishu_record("已淘汰")
    engine = AsyncMock(return_value={})

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["recEXIST1"])
        if rca._recall_background_tasks:
            await asyncio.gather(*list(rca._recall_background_tasks), return_exceptions=True)

    engine.assert_awaited_once()
    args, kwargs = engine.call_args
    assert args[0] == "recEXIST1"
    assert args[1] == "raw_2"             # raw_rowid 统一 raw_ 前缀格式
    assert kwargs.get("stop_at_review") is True
    with sqlite3.connect(recall_db) as conn:
        status = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 2").fetchone()[0]
    assert status == "召回待初评"


@pytest.mark.asyncio
async def test_rowid_recall_with_record_and_flow_status_is_rejected(recall_db, patched_feishu):
    """rowid 路径守卫：带飞书记录且已投递的「已确认淘汰」岗拒召（防状态污染与重复投递）。"""
    m_get, _ = patched_feishu
    m_get.return_value = _feishu_record("已投递")
    engine = AsyncMock(return_value={})

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["2"])

    engine.assert_not_awaited()
    with sqlite3.connect(recall_db) as conn:
        status = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 2").fetchone()[0]
    assert status == "已确认淘汰"


@pytest.mark.asyncio
async def test_reentrant_recall_is_blocked(recall_db, patched_feishu):
    """防重入：复评进行中（归一键 raw_1 命中集合）的岗位再次召回被拒绝，不重复标记/拉引擎。"""
    jas.register_recall_start(rca._raw_rowid_str(1))
    engine = AsyncMock(return_value={})
    sync_mock = MagicMock()

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", sync_mock), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()) as m_card:
        await rca._batch_recall_rejected_jobs("chatX", ["1"])

    engine.assert_not_awaited()
    sync_mock.assert_not_called()
    # 拒召原因必须写进结果卡片（"正在复评中"），而非静默失败
    card_json = json.dumps(m_card.call_args[0][1], ensure_ascii=False, default=str)
    assert "正在复评中" in card_json


@pytest.mark.asyncio
async def test_trigger_push_without_record_id_then_engine(recall_db):
    """_trigger_recall_reevaluation：空 record_id → 推送建档 → 重读非空 → 覆盖召回态 → 拉引擎。"""
    engine = AsyncMock(return_value={})

    def fake_sync(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE raw_jobs SET is_synced = 1, process_status = '已同步', feishu_record_id = 'recNEW9' "
                "WHERE job_link IN (%s)" % ",".join("?" * len(target_links)), list(target_links)
            )
        return ["recNEW9"]

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", side_effect=fake_sync), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine):
        await rca._trigger_recall_reevaluation({
            "raw_rowid": "raw_1", "record_id": None, "key": "1",
            "prev_status": "ai清洗淘汰", "job_link": "https://zhipin.com/job/1",
        })

    engine.assert_awaited_once_with("recNEW9", "raw_1", stop_at_review=True)
    with sqlite3.connect(recall_db) as conn:
        row = conn.execute("SELECT process_status, feishu_record_id FROM raw_jobs WHERE rowid = 1").fetchone()
    assert row == ("召回待初评", "recNEW9")


@pytest.mark.asyncio
async def test_trigger_rolls_back_when_push_fails_to_create_record(recall_db, patched_feishu):
    """推送后仍无飞书记录 → 回滚原淘汰态 + 回发提醒（静默成功会造成用户无感的滞留态）。"""
    m_get, _ = patched_feishu
    m_get.return_value = None

    def fake_sync(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
        with sqlite3.connect(db_path) as conn:
            # 模拟 sync 未能建档：只写已同步、不写 record_id
            conn.execute(
                "UPDATE raw_jobs SET is_synced = 1, process_status = '已同步' "
                "WHERE job_link IN (%s)" % ",".join("?" * len(target_links)), list(target_links)
            )
        return []

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", side_effect=fake_sync), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", AsyncMock()) as engine, \
         patch.object(rca, "send_feishu_message", AsyncMock()) as m_msg:
        await rca._trigger_recall_reevaluation({
            "raw_rowid": "raw_1", "record_id": None, "key": "1",
            "prev_status": "ai清洗淘汰", "job_link": "https://zhipin.com/job/1", "chat_id": "chatX",
        })

    engine.assert_not_awaited()
    with sqlite3.connect(recall_db) as conn:
        status = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 1").fetchone()[0]
    assert status == "ai清洗淘汰"        # 回滚原淘汰态
    m_msg.assert_awaited_once()          # 用户收到未启动提醒


@pytest.mark.asyncio
async def test_follow_status_query_failure_fails_closed(recall_db, patched_feishu):
    """守卫 fail-closed：飞书查询失败（None）时拒召，绝不静默放行覆盖实时状态。"""
    m_get, m_upd = patched_feishu
    m_get.return_value = None
    engine = AsyncMock(return_value={})

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["2"])

    m_upd.assert_not_called()
    engine.assert_not_awaited()


@pytest.mark.asyncio
async def test_follow_status_empty_string_is_allowed(recall_db, patched_feishu):
    """守卫放行面：跟进状态为空串（未流转）属白名单，正常放行进入复评。"""
    m_get, _ = patched_feishu
    m_get.return_value = _feishu_record("")
    engine = AsyncMock(return_value={})

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["2"])
        if rca._recall_background_tasks:
            await asyncio.gather(*list(rca._recall_background_tasks), return_exceptions=True)

    engine.assert_awaited_once()

@pytest.mark.asyncio
async def test_malformed_id_does_not_abort_whole_batch(recall_db, patched_feishu):
    """畸形 ID（非数字 rowid）只计单条失败，不中断整批、不发不出结果卡片（原子段入 try 回归）。"""
    engine = AsyncMock(return_value={})

    def fake_sync(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE raw_jobs SET is_synced = 1, process_status = '已同步', feishu_record_id = 'recNEW1' "
                "WHERE job_link IN (%s)" % ",".join("?" * len(target_links)), list(target_links)
            )
        return ["recNEW1"]

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", side_effect=fake_sync), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()) as m_card:
        await rca._batch_recall_rejected_jobs("chatX", ["12a", "1"])
        if rca._recall_background_tasks:
            await asyncio.gather(*list(rca._recall_background_tasks), return_exceptions=True)

    # 畸形 ID 单条失败，正常岗位仍完整走完链路
    engine.assert_awaited_once()
    card_json = json.dumps(m_card.call_args[0][1], ensure_ascii=False, default=str)
    assert "部分受理" in card_json


# --------------------------------------------------------- 2026-10-09 双端撕裂事故回归

@pytest.mark.asyncio
async def test_reject_skips_recall_in_progress(recall_db, patched_feishu):
    """P0-3 赛跑守卫：召回复评中的岗位（_recall_evaluating 登记）点「确认淘汰」必须跳过，
    不写飞书「不合适」、不覆盖 raw 状态——正是迈络事故的成因路径。"""
    _, m_upd = patched_feishu
    jas.register_recall_start("raw_2")  # 模拟该岗位正在复评

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch.object(rca, "send_feishu_card", AsyncMock()) as m_card:
        await rca._batch_reject_jobs("chatX", ["2"])

    body = json.dumps(m_card.call_args[0][1], ensure_ascii=False)
    assert "跳过" in body
    with sqlite3.connect(recall_db) as conn:
        st = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 2").fetchone()[0]
    assert st == "已确认淘汰"  # 原状态未被覆盖（fixture 本就是已确认淘汰）
    # 飞书侧未被写成「不合适」
    wrote_unsuitable = any(
        c.args and c.args[1] == {"跟进状态": "不合适"} for c in m_upd.call_args_list
    )
    assert not wrote_unsuitable


@pytest.mark.asyncio
async def test_reject_allows_stale_recall_residual_but_blocks_active(recall_db, patched_feishu):
    """岗哨1 R1 P1-2 死锁解除：「召回待初评」+ 不在评中（复评失败/进程重启残留）允许归档
    （用户处置出口）；其余活跃态（已流转）仍跳过。"""
    # 场景1：召回残留 → 放行归档
    with sqlite3.connect(recall_db) as conn:
        conn.execute("UPDATE raw_jobs SET process_status = '召回待初评' WHERE rowid = 2")
        conn.commit()
    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch.object(rca, "send_feishu_card", AsyncMock()) as m_card:
        await rca._batch_reject_jobs("chatX", ["2"])
    with sqlite3.connect(recall_db) as conn:
        st = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 2").fetchone()[0]
    assert st == "已确认淘汰"  # 残留态成功归档,不再死锁

    # 场景2:真在评中(key 在集合) → 即便状态是召回待初评也拦
    with sqlite3.connect(recall_db) as conn:
        conn.execute("UPDATE raw_jobs SET process_status = '召回待初评' WHERE rowid = 2")
        conn.commit()
    jas.register_recall_start("raw_2")
    try:
        with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
             patch.object(rca, "send_feishu_card", AsyncMock()) as m_card:
            await rca._batch_reject_jobs("chatX", ["2"])
        body = json.dumps(m_card.call_args[0][1], ensure_ascii=False)
        assert "正在召回复评中" in body
        with sqlite3.connect(recall_db) as conn:
            st = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 2").fetchone()[0]
        assert st == "召回待初评"  # 未被覆盖
    finally:
        jas.register_recall_end("raw_2")

    # 场景3:已流转活跃态(已同步) → 仍跳过
    with sqlite3.connect(recall_db) as conn:
        conn.execute("UPDATE raw_jobs SET process_status = '已同步' WHERE rowid = 2")
        conn.commit()
    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch.object(rca, "send_feishu_card", AsyncMock()) as m_card:
        await rca._batch_reject_jobs("chatX", ["2"])
    body = json.dumps(m_card.call_args[0][1], ensure_ascii=False)
    assert "不在淘汰队列" in body
    with sqlite3.connect(recall_db) as conn:
        st = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 2").fetchone()[0]
    assert st == "已同步"


@pytest.mark.asyncio
async def test_reject_writes_unified_confirmed_word(recall_db, patched_feishu):
    """P0-1 词表收敛：飞书卡片确认淘汰统一写「已确认淘汰」，不再写全库无读取方的「已淘汰」。"""
    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_reject_jobs("chatX", ["1"])

    with sqlite3.connect(recall_db) as conn:
        st = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 1").fetchone()[0]
    assert st == "已确认淘汰"


@pytest.mark.asyncio
async def test_recall_and_reject_receipts_contain_job_details(recall_db, patched_feishu):
    """P1-7 + 用户需求：召回/归档回执必须带岗位明细（公司 - 岗位），只报数量的回执无法审计动作对象。"""
    engine = AsyncMock(return_value={"outcome": "stopped", "error": "", "status": "已完成初步评估"})

    def fake_sync(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
        return []

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", side_effect=fake_sync), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()) as m_recall:
        await rca._batch_recall_rejected_jobs("chatX", ["1"])
        if rca._recall_background_tasks:
            await asyncio.gather(*list(rca._recall_background_tasks), return_exceptions=True)

    recall_body = json.dumps(m_recall.call_args[0][1], ensure_ascii=False)
    assert "本次动作岗位" in recall_body
    assert "测试公司A - AI大客户经理" in recall_body
    assert "后台自动复评中" in recall_body  # P1-4:不再提前宣告「成功」

    # 复位到淘汰态再归档（上一步召回后岗位已进召回待初评，会被赛跑守卫正确拦截）
    with sqlite3.connect(recall_db) as conn:
        conn.execute("UPDATE raw_jobs SET process_status = 'ai清洗淘汰', feishu_record_id = '' WHERE rowid = 1")
        conn.commit()

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch.object(rca, "send_feishu_card", AsyncMock()) as m_reject:
        await rca._batch_reject_jobs("chatX", ["1"])

    reject_body = json.dumps(m_reject.call_args[0][1], ensure_ascii=False)
    assert "测试公司A - AI大客户经理" in reject_body


@pytest.mark.asyncio
async def test_reeval_success_writes_back_synced(recall_db, patched_feishu):
    """P2-9 双端撕裂根治：复评成功后 raw 必须回写「已同步」，不再永久停留召回时刻的旧值。"""
    engine = AsyncMock(return_value={"outcome": "ready_to_deliver", "error": "", "status": "待投递"})

    def fake_sync(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE raw_jobs SET is_synced = 1, feishu_record_id = 'recNEW9' WHERE job_link IN ('https://zhipin.com/job/1')"
            )
        return []

    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", side_effect=fake_sync), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["1"])
        if rca._recall_background_tasks:
            await asyncio.gather(*list(rca._recall_background_tasks), return_exceptions=True)

    with sqlite3.connect(recall_db) as conn:
        st = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 1").fetchone()[0]
    assert st == "已同步"


# --------------------------------------------------------- 动作审计(P1-6 来源审计落地)

@pytest.mark.asyncio
async def test_action_audit_records_source_and_result(recall_db, patched_feishu):
    """P1-6 收敛:两端动作必须落审计——来源端(feishu_card/desktop)/动作/对象/结果可追溯。
    本用例锁飞书侧:召回(成功)与归档(成功)各落一条;桌面端由 test_unreject 系锁。"""
    from app.services import job_action_service as jas

    engine = AsyncMock(return_value={"outcome": "stopped", "error": "", "status": "已完成初步评估"})

    def fake_sync(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):
        return []

    # 双 patch 缺一不可:rca 是 from-import 绑定(批次层读库),jas 是函数内 import(审计写库)
    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("app.automation.scrape_runner._get_raw_db_path", return_value=recall_db), \
         patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", side_effect=fake_sync), \
         patch("app.automation.graph_runner.run_single_job_pipeline_async", engine), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_recall_rejected_jobs("chatX", ["1"])
        if rca._recall_background_tasks:
            await asyncio.gather(*list(rca._recall_background_tasks), return_exceptions=True)
    with sqlite3.connect(recall_db) as conn:
        conn.execute("UPDATE raw_jobs SET process_status = 'ai清洗淘汰', feishu_record_id = '' WHERE rowid = 1")
        conn.commit()
    with patch.object(rca, "_get_raw_db_path", return_value=recall_db), \
         patch("app.automation.scrape_runner._get_raw_db_path", return_value=recall_db), \
         patch.object(rca, "send_feishu_card", AsyncMock()):
        await rca._batch_reject_jobs("chatX", ["1"])

    audits = jas.list_action_audits(limit=20, db_path=recall_db)
    recall_rows = [a for a in audits if a["action"] == "recall" and a["source"] == "feishu_card"]
    reject_rows = [a for a in audits if a["action"] == "reject" and a["source"] == "feishu_card"]
    assert recall_rows and recall_rows[0]["result"] == "success"
    assert "测试公司A" in recall_rows[0]["job_label"]
    assert reject_rows and reject_rows[0]["result"] == "success"
    assert reject_rows[0]["target_id"] == "1"


def test_job_action_service_primitives(recall_db):
    """共享原语:ID 解析拆装/岗位名格式化/复评中判定(公共查询替代私有集合穿透)。"""
    from app.services import job_action_service as jas

    assert jas.parse_raw_rowid("raw_42") == 42
    assert jas.parse_raw_rowid("42") == 42
    with pytest.raises(ValueError):
        jas.parse_raw_rowid("not-a-number")
    assert jas.raw_rowid_key(42) == "raw_42"
    long_label = jas.format_job_label("某公司名字很长很长很长很长很长很长很长很长", "某岗位名同样很长很长很长很长很长很长")
    assert long_label.startswith("某公司名字很长很长很长很长很长很长很长很长"[:20])
    assert " - " in long_label and "未知" not in long_label
    assert jas.format_job_label(None, None) == "未知公司 - 未知岗位"

    # is_job_recalling:公共查询与私有集合同视野
    from app.services import report_card_actions as rca
    jas.register_recall_start("raw_7")
    try:
        assert jas.is_job_recalling(7) is True
        assert jas.is_job_recalling("raw_7") is True
        assert jas.is_job_recalling(8) is False
    finally:
        jas.register_recall_end("raw_7")


@pytest.mark.asyncio
async def test_desktop_unreject_records_audit(tmp_path):
    """桌面端放行落审计(source=desktop),与飞书侧来源可区分。"""
    from app.services import job_action_service as jas

    db_file = str(tmp_path / "audit_unreject.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT, job_title TEXT, company_name TEXT, city TEXT, salary TEXT,
                job_link TEXT, process_status TEXT, reject_reason TEXT, feishu_record_id TEXT
            )
        """)
        conn.execute("""
            INSERT INTO raw_jobs (rowid, platform, job_title, company_name, job_link, process_status)
            VALUES (501, 'zhilian', '审计岗', '审计公司', 'https://zhaopin.com/job/501', '清洗淘汰')
        """)
        conn.commit()

    from app.api.routes import processor
    with patch.object(processor, "DB_PATH", db_file), \
         patch("app.automation.scrape_runner._get_raw_db_path", return_value=db_file), \
         patch("app.api.routes.processor._run_unreject_and_evaluate", new_callable=AsyncMock):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            res = c.post("/api/v1/processor/unreject", json={"job_id": "raw_501"})
            assert res.status_code == 200

    audits = jas.list_action_audits(limit=10, db_path=db_file)
    assert audits and audits[0]["source"] == "desktop"
    assert audits[0]["action"] == "recall"
    assert "审计公司" in audits[0]["job_label"]
