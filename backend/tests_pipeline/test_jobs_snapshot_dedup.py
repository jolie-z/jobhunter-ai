import pytest
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
from app.automation.router import jobs_snapshot
from app.automation import run_snapshot as rs


@contextmanager
def _patched_feishu_sources(test_db, mock_pending, get_job_record=None):
    """Q15 共享 feishu mock 组：六路查询打桩（传 callable 走 side_effect，否则为固定返回值）。"""
    record_stub = (
        {"side_effect": get_job_record} if callable(get_job_record)
        else {"return_value": get_job_record}
    )
    with patch("app.automation.full_auto.RAW_DB_PATH", test_db), \
         patch("app.automation.run_snapshot.get_delivery_failures", return_value={}), \
         patch("app.services.feishu_service.get_pending_review_jobs_from_feishu", return_value=mock_pending), \
         patch("app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_delivered_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_failed_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_manual_rejected_jobs_from_feishu", return_value=[]), \
         patch("app.services.feishu_service.get_job_record_from_feishu", **record_stub):
        yield


@pytest.mark.asyncio
async def test_jobs_snapshot_strict_deduplication(tmp_path):
    """验证 jobs_snapshot 严格保证 1 岗位 1 卡片，已同步飞书的岗位绝不重复输出 SQLite 待清洗卡"""
    test_db = str(tmp_path / "test_hunter.db")
    with sqlite3.connect(test_db) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                job_title TEXT,
                company_name TEXT,
                salary TEXT,
                city TEXT,
                education_req TEXT,
                experience_req TEXT,
                jd_text TEXT,
                job_link TEXT,
                process_status TEXT,
                reject_reason TEXT,
                is_synced INTEGER DEFAULT 0,
                feishu_record_id TEXT DEFAULT ''
            )
        """)
        # 插入 8 条已同步飞书的岗位 + 2 条清洗淘汰岗位
        for i in range(1, 9):
            conn.execute(
                "INSERT INTO raw_jobs (rowid, platform, job_title, company_name, job_link, process_status, is_synced, feishu_record_id) "
                "VALUES (?, '智联招聘', ?, ?, ?, '已同步', 1, ?)",
                (i, f"AI产品经理_{i}", f"测试公司_{i}", f"https://zhaopin.com/job/{i}", f"rec_00{i}")
            )
        conn.execute(
            "INSERT INTO raw_jobs (rowid, platform, job_title, company_name, job_link, process_status, is_synced) "
            "VALUES (9, '智联招聘', '低薪岗位_9', '淘汰公司_9', 'https://zhaopin.com/job/9', '清洗淘汰', 0)"
        )
        conn.execute(
            "INSERT INTO raw_jobs (rowid, platform, job_title, company_name, job_link, process_status, is_synced) "
            "VALUES (10, '智联招聘', '黑名单_10', '淘汰公司_10', 'https://zhaopin.com/job/10', 'ai清洗淘汰', 0)"
        )
        conn.commit()

    from pathlib import Path
    with patch.object(rs, "_DB_PATH", Path(test_db)):
        # 登记本轮台账
        rs.begin("task_test_123", start_rowid=0, budgets={"zhilian": 10}, disabled=[])
        rs.register_record_ids([f"rec_00{i}" for i in range(1, 9)])

        # Mock 飞书接口返回值
        mock_pending = [
            {
                "job_id": f"rec_00{i}",
                "job_name": f"AI产品经理_{i}",
                "company_name": f"测试公司_{i}",
                "platform": "zhilian",
                "grade": "A",
                "salary": "25-35K",
                "city": "广州",
                "job_url": f"https://zhaopin.com/job/{i}",
                "is_custom": True,
            }
            for i in range(1, 5)
        ]

        mock_feishu_records = {
            f"rec_00{i}": {
                "record_id": f"rec_00{i}",
                "fields": {
                    "岗位名称": f"AI产品经理_{i}",
                    "公司名称": f"测试公司_{i}",
                    "招聘平台": "智联招聘",
                    "综合等级": "C",
                    "初评总分": 68.5,
                    "跟进状态": "已完成初步评估",
                    "岗位链接": f"https://zhaopin.com/job/{i}",
                }
            }
            for i in range(5, 9)
        }

        def fake_get_job_record(rid, table_id):
            return mock_feishu_records.get(rid)

        with _patched_feishu_sources(test_db, mock_pending, fake_get_job_record):
            res = await jobs_snapshot()
            data = res.get("data", [])

            # 验证结果：10 个岗位恰好返回 10 张卡片，没有任何双倍卡片！
            assert len(data) == 10, f"期望返回 10 个岗位卡片，实际返回 {len(data)}"

            # 验证卡片构成：2 张淘汰卡 (raw_9, raw_10) + 4 张待审批卡 (rec_001~004) + 4 张初评完成卡 (rec_005~008)
            raw_jobs = [j for j in data if str(j.get("job_id")).startswith("raw_")]
            feishu_jobs = [j for j in data if str(j.get("job_id")).startswith("rec_")]

            assert len(raw_jobs) == 2, f"SQLite 淘汰卡应为 2 张，实际为 {len(raw_jobs)}"
            assert len(feishu_jobs) == 8, f"飞书流转卡应为 8 张，实际为 {len(feishu_jobs)}"

            # 验证淘汰卡状态
            assert all(j["status"] == "rejected" for j in raw_jobs)
            # 验证待审批卡状态
            waiting_jobs = [j for j in feishu_jobs if j["status"] == "waiting"]
            assert len(waiting_jobs) == 4
            # 验证已完成初评卡状态
            done_jobs = [j for j in feishu_jobs if j["status"] == "done"]
            assert len(done_jobs) == 4


@pytest.mark.asyncio
async def test_jobs_snapshot_fuzzy_normalization_dedup(tmp_path):
    """验证包含全角括号、空格、分公司等细微差异的岗位也能被精准去重并只保留一张卡片"""
    test_db = str(tmp_path / "test_fuzzy.db")
    with sqlite3.connect(test_db) as conn:
        conn.execute("""
            CREATE TABLE raw_jobs (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT,
                job_title TEXT,
                company_name TEXT,
                salary TEXT,
                city TEXT,
                education_req TEXT,
                experience_req TEXT,
                jd_text TEXT,
                job_link TEXT,
                process_status TEXT,
                reject_reason TEXT,
                is_synced INTEGER DEFAULT 0,
                feishu_record_id TEXT DEFAULT ''
            )
        """)
        # SQLite 中带有全角括号和空格
        conn.execute(
            "INSERT INTO raw_jobs (rowid, platform, job_title, company_name, job_link, process_status, is_synced) "
            "VALUES (1, '智联招聘', 'AI 产品经理（B 端）', '广东杰纳医药科技有限公司', 'https://zhaopin.com/job/101?source=1', '待推送至飞书', 0)"
        )
        conn.commit()

    from pathlib import Path
    with patch.object(rs, "_DB_PATH", Path(test_db)):
        rs.begin("task_fuzzy_123", start_rowid=0, budgets={"zhilian": 1}, disabled=[])
        rs.register_record_ids(["rec_fuzzy_101"])

        # 飞书返回的记录去除了空格，使用半角括号
        mock_pending = [
            {
                "job_id": "rec_fuzzy_101",
                "job_name": "AI产品经理(B端)",
                "company_name": "广东杰纳医药科技",
                "platform": "zhilian",
                "grade": "B",
                "salary": "20-30K",
                "city": "广州",
                "job_url": "https://zhaopin.com/job/101",
                "is_custom": True,
            }
        ]

        with _patched_feishu_sources(test_db, mock_pending):
            res = await jobs_snapshot()
            data = res.get("data", [])

            # 验证结果：即使名称存在中英文括号与空格差异，也绝不出现两张卡片！
            assert len(data) == 1, f"期望返回 1 个岗位卡片，实际返回 {len(data)}"
            assert data[0]["job_id"] == "rec_fuzzy_101"
            assert data[0]["status"] == "waiting"
