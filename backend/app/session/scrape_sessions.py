"""
scrape_sessions 表 — 记录每个 (keyword, city, salary, platform) 组合的上次抓取页码，
实现同条件续抓。存放在 data/job_hunter.db 中。

2026-08-10 起同时承担「条件×平台」抓取进度台账（抓尽制模型）：
- predicted_total : 分母 = 该条件在该平台搜索出的岗位总数（预测值，每次搜索校准）
- scraped_count   : 分子 = 该条件在该平台实际入库数（跨任务累积）
- 分子追平分母 → 该条件在该平台视为抓尽，编排器切下一条件
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "job_hunter.db")


def init_scrape_sessions_table():
    """幂等建表，在 FastAPI 启动时调用"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scrape_sessions (
                keyword     TEXT    NOT NULL,
                city        TEXT    NOT NULL DEFAULT '',
                salary      TEXT    NOT NULL DEFAULT '',
                platform    TEXT    NOT NULL,
                last_page   INTEGER NOT NULL DEFAULT 1,
                last_run    TEXT,
                PRIMARY KEY (keyword, city, salary, platform)
            )
        """)
        # 条件进度台账列（存量库幂等迁移）
        for _col, ddl in [
            ("predicted_total", "ALTER TABLE scrape_sessions ADD COLUMN predicted_total INTEGER NOT NULL DEFAULT 0"),
            ("scraped_count", "ALTER TABLE scrape_sessions ADD COLUMN scraped_count INTEGER NOT NULL DEFAULT 0"),
            ("ttl_updated_at", "ALTER TABLE scrape_sessions ADD COLUMN ttl_updated_at TEXT DEFAULT ''"),
        ]:
            try:
                cursor.execute(ddl)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ 初始化 scrape_sessions 表失败: {e}")


def get_last_page(keyword: str, city: str, salary: str, platform: str) -> int:
    """查询同条件上次停在哪页，无记录返回 0（表示从第 1 页开始）"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_page FROM scrape_sessions WHERE keyword=? AND city=? AND salary=? AND platform=?",
            (keyword, city, salary, platform),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def update_last_page(keyword: str, city: str, salary: str, platform: str, last_page: int):
    """任务完成后回写实际抓到的最后一页"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO scrape_sessions (keyword, city, salary, platform, last_page, last_run)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(keyword, city, salary, platform)
               DO UPDATE SET last_page=excluded.last_page, last_run=excluded.last_run""",
            (keyword, city, salary, platform, last_page, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ 更新 scrape_sessions 失败: {e}")


def reset_session(keyword: str, city: str, salary: str, platform: str):
    """重置某个组合的续抓记录（用户想从头开始时调用）"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM scrape_sessions WHERE keyword=? AND city=? AND salary=? AND platform=?",
            (keyword, city, salary, platform),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─── 条件×平台 抓取进度台账（抓尽制模型） ───

def report_condition_round(
    keyword: str,
    city: str,
    salary: str,
    platform: str,
    inserted: int,
    predicted_total: int = None,
):
    """一轮抓取结束回写台账：分子累加本轮真实入库；拿到搜索总数时校准分母。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        if predicted_total is not None and int(predicted_total) > 0:
            cursor.execute(
                """INSERT INTO scrape_sessions
                   (keyword, city, salary, platform, last_page, last_run, predicted_total, scraped_count, ttl_updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                   ON CONFLICT(keyword, city, salary, platform) DO UPDATE SET
                     scraped_count = scraped_count + ?,
                     predicted_total = ?,
                     ttl_updated_at = ?,
                     last_run = excluded.last_run""",
                (keyword, city, salary, platform, now, int(predicted_total), max(0, int(inserted or 0)), now,
                 max(0, int(inserted or 0)), int(predicted_total), now),
            )
        else:
            cursor.execute(
                """INSERT INTO scrape_sessions
                   (keyword, city, salary, platform, last_page, last_run, predicted_total, scraped_count, ttl_updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, 0, ?, '')
                   ON CONFLICT(keyword, city, salary, platform) DO UPDATE SET
                     scraped_count = scraped_count + ?,
                     last_run = excluded.last_run""",
                (keyword, city, salary, platform, now, max(0, int(inserted or 0)),
                 max(0, int(inserted or 0))),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ 回写条件进度台账失败: {e}")


def get_condition_progress(keyword: str, city: str, salary: str, platform: str):
    """返回 (scraped_count, predicted_total)；无记录返回 (0, 0)。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT scraped_count, predicted_total FROM scrape_sessions WHERE keyword=? AND city=? AND salary=? AND platform=?",
            (keyword, city, salary, platform),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)
    except Exception:
        return 0, 0


def list_condition_progress():
    """返回全部条件进度行（供快照/前端展示）。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT keyword, city, salary, platform, scraped_count, predicted_total, ttl_updated_at, last_page FROM scrape_sessions"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def is_exhausted(scraped: int, predicted: int) -> bool:
    """分母已知且分子追平 → 抓尽。分母未知(0)时由编排器用「0新增=抓尽」兜底。"""
    return int(predicted or 0) > 0 and int(scraped or 0) >= int(predicted)
