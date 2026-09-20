# app/services/analytics_pipeline_service.py
"""
求职管道与招聘渠道数据分析服务层。
集中收敛核心大盘指标概览、漏斗分析、平台渠道转化率及投递面试多时间粒度趋势计算。
底座数据拉取与归一化委托至 app.services.feishu_jobs_fetcher。
"""
import asyncio
import logging
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.services.feishu_jobs_fetcher import (
    FIELD_CRAWL_TIME,
    FIELD_GRADE,
    FIELD_PLATFORM,
    FIELD_STATUS,
    PENDING_STATUSES,
    STATUS_NORMALIZE,
    extract_field,
    fetch_feishu_jobs,
    is_delivered_status,
    is_interview_status,
    is_offer_status,
    normalize_platform_name,
)

logger = logging.getLogger(__name__)

# 本地数据库路径
_LOCAL_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "job_hunter.db"
)
DEFAULT_DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or _LOCAL_DB

# 漏斗展示预设顺序
FUNNEL_STAGES = [
    "新线索", "已完成初步评估", "已深度初步评估", "简历人工复核",
    "待投递", "已投递", "面试中", "已获Offer",
]


def _get_conn(db_path: str = DEFAULT_DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


async def get_feishu_pipeline_stats() -> dict[str, Any]:
    """从飞书聚合管道统计数据，供战报和目标服务复用。"""
    jobs = await fetch_feishu_jobs()
    if not jobs:
        return {
            "feishu_total": 0, "total_delivered": 0, "total_interview": 0,
            "total_offer": 0, "total_pending": 0, "a_grade_count": 0,
            "today_delivered": 0, "week_delivered": 0, "month_delivered": 0,
        }

    now_dt = datetime.now()
    today = now_dt.strftime("%Y-%m-%d")
    monday_str = (now_dt - timedelta(days=now_dt.weekday())).strftime("%Y-%m-%d")
    month_start_str = now_dt.strftime("%Y-%m") + "-01"
    total_delivered = total_interview = total_offer = total_pending = a_grade = 0
    today_delivered = week_delivered = month_delivered = 0

    for job in jobs:
        status = extract_field(job, FIELD_STATUS)
        crawl_time = extract_field(job, FIELD_CRAWL_TIME)
        grade = extract_field(job, FIELD_GRADE)

        if grade and grade.upper() == "A":
            a_grade += 1

        if is_offer_status(status):
            total_offer += 1
            total_interview += 1
            total_delivered += 1
            if crawl_time.startswith(today):
                today_delivered += 1
            if crawl_time >= monday_str:
                week_delivered += 1
            if crawl_time >= month_start_str:
                month_delivered += 1
        elif is_interview_status(status):
            total_interview += 1
            total_delivered += 1
            if crawl_time.startswith(today):
                today_delivered += 1
            if crawl_time >= monday_str:
                week_delivered += 1
            if crawl_time >= month_start_str:
                month_delivered += 1
        elif status == "已投递":
            total_delivered += 1
            if crawl_time.startswith(today):
                today_delivered += 1
            if crawl_time >= monday_str:
                week_delivered += 1
            if crawl_time >= month_start_str:
                month_delivered += 1
        elif status in PENDING_STATUSES:
            total_pending += 1

    return {
        "feishu_total": len(jobs),
        "total_delivered": total_delivered,
        "total_interview": total_interview,
        "total_offer": total_offer,
        "total_pending": total_pending,
        "a_grade_count": a_grade,
        "today_delivered": today_delivered,
        "week_delivered": week_delivered,
        "month_delivered": month_delivered,
    }


def get_feishu_stats_sync() -> dict[str, Any]:
    """同步包装器：供同步代码（goal_service 等）调用。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, get_feishu_pipeline_stats()).result()
    else:
        return asyncio.run(get_feishu_pipeline_stats())


async def calculate_overview_stats(db_path: str = DEFAULT_DB_PATH) -> dict[str, Any]:
    """核心指标总览计算"""
    conn = _get_conn(db_path)
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        month_start = datetime.now().strftime("%Y-%m") + "-01"

        total_crawled = conn.execute("SELECT COUNT(*) as cnt FROM raw_jobs").fetchone()["cnt"]

        today_tokens = month_tokens = 0
        today_cost = month_cost = 0.0
        try:
            token_rows = conn.execute("SELECT total_tokens, cost_cny, created_at FROM token_log").fetchall()
            for r in token_rows:
                tokens = r["total_tokens"] or 0
                cost = r["cost_cny"] or 0.0
                created = r["created_at"] or ""
                if created >= today:
                    today_tokens += tokens
                    today_cost += cost
                if created >= month_start:
                    month_tokens += tokens
                    month_cost += cost
        except Exception:
            pass
    finally:
        conn.close()

    feishu_jobs = await fetch_feishu_jobs()
    feishu_total = len(feishu_jobs)

    today_new = yesterday_new = a_grade_count = 0
    total_pending = total_delivered = total_interview = total_offer = 0

    for job in feishu_jobs:
        status = extract_field(job, FIELD_STATUS)
        grade = extract_field(job, FIELD_GRADE)
        crawl_time = extract_field(job, FIELD_CRAWL_TIME)

        if crawl_time[:10] == today:
            today_new += 1
        elif crawl_time[:10] == yesterday:
            yesterday_new += 1

        if grade and grade.upper().startswith("A"):
            a_grade_count += 1

        if is_offer_status(status):
            total_offer += 1
            total_interview += 1
            total_delivered += 1
        elif is_interview_status(status):
            total_interview += 1
            total_delivered += 1
        elif status == "已投递":
            total_delivered += 1
        elif status in PENDING_STATUSES:
            total_pending += 1

    return {
        "total_crawled": total_crawled,
        "feishu_total": feishu_total,
        "today_crawled": today_new,
        "yesterday_crawled": yesterday_new,
        "total_pending": total_pending,
        "total_delivered": total_delivered,
        "total_interview": total_interview,
        "total_offer": total_offer,
        "a_grade_count": a_grade_count,
        "a_grade_rate": round(a_grade_count / max(feishu_total, 1) * 100, 1),
        "conversion_rate": round(total_delivered / max(feishu_total, 1) * 100, 1),
        "interview_rate": round(total_interview / max(total_delivered, 1) * 100, 1),
        "today_tokens": today_tokens,
        "today_cost_cny": round(today_cost, 4),
        "month_tokens": month_tokens,
        "month_cost_cny": round(month_cost, 4),
        "feishu_available": feishu_total > 0,
    }


async def calculate_funnel_stats(db_path: str = DEFAULT_DB_PATH) -> dict[str, Any]:
    """求职漏斗计算"""
    conn = _get_conn(db_path)
    try:
        total_crawled = conn.execute("SELECT COUNT(*) as cnt FROM raw_jobs").fetchone()["cnt"]
    except Exception:
        total_crawled = 0
    finally:
        conn.close()

    feishu_jobs = await fetch_feishu_jobs()
    if feishu_jobs:
        status_counts: dict[str, int] = defaultdict(int)
        for job in feishu_jobs:
            status = extract_field(job, FIELD_STATUS)
            if not status:
                continue
            status = STATUS_NORMALIZE.get(status, status)
            if is_interview_status(status):
                status_counts["面试中"] += 1
            elif is_offer_status(status):
                status_counts["已获Offer"] += 1
            else:
                status_counts[status] += 1

        total = len(feishu_jobs)
        funnel = []
        for stage in FUNNEL_STAGES:
            count = status_counts.get(stage, 0)
            funnel.append({"stage": stage, "count": count, "percent": round(count / max(total, 1) * 100, 1)})

        for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
            if status not in FUNNEL_STAGES:
                funnel.append({"stage": status, "count": count, "percent": round(count / max(total, 1) * 100, 1)})

        return {"source": "feishu", "total": total, "total_crawled": total_crawled, "funnel": funnel}

    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT process_status, COUNT(*) as cnt FROM raw_jobs GROUP BY process_status ORDER BY cnt DESC"
        ).fetchall()
        total = sum(r["cnt"] for r in rows)
        funnel = [{"stage": r["process_status"] or "未知", "count": r["cnt"], "percent": round(r["cnt"] / max(total, 1) * 100, 1)} for r in rows]
        return {"source": "local", "total": total, "total_crawled": total_crawled, "funnel": funnel}
    finally:
        conn.close()


async def calculate_platform_stats(db_path: str = DEFAULT_DB_PATH) -> dict[str, Any]:
    """招聘平台渠道转化分析计算"""
    crawl_by_platform: dict[str, int] = defaultdict(int)
    conn = _get_conn(db_path)
    try:
        crawl_rows = conn.execute(
            "SELECT platform, COUNT(*) as crawl_count FROM raw_jobs GROUP BY platform ORDER BY crawl_count DESC"
        ).fetchall()
        for r in crawl_rows:
            norm_p = normalize_platform_name(r["platform"])
            crawl_by_platform[norm_p] += r["crawl_count"]
    except Exception as e:
        logger.warning(f"⚠️ [analytics_pipeline] 本地抓取平台统计异常: {e}")
    finally:
        conn.close()

    feishu_jobs = await fetch_feishu_jobs()
    push_by_platform: dict[str, int] = defaultdict(int)
    deliver_by_platform: dict[str, int] = defaultdict(int)
    interview_by_platform: dict[str, int] = defaultdict(int)
    offer_by_platform: dict[str, int] = defaultdict(int)

    for job in feishu_jobs:
        raw_platform = extract_field(job, FIELD_PLATFORM) or "其他平台"
        platform = normalize_platform_name(raw_platform)
        status = extract_field(job, FIELD_STATUS)
        push_by_platform[platform] += 1
        if is_offer_status(status):
            offer_by_platform[platform] += 1
            interview_by_platform[platform] += 1
            deliver_by_platform[platform] += 1
        elif is_interview_status(status):
            interview_by_platform[platform] += 1
            deliver_by_platform[platform] += 1
        elif status == "已投递":
            deliver_by_platform[platform] += 1

    primary_platforms = ["BOSS直聘", "51job", "猎聘", "智联招聘", "小红书"]
    all_platforms = set(list(crawl_by_platform.keys()) + list(push_by_platform.keys()))

    valid_platforms = []
    for p in all_platforms:
        if p in primary_platforms:
            valid_platforms.append(p)
        elif p == "其他平台":
            if crawl_by_platform.get(p, 0) > 0 or push_by_platform.get(p, 0) > 0:
                valid_platforms.append(p)
        elif crawl_by_platform.get(p, 0) > 10 or deliver_by_platform.get(p, 0) > 0:
            valid_platforms.append(p)

    def _sort_key(x: str):
        if x == "其他平台":
            return (1, 0)
        return (0, -(crawl_by_platform.get(x, 0)))

    sorted_platforms = sorted(valid_platforms, key=_sort_key)
    platforms = []
    for p in sorted_platforms:
        crawl = crawl_by_platform.get(p, 0)
        push = push_by_platform.get(p, 0)
        deliver = deliver_by_platform.get(p, 0)
        interview = interview_by_platform.get(p, 0)
        offer = offer_by_platform.get(p, 0)
        platforms.append({
            "platform": p,
            "crawl_count": crawl,
            "push_count": push,
            "deliver_count": deliver,
            "interview_count": interview,
            "offer_count": offer,
            "deliver_rate": round(deliver / max(crawl, 1) * 100, 1),
        })

    names = [p["platform"] for p in platforms]
    logger.info(f"📊 [Analytics] 平台渠道统计归一化完成: 共 {len(platforms)} 个有效渠道: {names}")
    return {"platforms": platforms, "feishu_available": len(feishu_jobs) > 0}


async def calculate_trend_stats(time_range: str = "daily", db_path: str = DEFAULT_DB_PATH) -> dict[str, Any]:
    """抓取/投递/面试趋势分析计算"""
    conn = _get_conn(db_path)
    now = datetime.now()
    try:
        if time_range == "daily":
            days = 14
            start_date = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
            crawl_rows = conn.execute("""
                SELECT SUBSTR(crawl_time, 1, 10) as date, COUNT(*) as cnt
                FROM raw_jobs WHERE crawl_time >= ?
                GROUP BY SUBSTR(crawl_time, 1, 10) ORDER BY date ASC
            """, (start_date,)).fetchall()
            crawl_map = {r["date"]: r["cnt"] for r in crawl_rows}
            trend = [
                {
                    "date": (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"),
                    "label": (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")[5:],
                    "crawled": crawl_map.get((now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"), 0),
                    "delivered": 0,
                    "interviewed": 0,
                }
                for i in range(days)
            ]
        elif time_range == "weekly":
            weeks = 8
            trend = []
            for i in range(weeks - 1, -1, -1):
                week_start = now - timedelta(weeks=i, days=now.weekday())
                week_end = week_start + timedelta(days=6)
                ws, we = week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")
                cnt = conn.execute("""
                    SELECT COUNT(*) as cnt FROM raw_jobs
                    WHERE SUBSTR(crawl_time, 1, 10) >= ? AND SUBSTR(crawl_time, 1, 10) <= ?
                """, (ws, we)).fetchone()["cnt"]
                trend.append({
                    "date": ws,
                    "label": f"{week_start.strftime('%m/%d')}-{week_end.strftime('%m/%d')}",
                    "crawled": cnt,
                    "delivered": 0,
                    "interviewed": 0,
                })
        else:
            months = 6
            trend = []
            for i in range(months - 1, -1, -1):
                target = now.replace(day=1) - timedelta(days=i * 28)
                target = target.replace(day=1)
                month_str = target.strftime("%Y-%m")
                cnt = conn.execute("SELECT COUNT(*) as cnt FROM raw_jobs WHERE SUBSTR(crawl_time, 1, 7) = ?", (month_str,)).fetchone()["cnt"]
                trend.append({
                    "date": month_str + "-01",
                    "label": month_str,
                    "crawled": cnt,
                    "delivered": 0,
                    "interviewed": 0,
                })
    finally:
        conn.close()

    feishu_jobs = await fetch_feishu_jobs()
    if feishu_jobs:
        deliver_by_date: dict[str, int] = defaultdict(int)
        interview_by_date: dict[str, int] = defaultdict(int)
        for job in feishu_jobs:
            status = extract_field(job, FIELD_STATUS)
            crawl_time = extract_field(job, FIELD_CRAWL_TIME)
            if not crawl_time:
                continue
            date_key = crawl_time[:10]
            if is_delivered_status(status):
                deliver_by_date[date_key] += 1
            if is_interview_status(status) or is_offer_status(status):
                interview_by_date[date_key] += 1

        if time_range == "daily":
            for item in trend:
                item["delivered"] = deliver_by_date.get(item["date"], 0)
                item["interviewed"] = interview_by_date.get(item["date"], 0)
        elif time_range == "weekly":
            for item in trend:
                ws = item["date"]
                we_dt = datetime.strptime(ws, "%Y-%m-%d") + timedelta(days=6)
                we = we_dt.strftime("%Y-%m-%d")
                item["delivered"] = sum(v for k, v in deliver_by_date.items() if ws <= k <= we)
                item["interviewed"] = sum(v for k, v in interview_by_date.items() if ws <= k <= we)
        else:
            for item in trend:
                month_prefix = item["date"][:7]
                item["delivered"] = sum(v for k, v in deliver_by_date.items() if k[:7] == month_prefix)
                item["interviewed"] = sum(v for k, v in interview_by_date.items() if k[:7] == month_prefix)

    return {"range": time_range, "trend": trend, "feishu_available": len(feishu_jobs) > 0}
