"""
全链路指挥中心 — 平台抓取配置存储

单例模式：pipeline_scrape_config 表只有一行（id=1），
存储关键词队列、平台选择、全局城市/薪资等用户意图配置。
与 scrape_sessions（续抓页码）互补，不重叠。
"""

import json
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger("pipeline_config")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "job_hunter.db"
)

_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_scrape_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    keywords TEXT NOT NULL DEFAULT '[]',
    platforms TEXT NOT NULL DEFAULT '{}',
    default_city TEXT NOT NULL DEFAULT '',
    default_salary TEXT NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pipeline_keyword_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    city TEXT NOT NULL DEFAULT '',
    salary TEXT NOT NULL DEFAULT '',
    jobs_added INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'auto',
    pipeline_task_id TEXT NOT NULL DEFAULT '',
    used_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_initialized = False


def _ensure_table():
    global _initialized
    if _initialized:
        return
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL)
    conn.commit()
    conn.close()
    _initialized = True


def get_scrape_config() -> dict:
    """读取抓取配置，无记录时返回默认结构。"""
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM pipeline_scrape_config WHERE id = 1").fetchone()
    conn.close()

    if not row:
        return {
            "keywords": [],
            "platforms": {},
            "default_city": "",
            "default_salary": "",
            "updated_at": None,
        }

    return {
        "keywords": json.loads(row["keywords"] or "[]"),
        "platforms": json.loads(row["platforms"] or "{}"),
        "default_city": row["default_city"] or "",
        "default_salary": row["default_salary"] or "",
        "updated_at": row["updated_at"],
    }


def save_scrape_config(
    keywords: list,
    platforms: dict,
    default_city: str = "",
    default_salary: str = "",
) -> dict:
    """保存（UPSERT）抓取配置，返回保存后的完整数据。"""
    _ensure_table()
    # 强制每个平台的抓取上限硬性 clamp 到最大 50（保护爬虫稳定性与防风控）
    if isinstance(platforms, dict):
        for _plat, conf in platforms.items():
            if isinstance(conf, dict) and "limit" in conf:
                try:
                    conf["limit"] = min(max(int(conf.get("limit") or 0), 0), 50)
                except (ValueError, TypeError):
                    conf["limit"] = 20
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO pipeline_scrape_config (id, keywords, platforms, default_city, default_salary, updated_at)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            keywords = excluded.keywords,
            platforms = excluded.platforms,
            default_city = excluded.default_city,
            default_salary = excluded.default_salary,
            updated_at = excluded.updated_at
        """,
        (
            json.dumps(keywords, ensure_ascii=False),
            json.dumps(platforms, ensure_ascii=False),
            default_city,
            default_salary,
            now,
        ),
    )
    conn.commit()
    conn.close()
    logger.info(f"[pipeline_config] 抓取配置已保存: {len(keywords)} 关键词, {len(platforms)} 平台")
    return get_scrape_config()


# ─── 条件队列历史记录 ───

def add_keyword_history(
    keyword: str,
    city: str = "",
    salary: str = "",
    jobs_added: int = 0,
    source: str = "auto",
    pipeline_task_id: str = "",
) -> int:
    """写入一条历史记录。source: auto=链路执行自动记录, archive=手动归档。返回新记录 id。"""
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        """
        INSERT INTO pipeline_keyword_history (keyword, city, salary, jobs_added, source, pipeline_task_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (keyword.strip(), city or "", salary or "", int(jobs_added or 0), source, pipeline_task_id or ""),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def list_keyword_history(limit: int = 200) -> list:
    """按时间倒序返回历史记录。"""
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM pipeline_keyword_history ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_keyword_history(history_id: int) -> bool:
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM pipeline_keyword_history WHERE id = ?", (int(history_id),))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def find_keyword_history(keyword: str) -> list:
    """按关键词（忽略大小写/首尾空格）查历史记录，供添加时重复提醒。"""
    _ensure_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM pipeline_keyword_history WHERE TRIM(keyword) = ? COLLATE NOCASE ORDER BY id DESC",
        (keyword.strip(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
