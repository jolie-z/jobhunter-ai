# app/services/report_service.py
"""
战报数据聚合引擎 - 生成日报/周报/月报/终报的结构化数据。
数据来源: raw_jobs(本地) + token_log(本地) + 飞书(如可用) + job_goals(目标)。
"""
import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from app.services.report_insights import (
    generate_daily_suggestions,
    generate_monthly_suggestions,
    generate_weekly_suggestions,
)

# 主项目 live DB：默认用本仓库内 backend/data/job_hunter.db，
# 特殊部署可用环境变量 MAIN_PROJECT_DB 指向外部主库
_MAIN_PROJECT_DB = os.environ.get("MAIN_PROJECT_DB", "")
_LOCAL_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "job_hunter.db"
)
DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or (
    _MAIN_PROJECT_DB if _MAIN_PROJECT_DB and os.path.exists(_MAIN_PROJECT_DB) else _LOCAL_DB
)


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _feishu_stats() -> dict[str, Any]:
    """从飞书读取管道统计（复用 analytics_dashboard 缓存）。"""
    try:
        from app.api.routes.analytics_dashboard import get_feishu_stats_sync
        return get_feishu_stats_sync()
    except Exception:
        return {"feishu_total": 0, "total_delivered": 0, "total_interview": 0,
                "total_offer": 0, "total_pending": 0, "a_grade_count": 0,
                "today_delivered": 0, "week_delivered": 0}


def _get_goals(conn) -> dict | None:
    """读取求职目标配置。"""
    try:
        row = conn.execute("SELECT * FROM job_goals WHERE id = 1").fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _token_stats(conn, start: str, end: str) -> dict[str, Any]:
    """指定时间范围内的 token 统计及主力模型探测。"""
    try:
        r = conn.execute("""
            SELECT COALESCE(SUM(total_tokens), 0) as tokens,
                   COALESCE(SUM(cost_cny), 0) as cost,
                   COUNT(*) as calls
            FROM token_log WHERE created_at >= ? AND created_at < ?
        """, (start, end)).fetchone()
        m_row = conn.execute("""
            SELECT model_name FROM token_log
            WHERE created_at >= ? AND created_at < ? AND model_name != ''
            GROUP BY model_name ORDER BY SUM(total_tokens) DESC LIMIT 1
        """, (start, end)).fetchone()
        top_m = m_row["model_name"] if m_row and m_row["model_name"] else ""
        if not top_m:
            from common.config import _cfg
            top_m = _cfg("OPENAI_MODEL", "LLM_MODEL", "model", json_key="OPENAI_MODEL") or "mimo-v2.5-pro"
        return {
            "tokens": r["tokens"],
            "cost_cny": round(r["cost"], 4),
            "calls": r["calls"],
            "primary_model": top_m,
        }
    except Exception:
        return {"tokens": 0, "cost_cny": 0, "calls": 0, "primary_model": "mimo-v2.5-pro"}


def _normalize_platform_name(name: str) -> str:
    """规范化平台名称，兼容别名并保留用户自定义渠道。"""
    if not name or str(name).strip() in ("", "未知", "unknown", "None", "-", "null"):
        return "其他平台"
    n = str(name).strip()
    n_lower = n.lower()
    if "boss" in n_lower or "直聘" in n:
        return "BOSS直聘"
    if "51" in n_lower or "前程" in n:
        return "51job"
    if "猎聘" in n or "liepin" in n_lower:
        return "猎聘"
    if "智联" in n or "zhilian" in n_lower or "zhaopin" in n_lower:
        return "智联招聘"
    if "红书" in n or "xhs" in n_lower or "小红书" in n:
        return "小红书"
    if "拉勾" in n or "lagou" in n_lower:
        return "拉勾招聘"
    return n


