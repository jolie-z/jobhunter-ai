import asyncio
import logging
import random
import sqlite3
from typing import Any

import dateutil.parser

from app.core.cache import JobCache
from app.core.config import PROJECT_ROOT, settings  # noqa: F401
from app.core.feishu_client import feishu_client
from app.jobs.import_parser import (  # noqa: F401
    _51JOB_MOBILE_JOB_URL,
    _BOSS_MOBILE_JOB_URL,
    _PLACEHOLDER_VALUES,
    _SHARE_BOILERPLATE,
    VisionNotConfiguredError,
    _call_llm_for_job_parsing,
    _clean_and_parse_json,
    _detect_platform,
    _has_substantial_job_text,
    _meaningful,
    _merge_parsed_fields,
    _resolve_publish_date,
    normalize_job_url,
    parse_job_from_sources,
)
from app.jobs.import_service import (  # noqa: F401
    _IMPORT_SUMMARY_FIELDS,
    _IMPORT_WRITE_KEYS,
    DuplicateJobError,
    InvalidJobFieldsError,
    _sync_to_raw_jobs,
    assess_parse_quality,
    build_job_review_url,
    confirm_job_import,
    ensure_raw_jobs_indices,
    find_duplicate_job,
    format_job_import_summary,
    import_job_from_images_service,
    import_job_from_text_service,
)
from app.jobs.record_normalizer import (
    DETAIL_ONLY_FIELDS,
    normalize_job_record,
)

logger = logging.getLogger(__name__)


def _parse_fetch_time(job: dict[str, Any]) -> float:
    ft = job.get("fetch_time", "")
    base = 0.0
    if ft:
        if ft.isdigit():
            val = float(ft)
            base = val if val > 1e11 else val * 1000
        else:
            try:
                base = dateutil.parser.parse(ft).timestamp() * 1000
            except Exception:
                pass
    return base + random.random()


async def _pull_jobs_from_feishu() -> list[dict[str, Any]]:
    """从飞书拉取全量岗位并标准化（列表瘦身：排除大文本字段以提速）。"""
    table_id = settings.FEISHU_TABLE_ID_JOBS
    if not table_id:
        return []

    field_names = None
    try:
        all_fields = await feishu_client.list_bitable_fields(table_id)
        field_names = [f for f in all_fields if f not in DETAIL_ONLY_FIELDS]
        if not field_names:
            field_names = None
        else:
            logger.info(f"⚡ [列表瘦身] 从 {len(all_fields)} 个字段中精简，请求 {len(field_names)} 个字段")
    except Exception as e:
        logger.warning(f"⚠️ 获取飞书字段清单失败，本次降级为全字段拉取: {e}")

    try:
        raw_records = await feishu_client.search_bitable_records(table_id, field_names=field_names)
    except Exception as e:
        # 字段清单接口偶发返回已失效的字段名（FieldNameNotFound）：清掉字段缓存，降级全字段重试一次
        if field_names and "FieldNameNotFound" in str(e):
            logger.warning(f"⚠️ 字段清单含失效字段，清缓存并降级为全字段拉取重试: {e}")
            feishu_client._fields_cache.pop(table_id, None)
            field_names = None
            raw_records = await feishu_client.search_bitable_records(table_id, field_names=None)
        else:
            raise

    jobs = []
    for r in raw_records:
        j = normalize_job_record(r, slim=True)
        if j:
            jobs.append(j)

    status_priority = {
        "待沟通": 10, "已沟通": 9, "新线索": 8, "已投递": 7,
        "一面": 6, "二面": 5, "HR面": 4, "录用": 3,
        "不合适": 2, "已淘汰": 1
    }

    def _sort_key(job: dict[str, Any]):
        status = job.get("follow_status") or "新线索"
        prio = status_priority.get(status, 0)
        time_score = _parse_fetch_time(job)
        return (prio, time_score)

    jobs.sort(key=_sort_key, reverse=True)
    return jobs


_refresh_inflight = False


