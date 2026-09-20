"""运行台账（run_snapshot）测试：刷新不丢的各平台真实抓取统计。"""
import sqlite3

from app.automation import run_snapshot as rs

PLATFORM_CN = {"boss": "BOSS直聘", "liepin": "猎聘", "51job": "51job", "zhilian": "智联招聘"}


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE raw_jobs (platform TEXT, job_title TEXT)")
    for i, platform in enumerate(rows):
        conn.execute("INSERT INTO raw_jobs (platform, job_title) VALUES (?, ?)", (platform, f"t{i}"))
    conn.commit()
    conn.close()


from pathlib import Path
from unittest.mock import patch

def test_snapshot_counts_since_start_rowid(tmp_path):
    db = str(tmp_path / "raw.db")
    # 先插 2 条「历史」数据（start_rowid 之前），再插本轮数据
    _make_db(db, ["BOSS直聘", "BOSS直聘"])
    conn = sqlite3.connect(db)
    start_rowid = conn.execute("SELECT MAX(rowid) FROM raw_jobs").fetchone()[0]
    conn.close()
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO raw_jobs VALUES ('BOSS直聘','x')")
    conn.execute("INSERT INTO raw_jobs VALUES ('猎聘','y')")
    conn.execute("INSERT INTO raw_jobs VALUES ('猎聘','z')")
    conn.commit()
    conn.close()

    with patch.object(rs, "_DB_PATH", Path(db)):
        rs.begin("pipeline_t1", start_rowid, {"boss": 20, "liepin": 20, "51job": 20}, ["zhilian"])
        snap = rs.compute(db, PLATFORM_CN)

        assert snap["running"] is True
        assert snap["task_id"] == "pipeline_t1"
        assert snap["disabled"] == ["zhilian"]
        by_key = {p["key"]: p for p in snap["platforms"]}
        assert by_key["boss"]["current"] == 1     # 只算本轮，不算历史
        assert by_key["boss"]["total"] == 20
        assert by_key["liepin"]["current"] == 2
        assert by_key["51job"]["current"] == 0    # 有预算无入库也要展示
        rs.end()
        snap2 = rs.compute(db, PLATFORM_CN)
        assert snap2["running"] is False
        # 结束后数字保留可查
        assert {p["key"]: p["current"] for p in snap2["platforms"]}["boss"] == 1
