import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import common.config as _ccfg
from ai_agents.ai_evaluator import evaluate_single_job
from ai_agents.ai_scorer import deep_evaluate_resume
from ai_agents.engine_facade import process_resume_rewrite

# 🌟 修复 2：从底层 utils 导入文本提取工具
from app.core.feishu_utils import extract_feishu_text, is_custom_record
from app.core.utils import sanitize_filename

# 🌟 修复 1：去掉不存在的 feishu_api，导入真实的独立函数
from app.services.feishu_service import (
    extract_record_id,
    get_active_resume_from_feishu,
    get_job_record_from_feishu,
    get_mass_apply_resume_record_id,
    get_my_preferences,  # 新增导入偏好获取函数
    update_feishu_record,
)
from app.tasks.state import (
    GLOBAL_TASK_STATE,
    global_task_lock,
    schedule_task_cleanup,
    task_status,
)

# 🌟 核心修复：通过内置库动态计算出 backend 目录作为 BASE_DIR，彻底摆脱依赖
BASE_DIR = Path(__file__).resolve().parent.parent.parent

from app.services.search_service import research_company_serper  # noqa: E402

logger = logging.getLogger(__name__)

# ================= 优化：提取常量 =================
ERR_AI_FORMAT = "  ⚠️ AI 返回格式异常，已触发自动纠偏或跳过"

FIELD_RATING = "综合评级 (A-F)"
FIELD_AI_DETAIL = "AI评估详情"
FIELD_DREAM_PIC = "理想画像与能力信号"
FIELD_CORE_DICT = "核心能力词典"
FIELD_HIGH_LEV = "高杠杆匹配点"
FIELD_RED_FLAGS = "致命硬伤与毒点"
FIELD_ACTION_PLAN = "破局行动计划"
FIELD_CORE_MATCH = "核心-角色匹配"
FIELD_SALARY_MATCH = "高权-薪资契合"

STATUS_MANUAL_REVIEW = "简历人工复核"
STATUS_DEEP_EVAL_DONE = "已完成深度评估"
STATUS_TO_DELIVER = "待投递"
STATUS_DELIVERED = "已投递"
# ===================================================