def _kick_background_refresh() -> None:
    """启动后台静默更新，不阻塞当前请求（并发去重：同一时刻至多一个刷新在飞）。"""
    global _refresh_inflight
    if _refresh_inflight:
        return

    async def _refresh():
        global _refresh_inflight
        try:
            logger.info("🔄 [后台刷新] 开始从飞书静默拉取最新岗位数据...")
            jobs = await _pull_jobs_from_feishu()
            # 定序关键：set() 会清脏标记——拉取期间新到的 mark_dirty 必须保留，
            # 否则刷新窗口内的飞书侧变动会被这次 set 吞掉（丢失更新）
            dirty_during_fetch = JobCache.is_dirty()
            JobCache.set(jobs)
            if dirty_during_fetch:
                JobCache.mark_dirty()
                logger.info("🔥 [后台刷新] 拉取期间又收到外部变动，保留脏标记待下个读取再刷新")
            logger.info(f"✅ [后台刷新] 完成，已更新 {len(jobs)} 条岗位缓存")
        except Exception as e:
            logger.error(f"❌ [后台刷新] 失败: {e}")
        finally:
            _refresh_inflight = False

    try:
        loop = asyncio.get_running_loop()
        _refresh_inflight = True
        loop.create_task(_refresh())
    except RuntimeError:
        logger.warning("⚠️ [后台刷新] 无运行中的事件循环，跳过后台刷新")


async def fetch_and_clean_all_jobs(force: bool = False) -> list[dict[str, Any]]:
    """获取并清洗所有岗位数据。

    缓存策略：
    - force=True: 强制从飞书拉取，更新缓存
    - force=False: 优先返回有效缓存；若缓存过期（stale），先返回旧数据，同时触发后台静默刷新（stale-while-revalidate）；
      若完全无缓存，才阻塞拉取一次。
    - 飞书侧外部变动（表格手改/webhook 事件）会打脏标记：即使缓存未过期，也在首个读取时
      提前触发后台刷新（Q-M9-1 事件链消费端，刷新完成 set() 时清除脏标记）。
    """
    if force:
        logger.info("🔄 force=1：已清空缓存，强制从飞书拉取最新数据")
        JobCache.clear()
        jobs = await _pull_jobs_from_feishu()
        dirty_during_fetch = JobCache.is_dirty()
        JobCache.set(jobs)
        if dirty_during_fetch:
            JobCache.mark_dirty()
            logger.info("🔥 [force 刷新] 拉取期间又收到外部变动，保留脏标记待下个读取再刷新")
        return jobs

    # 1. 缓存有效，直接返回（最快路径，0 延迟）；但脏标记未消费时提前踢刷新
    cached_jobs = JobCache.get()
    if cached_jobs is not None:
        if JobCache.is_dirty():
            logger.info("🔥 [脏标记] 检测到飞书侧外部变动，缓存未过期也提前触发后台刷新（先返回当前缓存）")
            _kick_background_refresh()
        return cached_jobs

    # 2. 缓存已过期但有旧数据：立即返回旧数据，后台静默刷新（stale-while-revalidate）
    stale_jobs = JobCache.get_stale()
    if stale_jobs is not None:
        logger.info(f"⚡ [Stale-While-Revalidate] 命中过期缓存（{len(stale_jobs)} 条），先返回旧数据，后台静默刷新")
        _kick_background_refresh()
        return stale_jobs

    # 3. 完全无缓存（首次启动）：加锁避免并发重复拉取
    async with JobCache._lock:
        cached_jobs = JobCache.get()
        if cached_jobs is not None:
            return cached_jobs
        jobs = await _pull_jobs_from_feishu()
        JobCache.set(jobs)
        return jobs


