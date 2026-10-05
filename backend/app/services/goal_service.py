# app/services/goal_service.py
"""
求职目标管理服务 - SQLite 单行配置表 job_goals。
提供目标 CRUD + 实时进度计算。
"""
import sqlite3
from datetime import date, datetime
from typing import Any

from app.core.db_bootstrap import resolve_main_db_path

# 主项目 live DB：路径解析唯一真源在 app/core/db_bootstrap.resolve_main_db_path，
# 本常量只是 import 时冻结的一份快照（与历史行为一致：环境变量在 import 时读取）
DB_PATH = resolve_main_db_path()

DDL = """
CREATE TABLE IF NOT EXISTS job_goals (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    start_date TEXT NOT NULL,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    daily_deliver_target INTEGER DEFAULT 10,
    daily_crawl_target INTEGER DEFAULT 50,
    weekly_interview_target INTEGER DEFAULT 3,
    a_grade_deadline_hours INTEGER DEFAULT 24,
    total_offer_target INTEGER DEFAULT 1,
    plan_days INTEGER DEFAULT 60,
    report_time_daily TEXT DEFAULT '21:00',
    report_time_weekly TEXT DEFAULT '09:00',
    report_time_monthly TEXT DEFAULT '09:00',
    report_enabled_daily INTEGER DEFAULT 1,
    report_enabled_weekly INTEGER DEFAULT 1,
    report_enabled_monthly INTEGER DEFAULT 1,
    feishu_receive_id TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_table():
    """确保 job_goals 表存在。"""
    conn = _get_conn()
    conn.execute(DDL)
    conn.commit()
    conn.close()


def start_goals(params: dict[str, Any]) -> dict[str, Any]:
    """开始求职 - 创建或重置目标配置（单行 upsert）。"""
    ensure_table()
    conn = _get_conn()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = date.today().strftime("%Y-%m-%d")

    start_date = params.get("start_date", today_str)
    daily_deliver_target = max(1, int(params.get("daily_deliver_target", 10)))
    daily_crawl_target = max(1, int(params.get("daily_crawl_target", 50)))
    weekly_interview_target = max(0, int(params.get("weekly_interview_target", 3)))
    a_grade_deadline_hours = max(1, int(params.get("a_grade_deadline_hours", 24)))
    total_offer_target = max(1, int(params.get("total_offer_target", 1)))
    plan_days = max(7, int(params.get("plan_days", 60)))
    report_time_daily = params.get("report_time_daily", "21:00")
    report_time_weekly = params.get("report_time_weekly", "09:00")
    report_time_monthly = params.get("report_time_monthly", "09:00")
    report_enabled_daily = 1 if params.get("report_enabled_daily", True) else 0
    report_enabled_weekly = 1 if params.get("report_enabled_weekly", True) else 0
    report_enabled_monthly = 1 if params.get("report_enabled_monthly", True) else 0
    feishu_receive_id = params.get("feishu_receive_id", "")

    conn.execute("""
        INSERT OR REPLACE INTO job_goals (
            id, start_date, end_date, status,
            daily_deliver_target, daily_crawl_target, weekly_interview_target,
            a_grade_deadline_hours, total_offer_target, plan_days,
            report_time_daily, report_time_weekly, report_time_monthly,
            report_enabled_daily, report_enabled_weekly, report_enabled_monthly,
            feishu_receive_id, created_at, updated_at
        ) VALUES (
            1, ?, NULL, 'active',
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?
        )
    """, (
        start_date, daily_deliver_target, daily_crawl_target,
        weekly_interview_target, a_grade_deadline_hours, total_offer_target, plan_days,
        report_time_daily, report_time_weekly, report_time_monthly,
        report_enabled_daily, report_enabled_weekly, report_enabled_monthly,
        feishu_receive_id, now_str, now_str,
    ))
    conn.commit()
    conn.close()

    return get_current_goals()


def get_current_goals() -> dict[str, Any] | None:
    """获取当前目标配置 + 实时进度。"""
    ensure_table()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM job_goals WHERE id = 1").fetchone()
    if not row:
        conn.close()
        return None

    goals = dict(row)

    # 计算实时进度
    today_str = date.today().strftime("%Y-%m-%d")
    start_date = goals["start_date"]

    # 求职天数
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        days_elapsed = (date.today() - start_dt.date()).days + 1
    except Exception:
        days_elapsed = 1

    goals["days_elapsed"] = max(1, days_elapsed)
    goals["plan_days"] = goals.get("plan_days", 60)
    goals["time_progress_percent"] = round(min(days_elapsed / max(goals["plan_days"], 1) * 100, 100), 1)

    # 今日抓取量
    today_crawled = conn.execute(
        "SELECT COUNT(*) as cnt FROM raw_jobs WHERE SUBSTR(crawl_time, 1, 10) = ?",
        (today_str,)
    ).fetchone()["cnt"]
    goals["today_crawled"] = today_crawled
    goals["daily_crawl_progress"] = round(min(today_crawled / max(goals["daily_crawl_target"], 1) * 100, 100), 1)

    # 今日投递 + 总投递/面试/Offer（从飞书实时读取）
    try:
        from app.api.routes.analytics_dashboard import get_feishu_stats_sync
        fs = get_feishu_stats_sync()
        goals["today_delivered"] = fs.get("today_delivered", 0)
        total_delivered = fs.get("total_delivered", 0)
        total_interview = fs.get("total_interview", 0)
        total_offer = fs.get("total_offer", 0)
    except Exception:
        goals["today_delivered"] = 0
        total_delivered = 0
        total_interview = 0
        total_offer = 0

    goals["daily_deliver_progress"] = round(
        min(goals["today_delivered"] / max(goals["daily_deliver_target"], 1) * 100, 100), 1
    )
    goals["total_delivered"] = total_delivered
    goals["total_interview"] = total_interview
    goals["total_offer"] = total_offer
    goals["offer_progress_percent"] = round(min(total_offer / max(goals["total_offer_target"], 1) * 100, 100), 1)

    # 智能推导：建议每日抓取量（基于历史投递转化率）
    # 需要至少 7 天数据才有意义
    if days_elapsed >= 7 and total_delivered > 0:
        # 历史总抓取量
        total_crawled = conn.execute("SELECT COUNT(*) as cnt FROM raw_jobs").fetchone()["cnt"]
        if total_crawled > 0:
            conversion_rate = total_delivered / total_crawled  # 投递/抓取
            if conversion_rate > 0:
                suggested_crawl = int(goals["daily_deliver_target"] / conversion_rate)
                goals["suggested_daily_crawl"] = min(suggested_crawl, 500)
                goals["crawl_conversion_rate"] = round(conversion_rate * 100, 2)
            else:
                goals["suggested_daily_crawl"] = None
                goals["crawl_conversion_rate"] = 0
        else:
            goals["suggested_daily_crawl"] = None
            goals["crawl_conversion_rate"] = 0
    else:
        goals["suggested_daily_crawl"] = None
        goals["crawl_conversion_rate"] = 0
        goals["data_maturity_note"] = f"需积累更多数据（当前第{days_elapsed}天，建议≥7天）"

    conn.close()
    return goals


def update_goals(params: dict[str, Any]) -> dict[str, Any] | None:
    """更新目标参数（部分更新）。无目标行且有实际参数时按默认值自动建档（Q-M4-4 后端化），
    保存接收群/保存时间表不再依赖先手动 /start；空参数保持旧行为（无行返回 None）。"""
    if not params:
        return get_current_goals()
    ensure_table()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM job_goals WHERE id = 1").fetchone()
    if not row:
        conn.close()
        return start_goals(params)

    updatable_fields = [
        "daily_deliver_target", "daily_crawl_target", "weekly_interview_target",
        "a_grade_deadline_hours", "total_offer_target", "plan_days",
        "report_time_daily", "report_time_weekly", "report_time_monthly",
        "report_enabled_daily", "report_enabled_weekly", "report_enabled_monthly",
        "feishu_receive_id",
    ]

    sets = []
    values = []
    for field in updatable_fields:
        if field in params:
            sets.append(f"{field} = ?")
            values.append(params[field])

    if not sets:
        conn.close()
        return get_current_goals()

    sets.append("updated_at = ?")
    values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    values.append(1)  # id

    conn.execute(f"UPDATE job_goals SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    conn.close()

    return get_current_goals()


def finish_goals() -> dict[str, Any] | None:
    """结束求职（找到工作了）- 记录结束日期，状态改为 finished。"""
    ensure_table()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM job_goals WHERE id = 1").fetchone()
    if not row:
        conn.close()
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = date.today().strftime("%Y-%m-%d")

    conn.execute("""
        UPDATE job_goals SET status = 'finished', end_date = ?, updated_at = ? WHERE id = 1
    """, (today_str, now_str))
    conn.commit()
    conn.close()

    return get_current_goals()
