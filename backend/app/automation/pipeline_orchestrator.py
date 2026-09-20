"""
全链路全自动总编排器
====================
串联平台抓取、规则清洗、飞书推送、AI评估与状态机自动投递：
    平台抓取(scrape_runner) → 规则清洗(step1) → 飞书推送(step2)
    → 捞新线索(feishu) → AI初评/深评/改写/欢迎语/投递(graph_runner)
"""
import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from app.automation import pipeline_broadcast as pb
from app.automation.db import (
    append_autopilot_log,
    complete_autopilot_log,
    get_autopilot_config,
)
from app.automation.graph_runner import _run_jobs_through_graph
from app.automation.link_precheck import build_checked_batch
from app.automation.scrape_runner import (
    PLATFORM_CN,
    _derive_search_from_config,
    _get_raw_db_path,
    _reap_orphan_scrapers,
    execute_pipeline_scrape,
)
from app.core.feishu_utils import extract_feishu_text as _txt

logger = logging.getLogger(__name__)


async def run_full_auto_pipeline(
    keyword: str | None = None,
    city: str | None = None,
    salary: str | None = None,
    target_jobs: int | None = None,
    platforms: list[str] | None = None,
    stop_at_review: bool = False,
) -> str:
    """
    启动一轮全自动链路（后台异步执行），立即返回 pipeline_task_id 供前端订阅 SSE。
    未显式传入的抓取参数将从 autopilot 配置自动推导。
    stop_at_review=True 为定时链路模式：改写/话术全部做完后一律挂审批断点。
    """
    cur = pb.get_current_pipeline()
    if cur.get("running"):
        raise RuntimeError(f"已有链路正在运行中（{cur.get('task_id')}），请等待其完成或先终止后再启动")
    pipeline_task_id = f"pipeline_{uuid.uuid4().hex[:8]}"
    pb.create_pipeline_queue(pipeline_task_id)
    pb.set_current_pipeline(pipeline_task_id, True)

    from app.automation import abort as abort_mod
    abort_mod.begin_pipeline(pipeline_task_id)

    config = get_autopilot_config()
    derived = _derive_search_from_config(config)
    search = {
        "keyword": keyword or derived["keyword"],
        "city": city or derived["city"],
        "salary": salary or derived["salary"],
        "target_jobs": target_jobs or derived["target_jobs"],
        "platforms": platforms or derived["platforms"],
    }

    asyncio.create_task(_execute_pipeline(pipeline_task_id, config, search, stop_at_review=stop_at_review))
    return pipeline_task_id


