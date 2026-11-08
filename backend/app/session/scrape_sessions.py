"""
scrape_sessions 表 — 记录每个 (keyword, city, salary, platform) 组合的上次抓取页码，
实现同条件续抓。存放在 data/job_hunter.db 中。

2026-08-10 起同时承担「条件×平台」抓取进度台账（抓尽制模型）：
- predicted_total : 分母 = 该条件在该平台搜索出的岗位总数（预测值，每次搜索校准）
- scraped_count   : 分子 = 该条件在该平台实际入库数（跨任务累积）
- exhausted_at    : 抓尽时间；非空且未过 TTL 时，编排器跳过该条件
- no_new_rounds   : 连续「成功但 0 新增」轮数；达到阈值兜底判抓尽

抓尽判定（2026-10-30 重构）不再只看 scraped>=predicted：
- 采集器明确回报「已到平台底部」→ 立即抓尽（最可靠）
- 连续 N 轮成功但 0 新增 → 兜底抓尽（覆盖没有分母的平台）
- 抓尽后 TTL 到期自动重新打开，允许发现新岗位
"""
import os
import sqlite3
from datetime import datetime

from app.core.db_paths import job_hunter_db_path

DB_PATH = job_hunter_db_path(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "job_hunter.db"))

# 抓尽后多久自动重新打开（秒）；默认 7 天，可用环境变量覆盖
EXHAUSTION_TTL_SECONDS = int(os.getenv("JOBHUNTER_CONDITION_TTL_SECONDS", str(7 * 24 * 3600)))
# 连续多少轮「成功但 0 新增」兜底判抓尽；默认 3 轮
NO_NEW_EXHAUST_ROUNDS = max(1, int(os.getenv("JOBHUNTER_CONDITION_NO_NEW_ROUNDS", "3")))

