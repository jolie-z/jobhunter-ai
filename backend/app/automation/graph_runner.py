"""
LangGraph 图流转执行器
======================
负责：
- 岗位状态字典构建（_build_job_states）
- LangGraph 节点阶段映射（_NODE_STAGE_MAP）
- 多岗位并发图流转（_run_jobs_through_graph）
- 单岗位图流转（_run_single_job_graph）
- 单岗位拉起完整流水线（run_single_job_pipeline_async，支持中断恢复与淘汰放行）
"""
import asyncio
import logging
import sqlite3
import uuid
from typing import Any

from app.automation import pipeline_broadcast as pb
from app.core.feishu_utils import extract_feishu_text as _txt
from app.core.feishu_utils import is_custom_record
from app.services.pipeline_card_builders import extract_job_record_id

logger = logging.getLogger(__name__)


def _get_raw_db_path() -> str:
    import sys
    fa = sys.modules.get("app.automation.full_auto")
    if fa and hasattr(fa, "RAW_DB_PATH"):
        return fa.RAW_DB_PATH
    import os
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "job_hunter.db"
    )


def _build_job_states(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把飞书「新线索」转成岗位 dict 列表（与 scheduler 的字段约定一致）。"""
    return [
        {
            "job_id": lead.get("record_id", ""),
            "record_id": lead.get("record_id", ""),
            "platform": lead.get("platform", ""),
            "company_name": lead.get("company", ""),
            "job_name": lead.get("job_title", ""),
            "jd_text": lead.get("jd_text", ""),
            "salary": lead.get("salary", ""),
            "city": lead.get("city", ""),
            "experience": lead.get("experience", ""),
            "education": lead.get("education", ""),
            "company_scale": lead.get("company_scale") or lead.get("company_size") or lead.get("scale") or _txt(lead.get("_raw_fields", {}).get("公司规模", "")) or "",
            "job_url": lead.get("job_url", "") or lead.get("job_link", ""),
            "feishu_fields": lead.get("_raw_fields", {}),
            "_created_time": lead.get("_created_time", 0),
        }
        for lead in leads
    ]


# LangGraph 节点名 → 全链路阶段 映射（用于实时 job 事件广播）
_NODE_STAGE_MAP = {
    "evaluate_node": ("evaluating", "AI初评"),
    "deep_eval_node": ("deep_eval", "深度评估"),
    "rewrite_node": ("rewriting", "简历改写"),
    "quick_greeting_node": ("greeting", "欢迎语"),
    "greeting_node": ("greeting", "欢迎语"),
    "manual_review_node": ("review", "待审批"),
    "delivery_node": ("delivering", "自动投递"),
}


async def _run_jobs_through_graph(
    new_jobs: list[dict[str, Any]],
    resume_text: str,
    preferences_text: str,
    pipeline_task_id: str,
    mass_resume_text: str = "",
    stop_at_review: bool = False,
) -> list[dict[str, Any]]:
    """为每个岗位开一条 LangGraph 流水线，并把节点流转广播到主队列。返回各岗位最终结果列表。"""
    from app.automation import scheduler

    if not scheduler.pipeline_app:
        await pb.emit_log(pipeline_task_id, "❌ LangGraph 引擎未初始化，评估投递段跳过", "error")
        return []

    tasks = []
    for job in new_jobs:
        from app.automation import abort as abort_mod
        if abort_mod.is_aborted():
            await pb.emit_log(pipeline_task_id, "⛔ 收到终止指令，跳过剩余岗位", "error")
            break
        thread_id = job.get("record_id") or str(uuid.uuid4())
        state_config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "job_id": job.get("job_id", ""),
            "record_id": job.get("record_id", ""),
            "raw_job_id": job.get("raw_job_id", ""),
            "platform": job.get("platform", ""),
            "company_name": job.get("company_name", ""),
            "job_name": job.get("job_name", ""),
            "jd_text": job.get("jd_text", ""),
            "salary": job.get("salary", ""),
            "city": job.get("city", ""),
            "experience": job.get("experience", ""),
            "education": job.get("education", ""),
            "company_scale": job.get("company_scale") or job.get("company_size") or job.get("scale") or "",
            "job_url": job.get("job_url", ""),
            "resume_text": resume_text,
            "mass_resume_text": mass_resume_text or resume_text,
            "preferences_text": preferences_text,
            "company_intel": "",
            "feishu_fields": job.get("feishu_fields", {}),
            "stop_at_review": bool(stop_at_review),
            "pipeline_task_id": pipeline_task_id,
        }
        tasks.append(_run_single_job_graph(initial_state, state_config, pipeline_task_id))

    # 登记本轮进入评估的岗位 ID：jobs-snapshot 据此把看板限定在本轮岗位内（新任务自动覆盖上一轮）
    from app.automation import run_snapshot as _rs
    _rs.register_record_ids([j.get("record_id") for j in new_jobs])

    # 并发跑所有岗位的流水线，收集各自最终结果
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    results = []
    for job, r in zip(new_jobs, raw_results, strict=False):
        job_rid = extract_job_record_id(job)
        if isinstance(r, dict):
            if not r.get("record_id"):
                r["record_id"] = job_rid
            if not r.get("job_id"):
                r["job_id"] = job_rid
            results.append(r)
        else:
            results.append({
                "record_id": job_rid,
                "job_id": job_rid,
                "job_name": job.get("job_name", ""),
                "company_name": job.get("company_name", ""),
                "platform": job.get("platform", ""),
                "grade": "",
                "outcome": "failed",
                "error": str(r) if isinstance(r, Exception) else "流水线异常",
            })
    return results


async def _run_single_job_graph(
    initial_state: dict[str, Any],
    state_config: dict[str, Any],
    pipeline_task_id: str,
    on_node_done: Any | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """跑单个岗位的 LangGraph 流水线，每个节点完成时广播 job 事件。

    resume=True 时 astream 入参传 None：从该 thread_id 的最后一个 checkpoint 续跑
    （节点级持久化，最多重跑中断时正在执行的节点）；initial_state 仍作元数据与后处理上下文。
    """
    from app.automation import scheduler

    job_id = extract_job_record_id(initial_state)
    job_name = initial_state.get("job_name", "")
    platform = initial_state.get("platform", "")
    company_name = initial_state.get("company_name", "")
    salary = initial_state.get("salary", "")
    city = initial_state.get("city", "")
    education = initial_state.get("education", "")
    experience = initial_state.get("experience", "")
    company_scale = initial_state.get("company_scale") or initial_state.get("company_size") or initial_state.get("scale") or ""
    jd_text = initial_state.get("jd_text", "")
    job_url = initial_state.get("job_url", "")
    raw_job_id = initial_state.get("raw_job_id", "")

    common_meta = {
        "company_name": company_name,
        "company_scale": company_scale,
        "salary": salary,
        "city": city,
        "education": education,
        "experience": experience,
        "jd_text": jd_text,
        "job_url": job_url,
        "raw_job_id": raw_job_id,
    }

    try:
        await pb.emit_job(
            pipeline_task_id,
            job_id=job_id,
            job_name=job_name,
            node="evaluate_node",
            status="running",
            sub_status="ai_eval_queued",
            platform=platform,
            **common_meta
        )

        latest_grade = None
        latest_score = None

        async for event in scheduler.pipeline_app.astream(None if resume else initial_state, state_config):
            for node_name, state_update in event.items():
                stage, _label = _NODE_STAGE_MAP.get(node_name, (node_name, node_name))
                if isinstance(state_update, dict):
                    if state_update.get("grade"):
                        latest_grade = state_update.get("grade")
                    if state_update.get("score") is not None:
                        latest_score = state_update.get("score")
                    elif state_update.get("ai_score") is not None:
                        latest_score = state_update.get("ai_score")

                sub_status = "ai_eval"
                if node_name == "deep_eval_node":
                    sub_status = "deep_eval"
                elif node_name == "rewrite_node":
                    sub_status = "rewriting"
                elif node_name in ("quick_greeting_node", "greeting_node"):
                    sub_status = "greeting"

                job_kwargs = {**common_meta}
                if latest_score is not None:
                    job_kwargs["score"] = latest_score

                # 节点完成即点亮对应阶段（轨道推进），再广播岗位级事件
                if node_name in _NODE_STAGE_MAP:
                    await pb.emit_stage(pipeline_task_id, stage, "running")
                await pb.emit_job(
                    pipeline_task_id,
                    job_id=job_id,
                    job_name=job_name,
                    node=node_name,
                    status="done",
                    sub_status=sub_status,
                    grade=latest_grade,
                    platform=platform,
                    **job_kwargs
                )
                logger.info(f"  └─ [FullAuto] 岗位 {job_name} 节点完成: {node_name}")
                if on_node_done:
                    try:
                        await on_node_done(node_name, state_update if isinstance(state_update, dict) else {})
                    except Exception as cb_err:
                        logger.warning(f"[FullAuto] on_node_done 回调异常（不影响流水线）: {cb_err}")

        # 检查是否被审批断点拦截，并汇总最终结果（供任务报告）
        snapshot = await scheduler.pipeline_app.aget_state(state_config)
        final_vals = snapshot.values or {}
        final_grade = final_vals.get("grade") or latest_grade or ""
        final_score = final_vals.get("score") or final_vals.get("ai_score") or latest_score
        final_fields = final_vals.get("feishu_fields") or initial_state.get("feishu_fields") or {}
        review_type = "custom_tailored" if (
            final_vals.get("final_markdown")
            or is_custom_record(final_fields)
        ) else "mass_apply"

        base = {
            "record_id": job_id,
            "job_id": job_id,
            "job_name": job_name,
            "company_name": company_name,
            "platform": platform,
            "grade": final_grade,
        }
        if snapshot.next and snapshot.next[0] == "manual_review_node":
            review_kwargs = {**common_meta}
            if final_score is not None:
                review_kwargs["score"] = final_score

            await pb.emit_job(
                pipeline_task_id,
                job_id=job_id,
                job_name=job_name,
                node="manual_review_node",
                status="waiting",
                grade=final_grade,
                review_type=review_type,
                platform=platform,
                **review_kwargs
            )
            logger.info(f"⏸️ [FullAuto] 岗位 {job_name} 停在审批断点，等待老板放行")
            # 🌟 持久化到飞书：确保进入审批断点的岗位在飞书同步记录跟进状态，刷新页面不丢失（5s超时保护，绝不阻塞状态机）
            try:
                from app.services.feishu_service import update_feishu_record
                target_status = "简历人工复核" if review_type == "custom_tailored" else "海投人工复核"
                await asyncio.wait_for(
                    asyncio.to_thread(update_feishu_record, job_id, {"跟进状态": target_status}),
                    timeout=5.0
                )
            except Exception as e:
                logger.warning(f"⚠️ [FullAuto] 断点同步飞书跟进状态异常或超时: {e}")
            # 定时链路（stop_at_review）：登记进海投发射池，供每日「海投发射时间」消费。
            if initial_state.get("stop_at_review"):
                from app.automation.db import add_jobs_to_pending_pool
                add_jobs_to_pending_pool([{
                    "record_id": initial_state.get("record_id") or state_config["configurable"]["thread_id"],
                    "job_name": job_name,
                    "company_name": company_name,
                    "platform": platform,
                    "grade": final_grade,
                    "task_id": pipeline_task_id,
                }])
            return {**base, "outcome": "waiting", "error": ""}

        # 图跑完≠投递成功：delivery_node 失败时会把原因写进 state.error
        if final_vals.get("error"):
            err_msg = str(final_vals.get("error"))
            await pb.emit_job(
                pipeline_task_id,
                job_id=job_id,
                job_name=job_name,
                node="delivery_node",
                status="error",
                grade=final_grade,
                platform=platform,
                failure_info={
                    "step": "自动投递阶段",
                    "reason": err_msg,
                    "suggestion": "建议检查目标平台浏览器会话与登录态，并在确认后点击重启。",
                    "can_retry": True
                },
                **common_meta
            )
            logger.warning(f"❌ [FullAuto] 岗位 {job_name} 投递失败: {err_msg}")
            return {**base, "outcome": "failed", "error": err_msg}

        if final_vals.get("status") == "已投递":
            # 投递物料判定
            f_fields = initial_state.get("feishu_fields", {})
            from app.core.utils import (
                is_greeting_supported_platform,
                normalize_platform_code,
            )
            norm_plat = normalize_platform_code(platform)
            is_greet_plat = is_greeting_supported_platform(norm_plat)
            # 🌟 BOSS 微聊只发长图，PDF 备份仅为归档母本，不得向实时流水线推送为已送达物料
            has_pdf = False if norm_plat == "boss" else bool(f_fields.get("PDF备份") or f_fields.get("PDF 备份"))
            has_img = False if norm_plat in ("zhilian", "51job", "liepin") else bool(f_fields.get("图片保存"))
            has_greet = bool(is_greet_plat and (final_vals.get("greeting_message") or final_vals.get("greeting")))

            await pb.emit_job(
                pipeline_task_id,
                job_id=job_id,
                job_name=job_name,
                node="delivery_node",
                status="delivered",
                grade=final_grade,
                platform=platform,
                delivery_materials={
                    "pdf": has_pdf,
                    "image": has_img,
                    "greeting": has_greet,
                    "greeting_failed": bool(is_greet_plat and not has_greet and final_vals.get("greeting_failed")),
                },
                **common_meta
            )
            return {**base, "outcome": "delivered", "error": ""}

        # 其余：路由提前 END（如 D/F 级岗位停在已完成初评、或海投门槛拦截等）
        await pb.emit_job(
            pipeline_task_id,
            job_id=job_id,
            job_name=job_name,
            node="evaluate_node",
            status="done",
            sub_status="eval_done",
            grade=final_grade,
            platform=platform,
            **common_meta
        )
        return {**base, "outcome": "stopped", "error": final_vals.get("status", "")}

    except Exception as e:
        logger.error(f"❌ [FullAuto] 岗位 {job_name} 流水线异常: {e}", exc_info=True)
        await pb.emit_job(
            pipeline_task_id,
            job_id=job_id,
            job_name=job_name,
            node="error",
            status="error",
            platform=platform,
            failure_info={
                "step": "流水线异常",
                "reason": str(e),
                "suggestion": "请查看白盒日志详情，排查是否由于 LLM 超时或网络异常中断。",
                "can_retry": True
            },
            **common_meta
        )
        return {
            "job_name": job_name,
            "company_name": company_name,
            "platform": platform,
            "grade": "",
            "outcome": "failed",
            "error": str(e)[:100],
        }


async def run_single_job_pipeline_async(
    record_id: str,
    raw_rowid: str | None = None,
    pipeline_task_id: str | None = None,
    stop_at_review: bool = False,
    on_node_done: Any | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """单岗位拉起 LangGraph 评估/流转流水线（用于淘汰岗位放行或单条手动评估）

    on_node_done: 可选异步回调 on_node_done(node_name, state_update)，每个图节点完成时调用。
    resume: True 时从该 record_id 的 LangGraph checkpoint 续跑（服务重启后的中断恢复路径），
            setup 与后处理照常执行，仅图输入改为 None。
    """
    from app.automation import run_snapshot as _rs
    from app.automation.db import get_autopilot_config
    from app.services.feishu_service import (
        TABLE_ID,
        get_active_resume_from_feishu,
        get_job_record_from_feishu,
        get_my_preferences,
        get_resume_text_by_id,
    )

    if not pipeline_task_id:
        cur = pb.get_current_pipeline()
        pipeline_task_id = cur.get("task_id") or f"unreject_{uuid.uuid4().hex[:8]}"

    logger.info(f"🚀 [UnrejectPipeline] 启动单岗位 LangGraph 评估流水线: record_id={record_id}, raw_rowid={raw_rowid}, task_id={pipeline_task_id}")

    # 1. 获取岗位详情（raw_ 重试场景 record_id 为空，直接跳过飞书查询）
    rec = await asyncio.to_thread(get_job_record_from_feishu, record_id, TABLE_ID) if record_id else None
    feishu_fields = rec.get("fields", {}) if rec else {}

    company_name = _txt(feishu_fields.get("公司名称", ""))
    job_name = _txt(feishu_fields.get("岗位名称", ""))
    platform = _txt(feishu_fields.get("招聘平台", ""))
    jd_text = _txt(feishu_fields.get("岗位详情", ""))
    salary = _txt(feishu_fields.get("薪资", ""))
    city = _txt(feishu_fields.get("城市", ""))
    experience = _txt(feishu_fields.get("经验要求", ""))
    education = _txt(feishu_fields.get("学历要求", ""))
    job_url = _txt(feishu_fields.get("岗位链接", ""))

    # 如果飞书字段不全，尝试从 SQLite 补全
    if raw_rowid and (not job_name or not company_name or not jd_text):
        try:
            with sqlite3.connect(_get_raw_db_path()) as _conn:
                _conn.row_factory = sqlite3.Row
                clean_rowid = int(str(raw_rowid).replace("raw_", ""))
                _r = _conn.execute("SELECT * FROM raw_jobs WHERE rowid = ?", (clean_rowid,)).fetchone()
                if _r:
                    company_name = company_name or _r["company_name"] or ""
                    job_name = job_name or _r["job_title"] or ""
                    platform = platform or _r["platform"] or ""
                    jd_text = jd_text or _r["jd_text"] or ""
                    salary = salary or _r["salary"] or ""
                    city = city or _r["city"] or ""
                    experience = experience or _r["experience_req"] or ""
                    education = education or _r["education_req"] or ""
                    job_url = job_url or _r["job_link"] or ""
        except Exception as _e:
            logger.warning(f"[UnrejectPipeline] 从 SQLite 补齐字段异常: {_e}")

    # 2. 获取简历与配置
    config = get_autopilot_config()
    resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
    preferences_text = await asyncio.to_thread(get_my_preferences)

    # A/B 改写底稿
    rewrite_base_id = (config.get("rewrite_base_resume_id") or "").strip()
    if rewrite_base_id:
        base_text = await asyncio.to_thread(get_resume_text_by_id, rewrite_base_id)
        if base_text:
            resume_text = base_text

    mass_resume_id = (config.get("mass_apply_resume_id") or "").strip()
    mass_resume_text = ""
    if mass_resume_id:
        mass_resume_text = await asyncio.to_thread(get_resume_text_by_id, mass_resume_id)
    if not mass_resume_text:
        mass_resume_text = resume_text

    # 3. 注册到 run_snapshot，供 jobs_snapshot 快照轮询追踪
    if record_id:
        _rs.register_record_ids([record_id])

    raw_jid = f"raw_{raw_rowid}" if raw_rowid and not str(raw_rowid).startswith("raw_") else (raw_rowid or "")

    initial_state = {
        "job_id": record_id,
        "record_id": record_id,
        "raw_job_id": raw_jid,
        "platform": platform,
        "company_name": company_name,
        "job_name": job_name,
        "jd_text": jd_text,
        "salary": salary,
        "city": city,
        "experience": experience,
        "education": education,
        "job_url": job_url,
        "resume_text": resume_text or "",
        "mass_resume_text": mass_resume_text or resume_text or "",
        "preferences_text": preferences_text or "",
        "company_intel": "",
        "feishu_fields": feishu_fields,
        "stop_at_review": bool(stop_at_review),
        "pipeline_task_id": pipeline_task_id,
    }
    state_config = {"configurable": {"thread_id": record_id}}

    logger.info(f"🧠 [白盒日志] 正在为【{company_name} - {job_name}】执行 AI 评估与流水线流转...")
    res = await _run_single_job_graph(initial_state, state_config, pipeline_task_id, on_node_done=on_node_done, resume=resume)
    logger.info(f"🏁 [白盒日志] 【{company_name} - {job_name}】单岗位流转完成，结果: {res}")
    return res
