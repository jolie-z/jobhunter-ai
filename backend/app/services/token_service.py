import datetime
import logging
import os
import sqlite3
import uuid

logger = logging.getLogger("token_service")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "job_hunter.db")

_DDL = """
CREATE TABLE IF NOT EXISTS token_log (
    id TEXT PRIMARY KEY,
    action_name TEXT NOT NULL DEFAULT '',
    caller TEXT DEFAULT '',
    job_id TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    model_name TEXT DEFAULT '',
    cost_cny REAL DEFAULT 0,
    estimated INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_token_log_created ON token_log(created_at);
CREATE INDEX IF NOT EXISTS idx_token_log_action ON token_log(action_name);
CREATE INDEX IF NOT EXISTS idx_token_log_model ON token_log(model_name);
"""

_db_initialized = False


def _ensure_db():
    """确保表和索引存在（幂等），首次调用时执行一次。"""
    global _db_initialized
    if _db_initialized:
        return
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_DDL)
        # 兼容旧表：如果表已存在但缺少新列，用 ALTER TABLE 补上
        _migrate_if_needed(conn)
        conn.commit()
        conn.close()
        _db_initialized = True
    except Exception as e:
        logger.warning(f"[token_service] DDL 初始化失败（不影响主流程）: {e}")


def _migrate_if_needed(conn: sqlite3.Connection):
    """旧表可能缺少 caller / cost_cny / estimated 列，逐一补齐。"""
    cursor = conn.execute("PRAGMA table_info(token_log)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    migrations = [
        ("caller", "ALTER TABLE token_log ADD COLUMN caller TEXT DEFAULT ''"),
        ("cost_cny", "ALTER TABLE token_log ADD COLUMN cost_cny REAL DEFAULT 0"),
        ("estimated", "ALTER TABLE token_log ADD COLUMN estimated INTEGER DEFAULT 0"),
        ("cached_tokens", "ALTER TABLE token_log ADD COLUMN cached_tokens INTEGER DEFAULT 0"),
    ]
    for col_name, ddl in migrations:
        if col_name not in existing_cols:
            try:
                conn.execute(ddl)
            except Exception:
                pass  # 列已存在或其他原因，忽略


def _cleanup_old_records(conn: sqlite3.Connection, keep: int = 50):
    """写路径轮转：仅保留最新 keep 条 token_log 记录，防止无界增长（沿用 v1 时代的 50 条上限约定）。"""
    try:
        conn.execute("""
            DELETE FROM token_log WHERE id NOT IN (
                SELECT id FROM token_log ORDER BY created_at DESC LIMIT ?
            )
        """, (keep,))
    except Exception as e:
        logger.warning(f"[token_service] token_log 轮转清理失败（不影响本次写入）: {e}")


def log_token_usage(
    action_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model_name: str,
    job_id: str = None,
    caller: str = "",
    cost_cny: float = 0.0,
    estimated: int = 0,
    cached_tokens: int = 0,
):
    """写入一条 token 消耗记录。静默吞异常，绝不影响主流程。"""
    try:
        _ensure_db()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        log_id = str(uuid.uuid4())
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO token_log
                (id, action_name, caller, job_id, prompt_tokens, completion_tokens,
                 total_tokens, cached_tokens, model_name, cost_cny, estimated, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, action_name, caller, job_id, prompt_tokens, completion_tokens,
             total_tokens, cached_tokens or 0, model_name, cost_cny, estimated, created_at)
        )
        _cleanup_old_records(conn)

        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[token_service] 写 token_log 失败: {e}")


def recalculate_historical_costs(
    target_model: str | None = None,
    db_path: str = DB_PATH,
) -> dict:
    """
    根据当前计价规则重新核算历史 token_log 的成本（CNY）与预估标记。
    支持 target_model 过滤（与计价引擎保持一致的前缀/等值匹配），仅重算目标模型相关的历史记录，绝不污染其他模型。
    """
    from app.core.model_pricing import calc_cost_detailed
    _ensure_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT id, model_name, prompt_tokens, completion_tokens, cached_tokens, cost_cny, estimated FROM token_log"
    ).fetchall()

    updated_count = 0
    total_old_cost = 0.0
    total_new_cost = 0.0

    target = (target_model or "").lower().strip()

    for r in rows:
        row_model = (r["model_name"] or "").lower().strip()
        # 若指定了 target_model，仅重算匹配的模型（跳过空模型名，并与 get_custom_pricing 前缀规则保持同向）
        if target:
            if not row_model:
                continue
            is_match = (row_model == target) or row_model.startswith(target)
            if not is_match:
                continue

        old_cost = float(r["cost_cny"] or 0.0)
        new_cost, is_est = calc_cost_detailed(
            model_name=r["model_name"] or "",
            prompt_tokens=int(r["prompt_tokens"] or 0),
            completion_tokens=int(r["completion_tokens"] or 0),
            cached_tokens=int(r["cached_tokens"] or 0),
        )
        total_old_cost += old_cost
        total_new_cost += new_cost
        # 重算后 estimated 标记代表价格是否处于预估态（0=按用户/官方单价精准核算，1=按MiMo预估兜底）
        est_val = 1 if is_est else 0
        cursor.execute(
            "UPDATE token_log SET cost_cny = ?, estimated = ? WHERE id = ?",
            (new_cost, est_val, r["id"]),
        )
        updated_count += 1

    conn.commit()
    conn.close()
    logger.info(
        f"[token_service] 历史数据成本重算完成 (target_model={target_model or 'ALL'}): 更新 {updated_count} 条记录, "
        f"该批次总成本由 ¥{total_old_cost:.4f} 修正为 ¥{total_new_cost:.4f}"
    )
    return {
        "target_model": target_model,
        "updated_count": updated_count,
        "old_total_cost": round(total_old_cost, 4),
        "new_total_cost": round(total_new_cost, 4),
    }
