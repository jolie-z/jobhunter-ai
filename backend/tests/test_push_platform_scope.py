"""推送引擎平台范围 + 限量 scoping 测试（2026-09-28 /agent 推送范围批）。

真实引擎级测试：临时 SQLite 造数（多平台 × 待推送），直接调
sync_sqlite_to_feishu(target_links=, platform=, limit=)。
飞书 HTTP 全量 mock（查重 search 返回不存在 → 写入 records 返回成功），
断言写入集合严格圈在参数范围内、is_synced 回写正确。
"""
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from job_processor import step2_sync_feishu

RAW_COLS = (
    "job_link TEXT PRIMARY KEY, platform TEXT, job_title TEXT, company_name TEXT, "
    "city TEXT, jd_text TEXT, salary TEXT, work_address TEXT, publish_date TEXT, "
    "process_status TEXT, is_synced INTEGER DEFAULT 0, feishu_record_id TEXT DEFAULT ''"
)


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE raw_jobs ({RAW_COLS})")
    # 四平台各若干条「待推送」岗位
    for plat, n in (("智联招聘", 4), ("BOSS直聘", 3), ("51job", 2), ("猎聘", 1)):
        for i in range(n):
            conn.execute(
                "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, city, jd_text, process_status) "
                "VALUES (?, ?, ?, ?, ?, ?, '待推送至飞书')",
                (f"{plat}-link-{i}", plat, f"{plat}岗{i}", "测试公司", "广州", "职责描述"),
            )
    conn.commit()
    conn.close()


def _fake_requests_post(url, **kwargs):
    """查重接口返回「不存在」；写入接口返回成功 record_id。"""
    resp = MagicMock()
    if "records/search" in url:
        resp.json.return_value = {"code": 0, "data": {"items": []}}
    else:
        resp.json.return_value = {"code": 0, "data": {"record": {"record_id": "rec_new"}}}
    return resp


@pytest.fixture
def push_db(tmp_path):
    db = tmp_path / "push.db"
    _make_db(db)
    return str(db)


def _push(db_path, **kwargs):
    with patch.object(step2_sync_feishu, "get_tenant_access_token", return_value="tok"), \
         patch.object(step2_sync_feishu.requests, "post", side_effect=_fake_requests_post):
        return step2_sync_feishu.sync_sqlite_to_feishu(db_path, "raw_jobs", None, **kwargs)


def _pushed_links(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT job_link FROM raw_jobs WHERE is_synced = 1"
    ).fetchall()
    conn.close()
    return sorted(r[0] for r in rows)


def test_platform_filter_pushes_only_target_platform(push_db):
    """platform 过滤：仅智联 4 条被推送，其他平台原地不动。"""
    _push(push_db, platform="智联招聘")
    assert len(_pushed_links(push_db)) == 4
    assert _pushed_links(push_db) == [f"智联招聘-link-{i}" for i in range(4)]


def test_platform_none_pushes_all_regression(push_db):
    """回归：不传 platform 保持既有全量行为，10 条全推。"""
    _push(push_db)
    assert len(_pushed_links(push_db)) == 10


def test_target_links_precise_push(push_db):
    """target_links 精准：只推指定链接。"""
    _push(push_db, target_links=["智联招聘-link-1", "51job-link-0"])
    assert _pushed_links(push_db) == ["51job-link-0", "智联招聘-link-1"]


def test_target_links_with_platform_narrows(push_db):
    """叠加：target_links 圈选后 platform 收窄（交集生效）。"""
    _push(push_db, target_links=["智联招聘-link-1", "51job-link-0"], platform="智联招聘")
    assert _pushed_links(push_db) == ["智联招聘-link-1"]


def test_platform_with_limit(push_db):
    """platform + limit：平台过滤后限量截断（rowid 倒序取最新 N 条）。"""
    _push(push_db, platform="智联招聘", limit=2)
    assert set(_pushed_links(push_db)) <= {f"智联招聘-link-{i}" for i in range(4)}
    assert len(_pushed_links(push_db)) == 2


def test_empty_target_links_returns_noop(push_db):
    """引擎既有语义保留：target_links 空列表 = 直接返回（本轮无通过岗位）。"""
    pushed = _push(push_db, target_links=[])
    assert pushed == []  # 引擎返回空列表
    assert _pushed_links(push_db) == []
