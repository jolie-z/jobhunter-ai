"""raw_jobs 关键字段二级索引回归测试。

验证内容：
1. ensure_raw_jobs_indices 幂等执行无报错；
2. idx_raw_jobs_status、idx_raw_jobs_platform、idx_raw_jobs_feishu_rid 成功建立；
3. Step 2 同步查询使用 idx_raw_jobs_status 索引搜索；
4. 大盘按 platform 统计使用 idx_raw_jobs_platform 覆盖索引；
5. feishu_record_id 反查使用 idx_raw_jobs_feishu_rid 索引搜索。
"""
import sqlite3
import pytest
from app.jobs.service import ensure_raw_jobs_indices


RAW_JOBS_SCHEMA = """
CREATE TABLE raw_jobs (
    job_link TEXT PRIMARY KEY,
    job_title TEXT,
    company_name TEXT,
    city TEXT,
    jd_text TEXT,
    salary TEXT,
    work_address TEXT,
    company_size TEXT,
    industry TEXT,
    education_req TEXT,
    experience_req TEXT,
    publish_date TEXT,
    platform TEXT,
    crawl_time DATETIME DEFAULT (datetime('now', 'localtime')),
    process_status TEXT DEFAULT '已存入数据',
    reject_reason TEXT,
    is_synced INTEGER DEFAULT 0,
    feishu_record_id TEXT DEFAULT ''
);
"""


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(RAW_JOBS_SCHEMA)
    yield conn
    conn.close()


def test_ensure_raw_jobs_indices_creates_all_indices(memory_db):
    """验证四个二级索引均被正确创建。"""
    ensure_raw_jobs_indices(conn=memory_db)

    indices = {
        row[0]
        for row in memory_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='raw_jobs'"
        ).fetchall()
    }
    assert "idx_raw_jobs_status" in indices
    assert "idx_raw_jobs_platform" in indices
    assert "idx_raw_jobs_feishu_rid" in indices
    assert "idx_raw_jobs_company_title_city" in indices


def test_ensure_raw_jobs_indices_is_idempotent(memory_db):
    """验证幂等性：多次执行不会抛异常。"""
    ensure_raw_jobs_indices(conn=memory_db)
    ensure_raw_jobs_indices(conn=memory_db)
    ensure_raw_jobs_indices(conn=memory_db)


def test_query_plan_uses_indices(memory_db):
    """验证核心业务 SQL 执行计划精准命中对应的二级索引。"""
    ensure_raw_jobs_indices(conn=memory_db)

    # 1. Step 2 同步查询：命中 idx_raw_jobs_status
    plan_sync = memory_db.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT rowid, job_title FROM raw_jobs "
        "WHERE process_status = '待推送至飞书' AND (is_synced = 0 OR is_synced IS NULL)"
    ).fetchall()
    plan_sync_str = " ".join(str(row) for row in plan_sync)
    assert "idx_raw_jobs_status" in plan_sync_str
    assert "SCAN raw_jobs')" not in plan_sync_str

    # 2. 大盘按平台统计：命中 idx_raw_jobs_platform 覆盖索引
    plan_platform = memory_db.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT platform, COUNT(*) FROM raw_jobs GROUP BY platform"
    ).fetchall()
    plan_platform_str = " ".join(str(row) for row in plan_platform)
    assert "idx_raw_jobs_platform" in plan_platform_str
    assert "COVERING INDEX" in plan_platform_str

    # 3. 飞书 record_id 反查：命中 idx_raw_jobs_feishu_rid
    plan_feishu = memory_db.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT rowid, job_title FROM raw_jobs WHERE feishu_record_id = 'rec_test'"
    ).fetchall()
    plan_feishu_str = " ".join(str(row) for row in plan_feishu)
    assert "idx_raw_jobs_feishu_rid" in plan_feishu_str

    # 4. 爬虫三要素查重：命中 idx_raw_jobs_company_title_city 覆盖索引
    plan_dedup = memory_db.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT 1 FROM raw_jobs WHERE company_name = 'test_co' AND job_title = 'dev' AND city = 'gz'"
    ).fetchall()
    plan_dedup_str = " ".join(str(row) for row in plan_dedup)
    assert "idx_raw_jobs_company_title_city" in plan_dedup_str
    assert "COVERING INDEX" in plan_dedup_str
    assert "SCAN raw_jobs')" not in plan_dedup_str

    # 5. Boss OR 查重：命中 MULTI-INDEX OR (主键索引 + 三要素索引)
    plan_boss = memory_db.execute(
        "EXPLAIN QUERY PLAN "
        "SELECT 1 FROM raw_jobs WHERE job_link = 'https://test.com' OR (company_name = 'test_co' AND job_title = 'dev' AND city = 'gz')"
    ).fetchall()
    plan_boss_str = " ".join(str(row) for row in plan_boss)
    assert "MULTI-INDEX OR" in plan_boss_str
    assert "SCAN raw_jobs')" not in plan_boss_str
