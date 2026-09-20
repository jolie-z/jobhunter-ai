"""db_backup 测试：每日滚动热备。"""
import sqlite3

from app.automation import db_backup


def _make_source(path, table="t1"):
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute(f"INSERT INTO {table} (v) VALUES ('hello')")
    conn.commit()
    conn.close()


def test_backup_creates_verifiable_snapshot(tmp_path):
    src = tmp_path / "src" / "job_hunter.db"
    src.parent.mkdir(parents=True)
    _make_source(src)
    bdir = tmp_path / "backups"

    outcome = db_backup.run_daily_backup(
        targets=[(src, "job_hunter")], backup_dir=bdir, retention=7
    )

    assert outcome["ok"] == 1
    # 直接校验快照可独立打开且数据完整
    conn = sqlite3.connect(str(list(bdir.glob("job_hunter_*.db"))[0]))
    assert conn.execute("SELECT v FROM t1").fetchone()[0] == "hello"
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    conn.close()


def test_backup_missing_source_isolated(tmp_path):
    """源库不存在时优雅跳过，不拖垮同轮其他库。"""
    good = tmp_path / "good.db"
    _make_source(good)
    bdir = tmp_path / "backups"

    outcome = db_backup.run_daily_backup(
        targets=[(tmp_path / "nope.db", "ghost"), (good, "good")],
        backup_dir=bdir,
        retention=7,
    )

    assert [r["status"] for r in outcome["results"]] == ["skipped", "ok"]
    assert outcome["ok"] == 1


def test_retention_prunes_old_snapshots(tmp_path):
    src = tmp_path / "src.db"
    _make_source(src)
    bdir = tmp_path / "backups"
    bdir.mkdir()
    # 预置 8 份历史快照（时间戳单调递增命名）
    for i in range(8):
        (bdir / f"keep_{i:08d}_1200.db").write_bytes(b"x")

    outcome = db_backup.run_daily_backup(
        targets=[(src, "keep")], backup_dir=bdir, retention=7
    )

    assert outcome["ok"] == 1
    assert outcome["results"][0]["pruned"] >= 1
    remaining = list(bdir.glob("keep_*.db"))
    assert len(remaining) == 7  # 8 旧 + 1 新，保留最近 7 份
    assert any("0000000" not in p.name for p in remaining)  # 最旧的被清


def test_rerun_same_minute_overwrites(tmp_path):
    """同分钟重跑不报错（VACUUM INTO 目标冲突时先删旧产物）。"""
    src = tmp_path / "src.db"
    _make_source(src)
    bdir = tmp_path / "backups"
    targets = [(src, "rerun")]

    first = db_backup.run_daily_backup(targets=targets, backup_dir=bdir)
    second = db_backup.run_daily_backup(targets=targets, backup_dir=bdir)

    assert first["ok"] == 1 and second["ok"] == 1
