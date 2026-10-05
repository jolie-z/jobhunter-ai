"""51job 采集词级检查点 — 同词 24h 内不重抓（账号级节流的一半）。

落盘：data/job_hunter.db（与 raw_jobs 同库，复用 WAL 连接）。
DDL（plan §3.3-4，plan-review R2 PASS）：
    CREATE TABLE IF NOT EXISTS collect_progress_51job (
        combo_key   TEXT PRIMARY KEY,    -- f"{keyword}:{city_code}:{salary_code}"，None 记 "any"
        last_collected_at TEXT NOT NULL  -- "YYYY-MM-DD HH:MM:SS" 本地时间，与 raw_jobs.crawl_time 同口径
    );
"""
import datetime
import sqlite3

RECHECK_INTERVAL_SECS = 24 * 3600  # 同词 24h 内跳过


def _norm(v) -> str:
    """combo 分量规范化：空值统一记 'any'，防 None/'' 产生两条不同 key。"""
    s = (str(v).strip() if v is not None else "") or "any"
    return s


def combo_key(keyword, city_code, salary_code) -> str:
    """构造规范 combo key：keyword:city_code:salary_code（三个分量都必出现）。"""
    return f"{_norm(keyword)}:{_norm(city_code)}:{_norm(salary_code)}"


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collect_progress_51job (
            combo_key   TEXT PRIMARY KEY,
            last_collected_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cp51_time ON collect_progress_51job(last_collected_at)")
    conn.commit()


def get_last_collected(conn: sqlite3.Connection, key: str) -> str | None:
    """返回该词上次采集时间字符串；无记录返回 None。表缺失按 None（不阻断）。"""
    try:
        row = conn.execute(
            "SELECT last_collected_at FROM collect_progress_51job WHERE combo_key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        ensure_table(conn)
        return None


def should_skip(conn: sqlite3.Connection, key: str, interval_secs: int = RECHECK_INTERVAL_SECS) -> bool:
    """同词 24h 内已采过 → True（跳过，避免重复高频抓同一个词）。"""
    last = get_last_collected(conn, key)
    if not last:
        return False
    try:
        last_dt = datetime.datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return (datetime.datetime.now() - last_dt).total_seconds() < interval_secs


def mark_collected(conn: sqlite3.Connection, key: str) -> None:
    """标记该词已完成采集（词级检查点）。幂等 upsert。"""
    ensure_table(conn)
    conn.execute(
        "INSERT INTO collect_progress_51job (combo_key, last_collected_at) VALUES (?, ?) "
        "ON CONFLICT(combo_key) DO UPDATE SET last_collected_at = excluded.last_collected_at",
        (key, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