async def _execute_pipeline(
    pipeline_task_id: str,
    config: dict[str, Any],
    search: dict[str, Any],
    stop_at_review: bool = False,
):
    """全链路主体：抓取 → 清洗 → 飞书 → 评估投递。全程广播阶段事件，结束时发飞书任务报告。"""
    log_task_id = str(uuid.uuid4())
    append_autopilot_log(log_task_id, "running", 0, f"全自动链路启动: {search['keyword']} / {search['city']}")

    started_at = datetime.now()
    scrape_counts_cn: dict[str, int] = {}
    disabled_platforms: list[str] = []
    synced_ids: list[str] = []
    rejected_rowids: list[str] = []

    from app.automation import abort as abort_mod

    try:
        await pb.emit_log(pipeline_task_id, f"🚀 全自动链路启动 | 关键词「{search['keyword']}」城市「{search['city']}」平台 {search['platforms']}")

        # ===== 阶段 1: 平台抓取（关键词队列 + 平台预算制）=====
        start_rowid, scrape_counts_cn, disabled_platforms = await execute_pipeline_scrape(
            pipeline_task_id=pipeline_task_id,
            search=search,
        )

        async def _send_task_report(
            job_results: list[dict[str, Any]],
            dedup_count: int = 0,
            rejected_ids: list[str] | None = None,
        ):
            """链路出口统一发飞书任务报告；报告失败只告警，不影响链路收尾。"""
            try:
                if not config.get("feishu_enable_report", True):
                    await pb.emit_log(pipeline_task_id, "📮 任务报告推送已在飞书面板关闭，跳过发送")
                    return
                from app.automation import pipeline_report as pr
                raw_db = _get_raw_db_path()
                cleaning_stats = await asyncio.to_thread(
                    pr.collect_cleaning_stats, raw_db, start_rowid)
                text = pr.build_pipeline_report(
                    started_at=started_at,
                    scrape_counts=scrape_counts_cn,
                    disabled_platforms=[PLATFORM_CN.get(p, p) for p in disabled_platforms],
                    platform_cn={},
                    cleaning=cleaning_stats,
                    synced_count=len(synced_ids),
                    job_results=job_results,
                    aborted=abort_mod.is_aborted(),
                    dedup_count=dedup_count,
                )
                actual_rejected_ids = rejected_ids if rejected_ids is not None else []
                await pb.emit_log(pipeline_task_id, "📮 正在生成任务战报卡片并推送飞书…")
                card_ok = await pr.send_pipeline_master_card(
                    started_at=started_at,
                    scrape_counts=scrape_counts_cn,
                    cleaning=cleaning_stats,
                    job_results=job_results,
                    dedup_count=dedup_count,
                    rejected_ids=actual_rejected_ids,
                )
                if not card_ok:
                    await pr.send_pipeline_report(text)
            except Exception as rep_e:
                logger.warning(f"[FullAuto] 任务报告发送异常（不阻断链路）: {rep_e}")

        # 终止守卫
        if abort_mod.is_aborted():
            await _send_task_report([])
            await pb.emit_stage(pipeline_task_id, "done", "done")
            await pb.emit_end(pipeline_task_id, {"reason": "aborted"})
            complete_autopilot_log(log_task_id, "failed", 0, "手动终止")
            return

        # ===== 阶段 2: 规则清洗（只清洗本轮采集的行）=====
        await pb.emit_stage(pipeline_task_id, "cleaning", "running")
        from job_processor import step1_rule_filter
        await step1_rule_filter._async_run_pipeline(
            sse_task_id=pipeline_task_id, limit=None, min_rowid=start_rowid)

        try:
            def _fetch_rejected_jobs():
                with sqlite3.connect(_get_raw_db_path()) as _c:
                    _c.row_factory = sqlite3.Row
                    return [
                        dict(r) for r in _c.execute(
                            "SELECT rowid, platform, job_title, company_name, salary, city, "
                            "education_req, experience_req, jd_text, job_link, process_status, reject_reason "
                            "FROM raw_jobs WHERE rowid > ? AND process_status IN ('清洗淘汰', 'ai清洗淘汰')",
                            (start_rowid,)
                        ).fetchall()
                    ]
            rejected_list = await asyncio.to_thread(_fetch_rejected_jobs)
            rejected_rowids = [str(rj["rowid"]) for rj in rejected_list if rj.get("rowid")]
            for rj in rejected_list:
                await pb.emit_job(
                    pipeline_task_id,
                    job_id=f"raw_{rj['rowid']}",
                    job_name=rj.get("job_title") or "未知岗位",
                    node="clean_rejected",
                    status="rejected",
                    platform=rj.get("platform") or "",
                    company_name=rj.get("company_name") or "",
                    salary=rj.get("salary") or "",
                    city=rj.get("city") or "",
                    education=rj.get("education_req") or "",
                    experience=rj.get("experience_req") or "",
                    jd_text=rj.get("jd_text") or "",
                    job_url=rj.get("job_link") or "",
                    reject_reason=rj.get("reject_reason") or "触发清洗淘汰规则",
                    reject_type="ai" if rj.get("process_status") == "ai清洗淘汰" else "rule",
                )
            if rejected_list:
                await pb.emit_log(pipeline_task_id, f"🧹 本轮共拦截淘汰 {len(rejected_list)} 个岗位（已沉淀至「淘汰岗位」回收站）")
        except Exception as _rej_e:
            logger.warning(f"[FullAuto] 广播淘汰岗位异常（不阻断链路）: {_rej_e}")

        await pb.emit_stage(pipeline_task_id, "cleaning", "done")

        # ===== 阶段 3: 飞书推送（只推送本轮采集的行）=====
        await pb.emit_stage(pipeline_task_id, "feishu_sync", "running")
        from job_processor import step2_sync_feishu
        synced_ids = await asyncio.to_thread(
            step2_sync_feishu.sync_sqlite_to_feishu,
            _get_raw_db_path(), "raw_jobs", pipeline_task_id, None, start_rowid
        )
        synced_ids = [rid for rid in (synced_ids or []) if isinstance(rid, str)]
        await pb.emit_stage(pipeline_task_id, "feishu_sync", "done")

        # 终止守卫
        if abort_mod.is_aborted():
            await _send_task_report([])
            await pb.emit_stage(pipeline_task_id, "done", "done")
            await pb.emit_end(pipeline_task_id, {"reason": "aborted"})
            complete_autopilot_log(log_task_id, "failed", 0, "手动终止")
            return

        # ===== 阶段 4: 只评估本轮采集的岗位 =====
        from app.services.feishu_service import (
            TABLE_ID,
            get_active_resume_from_feishu,
            get_job_record_from_feishu,
            get_my_preferences,
            get_resume_text_by_id,
        )

        mass_resume_id = (config.get("mass_apply_resume_id") or "").strip()
        resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
        preferences_text = await asyncio.to_thread(get_my_preferences)
        if not resume_text:
            await pb.emit_log(pipeline_task_id, "❌ 找不到激活简历，评估投递段中止", "error")
            await _send_task_report([])
            await pb.emit_stage(pipeline_task_id, "done", "done")
            await pb.emit_end(pipeline_task_id, {"reason": "no_resume"})
            complete_autopilot_log(log_task_id, "failed", 0, "找不到激活简历")
            return

        rewrite_base_id = (config.get("rewrite_base_resume_id") or "").strip()
        if rewrite_base_id:
            base_text = await asyncio.to_thread(get_resume_text_by_id, rewrite_base_id)
            if base_text:
                resume_text = base_text
                await pb.emit_log(pipeline_task_id, "🧾 已启用指定 A/B 底稿：本轮评估与改写均使用该简历")
            else:
                await pb.emit_log(pipeline_task_id, "⚠️ 指定的 A/B 底稿读取失败，回退使用启用简历", "error")

        mass_resume_text = ""
        if mass_resume_id:
            mass_resume_text = await asyncio.to_thread(get_resume_text_by_id, mass_resume_id)
        if not mass_resume_text:
            mass_resume_text = resume_text

        def _get_raw_id_mapping():
            with sqlite3.connect(_get_raw_db_path()) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT rowid, feishu_record_id, job_link FROM raw_jobs WHERE rowid > ?",
                    (start_rowid,)
                ).fetchall()
                rec_to_raw = {}
                for r in rows:
                    if r["feishu_record_id"]:
                        rec_to_raw[r["feishu_record_id"]] = (f"raw_{r['rowid']}", r["job_link"] or "")
                return rec_to_raw

        raw_id_map = await asyncio.to_thread(_get_raw_id_mapping)

        new_jobs = []
        for rid in synced_ids:
            rec = await asyncio.to_thread(get_job_record_from_feishu, rid, TABLE_ID)
            if not rec:
                continue
            f = rec.get("fields", {})
            raw_info = raw_id_map.get(rid, ("", ""))
            raw_jid = raw_info[0]
            raw_link = raw_info[1]
            job_url = _txt(f.get("岗位链接", "")) or raw_link

            new_jobs.append({
                "job_id": rid,
                "record_id": rid,
                "raw_job_id": raw_jid,
                "job_url": job_url,
                "platform": _txt(f.get("招聘平台", "")),
                "company_name": _txt(f.get("公司名称", "")),
                "job_name": _txt(f.get("岗位名称", "")),
                "jd_text": _txt(f.get("岗位详情", "")),
                "salary": _txt(f.get("薪资", "")),
                "city": _txt(f.get("城市", "")),
                "experience": _txt(f.get("经验要求", "")),
                "education": _txt(f.get("学历要求", "")),
                "company_scale": _txt(f.get("公司规模", "")) or "",
                "feishu_fields": f,
                "_created_time": rec.get("created_time", 0),
            })
        await pb.emit_log(
            pipeline_task_id,
            f"📥 本轮新采集 {len(new_jobs)} 条（全自动链只评估本轮；旧存量走人工批量评估）")

        if not new_jobs:
            await _send_task_report([])
            await pb.emit_stage(pipeline_task_id, "done", "done")
            await pb.emit_end(pipeline_task_id, {"jobs": 0})
            complete_autopilot_log(log_task_id, "success", 0, "本轮无新采集岗位")
            return

        dedup_pending_pairs: list = []
        dedup_count: int = 0
        try:
            from app.services.job_dedup_gate import run_dedup_gate
            new_jobs, marked_duplicates, dedup_pending_pairs = await run_dedup_gate(
                new_jobs, log=lambda m: pb.emit_log(pipeline_task_id, m))
            dedup_count = len(marked_duplicates)
        except Exception as e:
            logger.warning(f"[FullAuto] 疑似重复检测异常（不阻断链路，岗位照常评估）: {e}", exc_info=True)

        batch_limit = config.get("batch_limit", 20)
        new_jobs = await build_checked_batch(new_jobs, batch_limit, pipeline_task_id)

        await pb.emit_stage(pipeline_task_id, "evaluating", "running")
        job_results = await _run_jobs_through_graph(
            new_jobs, resume_text, preferences_text, pipeline_task_id,
            mass_resume_text, stop_at_review=stop_at_review
        )

        if dedup_pending_pairs:
            try:
                from app.services.job_dedup_gate import backfill_batch_dup_conclusions
                await backfill_batch_dup_conclusions(
                    dedup_pending_pairs, log=lambda m: pb.emit_log(pipeline_task_id, m))
            except Exception as e:
                logger.warning(f"[FullAuto] 重复岗位母本结论回填异常（不阻断链路）: {e}", exc_info=True)

        await _send_task_report(job_results, dedup_count=dedup_count, rejected_ids=rejected_rowids)

        await pb.emit_stage(pipeline_task_id, "done", "done")
        await pb.emit_end(pipeline_task_id, {"jobs": len(new_jobs)})
        complete_autopilot_log(log_task_id, "success", len(new_jobs), f"已派发 {len(new_jobs)} 个岗位流水线")

    except Exception as e:
        logger.error(f"🚨 [FullAuto] 链路崩溃: {e}", exc_info=True)
        await pb.emit_log(pipeline_task_id, f"🚨 链路异常: {e}", "error")
        try:
            from app.automation import pipeline_report as pr
            fail_lines = [
                "🚨 全链路任务失败通知",
                f"🕐 {started_at.strftime('%Y-%m-%d %H:%M')}",
                f"❌ 失败原因: {str(e)[:200]}",
            ]
            if scrape_counts_cn:
                fail_lines.append("🕷️ 失败前已抓取: " + " · ".join(f"{k} {v}" for k, v in scrape_counts_cn.items()))
            if not config.get("feishu_enable_alert", True):
                logger.info("[FullAuto] 异常告警推送已在飞书面板关闭，跳过发送")
            else:
                await pr.send_pipeline_report("\n".join(fail_lines))
        except Exception as rep_e:
            logger.warning(f"[FullAuto] 失败通知发送异常: {rep_e}")
        await pb.emit_end(pipeline_task_id, {"error": str(e)})
        complete_autopilot_log(log_task_id, "failed", 0, f"执行崩溃: {e}")
    finally:
        try:
            await _reap_orphan_scrapers(pipeline_task_id, timeout=10.0)
        except Exception as reap_e:
            logger.warning(f"[FullAuto] 孤儿清理异常（不阻断收尾）: {reap_e}")
        pb.set_current_pipeline(pipeline_task_id, False)
        from app.automation import abort as abort_mod
        abort_mod.end_pipeline()
        from app.automation import run_snapshot as run_snapshot_mod
        run_snapshot_mod.end()