def _sqlite_row_to_detail(row: Any) -> dict[str, Any]:
    r = dict(row)
    return {
        "record_id": f"raw_{r['rowid']}",
        "job_name": r.get("job_title") or "未知岗位",
        "company_name": r.get("company_name") or "未知公司",
        "city": r.get("city") or "未知城市",
        "salary": r.get("salary") or "面议",
        "follow_status": r.get("process_status") or "新线索",
        "scale": r.get("company_size") or "规模不详",
        "industry": r.get("industry") or "未知行业",
        "education": r.get("education_req") or "学历不限",
        "experience": r.get("experience_req") or "经验不限",
        "job_detail": r.get("jd_text") or "暂无详情",
        "hr_skills": [t.strip() for t in (r.get("hr_skill_tags") or "").split(",") if t.strip()],
        "benefits": [t.strip() for t in (r.get("welfare_tags") or "").split(",") if t.strip()],
        "hr_active": "",
        "delivery_date": "",
        "fetch_time": "",
        "work_address": r.get("work_address") or "",
        "my_review": "",
        "interview_transcript": "",
        "ai_rewrite_json": "",
        "manual_refined_resume": "",
        "dream_picture": "",
        "ats_ability_analysis": "",
        "resume_audit": "",
        "strong_fit_assessment": "",
        "risk_red_flags": r.get("reject_reason") or "",
        "deep_action_plan": "",
        "composite_diagnosis_report": "",
        "greeting_msg": "",
        "platform": r.get("platform") or "未知",
        "role": "未知",
        "publish_date": r.get("publish_date") or "",
        "grade": "",
        "company_intro": r.get("company_intro") or "",
        "role_match": 0,
        "skills_align": 0,
        "seniority": 0,
        "compensation": 0,
        "interview_prob": 0,
        "company_stage": 0,
        "market_fit": 0,
        "growth": 0,
        "ai_evaluation_detail": "",
        "job_link": r.get("job_link") or "",
    }


async def fetch_job_detail_service(job_id: str) -> dict[str, Any]:
    """按需拉取单个岗位的完整字段（含列表瘦身裁掉的大文本），供详情页使用。
    兼容飞书 record_id、本地 SQLite raw_id、纯数字 rowid 及复合 ID。"""
    from app.automation.full_auto import RAW_DB_PATH
    from app.services.feishu_service import extract_record_id

    if not job_id:
        raise ValueError("缺少岗位 ID")

    pure_record_id = extract_record_id(job_id) or str(job_id).strip()

    # 1. 检查是否为 SQLite raw_job（以 raw_ 开头或纯数字）
    is_sqlite_id = pure_record_id.startswith("raw_") or pure_record_id.isdigit()
    if is_sqlite_id:
        row_id_str = pure_record_id.replace("raw_", "")
        try:
            with sqlite3.connect(RAW_DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT rowid, platform, job_title, company_name, salary, city, "
                    "education_req, experience_req, jd_text, job_link, process_status, reject_reason, "
                    "welfare_tags, industry, company_size, work_address, hr_skill_tags, publish_date, company_intro "
                    "FROM raw_jobs WHERE rowid = ?",
                    (row_id_str,)
                ).fetchone()
                if row:
                    return _sqlite_row_to_detail(row)
        except Exception as e:
            logger.warning(f"查询 SQLite raw_jobs 异常: {e}")

    # 2. 飞书 Bitable 岗位
    table_id = settings.FEISHU_TABLE_ID_JOBS
    if table_id and (pure_record_id.startswith("rec") or not is_sqlite_id):
        try:
            record = await feishu_client.fetch_bitable_record_by_id(table_id, pure_record_id)
            if record:
                return normalize_job_record(record)
        except Exception as e:
            logger.warning(f"查询飞书 Bitable 岗位 {pure_record_id} 异常: {e}")

    # 3. 兜底策略：在 SQLite 中全文/URL/名称模糊查找
    try:
        with sqlite3.connect(RAW_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT rowid, platform, job_title, company_name, salary, city, "
                "education_req, experience_req, jd_text, job_link, process_status, reject_reason, "
                "welfare_tags, industry, company_size, work_address, hr_skill_tags, publish_date, company_intro "
                "FROM raw_jobs WHERE job_link = ? OR job_title LIKE ? OR company_name LIKE ? ORDER BY rowid DESC LIMIT 1",
                (job_id, f"%{job_id}%", f"%{job_id}%")
            ).fetchone()
            if row:
                return _sqlite_row_to_detail(row)
    except Exception as e:
        logger.warning(f"SQLite 兜底查询岗位 {job_id} 异常: {e}")

    raise ValueError(f"未找到岗位记录: {job_id}")
