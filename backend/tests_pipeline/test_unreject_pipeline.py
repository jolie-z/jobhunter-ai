import sqlite3
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import processor

client = TestClient(app)


def test_unreject_by_job_id_and_link(tmp_path):
    """测试通过 job_id (raw_xxx) 或 job_link 放行淘汰岗位，解除淘汰状态并启动后台评估"""
    # 模拟临时 SQLite 数据库
    db_file = str(tmp_path / "test_unreject.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                job_title TEXT,
                company_name TEXT,
                city TEXT,
                salary TEXT,
                job_link TEXT,
                process_status TEXT,
                reject_reason TEXT,
                feishu_record_id TEXT
            )
        """)
        conn.execute("""
            INSERT INTO raw_jobs (rowid, platform, job_title, company_name, city, salary, job_link, process_status, reject_reason)
            VALUES (101, 'zhilian', '产品经理', '测试科技', '深圳', '20-30k', 'https://zhaopin.com/job/101', '清洗淘汰', '经验不符')
        """)
        conn.commit()

    with patch.object(processor, "DB_PATH", db_file):
        with patch("app.api.routes.processor._run_unreject_and_evaluate", new_callable=AsyncMock) as mock_task:
            res = client.post("/api/v1/processor/unreject", json={
                "job_id": "raw_101",
                "job_link": "https://zhaopin.com/job/101",
                "pipeline_task_id": "pipeline_test_999"
            })
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"

            # 验证 SQLite 数据库状态已改为 '待推送至飞书'，死因清空
            with sqlite3.connect(db_file) as conn:
                r = conn.execute("SELECT process_status, reject_reason FROM raw_jobs WHERE rowid = 101").fetchone()
                assert r[0] == "待推送至飞书"
                assert r[1] is None

            # 验证后台任务已被调度
            mock_task.assert_called_once_with("pipeline_test_999", 101, "https://zhaopin.com/job/101")


def test_confirm_reject(tmp_path):
    """测试确认淘汰接口将岗位标记为已确认淘汰"""
    db_file = str(tmp_path / "test_confirm.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                job_title TEXT,
                job_link TEXT,
                process_status TEXT
            )
        """)
        conn.execute("""
            INSERT INTO raw_jobs (rowid, platform, job_title, job_link, process_status)
            VALUES (202, 'boss', '前端工程师', 'https://zhipin.com/job/202', 'ai清洗淘汰')
        """)
        conn.commit()

    with patch.object(processor, "DB_PATH", db_file):
        res = client.post("/api/v1/processor/confirm-reject", json={
            "job_id": "raw_202",
            "job_link": "https://zhipin.com/job/202"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"

        with sqlite3.connect(db_file) as conn:
            r = conn.execute("SELECT process_status FROM raw_jobs WHERE rowid = 202").fetchone()
            assert r[0] == "已确认淘汰"


@pytest.mark.asyncio
async def test_run_unreject_and_evaluate_triggers_pipeline(tmp_path, monkeypatch):
    """测试 _run_unreject_and_evaluate 协程成功调用 sync_sqlite_to_feishu 并拉起 run_single_job_pipeline_async"""
    # 密闭化：DB_PATH 必须指向临时库——该协程会回查 raw_jobs 取 feishu_record_id，
    # 不隔离时会读到真实生产库（本地侥幸过、CI 无表炸红）
    db_file = str(tmp_path / "test_unreject_pipeline.db")
    with sqlite3.connect(db_file) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                job_link TEXT,
                feishu_record_id TEXT
            )
        """)
        conn.execute(
            "INSERT INTO raw_jobs (job_link, feishu_record_id) VALUES (?, '')",
            ("https://zhaopin.com/job/888",),
        )
        conn.commit()
    monkeypatch.setattr(processor, "DB_PATH", db_file)

    with patch("job_processor.step2_sync_feishu.sync_sqlite_to_feishu", return_value=["rec_synced_888"]) as mock_sync:
        with patch("app.automation.full_auto.run_single_job_pipeline_async", new_callable=AsyncMock) as mock_pipe:
            await processor._run_unreject_and_evaluate(
                task_id="pipeline_test_abc",
                row_id=None,
                job_link="https://zhaopin.com/job/888"
            )
            mock_sync.assert_called_once()
            mock_pipe.assert_called_once_with(
                record_id="rec_synced_888",
                raw_rowid=None,
                pipeline_task_id="pipeline_test_abc"
            )