_EMPTY_STATE = {
    "scraped": 0,
    "predicted": 0,
    "last_page": 0,
    "last_run": "",
    "exhausted_at": "",
    "no_new_rounds": 0,
    "exhausted": False,
}


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
            ("exhausted_at", "ALTER TABLE scrape_sessions ADD COLUMN exhausted_at TEXT DEFAULT ''"),
            ("no_new_rounds", "ALTER TABLE scrape_sessions ADD COLUMN no_new_rounds INTEGER NOT NULL DEFAULT 0"),
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
    """任务完成后回写实际抓到的最后一页；0 表示已到平台底部，下次从第 1 页重新开始"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO scrape_sessions (keyword, city, salary, platform, last_page, last_run)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(keyword, city, salary, platform)
               DO UPDATE SET last_page=excluded.last_page, last_run=excluded.last_run""",
            (keyword, city, salary, platform, max(0, int(last_page or 0)), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ 更新 scrape_sessions 失败: {e}")


def reset_session(keyword: str, city: str, salary: str, platform: str):
    """重置某个组合的续抓记录与抓尽状态（用户想从头开始时调用）"""
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
    *,
    hit_bottom: bool = False,
    success: bool = True,
):
    """一轮抓取结束回写台账。

    - 分子累加本轮真实新增入库；拿到搜索总数时校准分母。
    - hit_bottom=True：采集器明确到达平台底部 → 立即标记抓尽。
    - success=False（引擎崩溃/用户急停）：只更新时间，不推进「连续 0 新增」计数，
      避免把故障轮误判成抓尽。
    - 成功且有新增：清空抓尽状态，重新打开条件。
    - 成功但连续 0 新增达到阈值：兜底标记抓尽。
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        inserted = max(0, int(inserted or 0))
        predicted = int(predicted_total or 0)

        # 2026-10-31：hit_bottom 不能无条件等于“抓尽”。陈旧游标/页面加载失败都可能
        # 触发底部信号；若累计进度远低于预测分母（<80%），先按“连续 0 新增”兜底，
        # 不写 exhausted_at（避免条件被 7 天静默跳过）。真抓尽会在 scraped 追平分母
        # 或连续 NO_NEW_EXHAUST_ROUNDS 轮后落账。
        prior_scraped = 0
        prior_predicted = 0
        prior = cursor.execute(
            "SELECT scraped_count, predicted_total FROM scrape_sessions "
            "WHERE keyword=? AND city=? AND salary=? AND platform=?",
            (keyword, city, salary, platform),
        ).fetchone()
        if prior:
            prior_scraped = int(prior[0] or 0)
            prior_predicted = int(prior[1] or 0)
        effective_predicted = predicted or prior_predicted
        if hit_bottom and effective_predicted > 0 and (prior_scraped + inserted) < effective_predicted * 0.8:
            print(
                f"⚠️ [台账] {platform} hit_bottom 但进度 "
                f"{prior_scraped + inserted}/{effective_predicted} 不足 80%，"
                f"暂不标记抓尽（按连续 0 新增兜底）"
            )
            hit_bottom = False

        if predicted > 0:
            cursor.execute(
                """INSERT INTO scrape_sessions
                   (keyword, city, salary, platform, last_page, last_run, predicted_total, scraped_count,
                    ttl_updated_at, exhausted_at, no_new_rounds)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, '', 0)
                   ON CONFLICT(keyword, city, salary, platform) DO UPDATE SET
                     scraped_count = scraped_count + ?,
                     predicted_total = ?,
                     ttl_updated_at = ?,
                     last_run = excluded.last_run""",
                (keyword, city, salary, platform, now, predicted, inserted, now,
                 inserted, predicted, now),
            )
        else:
            cursor.execute(
                """INSERT INTO scrape_sessions
                   (keyword, city, salary, platform, last_page, last_run, predicted_total, scraped_count,
                    ttl_updated_at, exhausted_at, no_new_rounds)
                   VALUES (?, ?, ?, ?, 1, ?, 0, ?, '', '', 0)
                   ON CONFLICT(keyword, city, salary, platform) DO UPDATE SET
                     scraped_count = scraped_count + ?,
                     last_run = excluded.last_run""",
                (keyword, city, salary, platform, now, inserted, inserted),
            )

        # 抓尽状态机：失败轮不推进；成功轮按「底部 / 有新增 / 连续0新增 / 分子追平分母」更新
        cursor.execute(
            """UPDATE scrape_sessions SET
                 no_new_rounds = CASE
                   WHEN ? = 0 THEN no_new_rounds
                   WHEN ? <= 0 THEN no_new_rounds + 1
                   ELSE 0 END,
                 exhausted_at = CASE
                   WHEN ? = 0 THEN exhausted_at
                   WHEN ? = 1 THEN ?
                   WHEN ? > 0 THEN ''
                   WHEN no_new_rounds + 1 >= ? THEN ?
                   WHEN predicted_total > 0 AND scraped_count >= predicted_total THEN ?
                   ELSE exhausted_at END
               WHERE keyword=? AND city=? AND salary=? AND platform=?""",
            (
                1 if success else 0, inserted,
                1 if success else 0, 1 if hit_bottom else 0, now,
                inserted,
                NO_NEW_EXHAUST_ROUNDS, now,
                now,
                keyword, city, salary, platform,
            ),
        )
        conn.commit()
    except Exception as e:
        print(f"⚠️ 回写条件进度台账失败: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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


def _parse_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _exhaustion_expired(exhausted_at: str, now: datetime | None = None) -> bool:
    """抓尽时间是否已过 TTL。脏数据按已过期处理，避免永久冻结。"""
    dt = _parse_iso(exhausted_at)
    if dt is None:
        return True
    return ((now or datetime.now()) - dt).total_seconds() >= EXHAUSTION_TTL_SECONDS


def _row_is_exhausted(row: dict, now: datetime | None = None) -> bool:
    exhausted_at = (row.get("exhausted_at") or "").strip()
    if not exhausted_at:
        return False
    return not _exhaustion_expired(exhausted_at, now)


def clear_exhaustion(keyword: str, city: str, salary: str, platform: str):
    """清空抓尽状态并重置续抓页码（TTL 到期重新打开时调用）。

    抓尽期间平台可能新增了岗位，重新打开必须从第 1 页开始才能发现；
    否则会从已经越过的末页继续抓空页。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE scrape_sessions SET exhausted_at='', no_new_rounds=0, last_page=0 "
            "WHERE keyword=? AND city=? AND salary=? AND platform=?",
            (keyword, city, salary, platform),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_condition_state(keyword: str, city: str, salary: str, platform: str) -> dict:
    """返回单条件×平台的完整状态（进度 + 抓尽 + 续抓页码）。

    TTL 到期的抓尽状态会在这里惰性清空，编排器下一轮即可重新尝试。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT scraped_count, predicted_total, last_page, last_run, exhausted_at, no_new_rounds "
            "FROM scrape_sessions WHERE keyword=? AND city=? AND salary=? AND platform=?",
            (keyword, city, salary, platform),
        ).fetchone()
        conn.close()
        if not row:
            return dict(_EMPTY_STATE)
        state = {
            "scraped": int(row["scraped_count"] or 0),
            "predicted": int(row["predicted_total"] or 0),
            "last_page": int(row["last_page"] or 0),
            "last_run": row["last_run"] or "",
            "exhausted_at": (row["exhausted_at"] or "").strip(),
            "no_new_rounds": int(row["no_new_rounds"] or 0),
        }
        if state["exhausted_at"] and _exhaustion_expired(state["exhausted_at"]):
            clear_exhaustion(keyword, city, salary, platform)
            state["exhausted_at"] = ""
            state["no_new_rounds"] = 0
            state["last_page"] = 0
        state["exhausted"] = bool(state["exhausted_at"])
        return state
    except Exception:
        return dict(_EMPTY_STATE)


def is_condition_exhausted(keyword: str, city: str, salary: str, platform: str) -> bool:
    """该条件×平台是否处于抓尽状态（含 TTL 自动重开）。"""
    return bool(get_condition_state(keyword, city, salary, platform).get("exhausted"))


def list_condition_progress():
    """返回全部条件进度行（供快照/前端展示），附带 exhausted 布尔值。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT keyword, city, salary, platform, scraped_count, predicted_total, "
            "ttl_updated_at, last_page, last_run, exhausted_at, no_new_rounds FROM scrape_sessions"
        ).fetchall()
        conn.close()
        now = datetime.now()
        out = []
        for r in rows:
            item = dict(r)
            item["exhausted"] = _row_is_exhausted(item, now)
            out.append(item)
        return out
    except Exception:
        return []


def is_exhausted(scraped: int, predicted: int) -> bool:
    """旧口径（仅看分子分母），保留给历史调用/测试；编排器已改用 is_condition_exhausted。"""
    return int(predicted or 0) > 0 and int(scraped or 0) >= int(predicted)
