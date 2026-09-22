"""召回/遗留 process_status 快照映射回归（两跳投递中误锁 bug 的后端环）。

背景：SQLite 段旧三元链对「召回待初评」等未映射值输出裸 running（无 sub_status），
前端合并层次跳会乐观注入 sub_status="delivering"，卡片误锁成「正在自动投递中」。
本文件锁定 _map_sqlite_process_status 白名单映射的全部分支 + 端到端快照字段。
"""
import pytest
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path

from app.automation.snapshot_service import _map_sqlite_process_status
from app.automation.router import jobs_snapshot
from app.automation import run_snapshot as rs


class TestSqliteProcessStatusMapping:
    """改1 映射表全部分支逐值断言（DB 实际存在的 8 值 + 运行期写入的「待投递」+ 未知值兜底）。"""

    def test_ai_clean_rejected(self):
        m = _map_sqlite_process_status("ai清洗淘汰")
        assert m["status"] == "rejected"
        assert m["sub_status"] is None
        assert m["last_action_desc"] == "触发AI排雷规则淘汰"

    def test_clean_rejected(self):
        m = _map_sqlite_process_status("清洗淘汰")
        assert m["status"] == "rejected"
        assert m["last_action_desc"] == "触发规则清洗淘汰"

    def test_confirmed_rejected(self):
        m = _map_sqlite_process_status("已确认淘汰")
        assert m["status"] == "rejected"
        assert m["last_action_desc"] == "已确认淘汰"

    def test_stored(self):
        m = _map_sqlite_process_status("已存入数据")
        assert m["status"] == "scraped"
        assert m["sub_status"] is None
        assert m["last_action_desc"] == "入库待清洗"

    def test_recall_pending_eval(self):
        m = _map_sqlite_process_status("召回待初评")
        assert m["status"] == "running"
        assert m["sub_status"] == "ai_eval_queued"
        assert m["last_action_desc"] == "♻️ 已召回，等待AI重新初评"

    def test_pending_push(self):
        m = _map_sqlite_process_status("待推送至飞书")
        assert m["status"] == "running"
        assert m["sub_status"] == "ai_eval_queued"
        assert m["last_action_desc"] == "已入库，待推送至飞书"

    def test_scored(self):
        m = _map_sqlite_process_status("已进行打分")
        assert m["status"] == "running"
        assert m["sub_status"] == "ai_eval_queued"
        assert m["last_action_desc"] == "AI打分完成，等待流转"

    def test_ready_to_deliver(self):
        m = _map_sqlite_process_status("待投递")
        assert m["status"] == "ready_to_deliver"
        assert m["sub_status"] is None
        assert m["last_action_desc"] == "待投递"

    def test_unknown_falls_to_eval_queued_not_bare_running(self):
        """未知未来值兜底必须是评估排队（带 sub_status），绝不裸 running。"""
        m = _map_sqlite_process_status("某个未来新增状态")
        assert m["status"] == "running"
        assert m["sub_status"] == "ai_eval_queued"

    def test_none_and_empty_fall_to_unknown_branch(self):
        """process_status 为 NULL/空串（表无 NOT NULL 约束，真实可达）必须走未知兜底而非抛异常。"""
        for bad in (None, ""):
            m = _map_sqlite_process_status(bad)
            assert m["status"] == "running"
            assert m["sub_status"] == "ai_eval_queued"


@contextmanager
def _patched_feishu_sources(test_db):
    with patch("app.automation.full_auto.RAW_DB_PATH", test_db), \
         patch("app.automation.run_snapshot.get_delivery_failures", return_value={}), \
         patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_delivered_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_failed_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_manual_rejected_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_job_record_from_feishu", return_value=None):
        yield


@pytest.mark.asyncio
async def test_recall_pending_eval_job_snapshot_fields(tmp_path):
    """端到端：召回待初评岗位的快照卡片必须是 running+ai_eval_queued，绝不裸 running。"""
    test_db = str(tmp_path / "test_hunter.db")
    with sqlite3.connect(test_db) as conn:
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
            "process_status, reject_reason, crawl_time) "
            "VALUES (1, 'BOSS直聘', 'AI大客户经理', '测试公司', 'https://zhipin.com/job/1', "
            "'召回待初评', '触发 AI 侦察兵排雷: 触发绝不条件 [销售]', '2026-09-22 09:03:00')"
        )
        conn.commit()

    with patch.object(rs, "_DB_PATH", Path(test_db)):
        rs.begin("task_recall_test", start_rowid=0, budgets={"boss": 5}, disabled=[])
        try:
            with _patched_feishu_sources(test_db):
                res = await jobs_snapshot()
        finally:
            rs.end()  # 清理模块级 runtime 台账，避免跨用例泄漏
        card = next((j for j in res.get("data", []) if j.get("job_id") == "raw_1"), None)

    assert card is not None
    assert card["status"] == "running"
    assert card["sub_status"] == "ai_eval_queued"
    assert card["node"] == "scrape_node"
    assert card["last_action_desc"] == "♻️ 已召回，等待AI重新初评"
    # is_ai_reject 语义锁定：仅 ai清洗淘汰 为 "ai"，召回待初评等其余态保持 "rule"
    assert card["reject_type"] == "rule"
