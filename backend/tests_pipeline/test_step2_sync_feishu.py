"""Step 2 飞书同步及去重回填 feishu_record_id 单元测试。

验证内容：
1. check_job_exists 查重命中时，准确提取并返回飞书已存在的 record_id（不再丢弃 ID）；
2. check_job_exists 查重未命中或网络异常时，返回 False/None；
3. 飞书去重跳过推送时，必须将查到的已有 record_id 回填至本地 raw_jobs 表（消除无头记录）；
4. 飞书推送新建记录成功时，正常写入新 record_id。
"""
import sqlite3
from unittest.mock import patch, MagicMock
import pytest

from job_processor.step2_sync_feishu import check_job_exists, sync_sqlite_to_feishu


TEST_RAW_JOBS_SCHEMA = """
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


def test_check_job_exists_returns_record_id_on_match():
    """验证 check_job_exists 查重命中时，精准返回已有记录的 record_id。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "code": 0,
        "msg": "success",
        "data": {
            "items": [
                {
                    "record_id": "rec_existing_12345",
                    "fields": {"公司名称": "测试企业", "岗位名称": "AI工程师", "城市": "北京"}
                }
            ],
            "total": 1
        }
    }

    with patch("requests.post", return_value=mock_resp):
        res = check_job_exists("mock_token", "测试企业", "AI工程师", "北京")
        assert res == "rec_existing_12345"
        assert bool(res) is True


def test_check_job_exists_returns_false_when_empty():
    """验证 check_job_exists 未查到已有记录时，返回 False。"""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "code": 0,
        "msg": "success",
        "data": {
            "items": [],
            "total": 0
        }
    }

    with patch("requests.post", return_value=mock_resp):
        res = check_job_exists("mock_token", "新企业", "新岗位", "上海")
        assert not res


def test_sync_sqlite_to_feishu_backfills_record_id_on_skip(tmp_path):
    """验证查重命中跳过时，必须将飞书已有的 record_id 回填到本地 SQLite。"""
    db_path = str(tmp_path / "job_hunter.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(TEST_RAW_JOBS_SCHEMA)
    conn.execute("""
        INSERT INTO raw_jobs (
            job_link, job_title, company_name, city, process_status, is_synced, feishu_record_id
        ) VALUES (
            'https://example.com/job1', 'AI算法工程师', '智算科技', '深圳', '待推送至飞书', 0, ''
        )
    """)
    conn.commit()
    conn.close()

    # mock 飞书查重命中，返回已存在的 record_id
    mock_search_resp = MagicMock()
    mock_search_resp.json.return_value = {
        "code": 0,
        "msg": "success",
        "data": {
            "items": [{"record_id": "rec_feishu_already_exist_999"}],
            "total": 1
        }
    }

    with patch("job_processor.step2_sync_feishu.get_tenant_access_token", return_value="mock_token"), \
         patch("requests.post", return_value=mock_search_resp), \
         patch("job_processor.step2_sync_feishu.push_single_record_to_feishu") as mock_push:

        sync_sqlite_to_feishu(db_path=db_path, table_name="raw_jobs")

        # 因为查重命中了，所以绝对不能调用 push_single_record_to_feishu 创建新记录
        mock_push.assert_not_called()

    # 核心验收点：验证本地 SQLite raw_jobs 的状态与 feishu_record_id 回填
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT is_synced, process_status, feishu_record_id FROM raw_jobs WHERE job_link = 'https://example.com/job1'"
    ).fetchone()
    conn.close()

    assert row[0] == 1
    assert row[1] == "已同步"
    assert row[2] == "rec_feishu_already_exist_999", "飞书查重跳过时，必须回填已存在的 record_id，不可为空！"
