# tests/test_db_bootstrap.py
"""主库统一建表引导 + goals/update 缺行自动建档（2026-09-22 新机装配排查批）。

全新克隆无 backend/data/job_hunter.db（gitignore 整目录）：
- 引导须在父目录缺失时也能建库，且幂等、绝不触碰已有表/数据；
- update_goals 无目标行时按默认值自动建档，保存接收群不再依赖先手动 /start。
"""
import sqlite3

from app.core.db_bootstrap import (
    _split_statements,
    ensure_main_db_schema,
    resolve_main_db_path,
)
from app.services import goal_service

EXPECTED_TABLES = {
    "custom_model_pricing", "evaluation_weights", "job_goals", "job_preferences",
    "job_strategies", "pipeline_keyword_history", "pipeline_latest_run",
    "pipeline_scrape_config", "raw_jobs", "scrape_sessions", "token_log", "xhs_raw_posts",
}
EXPECTED_TRIGGERS = {"trg_raw_jobs_insert_updated", "trg_raw_jobs_status_updated"}


def _object_names(db_path: str, types: tuple[str, ...]) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        marks = ",".join("?" * len(types))
        return {r[0] for r in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type IN ({marks})", types)}


def test_ensure_main_db_schema_fresh_creates_all(tmp_path):
    # 父目录也不存在，模拟全新克隆：验证 makedirs + 全量建表/触发器
    db_path = str(tmp_path / "sub" / "fresh.db")
    created = ensure_main_db_schema(db_path)

    assert EXPECTED_TABLES <= _object_names(db_path, ("table",))
    assert EXPECTED_TRIGGERS <= _object_names(db_path, ("trigger",))
    assert EXPECTED_TABLES <= set(created)


def test_ensure_main_db_schema_idempotent(tmp_path):
    db_path = str(tmp_path / "fresh.db")
    ensure_main_db_schema(db_path)
    # 第二遍不该再新建任何对象
    assert ensure_main_db_schema(db_path) == []


def test_ensure_main_db_schema_preserves_existing_table(tmp_path):
    # 已有表（哪怕列更少）原样保留，引导绝不替换/重建
    db_path = str(tmp_path / "old.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE token_log (id TEXT PRIMARY KEY, action_name TEXT NOT NULL)")
        conn.execute("INSERT INTO token_log VALUES ('t1', 'eval')")

    ensure_main_db_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM token_log").fetchone()[0] == 1
        cols = {r[1] for r in conn.execute("PRAGMA table_info(token_log)")}
        assert "cost_cny" not in cols  # 旧结构未被替换成蓝本新结构


def test_raw_jobs_trigger_maintains_updated_at(tmp_path):
    db_path = str(tmp_path / "fresh.db")
    ensure_main_db_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO raw_jobs (job_link, crawl_time) VALUES ('u1', '2026-09-22 10:00:00')")
        row = conn.execute("SELECT updated_at FROM raw_jobs WHERE job_link = 'u1'").fetchone()
        assert row[0] == "2026-09-22 10:00:00"


def test_update_goals_autocreates_row_when_missing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "goals.db")
    monkeypatch.setattr(goal_service, "DB_PATH", db_path)
    ensure_main_db_schema(db_path)  # 生产中启动引导先行，测试对齐同一起点

    result = goal_service.update_goals({"feishu_receive_id": "oc_test"})

    assert result is not None
    assert result["feishu_receive_id"] == "oc_test"
    assert result["status"] == "active"


def test_update_goals_partial_keeps_other_fields(tmp_path, monkeypatch):
    db_path = str(tmp_path / "goals.db")
    monkeypatch.setattr(goal_service, "DB_PATH", db_path)
    ensure_main_db_schema(db_path)

    goal_service.update_goals({"feishu_receive_id": "oc_a", "plan_days": 30})
    result = goal_service.update_goals({"plan_days": 90})

    assert result["plan_days"] == 90
    assert result["feishu_receive_id"] == "oc_a"  # 部分更新不重置其他字段


def test_split_statements_keeps_trigger_body_intact():
    # P1 回归守卫：触发器 BEGIN...END 体内的分号不得切碎语句
    script = (
        "CREATE TABLE t (a TEXT);\n"
        "CREATE TRIGGER trg AFTER INSERT ON t FOR EACH ROW\n"
        "BEGIN\n"
        "    UPDATE t SET a = datetime('now', 'localtime') WHERE rowid = NEW.rowid;\n"
        "END;\n"
    )
    stmts = _split_statements(script)
    assert len(stmts) == 2
    assert stmts[1].startswith("CREATE TRIGGER")
    assert stmts[1].rstrip().endswith("END;")


def test_resolve_main_db_path_analytics_override_wins(tmp_path, monkeypatch):
    # ANALYTICS_DB_PATH 是显式覆盖：文件不存在也采纳（QA 隔离栈先指路径后建库）
    missing = str(tmp_path / "not_yet.db")
    monkeypatch.setenv("ANALYTICS_DB_PATH", missing)
    monkeypatch.delenv("MAIN_PROJECT_DB", raising=False)
    assert resolve_main_db_path() == missing


def test_resolve_main_db_path_main_project_only_when_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("ANALYTICS_DB_PATH", raising=False)
    existing = tmp_path / "external.db"
    existing.write_text("")
    monkeypatch.setenv("MAIN_PROJECT_DB", str(existing))
    assert resolve_main_db_path() == str(existing)
    # 文件不存在则回落仓内默认
    monkeypatch.setenv("MAIN_PROJECT_DB", str(tmp_path / "ghost.db"))
    assert resolve_main_db_path() == goal_service.DB_PATH


def test_resolve_main_db_path_default_matches_goal_service(monkeypatch):
    # 单一真源：goal_service.DB_PATH 直接复用 resolve_main_db_path
    monkeypatch.delenv("ANALYTICS_DB_PATH", raising=False)
    monkeypatch.delenv("MAIN_PROJECT_DB", raising=False)
    assert resolve_main_db_path().endswith("backend/data/job_hunter.db")
    assert goal_service.DB_PATH == resolve_main_db_path()