async def send_sse_msg(queue: asyncio.Queue, msg_type: str, message: str, **kwargs):
    payload = {"type": msg_type, "message": message}
    payload.update(kwargs)
    await queue.put(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

async def _handle_evaluate(job_id: str, record_id: str, platform: str, company_name: str, job_name: str, jd_text: str, salary: str, city: str, experience: str, education: str, resume_text: str, preferences_text: str, queue: asyncio.Queue):
    await send_sse_msg(queue, "info", f"  🔍 正在背调【{company_name}】公司情报...")
    company_intel = await research_company_serper(company_name)
    await send_sse_msg(queue, "info", "  🧠 正在呼叫 LLM 进行深度评估...")

    job_data = {
        "record_id": record_id,
        "table_id": _ccfg.FEISHU_TABLE_ID_JOBS,
        "platform": platform,
        "company": company_name,
        "job_title": job_name,
        "jd_text": jd_text,
        "salary": salary,
        "city": city,
        "experience": experience,
        "education": education,
    }

    loop = asyncio.get_running_loop()

    def progress_callback(info: dict):
        try:
            msg = info.get("message", "")
            stage = info.get("stage", 1)
            total_stages = info.get("total_stages", 4)
            stage_title = info.get("title", "")
            asyncio.run_coroutine_threadsafe(
                send_sse_msg(
                    queue,
                    "progress",
                    msg,
                    job_id=job_id,
                    record_id=record_id,
                    sub_stage=stage,
                    total_stages=total_stages,
                    stage_title=stage_title,
                ),
                loop,
            )
        except Exception as e:
            print(f"⚠️ [progress_callback] 推送异常: {e}")

    import time
    start_time = time.time()

    try:
        result = await asyncio.to_thread(
            evaluate_single_job,
            job_data,
            resume_text,
            company_intel,
            preferences_text,
            "auto",
            progress_callback,
        )
    except ValueError as ve:
        # B5：AI 返回格式异常同样按岗位失败抛出，不能 return None 让主循环虚报 success
        await send_sse_msg(queue, "error", ERR_AI_FORMAT, job_id=job_id)
        raise RuntimeError(f"AI 返回格式异常: {ve}") from ve

    elapsed_time = time.time() - start_time

    if result["success"]:
        ai_score = result.get("ai_score", 0)
        target_status = result.get("status", "待人工评估")
        usage = result.get("usage", {})
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        tt = usage.get("total_tokens", 0)

        await send_sse_msg(queue, "info", f"📈 Token 消耗 → 提示: {pt} / 补全: {ct}", job_id=job_id)
        await send_sse_msg(queue, "info", f"  📊 诊断报告已出！AI 综合得分: {ai_score}分 (耗时 {elapsed_time:.1f}s)", usage={"prompt": pt, "completion": ct, "total": tt})
        await send_sse_msg(queue, "info", "  ☁️ 正在将评估结果回写到飞书...")

        update_success = await asyncio.to_thread(
            update_feishu_record,
            record_id,
            result["update_data"],
            _ccfg.FEISHU_TABLE_ID_JOBS
        )

        if update_success:
            job_updates = {"followStatus": target_status, "aiScore": ai_score, "grade": result.get("grade", "")}
            await send_sse_msg(
                queue,
                "progress",
                f"  ✅ 评估完成，状态已更新为: {target_status}",
                job_id=job_id,
                record_id=record_id,
                sub_stage=4,
                total_stages=4,
                stage_title="已完成",
            )
            await send_sse_msg(queue, "info", f"  ✅ 评估完成，状态已更新为: {target_status}", usage={"prompt": pt, "completion": ct, "total": tt})
            rationales_text = result.get("rationales_text", "")
            if rationales_text:
                for dim_block in rationales_text.split("\n\n")[:10]:
                    await send_sse_msg(queue, "info", f"[诊断] {dim_block}")
            return job_updates
        else:
            # B5：回写飞书失败必须按岗位失败处理并抛出，主循环虚报 success 会瞒报丢结果
            raise RuntimeError("评估结果回写飞书失败，本岗位评估结果未保存")
    else:
        raise RuntimeError(result.get("error", "评估失败"))

# Optimization: Removed unused `platform` and `company_name` parameters
async def _handle_rewrite(job_id: str, record_id: str, job_name: str, jd_text: str, fields: dict, resume_text: str, queue: asyncio.Queue):
    await send_sse_msg(queue, "info", "  🧠 正在构思高情商打招呼语...")
    await send_sse_msg(queue, "info", "  📝 正在根据 JD 生成 Markdown 定制简历...")

    import time
    start_time = time.time()

    diagnosis_dict = {
        FIELD_RATING: extract_feishu_text(fields.get(FIELD_RATING, "")),
        FIELD_AI_DETAIL: extract_feishu_text(fields.get(FIELD_AI_DETAIL, "")),
        FIELD_DREAM_PIC: extract_feishu_text(fields.get(FIELD_DREAM_PIC, "")),
        FIELD_CORE_DICT: extract_feishu_text(fields.get(FIELD_CORE_DICT, "")),
        FIELD_HIGH_LEV: extract_feishu_text(fields.get(FIELD_HIGH_LEV, "")),
        FIELD_RED_FLAGS: extract_feishu_text(fields.get(FIELD_RED_FLAGS, "")),
        FIELD_ACTION_PLAN: extract_feishu_text(fields.get(FIELD_ACTION_PLAN, "")),
    }

    try:
        md_resume, rewrite_usage = await asyncio.to_thread(
            process_resume_rewrite,
            jd_text,
            diagnosis_dict,
            job_name
        )
    except ValueError as ve:
        # B5：AI 返回格式异常同样按岗位失败抛出，不能 return None 让主循环虚报 success
        await send_sse_msg(queue, "error", ERR_AI_FORMAT, job_id=job_id)
        raise RuntimeError(f"AI 返回格式异常: {ve}") from ve

    from ai_agents.engine_facade import process_greeting_generation
    try:
        greeting, greeting_usage = await asyncio.to_thread(
            process_greeting_generation,
            jd_text,
            diagnosis_dict,
            resume_text,
            job_name
        )
    except ValueError as ve:
        # B7：greeting 与简历本体的 AI 格式异常分别归类报错，避免笼统的「或简历失败」掩盖真实环节
        await send_sse_msg(queue, "error", ERR_AI_FORMAT, job_id=job_id)
        raise RuntimeError(f"打招呼语生成环节 AI 返回格式异常: {ve}") from ve
    except Exception as ge:
        raise RuntimeError(f"打招呼语生成环节异常: {ge}") from ge

    elapsed_time = time.time() - start_time

    rw_pt = (rewrite_usage.get("prompt_tokens", 0) if rewrite_usage else 0) + (greeting_usage.get("prompt_tokens", 0) if greeting_usage else 0)
    rw_ct = (rewrite_usage.get("completion_tokens", 0) if rewrite_usage else 0) + (greeting_usage.get("completion_tokens", 0) if greeting_usage else 0)
    rw_tt = (rewrite_usage.get("total_tokens", 0) if rewrite_usage else 0) + (greeting_usage.get("total_tokens", 0) if greeting_usage else 0)

    await send_sse_msg(queue, "info", f"📈 Token 消耗 → 提示: {rw_pt} / 补全: {rw_ct} / 总计: {rw_tt}", job_id=job_id)

    if md_resume and greeting:
        await send_sse_msg(
            queue,
            "info",
            f"  ✓ 改写完成 (耗时 {elapsed_time:.1f}s)",
            usage={"prompt": rw_pt, "completion": rw_ct, "total": rw_tt}
        )

        from ai_agents.markdown_to_json import convert_and_stitch_resume
        stitched_json_str = convert_and_stitch_resume(md_resume)

        fields_to_update = {
            "打招呼语": greeting,
            "AI改写JSON": stitched_json_str,
            "跟进状态": STATUS_MANUAL_REVIEW
        }

        await send_sse_msg(queue, "info", "  ☁️ 正在将打招呼语与 AI 改写 Markdown 写回飞书...")

        update_success = await asyncio.to_thread(
            update_feishu_record,
            record_id,
            fields_to_update,
            _ccfg.FEISHU_TABLE_ID_JOBS
        )

        if update_success:
            await send_sse_msg(queue, "info", f"  ✅ 简历改写完成，状态已更新为: {STATUS_MANUAL_REVIEW}")
            return {"followStatus": STATUS_MANUAL_REVIEW}
        else:
            # B5：回写飞书失败必须按岗位失败处理并抛出，主循环虚报 success 会瞒报丢结果
            raise RuntimeError("改写结果回写飞书失败，本岗位改写结果未保存")
    else:
        raise RuntimeError("AI 生成打招呼语或简历失败")

async def _handle_deep_evaluate(job_id: str, record_id: str, jd_text: str, salary: str, city: str, experience: str, education: str, fields: dict, resume_text: str, queue: asyncio.Queue):
    await send_sse_msg(queue, "info", "  🧠 正在进行深度评估与破局计划生成...")

    full_jd_info = (
        f"【岗位基本信息】\n"
        f"薪资范围: {salary} | 工作城市: {city} | 经验要求: {experience} | 学历要求: {education}\n\n"
        f"【岗位详情】\n{jd_text}"
    )

    first_stage_scores = {
        FIELD_RATING: extract_feishu_text(fields.get(FIELD_RATING, "")),
        FIELD_CORE_MATCH: fields.get(FIELD_CORE_MATCH),
        FIELD_SALARY_MATCH: fields.get(FIELD_SALARY_MATCH),
        FIELD_AI_DETAIL: extract_feishu_text(fields.get(FIELD_AI_DETAIL, "")),
    }

    import time
    start_time = time.time()

    try:
        deep_result, deep_usage = await asyncio.to_thread(
            deep_evaluate_resume,
            resume_text,
            full_jd_info,
            first_stage_scores
        )
    except ValueError as ve:
        # B5：AI 返回格式异常同样按岗位失败抛出，不能 return None 让主循环虚报 success
        await send_sse_msg(queue, "error", ERR_AI_FORMAT, job_id=job_id)
        raise RuntimeError(f"AI 返回格式异常: {ve}") from ve

    elapsed_time = time.time() - start_time
    pt = deep_usage.get("prompt_tokens", 0)
    ct = deep_usage.get("completion_tokens", 0)
    tt = deep_usage.get("total_tokens", 0)

    await send_sse_msg(queue, "info", f"📈 Token 消耗 → 提示: {pt} / 补全: {ct}", job_id=job_id)
    await send_sse_msg(queue, "info", f"  ✓ 深度评估完成 (耗时 {elapsed_time:.1f}s)", usage={"prompt": pt, "completion": ct, "total": tt})

    extracted = deep_result.get("extracted_skills", [])
    extracted_str = "、".join(extracted) if isinstance(extracted, list) else str(extracted)

    fields_to_update = {
        FIELD_DREAM_PIC: str(deep_result.get("dream_picture", "") or deep_result.get(FIELD_DREAM_PIC, "")),
        FIELD_CORE_DICT: str(deep_result.get("ats_ability_analysis", "") or deep_result.get(FIELD_CORE_DICT, "")),
        "简历逐行审计": str(deep_result.get("resume_audit", "")),
        FIELD_HIGH_LEV: str(deep_result.get("strong_fit_assessment", "") or deep_result.get(FIELD_HIGH_LEV, "")),
        FIELD_RED_FLAGS: str(deep_result.get("risk_red_flags", "") or deep_result.get(FIELD_RED_FLAGS, "")),
        FIELD_ACTION_PLAN: str(deep_result.get("deep_action_plan", "") or deep_result.get(FIELD_ACTION_PLAN, "")),
        "跟进状态": STATUS_DEEP_EVAL_DONE,
    }
    if extracted_str:
        fields_to_update[FIELD_CORE_DICT] = (
            f"【核心技能词条】{extracted_str}\n\n"
            + fields_to_update[FIELD_CORE_DICT]
        )

    await send_sse_msg(queue, "info", "  ☁️ 正在将深度评估结果回写到飞书...")

    update_success = await asyncio.to_thread(
        update_feishu_record,
        record_id,
        fields_to_update,
        _ccfg.FEISHU_TABLE_ID_JOBS
    )

    if update_success:
        await send_sse_msg(queue, "info", f"  ✅ 深度评估完成，状态已更新为: {STATUS_DEEP_EVAL_DONE}")
        return {"followStatus": STATUS_DEEP_EVAL_DONE}
    else:
        # B5：回写飞书失败必须按岗位失败处理并抛出，主循环虚报 success 会瞒报丢结果
        raise RuntimeError("深度评估结果回写飞书失败，本岗位深评结果未保存")

# Optimization: helper function for scheduling
def _parse_scheduled_time(scheduled_at: str) -> int:
    try:
        dt = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError(f"无效的时间格式: {scheduled_at}")

    tz_beijing = timezone(timedelta(hours=8))
    dt = dt.replace(tzinfo=tz_beijing)
    return int(dt.timestamp() * 1000)

def _extract_delivery_materials(fields: dict) -> tuple[str, str, list, str, str]:
    pdf_attachments = fields.get("PDF备份", [])
    file_token = ""
    pdf_name = "专属定制简历"
    if pdf_attachments and isinstance(pdf_attachments, list) and len(pdf_attachments) > 0:
        file_token = pdf_attachments[0].get("file_token", "")
        pdf_name = pdf_attachments[0].get("name", "专属定制简历").replace(".pdf", "")

    image_attachments = fields.get("图片保存", []) or []
    image_items = []
    if isinstance(image_attachments, list):
        for att in image_attachments:
            token = att.get("file_token", "")
            if token:
                image_items.append({"token": token, "name": att.get("name", "image.jpg")})

    job_link_obj = fields.get("岗位链接", {})
    job_url = job_link_obj.get("link", "") if isinstance(job_link_obj, dict) else str(job_link_obj)

    greeting = extract_feishu_text(fields.get("打招呼语", ""))
    return file_token, pdf_name, image_items, job_url, greeting

async def _dispatch_to_platform(queue: asyncio.Queue, platform: str, job_data: dict) -> dict | None:
    from app.automation.workflow import delivery_node

    # 🌟 统一收口至 delivery_node：复用全局串行锁 (_delivery_serial_lock)
    # 与在途防重集合 (_DELIVERY_INFLIGHT_RECORD_IDS)，彻底根治旁路并发抢占浏览器与同岗双投敞口
    mock_state = {
        "job_id": job_data.get("record_id", ""),
        "record_id": job_data.get("record_id", ""),
        "platform": platform,
        "job_url": job_data.get("job_url", ""),
        "file_token": job_data.get("file_token", ""),
        "pdf_filename": job_data.get("pdf_name", ""),
        "greeting": job_data.get("greeting", ""),
        "image_items": job_data.get("image_items", []),
        "company_name": job_data.get("company_name", ""),
        "job_name": job_data.get("job_name", ""),
        "grade": "C",
        "is_custom": True,
        "feishu_fields": job_data.get("feishu_fields") or {},
    }
    await send_sse_msg(queue, "info", f"  🎯 统一管线接入：调用 [{platform}] 投递节点（已启用全局串行与在途锁防护）...")
    res = await delivery_node(mock_state)
    if res.get("status") == "已投递":
        await send_sse_msg(queue, "info", f"  ✅ 投递成功，状态已更新为: {STATUS_DELIVERED}")
        return {"followStatus": STATUS_DELIVERED}
    else:
        err_text = str(res.get("error") or "投递引擎执行失败，请检查控制台日志了解详情")
        raise RuntimeError(err_text)

# Optimization: removed unused job_id parameter
async def _handle_deliver(record_id: str, platform: str, fields: dict, scheduled_at: str | None, queue: asyncio.Queue):
    if scheduled_at:
        timestamp_ms = _parse_scheduled_time(scheduled_at)
        ok = update_feishu_record(record_id, {
            "定时投递时间": timestamp_ms,
            "跟进状态": STATUS_TO_DELIVER
        }, _ccfg.FEISHU_TABLE_ID_JOBS)
        if not ok:
            raise RuntimeError(f"双保险写入失败：无法将 {record_id} 的定时投递信息写入飞书，请重试")
        await send_sse_msg(queue, "info", f"  ⏰ 定时投递已登记：{scheduled_at}，调度器将在到达时间后自动执行")
        return {"followStatus": STATUS_TO_DELIVER}

    # Optimization: Fix f-string warning
    await send_sse_msg(queue, "info", "  🚀 正在准备自动投递物料...")

    file_token, pdf_name, image_items, job_url, greeting = _extract_delivery_materials(fields)

    if not job_url:
        raise ValueError("❌ 数据不全：缺少 [岗位链接]，无法执行投递")

    platform_lower = platform.lower()
    is_boss = "boss" in platform_lower
    is_liepin = "liepin" in platform_lower or "猎聘" in platform
    is_zhilian = "zhilian" in platform_lower or "智联" in platform
    is_51job = "51job" in platform_lower or "前程" in platform

    if is_boss:
        if not image_items:
            raise ValueError("❌ BOSS直聘物料不全：缺少 [图片保存]，请在定制面板保存图片简历")
        if not greeting:
            raise ValueError("❌ BOSS直聘物料不全：缺少 [打招呼语]，无法执行微聊投递")
    elif is_liepin or is_zhilian:
        plat_name = "猎聘" if is_liepin else "智联招聘"
        if not file_token:
            raise ValueError(f"❌ {plat_name}物料不全：缺少 [PDF备份]，请在定制面板保存 PDF 简历")
        if not greeting:
            raise ValueError(f"❌ {plat_name}物料不全：缺少 [打招呼语]，无法执行投递")
    elif is_51job:
        if not file_token:
            raise ValueError("❌ 51job物料不全：缺少 [PDF备份]，请在定制面板保存 PDF 简历")
    else:
        if not (file_token or image_items):
            raise ValueError("❌ 数据不全：缺少 [PDF备份或图片简历]，无法执行投递")

    company = extract_feishu_text(fields.get("公司名称", "")) or ""
    job_title = extract_feishu_text(fields.get("岗位名称", "")) or ""

    job_data = {
        "record_id": record_id,
        "job_url": job_url,
        "file_token": file_token,
        "pdf_name": pdf_name,
        "greeting": greeting,
        "image_items": image_items,
        "feishu_fields": fields,
        "company_name": company,
        "job_name": job_title,
    }

    return await _dispatch_to_platform(queue, platform, job_data)

# 🌟 海投批量投递：直接拉取海投简历物料（PDF+长图）按平台形态投递，
# 不走评估/改写；成功后把海投物料覆盖回写飞书「PDF备份/图片保存」做归档
async def _handle_mass_apply(record_id: str, platform: str, fields: dict, mats: dict, greeting: str, queue: asyncio.Queue, job_id: str = ""):
    job_title = extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位"
    company = extract_feishu_text(fields.get("公司名称", "")) or "未知公司"
    pdf_name = f"{company}_{job_title}.pdf"
    target_jid = job_id or record_id

    await send_sse_msg(queue, "progress", f"正在为【{company} · {job_title}】校验母本...",
                       job_id=target_jid, record_id=record_id, sub_stage=1, total_stages=4, stage_title="母本校验")
    await send_sse_msg(queue, "info", f"  🎨 正在为【{company} · {job_title}】装配高保真海投物料（PDF+长图+通用招呼语）...")

    from app.automation.db import get_autopilot_config
    from app.automation.materials import _render_mass_resume_materials_with_name
    cfg = get_autopilot_config()
    mass_resume_id = cfg.get("mass_apply_resume_id") or ""

    await send_sse_msg(queue, "progress", f"正在为【{company} · {job_title}】渲染高保真物料...",
                       job_id=target_jid, record_id=record_id, sub_stage=2, total_stages=4, stage_title="高清渲染")

    # 优先生成专属命名的母本高保真物料（与页面预览 100% 像素级对齐）
    materials_res = await _render_mass_resume_materials_with_name(mass_resume_id, pdf_name)
    if not materials_res:
        materials_res = mats

    await send_sse_msg(queue, "progress", "正在装配招呼语与物料附件...",
                       job_id=target_jid, record_id=record_id, sub_stage=3, total_stages=4, stage_title="招呼装配")

    patch: dict[str, Any] = {
        "跟进状态": "待投递",
    }
    if materials_res and materials_res.get("pdf_token"):
        patch["PDF备份"] = [{"file_token": materials_res["pdf_token"], "name": f"{company}_{job_title}.pdf"}]
    if materials_res and materials_res.get("img_token"):
        patch["图片保存"] = [{"file_token": materials_res["img_token"], "name": f"{company}_{job_title}-长图.jpg"}]

    if "51job" not in platform.lower() and "前程" not in platform and greeting:
        patch["打招呼语"] = greeting

    # B5 同口径：回写飞书失败必须按岗位失败抛出，不能虚报 success 让岗位永远进不了待投递队列
    update_ok = await asyncio.to_thread(update_feishu_record, record_id, patch, _ccfg.FEISHU_TABLE_ID_JOBS)
    if not update_ok:
        raise RuntimeError(f"海投物料/状态回写飞书失败，岗位 {record_id} 未入队「待投递」，请重试")
    try:
        from app.automation.routes.delivery_router import _mark_approved_guarded
        await asyncio.to_thread(_mark_approved_guarded, record_id)
    except Exception as e:
        logger.warning(f"标记审批放行异常: {e}")

    await send_sse_msg(queue, "progress", "装配完成，已进入待投递队列",
                       job_id=target_jid, record_id=record_id, sub_stage=4, total_stages=4, stage_title="入队待投")
    await send_sse_msg(queue, "info", f"  ✅【{company} · {job_title}】物料装配完毕，已进入「待投递」队列")
    return {"status": "success", "record_id": record_id}

# 🌟 批量批准投递处理器：物料三要素质检 + 缺料秒级自愈（生成专属PDF/长图）+ 飞书跟进状态流转为「待投递」
async def _handle_approve(record_id: str, platform: str, fields: dict, queue: asyncio.Queue, job_id: str = "") -> dict:
    job_title = extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位"
    company_name = extract_feishu_text(fields.get("公司名称", "")) or "未知公司"
    target_jid = job_id or record_id
    pdf_name = f"{sanitize_filename(company_name)}_{sanitize_filename(job_title)}.pdf"

    # 阶段 1：物料校验
    await send_sse_msg(queue, "progress", f"正在为【{company_name} · {job_title}】核验投递物料...",
                       job_id=target_jid, record_id=record_id, sub_stage=1, total_stages=4, stage_title="物料校验")

    raw_custom_json = extract_feishu_text(fields.get("AI改写JSON", "")).strip()
    # 🌟 统一精投判定口径（is_custom_record），与 auto-heal/投递编排同源；
    # 此前 startswith("{") 曾把 markdown 降级存的定制改写误判成海投而覆盖定制物料
    is_custom = is_custom_record(fields)

    pdf_attachments = fields.get("PDF备份", [])
    has_valid_pdf = bool(isinstance(pdf_attachments, list) and len(pdf_attachments) > 0 and pdf_attachments[0].get("file_token"))
    img_attachments = fields.get("图片保存", [])
    has_valid_img = bool(isinstance(img_attachments, list) and len(img_attachments) > 0 and img_attachments[0].get("file_token"))
    greeting = extract_feishu_text(fields.get("打招呼语", "")).strip()

    patch_fields: dict[str, Any] = {}

    # 🌟 防脏物料穿透（与 auto-heal 同口径）：精投岗挂着「我的简历/通用简历」这类海投命名 PDF，
    # 或挂了别的岗位的定制简历时，必须重渲染定制简历，不得当合规物料直接批准入队
    existing_pdf_name = pdf_attachments[0].get("name", "") if has_valid_pdf else ""
    is_stale_custom_pdf = is_custom and has_valid_pdf and (
        existing_pdf_name.startswith(("我的简历", "通用简历", "海投简历", "e2e_base"))
        or not existing_pdf_name.startswith((pdf_name[:-4], f"{company_name}_{job_title}"))
    )

    # 阶段 2：高清渲染（缺简历附件则执行秒级自愈）
    if not has_valid_pdf or is_stale_custom_pdf or (not has_valid_img and "boss" in platform.lower()):
        await send_sse_msg(queue, "progress", f"正在为【{company_name} · {job_title}】极速渲染最新物料(PDF+长图)...",
                           job_id=target_jid, record_id=record_id, sub_stage=2, total_stages=4, stage_title="高清渲染")
        from app.automation.materials import (
            _render_custom_resume_materials,
            _render_mass_resume_materials_with_name,
        )
        materials_res = None
        if is_custom:
            try:
                struct_data = json.loads(raw_custom_json)
                materials_res = await _render_custom_resume_materials(struct_data, pdf_name)
            except Exception as e:
                logger.warning(f"解析定制简历 JSON 异常: {e}")

        if not materials_res:
            from app.automation.db import get_autopilot_config
            cfg = get_autopilot_config()
            active_resume_id = cfg.get("mass_apply_resume_id", "")
            # B-12：无定制简历 JSON 时的回落要明示，避免用户以为批准的是定制简历
            await send_sse_msg(queue, "info", "  ℹ️ 未检测到可用的定制简历，已回落使用海投母本简历渲染物料")
            materials_res = await _render_mass_resume_materials_with_name(active_resume_id, pdf_name)

        if materials_res:
            if materials_res.get("pdf_token"):
                patch_fields["PDF备份"] = [{"file_token": materials_res["pdf_token"], "name": pdf_name}]
            if materials_res.get("img_token"):
                patch_fields["图片保存"] = [{"file_token": materials_res["img_token"], "name": f"{company_name}_{job_title}-长图.jpg"}]
        else:
            # P3 加固：自愈渲染失败必须按岗位失败中止，与 auto_heal_and_approve 的 422 口径一致；
            # 不能让空物料岗位流入「待投递」，否则要到投递网关才报错，白白浪费一次发射
            raise RuntimeError(
                f"简历物料自愈失败（PDF/长图均未生成），岗位 {record_id} 未入队「待投递」，请检查简历库与飞书连接后重试"
            )
    else:
        await send_sse_msg(queue, "progress", f"【{company_name} · {job_title}】物料附件已完备，准备飞书入队...",
                           job_id=target_jid, record_id=record_id, sub_stage=2, total_stages=4, stage_title="高清渲染")

    # 补齐打招呼语（若直聊平台缺失）
    if "51job" not in platform.lower() and "前程" not in platform and not greeting:
        from app.automation.db import get_autopilot_config
        cfg = get_autopilot_config()
        mass_greeting = str(cfg.get("mass_apply_greeting") or "").strip()
        if mass_greeting:
            patch_fields["打招呼语"] = mass_greeting

    # 阶段 3：飞书归档
    await send_sse_msg(queue, "progress", f"正在将【{company_name} · {job_title}】归档至「待投递」队列...",
                       job_id=target_jid, record_id=record_id, sub_stage=3, total_stages=4, stage_title="飞书归档")

    patch_fields["跟进状态"] = "待投递"
    # B5 同口径：回写飞书失败必须按岗位失败抛出，不能虚报 success 瞒报丢结果
    update_ok = await asyncio.to_thread(update_feishu_record, record_id, patch_fields, _ccfg.FEISHU_TABLE_ID_JOBS)
    if not update_ok:
        raise RuntimeError(f"批准结果回写飞书失败，岗位 {record_id} 未入队「待投递」，请重试")

    try:
        from app.automation.routes.delivery_router import _mark_approved_guarded
        await asyncio.to_thread(_mark_approved_guarded, record_id)
    except Exception as e:
        logger.warning(f"标记审批放行异常: {e}")

    try:
        from app.core.cache import JobCache
        JobCache.patch_record_fields(record_id, {"follow_status": "待投递"})
    except Exception as e:
        logger.warning(f"JobCache 同步更新待投递状态异常: {e}")

    # 阶段 4：放行待投
    await send_sse_msg(queue, "progress", f"【{company_name} · {job_title}】批准入队完成，已进入待投递队列",
                       job_id=target_jid, record_id=record_id, sub_stage=4, total_stages=4, stage_title="放行待投")
    await send_sse_msg(queue, "info", f"  ✅【{company_name} · {job_title}】物料质检与批准成功，已入队「待投递」")

    return {
        "status": "success",
        "record_id": record_id,
        "followStatus": "待投递",
        "follow_status": "待投递"
    }

# Optimization: helper function to process a single job to reduce complexity of run_batch_ai_task
def _infer_platform_from_id(job_id: str) -> str:
    """从岗位 id 关键词兜底推断平台（仅当飞书记录缺「招聘平台」字段时使用）。"""
    if "猎聘" in job_id:
        return "猎聘"
    if "51job" in job_id or "前程无忧" in job_id:
        return "51job"
    if "智联招聘" in job_id:
        return "智联招聘"
    return "BOSS直聘"

async def _process_single_job(job_id: str, index: int, total_jobs: int, task_type: str, resume_text: str, preferences_text: str, queue: asyncio.Queue, scheduled_at: str | None, mass_materials: dict | None = None, mass_greeting: str = "", prefetched: dict[str, dict] | None = None) -> dict | None:
    await send_sse_msg(queue, "progress", f"正在处理 {index}/{total_jobs}: {job_id}...", job_id=job_id, current=index, total=total_jobs)

    record_id = extract_record_id(job_id)

    await send_sse_msg(queue, "info", "  📡 正在从飞书拉取岗位详情...")

    # 去重关卡预取过的记录直接复用，省一次飞书拉取
    job_record = (prefetched or {}).get(record_id) or await asyncio.to_thread(
        get_job_record_from_feishu,
        record_id,
        _ccfg.FEISHU_TABLE_ID_JOBS
    )

    if not job_record:
        raise ValueError(f"无法从飞书获取岗位记录 {record_id}")

    fields = job_record.get("fields", {})

    # 平台以飞书记录的「招聘平台」字段为准（id 前缀仅作字段缺失时的兜底），
    # 避免四平台之外的岗位（如小红书）被默认误判为 BOSS直聘
    platform = extract_feishu_text(fields.get("招聘平台", "")).strip() or _infer_platform_from_id(job_id)

    job_name = extract_feishu_text(fields.get("岗位名称", ""))
    company_name = extract_feishu_text(fields.get("公司名称", ""))
    jd_text = extract_feishu_text(fields.get("岗位详情", ""))
    salary = extract_feishu_text(fields.get("薪资", ""))
    city = extract_feishu_text(fields.get("城市", ""))
    experience = extract_feishu_text(fields.get("经验要求", ""))
    education = extract_feishu_text(fields.get("学历要求", ""))

    print(f"📡 [飞书数据] 已成功拉取到 {company_name} - {job_name} 的岗位记录")
    await send_sse_msg(queue, "info", f"  ✓ 已获取【{company_name} - {job_name}】的岗位详情")

    # 海投与批量批准不依赖 JD 文本（不做评估/改写），其余任务仍要求 JD 足够长
    if task_type not in ("mass_apply", "approve") and (not jd_text or len(jd_text.strip()) < 50):
        raise ValueError("岗位详情为空或过短，无法进行 AI 处理")

    # B4/B6 后端权威门禁：深评/改写必须先跑过初步评估（有 A-F 评级）。
    # 前端列表数据可能过期，此处以飞书实时字段为准；未初评岗位直接按岗位失败跳过，
    # 避免空诊断白烧重度 token 并把状态机覆盖成「已完成深度评估/简历人工复核」。
    if task_type in ("deep_evaluate", "rewrite"):
        existing_grade = extract_feishu_text(fields.get("综合评级 (A-F)", "")).strip()
        if not existing_grade:
            raise ValueError("岗位尚未完成初步评估（无 A-F 评级），请先执行「初步评估」后再深评/改写")

    res = None
    if task_type == "evaluate":
        res = await _handle_evaluate(job_id, record_id, platform, company_name, job_name, jd_text, salary, city, experience, education, resume_text, preferences_text, queue)
    elif task_type == "rewrite":
        res = await _handle_rewrite(job_id, record_id, job_name, jd_text, fields, resume_text, queue)
    elif task_type == "deep_evaluate":
        res = await _handle_deep_evaluate(job_id, record_id, jd_text, salary, city, experience, education, fields, resume_text, queue)
    elif task_type == "deliver":
        res = await _handle_deliver(record_id, platform, fields, scheduled_at, queue)
    elif task_type == "mass_apply":
        res = await _handle_mass_apply(record_id, platform, fields, mass_materials or {}, mass_greeting, queue, job_id=job_id)
    elif task_type == "approve":
        res = await _handle_approve(record_id, platform, fields, queue, job_id=job_id)

    return res

async def run_batch_ai_task(
    task_id: str,
    task_type: str,
    job_ids: list[str],
    queue: asyncio.Queue,
    scheduled_at: str | None = None
):
    if global_task_lock.locked():
        await send_sse_msg(queue, "info", "系统繁忙，正在排队等待执行...")

    async with global_task_lock:
        GLOBAL_TASK_STATE["is_processing"] = True
        GLOBAL_TASK_STATE["current_task_id"] = task_id
        try:
            if task_id not in task_status:
                task_status[task_id] = {"job_ids": list(job_ids), "total": len(job_ids), "completed": 0}
            task_status[task_id]["status"] = "running"
            task_status[task_id]["started_at"] = datetime.now().isoformat()

            await send_sse_msg(queue, "start", f"批量任务已启动，共 {len(job_ids)} 个岗位", total=len(job_ids))

            resume_text = ""
            preferences_text = ""
            mass_materials: dict | None = None
            mass_greeting = ""
            # 🔁 疑似重复关卡数据（evaluate 批次用）
            prefetched: dict[str, dict] = {}
            dedup_pairs: list = []

            if task_type == "mass_apply":
                # ── 海投准备：配置读取 → 打招呼语/简历预检 → 物料渲染一次 ──
                from app.automation.db import get_autopilot_config
                from app.automation.materials import _render_mass_resume_materials

                cfg = get_autopilot_config()
                mass_greeting = (cfg.get("mass_apply_greeting") or "").strip()
                resume_id = (cfg.get("mass_apply_resume_id") or "").strip()
                if not resume_id:
                    await send_sse_msg(queue, "info", "⚙️ 未单独指定海投简历 ID，自动提取【海投简历/启用】版本...")
                    resume_id = await asyncio.to_thread(get_mass_apply_resume_record_id)
                if not resume_id:
                    raise ValueError("未配置海投简历且无启用简历，请前往「全链路中心-打招呼语模块」或「简历中心」配置海投简历")

                needs_greeting = any(_infer_platform_from_id(j) in ("BOSS直聘", "猎聘", "智联招聘") for j in job_ids)
                if needs_greeting and not mass_greeting:
                    raise ValueError("尚未配置「海投通用打招呼语」，请前往「全链路中心-打招呼语模块」配置后再执行海投")

                await send_sse_msg(queue, "info", "📎 开始渲染海投简历物料（PDF+长图，仅渲染一次）...")
                mass_materials = await _render_mass_resume_materials(resume_id)
                if not mass_materials:
                    raise ValueError("海投简历渲染/上传失败，请检查简历库与飞书连接")
                await send_sse_msg(queue, "info", f"✓ 海投物料就绪：{mass_materials['name']}（PDF+长图）")

                # 51job 海投会话重置：新任务首岗位必须重传「海投简历」（同名旧附件会被删除），
                # 同一任务内后续岗位复用，避免重复上传
                try:
                    job51_dir = str(BASE_DIR / "51job_scraper")
                    if job51_dir not in sys.path:
                        sys.path.insert(0, job51_dir)
                    import importlib as _importlib
                    _importlib.import_module("51job_auto_delivery").reset_mass_apply_session()
                except Exception as e:
                    print(f"⚠️ 重置 51job 海投会话状态失败（引擎内会走兜底逻辑）: {e}")
            elif task_type == "approve":
                await send_sse_msg(queue, "info", "⚡ 批量批准投递流已就绪，正在并发质检物料与自动入队...")
            else:
                await send_sse_msg(queue, "info", "☁️ 正在从飞书配置中心读取【启用】状态的简历...")
                resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
                if not resume_text:
                    raise ValueError("未在飞书【我的简历库】中找到处于[启用]状态的简历！请前往控制台添加。")

                await send_sse_msg(queue, "info", f"✓ 简历文本已加载，共 {len(resume_text)} 字符")
                await send_sse_msg(queue, "info", "⚙️ 正在加载求职偏好与底线配置...")

                try:
                    preferences_text = await asyncio.to_thread(get_my_preferences)
                except Exception as pref_err:
                    print(f"⚠️ 读取求职偏好失败: {pref_err}")
                    preferences_text = ""

                # 🔁 疑似重复关卡（自 service 版引擎移植）：≥2 条的批量初评先过查重
                # （同公司改名/跨平台重发不重复烧 token）。关卡异常一律 fail-open 照常评估。
                if task_type == "evaluate" and len(job_ids) >= 2:
                    try:
                        from app.services.job_dedup_gate import run_dedup_gate

                        # B3：并发预取（Semaphore 5 限流，避免瞬间打满飞书 QPS），
                        # 原串行逐条 await 在大批量时启动要数十秒且无进度反馈
                        _sem = asyncio.Semaphore(5)

                        async def _fetch_record(rid: str):
                            async with _sem:
                                return rid, await asyncio.to_thread(
                                    get_job_record_from_feishu, rid, _ccfg.FEISHU_TABLE_ID_JOBS)

                        fetched = await asyncio.gather(
                            *(_fetch_record(extract_record_id(jid)) for jid in job_ids),
                            return_exceptions=True,
                        )
                        gate_records = []
                        for item in fetched:
                            if isinstance(item, BaseException) or not item or not item[1]:
                                continue
                            rid, rec = item
                            prefetched[rid] = rec
                            f = rec.get("fields", {})
                            gate_records.append({
                                "record_id": rid,
                                "company": extract_feishu_text(f.get("公司名称", "")),
                                "job_title": extract_feishu_text(f.get("岗位名称", "")),
                                "jd_text": extract_feishu_text(f.get("岗位详情", "")),
                                "city": extract_feishu_text(f.get("城市", "")),
                                "platform": extract_feishu_text(f.get("招聘平台", "")) or "未知渠道",
                                "job_url": extract_feishu_text(f.get("岗位链接", "")),
                            })
                        kept, _marked, dedup_pairs = await run_dedup_gate(
                            gate_records, log=lambda m: send_sse_msg(queue, "info", m))
                        if len(kept) < len(gate_records):
                            kept_rids = {r["record_id"] for r in kept}
                            job_ids = [jid for jid in job_ids if extract_record_id(jid) in kept_rids]
                            task_status[task_id]["total"] = len(job_ids)
                            # 同步登记表：被去重拦下的岗位已不处理，删除拦截不应再误拦（B13）
                            task_status[task_id]["job_ids"] = list(job_ids)
                            await send_sse_msg(queue, "info", f"🔁 去重后实际待评估 {len(job_ids)} 个岗位", total=len(job_ids))
                    except Exception as gate_err:
                        print(f"⚠️ [去重关卡] 异常（不阻断批量评估）: {gate_err}")

            total_jobs = len(job_ids)
            # B1/B2/B5：岗位级三态计数。success=成功写回飞书；failed=异常/AI格式错/回写失败；
            # skipped=引擎明确跳过（如未知平台不投递），不计失败但如实上报
            success_count = 0
            failed_count = 0
            skipped_count = 0
            if task_type == "evaluate":
                # 🌊 接入三波次漏斗流水线 (Wave-Phased Pipeline)
                # Wave 1: 全量并发初评 (KV Cache 极速秒出)
                # Funnel Gate: C/D/F 级岗位立即归档，0 浪费 Token；A/B 级进入优质岗
                # Wave 2: 优质岗并发深度画像与能力审计
                # Wave 3: 优质岗并发定制改写与高情商破冰语
                from app.tasks.wave_pipeline import run_wave_evaluation_pipeline

                success_count, failed_count, skipped_count = await run_wave_evaluation_pipeline(
                    job_ids=job_ids,
                    task_id=task_id,
                    resume_text=resume_text,
                    preferences_text=preferences_text,
                    queue=queue,
                    prefetched=prefetched,
                )
                task_status[task_id]["completed"] = total_jobs
            else:
                for index, job_id in enumerate(job_ids, start=1):
                    print(f"\n🔍 [正在处理] 第 {index} 个岗位: {job_id}")
                    _sent_terminal = False
                    job_updates = {}
                    job_failed = False
                    try:
                        res = await _process_single_job(
                            job_id, index, total_jobs, task_type, resume_text, preferences_text, queue, scheduled_at,
                            mass_materials=mass_materials, mass_greeting=mass_greeting, prefetched=prefetched
                        )

                        if res:
                            job_updates = res
                            success_count += 1
                        else:
                            skipped_count += 1

                        await send_sse_msg(queue, "info", f"✅ 岗位 {job_id} 流程已完全结束，正在同步 UI...")
                        await send_sse_msg(queue, "success", f"✓ {job_id} 处理完成", job_id=job_id, job_updates=job_updates)
                        _sent_terminal = True

                        wave_label = (
                            "Wave 2 深度画像" if task_type == "deep_evaluate"
                            else ("Wave 3 定制改写" if task_type == "rewrite"
                            else ("批量批准投递" if task_type == "approve"
                            else ("海投投递" if task_type == "mass_apply" else "批量任务")))
                        )
                        await send_sse_msg(
                            queue, "wave_status",
                            f"{wave_label} 进度 {index}/{total_jobs}",
                            wave=2 if task_type == "deep_evaluate" else (3 if task_type == "rewrite" else 1),
                            total_waves=1,
                            wave_name=wave_label,
                            wave_current=index,
                            wave_total=total_jobs,
                            total_jobs=total_jobs,
                            status_text=f"{wave_label} 进度 {index}/{total_jobs}"
                        )

                    except Exception as e:
                        job_failed = True
                        print(f"🚨 [处理过程发生致命异常]: {str(e)}")
                        await send_sse_msg(queue, "error", f"  ✗ {job_id} 处理失败: {str(e)}", job_id=job_id)
                        _sent_terminal = True
                    finally:
                        if job_failed:
                            failed_count += 1
                        # B1：无论成败，进度都必须推进，否则单岗异常后 completed 永久卡死
                        task_status[task_id]["completed"] = index
                        if not _sent_terminal:
                            await send_sse_msg(queue, "error", f"  ✗ {job_id} 处理意外中止", job_id=job_id)

            # 批次内母本已评完：把初评结论回填给对应「疑似重复」副本（自 service 版引擎移植）
            if task_type == "evaluate" and dedup_pairs:
                try:
                    from app.services.job_dedup_gate import (
                        backfill_batch_dup_conclusions,
                    )
                    await backfill_batch_dup_conclusions(
                        dedup_pairs, log=lambda m: send_sse_msg(queue, "info", m))
                except Exception as bf_err:
                    print(f"⚠️ [去重关卡] 母本结论回填异常（不阻断任务）: {bf_err}")

            task_status[task_id]["status"] = "completed"
            task_status[task_id]["completed_at"] = datetime.now().isoformat()
            task_status[task_id]["success"] = success_count
            task_status[task_id]["failed"] = failed_count
            task_status[task_id]["skipped"] = skipped_count
            # B2：批次末尾按真实成败汇总，不再无差别「全部完成」瞒报失败
            if failed_count == 0 and skipped_count == 0:
                await send_sse_msg(queue, "complete", f"🎉 批量任务全部完成！共 {total_jobs} 个岗位")
            else:
                summary_parts = [f"✅ 成功 {success_count}"]
                if failed_count:
                    summary_parts.append(f"❌ 失败 {failed_count}")
                if skipped_count:
                    summary_parts.append(f"⏭️ 跳过 {skipped_count}")
                await send_sse_msg(
                    queue,
                    "complete",
                    f"🏁 批量任务结束（共 {total_jobs} 个岗位）：{'，'.join(summary_parts)}，失败岗位可单独重试",
                    success=success_count, failed=failed_count, skipped=skipped_count,
                )

        except Exception as e:
            if task_id in task_status:
                task_status[task_id]["status"] = "failed"
                task_status[task_id]["error"] = str(e)

            import traceback
            print(f"\n🚨 [致命错误] 批量评估任务彻底崩溃: {str(e)}")
            traceback.print_exc()

            await send_sse_msg(queue, "error", f"❌ 批量任务执行失败: {str(e)}")
        finally:
            GLOBAL_TASK_STATE["is_processing"] = False
            GLOBAL_TASK_STATE["last_completed_task_id"] = task_id
            if GLOBAL_TASK_STATE.get("current_task_id") == task_id:
                GLOBAL_TASK_STATE["current_task_id"] = None
            await queue.put('data: {"type": "end"}\n\n')
            schedule_task_cleanup(task_id)
