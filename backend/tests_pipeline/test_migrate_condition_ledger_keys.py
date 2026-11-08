"""迁移脚本回归测试：merge / create / 幂等 / dry-run / 非配置行不动。

迁移脚本是本次唯一会改生产数据的组件，单独用临时库直测。
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_migration_module():
    path = BACKEND_DIR / "scripts" / "migrate_condition_ledger_keys.py"
    spec = importlib.util.spec_from_file_location("migrate_condition_ledger_keys", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(tmp_path):
    db = tmp_path / "ledger.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
    CREATE TABLE pipeline_scrape_config (
        id INTEGER PRIMARY KEY DEFAULT 1,
        keywords TEXT NOT NULL DEFAULT '[]',
        platforms TEXT NOT NULL DEFAULT '{}',
        default_city TEXT NOT NULL DEFAULT '',
        default_salary TEXT NOT NULL DEFAULT '',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE scrape_sessions (
        keyword TEXT NOT NULL,
        city TEXT NOT NULL DEFAULT '',
        salary TEXT NOT NULL DEFAULT '',
        platform TEXT NOT NULL,
        last_page INTEGER NOT NULL DEFAULT 1,
        last_run TEXT,
        predicted_total INTEGER NOT NULL DEFAULT 0,
        scraped_count INTEGER NOT NULL DEFAULT 0,
        ttl_updated_at TEXT DEFAULT '',
        exhausted_at TEXT DEFAULT '',
        no_new_rounds INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (keyword, city, salary, platform)
    );
    """)
    conn.execute(
        "INSERT INTO pipeline_scrape_config "
        "(id, keywords, platforms, default_city, default_salary) "
        "VALUES (1, ?, '{}', '广州', '15-20K')",
        (json.dumps([{"keyword": "AI产品经理", "city": "广州", "salary": "15-20K"}],
                    ensure_ascii=False),),
    )
    # 标准行（真实页码 38，分子 0）+ 平台映射行（分子 194）
    conn.execute(
        "INSERT INTO scrape_sessions "
        "(keyword, city, salary, platform, last_page, predicted_total, scraped_count) "
        "VALUES ('AI产品经理','广州','15-20K','zhilian',38,0,0)"
    )
    conn.execute(
        "INSERT INTO scrape_sessions "
        "(keyword, city, salary, platform, last_page, predicted_total, scraped_count) "
        "VALUES ('AI产品经理','广州','15K-25K','zhilian',1,0,194)"
    )
    # 不在当前配置里的历史条件：迁移不应触碰
    conn.execute(
        "INSERT INTO scrape_sessions "
        "(keyword, city, salary, platform, last_page, predicted_total, scraped_count) "
        "VALUES ('旧条件','广州','15K-25K','zhilian',2,0,9)"
    )
    conn.commit()
    conn.close()
    return db


def _rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = {(r["keyword"], r["salary"]): dict(r) for r in conn.execute("SELECT * FROM scrape_sessions")}
    conn.close()
    return rows


def _run_main(mod, db, monkeypatch, dry_run=False):
    argv = ["migrate_condition_ledger_keys.py", "--db", str(db)]
    if dry_run:
        argv.append("--dry-run")
    else:
        argv.append("--force")
    monkeypatch.setattr(sys, "argv", argv)
    return mod.main()


def test_requires_force_without_dry_run(tmp_path, monkeypatch):
    """实际迁移必须先停服并显式 --force，避免后端运行时并发覆盖。"""
    mod = _load_migration_module()
    db = _make_db(tmp_path)

    monkeypatch.setattr(sys, "argv", ["migrate_condition_ledger_keys.py", "--db", str(db)])
    assert mod.main() == 3
    # 没有 --force 时不得动库
    assert ("AI产品经理", "15K-25K") in _rows(db)


def test_merge_standard_and_native_rows(tmp_path, monkeypatch):
    mod = _load_migration_module()
    db = _make_db(tmp_path)

    assert _run_main(mod, db, monkeypatch) == 0
    rows = _rows(db)

    assert ("AI产品经理", "15K-25K") not in rows
    merged = rows[("AI产品经理", "15-20K")]
    assert merged["scraped_count"] == 194
    assert merged["last_page"] == 38
    assert rows[("旧条件", "15K-25K")]["scraped_count"] == 9

    # 幂等：再跑一次不重复累加
    assert _run_main(mod, db, monkeypatch) == 0
    assert _rows(db)[("AI产品经理", "15-20K")]["scraped_count"] == 194


def test_create_standard_row_when_missing(tmp_path, monkeypatch):
    mod = _load_migration_module()
    db = _make_db(tmp_path)

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE pipeline_scrape_config SET keywords=? WHERE id=1",
        (json.dumps([{"keyword": "AI智能", "city": "广州", "salary": "15-20K"}],
                    ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO scrape_sessions "
        "(keyword, city, salary, platform, last_page, predicted_total, scraped_count) "
        "VALUES ('AI智能','广州','15K-25K','zhilian',3,20,10)"
    )
    conn.commit()
    conn.close()

    assert _run_main(mod, db, monkeypatch) == 0
    created = _rows(db)[("AI智能", "15-20K")]
    assert created["scraped_count"] == 10
    assert created["predicted_total"] == 20
    assert created["last_page"] == 0  # 映射行页码不可信，强制从第 1 页重扫
    assert ("AI智能", "15K-25K") not in _rows(db)


def test_dry_run_does_not_write(tmp_path, monkeypatch):
    mod = _load_migration_module()
    db = _make_db(tmp_path)
    before = _rows(db)

    assert _run_main(mod, db, monkeypatch, dry_run=True) == 0
    assert _rows(db) == before


def test_no_config_is_noop(tmp_path, monkeypatch):
    mod = _load_migration_module()
    db = _make_db(tmp_path)

    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM pipeline_scrape_config")
    conn.commit()
    conn.close()

    assert _run_main(mod, db, monkeypatch) == 0
    assert ("AI产品经理", "15K-25K") in _rows(db)