def _crawl_stats(conn, start: str, end: str) -> dict[str, Any]:
    """指定时间范围内的抓取统计，并动态聚合系统库中已有的全部渠道名称与在库量。"""
    total = conn.execute("""
        SELECT COUNT(*) as cnt FROM raw_jobs
        WHERE crawl_time >= ? AND crawl_time < ?
    """, (start, end)).fetchone()["cnt"]

    # 本统计周期内的平台抓取
    period_rows = conn.execute("""
        SELECT platform, COUNT(*) as cnt FROM raw_jobs
        WHERE crawl_time >= ? AND crawl_time < ?
        GROUP BY platform
    """, (start, end)).fetchall()

    # 系统库中所有已有的历史渠道
    all_rows = conn.execute("""
        SELECT platform, COUNT(*) as cnt FROM raw_jobs
        GROUP BY platform
    """).fetchall()

    today_map: dict[str, int] = defaultdict(int)
    for r in period_rows:
        p = _normalize_platform_name(r["platform"])
        today_map[p] += r["cnt"]

    total_map: dict[str, int] = defaultdict(int)
    for r in all_rows:
        p = _normalize_platform_name(r["platform"])
        total_map[p] += r["cnt"]

    # 排序：优先按主流平台排序，自定渠道按总量降序，其他平台置底
    primary_order = ["BOSS直聘", "51job", "猎聘", "智联招聘", "小红书"]
    all_platform_keys = set(list(total_map.keys()) + list(today_map.keys()) + primary_order)

    def _sort_platform(p: str):
        return (2, 0) if p == "其他平台" else (0, primary_order.index(p)) if p in primary_order else (1, -total_map.get(p, 0))

    sorted_keys = sorted(all_platform_keys, key=_sort_platform)

    platforms = []
    by_platform = {}
    for p in sorted_keys:
        t_cnt = today_map.get(p, 0)
        tot_cnt = total_map.get(p, 0)
        # 主流平台或库中已有数据的渠道全部保留
        if tot_cnt > 0 or t_cnt > 0 or p in primary_order:
            platforms.append({
                "name": p,
                "today": t_cnt,
                "period_count": t_cnt,
                "total": tot_cnt,
            })
            by_platform[p] = t_cnt

    # 清洗淘汰数
    rejected = conn.execute("""
        SELECT COUNT(*) as cnt FROM raw_jobs
        WHERE crawl_time >= ? AND crawl_time < ?
        AND process_status IN ('清洗淘汰', 'ai清洗淘汰', '已确认淘汰')
    """, (start, end)).fetchone()["cnt"]

    return {
        "total": total,
        "by_platform": by_platform,
        "platforms": platforms,
        "rejected": rejected,
        "pass_rate": round((total - rejected) / max(total, 1) * 100, 1),
    }


def _pipeline_snapshot(conn) -> dict[str, int]:
    """当前管道状态快照。"""
    rows = conn.execute("""
        SELECT process_status, COUNT(*) as cnt
        FROM raw_jobs GROUP BY process_status
    """).fetchall()
    return {r["process_status"] or "未知": r["cnt"] for r in rows}


# ============================================================
# 报告生成函数
# ============================================================

def generate_daily_report(target_date: str | None = None) -> dict[str, Any]:
    """
    生成日报数据。
    target_date: "YYYY-MM-DD"，默认今天。
    """
    if not target_date:
        target_date = date.today().strftime("%Y-%m-%d")

    next_day = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    conn = _get_conn()
    goals = _get_goals(conn)

    # 抓取统计
    crawl = _crawl_stats(conn, target_date, next_day)

    # Token 统计
    tokens = _token_stats(conn, target_date, next_day)

    # 本月累计 token
    month_start = target_date[:7] + "-01"
    month_tokens = _token_stats(conn, month_start, next_day)

    # 管道快照
    pipeline = _pipeline_snapshot(conn)
    pending_clean = pipeline.get("已存入数据", 0) + pipeline.get("待AI初筛", 0)

    # 求职天数
    days_elapsed = 1
    if goals and goals.get("start_date"):
        try:
            days_elapsed = (datetime.strptime(target_date, "%Y-%m-%d") - datetime.strptime(goals["start_date"], "%Y-%m-%d")).days + 1
        except Exception:
            pass

    # 建议
    suggestions = generate_daily_suggestions(conn, goals, crawl["total"])

    # 飞书管道数据
    fs = _feishu_stats()

    conn.close()

    return {
        "type": "daily",
        "date": target_date,
        "days_elapsed": days_elapsed,
        "crawl": crawl,
        "tokens": tokens,
        "month_tokens": month_tokens,
        "pipeline": pipeline,
        "pending_clean": pending_clean,
        "feishu": fs,
        "goals": {
            "daily_crawl_target": goals.get("daily_crawl_target", 50) if goals else 50,
            "daily_deliver_target": goals.get("daily_deliver_target", 10) if goals else 10,
        },
        "suggestions": suggestions,
    }


