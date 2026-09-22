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
    rca._recall_evaluating.clear()
    rca._recall_background_tasks.clear()
    yield
    rca._recall_evaluating.clear()
    rca._recall_background_tasks.clear()


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
    assert rca._raw_rowid_str(2) not in rca._recall_evaluating  # 归一键（raw_2）必须已释放（不得永久锁死）
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
    rca._recall_evaluating.add(rca._raw_rowid_str(1))
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
    assert "部分完成" in card_json