def generate_weekly_report(week_start: str | None = None) -> dict[str, Any]:
    """
    生成周报数据。
    week_start: 周一日期 "YYYY-MM-DD"，默认本周一。
    """
    if not week_start:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.strftime("%Y-%m-%d")

    week_end_dt = datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=7)
    week_end = week_end_dt.strftime("%Y-%m-%d")

    # 上周
    prev_start_dt = datetime.strptime(week_start, "%Y-%m-%d") - timedelta(days=7)
    prev_start = prev_start_dt.strftime("%Y-%m-%d")

    conn = _get_conn()
    goals = _get_goals(conn)

    # 本周数据
    crawl = _crawl_stats(conn, week_start, week_end)
    tokens = _token_stats(conn, week_start, week_end)

    # 上周数据（环比）
    prev_crawl = _crawl_stats(conn, prev_start, week_start)
    prev_tokens = _token_stats(conn, prev_start, week_start)

    # 环比变化
    crawl_change = round((crawl["total"] - prev_crawl["total"]) / max(prev_crawl["total"], 1) * 100, 1)
    token_change = round((tokens["tokens"] - prev_tokens["tokens"]) / max(prev_tokens["tokens"], 1) * 100, 1)

    # 每日抓取分布
    daily_breakdown = []
    for i in range(7):
        d = (datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d")
        d_next = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        day_crawl = _crawl_stats(conn, d, d_next)
        daily_breakdown.append({"date": d, "crawled": day_crawl["total"]})

    # 管道快照
    pipeline = _pipeline_snapshot(conn)

    # 飞书管道数据
    fs = _feishu_stats()

    # 求职天数
    days_elapsed = 1
    if goals and goals.get("start_date"):
        try:
            days_elapsed = (date.today() - datetime.strptime(goals["start_date"], "%Y-%m-%d").date()).days + 1
        except Exception:
            pass

    # 周度复盘与建议
    suggestions = generate_weekly_suggestions(
        crawl["total"],
        crawl_change,
        crawl.get("platforms", []),
        fs,
    )

    conn.close()

    return {
        "type": "weekly",
        "week_start": week_start,
        "week_end": (week_end_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
        "days_elapsed": days_elapsed,
        "crawl": crawl,
        "prev_crawl_total": prev_crawl["total"],
        "crawl_change_percent": crawl_change,
        "tokens": tokens,
        "prev_tokens_total": prev_tokens["tokens"],
        "token_change_percent": token_change,
        "daily_breakdown": daily_breakdown,
        "pipeline": pipeline,
        "feishu": fs,
        "goals": {
            "daily_crawl_target": goals.get("daily_crawl_target", 50) if goals else 50,
            "weekly_interview_target": goals.get("weekly_interview_target", 3) if goals else 3,
        },
        "suggestions": suggestions,
    }


def generate_monthly_report(month: str | None = None) -> dict[str, Any]:
    """
    生成月报数据。
    month: "YYYY-MM"，默认本月。
    """
    if not month:
        month = date.today().strftime("%Y-%m")

    month_start = month + "-01"
    # 下月第一天
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 12:
        next_month_start = f"{year + 1}-01-01"
    else:
        next_month_start = f"{year}-{mon + 1:02d}-01"

    conn = _get_conn()
    goals = _get_goals(conn)

    # 本月数据
    crawl = _crawl_stats(conn, month_start, next_month_start)
    tokens = _token_stats(conn, month_start, next_month_start)

    # 管道快照
    pipeline = _pipeline_snapshot(conn)
    total_jobs = sum(pipeline.values())

    # 求职天数 & 进度
    days_elapsed = 1
    plan_days = 60
    if goals:
        plan_days = goals.get("plan_days", 60)
        if goals.get("start_date"):
            try:
                days_elapsed = (date.today() - datetime.strptime(goals["start_date"], "%Y-%m-%d").date()).days + 1
            except Exception:
                pass

    # 平台质量矩阵（本月抓取量 vs 初筛通过率 vs 在库沉淀）
    rejected_rows = conn.execute("""
        SELECT platform, COUNT(*) as cnt FROM raw_jobs
        WHERE crawl_time >= ? AND crawl_time < ?
        AND process_status IN ('清洗淘汰', 'ai清洗淘汰', '已确认淘汰')
        GROUP BY platform
    """, (month_start, next_month_start)).fetchall()
    rejected_map: dict[str, int] = defaultdict(int)
    for r in rejected_rows:
        p = _normalize_platform_name(r["platform"])
        rejected_map[p] += r["cnt"]

    stock_map = {item["name"]: item["total"] for item in crawl.get("platforms", [])}

    platform_roi = []
    for platform, count in sorted(crawl["by_platform"].items(), key=lambda x: -x[1]):
        rejected = rejected_map.get(platform, 0)
        total_in_stock = stock_map.get(platform, 0)
        passed = max(0, count - rejected)
        pass_rate = round(passed / max(count, 1) * 100, 1)
        platform_roi.append({
            "platform": platform,
            "crawled": count,
            "rejected": rejected,
            "passed": passed,
            "pass_rate": pass_rate,
            "total_in_stock": total_in_stock,
        })

    conn.close()

    # 飞书管道数据
    fs = _feishu_stats()

    # 月度漏斗转化率
    total_delivered = fs.get("total_delivered", 0)
    total_interview = fs.get("total_interview", 0)
    total_offer = fs.get("total_offer", 0)
    interview_rate = round(total_interview / max(total_delivered, 1) * 100, 1)
    offer_rate = round(total_offer / max(total_interview, 1) * 100, 1)

    # 月度宏观战略建议
    suggestions = generate_monthly_suggestions(
        crawl["total"],
        crawl.get("pass_rate", 100),
        platform_roi,
        fs,
    )

    return {
        "type": "monthly",
        "month": month,
        "days_elapsed": days_elapsed,
        "plan_days": plan_days,
        "crawl": crawl,
        "tokens": tokens,
        "pipeline": pipeline,
        "total_jobs": total_jobs,
        "platform_roi": platform_roi,
        "feishu": fs,
        "funnel_rates": {
            "interview_rate": interview_rate,
            "offer_rate": offer_rate,
        },
        "suggestions": suggestions,
    }


def generate_final_report() -> dict[str, Any]:
    """
    生成终报数据 - 从 start_date 到 end_date 的全程总结。
    """
    conn = _get_conn()
    goals = _get_goals(conn)

    if not goals:
        conn.close()
        return {"type": "final", "error": "无求职目标记录"}

    start_date = goals.get("start_date", date.today().strftime("%Y-%m-%d"))
    end_date = goals.get("end_date") or date.today().strftime("%Y-%m-%d")
    next_day = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    # 全程统计
    crawl = _crawl_stats(conn, start_date, next_day)
    tokens = _token_stats(conn, start_date, next_day)
    pipeline = _pipeline_snapshot(conn)

    # 天数
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (end_dt - start_dt).days + 1
    except Exception:
        total_days = 1

    # 平台贡献
    platform_contribution = []
    for platform, count in sorted(crawl["by_platform"].items(), key=lambda x: -x[1]):
        platform_contribution.append({
            "platform": platform,
            "crawled": count,
            "percent": round(count / max(crawl["total"], 1) * 100, 1),
        })

    conn.close()

    # 飞书管道数据
    fs = _feishu_stats()

    return {
        "type": "final",
        "start_date": start_date,
        "end_date": end_date,
        "total_days": total_days,
        "crawl": crawl,
        "tokens": tokens,
        "pipeline": pipeline,
        "platform_contribution": platform_contribution,
        "feishu": fs,
        "goals": {
            "total_offer_target": goals.get("total_offer_target", 1),
            "plan_days": goals.get("plan_days", 60),
        },
    }
