"""三波次漏斗流水线引擎 (Wave-Phased Pipeline)

实现架构：
1. Wave 1: 批量并发初评波次 (全量岗位并发发起 8 维度评估，100% 命中不可变母本简历前缀缓存，极速秒出)
2. Funnel Gate: 评级门禁判定 (C/D/F 级岗位就地归档为「已完成初步评估」或「清洗淘汰」，0 算力浪费；A/B 级进入优质岗)
3. Wave 2: 优质岗并发深评波次 (仅优质岗并发生成深度画像、能力信号与审计)
4. Wave 3: 优质岗并发改写与破冰波次 (仅优质岗并发生成定制简历与超轻量打招呼语)
"""

import asyncio
import json
import logging
import time

from ai_agents.ai_evaluator import (
    evaluate_single_job,
    get_auto_eval_threshold,
    warmup_eval_cache,
)
from ai_agents.ai_scorer import deep_evaluate_resume, warmup_deep_eval_cache
from ai_agents.engine_facade import process_greeting_generation, process_resume_rewrite
from ai_agents.markdown_to_json import convert_and_stitch_resume
from ai_agents.skill_rewrite import warmup_rewrite_cache
from app.core.feishu_utils import grade_meets_threshold
from app.services.feishu_service import (
    extract_feishu_text,
    extract_record_id,
    get_job_record_from_feishu,
    update_feishu_record,
)
from app.services.search_service import research_company_serper
from common import config as _ccfg

logger = logging.getLogger("app.tasks.wave_pipeline")

# 飞书字段与状态常量
FIELD_RATING = "综合评级 (A-F)"
FIELD_CORE_MATCH = "核心-角色匹配"
FIELD_SALARY_MATCH = "高权-薪资契合"
FIELD_AI_DETAIL = "AI评估详情"
FIELD_DREAM_PIC = "理想画像与能力信号"
FIELD_CORE_DICT = "核心能力词典"
FIELD_HIGH_LEV = "高杠杆匹配点"
FIELD_RED_FLAGS = "致命硬伤与毒点"
FIELD_ACTION_PLAN = "破局行动计划"
STATUS_MANUAL_REVIEW = "简历人工复核"


async def send_sse_msg(queue: asyncio.Queue, msg_type: str, message: str, **kwargs):
    payload = {"type": msg_type, "message": message}
    payload.update(kwargs)
    await queue.put(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")


def _infer_platform(job_id: str, fields: dict) -> str:
    raw = extract_feishu_text(fields.get("招聘平台", "")).strip()
    if raw:
        return raw
    jid_lower = job_id.lower()
    if "boss" in jid_lower:
        return "BOSS直聘"
    if "liepin" in jid_lower or "猎聘" in jid_lower:
        return "猎聘"
    if "51job" in jid_lower or "前程无忧" in jid_lower:
        return "51job"
    if "zhilian" in jid_lower or "智联" in jid_lower:
        return "智联招聘"
    return "BOSS直聘"


async def run_wave_evaluation_pipeline(
    job_ids: list[str],
    task_id: str,
    resume_text: str,
    preferences_text: str,
    queue: asyncio.Queue,
    prefetched: dict[str, dict] | None = None,
) -> tuple[int, int, int]:
    """执行批量初评的三波次漏斗流水线。返回 (success_count, failed_count, skipped_count)。"""
    total_requested = len(job_ids)
    logger.info("🌊 [WavePipeline] [%s] 启动三波次漏斗流水线，目标岗位数: %d", task_id, total_requested)

    # Step 0: 预取与校验岗位元数据 (并发 Semaphore 5)
    await send_sse_msg(queue, "info", f"📡 正在拉取并校验 {total_requested} 个岗位的飞书元数据...")
    fetch_sem = asyncio.Semaphore(5)

    async def _fetch_single(jid: str) -> dict | None:
        rid = extract_record_id(jid)
        rec = (prefetched or {}).get(rid) or (prefetched or {}).get(jid)
        if not rec:
            async with fetch_sem:
                rec = await asyncio.to_thread(get_job_record_from_feishu, rid, _ccfg.FEISHU_TABLE_ID_JOBS)
        if not rec:
            await send_sse_msg(queue, "error", f"无法从飞书获取岗位记录 {rid}", job_id=jid)
            return None
        fields = rec.get("fields", {})
        jd_text = extract_feishu_text(fields.get("岗位详情", "")).strip()
        if not jd_text or len(jd_text) < 50:
            await send_sse_msg(queue, "error", "岗位详情为空或过短 (<50字)，跳过评估", job_id=jid)
            return None
        return {
            "job_id": jid, "record_id": rid, "platform": _infer_platform(jid, fields),
            "company_name": extract_feishu_text(fields.get("公司名称", "")),
            "job_name": extract_feishu_text(fields.get("岗位名称", "")),
            "jd_text": jd_text, "salary": extract_feishu_text(fields.get("薪资", "")),
            "city": extract_feishu_text(fields.get("城市", "")),
            "experience": extract_feishu_text(fields.get("经验要求", "")),
            "education": extract_feishu_text(fields.get("学历要求", "")),
            "fields": fields,
        }

    fetched_results = await asyncio.gather(*[_fetch_single(jid) for jid in job_ids])
    valid_jobs: list[dict] = [item for item in fetched_results if item is not None]
    failed_count = total_requested - len(valid_jobs)
    skipped_count = 0
    success_count = 0

    if not valid_jobs:
        await send_sse_msg(queue, "error", "没有有效且详情合格的待评估岗位")
        return success_count, failed_count, skipped_count

    total_valid = len(valid_jobs)
    w1_state = {"done": 0}
    w1_lock = asyncio.Lock()
    await send_sse_msg(queue, "info", f"🌊 【波次 1/3：批量初评】启动全量并发初评（共 {total_valid} 个有效岗位，首部母本简历对齐 KV Cache）...", total=total_valid)
    await send_sse_msg(
        queue, "wave_status",
        f"Wave 1 极速初评 (0/{total_valid})",
        wave=1, total_waves=3, wave_name="初评",
        wave_current=0, wave_total=total_valid, total_jobs=total_requested,
        status_text=f"Wave 1 极速初评 (0/{total_valid})"
    )

    # 🌊 Wave 1: 批量并发初评波次 (Semaphore 5 限流，共享母本简历 KV Cache 前缀)
    wave1_sem = asyncio.Semaphore(5)
    loop = asyncio.get_running_loop()

    async def _eval_wave1_job(item: dict) -> dict:
        jid, rid = item["job_id"], item["record_id"]
        company, job_title = item["company_name"], item["job_name"]
        async with wave1_sem:
            logger.info("🚀 [Wave 1] 正在并发初评: %s - %s (%s)", company, job_title, jid)
            await send_sse_msg(queue, "progress", "🧠 [1/4] 正在进行 8维度初评...", job_id=jid, record_id=rid, sub_stage=1, total_stages=4, stage_title="8维度初评中")
            intel = await research_company_serper(company)
            job_data = {
                "record_id": rid, "table_id": _ccfg.FEISHU_TABLE_ID_JOBS, "platform": item["platform"],
                "company": company, "job_title": job_title, "jd_text": item["jd_text"],
                "salary": item["salary"], "city": item["city"], "experience": item["experience"], "education": item["education"],
            }
            def _pcb(info: dict):
                try:
                    asyncio.run_coroutine_threadsafe(send_sse_msg(queue, "progress", info.get("message", ""), job_id=jid, record_id=rid, sub_stage=info.get("stage", 1), total_stages=info.get("total_stages", 4), stage_title=info.get("title", "")), loop)
                except Exception:
                    pass

            start_t = time.time()
            res = await asyncio.to_thread(evaluate_single_job, job_data, resume_text, intel, preferences_text, "eval_only", _pcb)
            cost_s = time.time() - start_t
            if not res or not res.get("success"):
                raise RuntimeError(res.get("error", "初评未返回成功状态") if res else "初评结果为空")

            ai_score, grade = res.get("ai_score", 0), res.get("grade", "F")
            write_ok = await asyncio.to_thread(update_feishu_record, rid, res.get("update_data", {}), _ccfg.FEISHU_TABLE_ID_JOBS)
            if not write_ok:
                raise RuntimeError(f"飞书初评字段回写失败: {rid}")

            usage = res.get("usage") or {}
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            cached = usage.get("cached_tokens", 0)
            cache_tag = f" (🔥命中缓存: {cached})" if cached > 0 else ""
            token_hint = f" [提示: {pt}{cache_tag} / 补全: {ct}]" if (pt or ct) else ""

            await send_sse_msg(queue, "info", f"  ✓ [{company} - {job_title}] 初评完成: {ai_score}分 / {grade}级{token_hint} (耗时 {cost_s:.1f}s)", usage=usage)
            await send_sse_msg(queue, "progress", f"  ✓ 初评完成: {ai_score}分 ({grade}级)", job_id=jid, record_id=rid, sub_stage=2, total_stages=4, stage_title=f"初评 {grade} 级")
            async with w1_lock:
                w1_state["done"] += 1
                curr_w1 = w1_state["done"]
            await send_sse_msg(
                queue, "wave_status",
                f"Wave 1 极速初评 ({curr_w1}/{total_valid})",
                wave=1, total_waves=3, wave_name="初评",
                wave_current=curr_w1, wave_total=total_valid, total_jobs=total_requested,
                status_text=f"Wave 1 极速初评 ({curr_w1}/{total_valid})"
            )
            return {"success": True, "item": item, "eval_result": res, "ai_score": ai_score, "grade": grade, "company_intel": intel}

    async def _safe_eval_wrapper(item: dict) -> dict:
        try:
            return await _eval_wave1_job(item)
        except Exception as e:
            jid = item["job_id"]
            logger.error("❌ [Wave 1 异常] 岗位 %s: %s", jid, e)
            await send_sse_msg(queue, "error", f"  ✗ {jid} 初评失败: {str(e)}", job_id=jid)
            return {"success": False, "item": item, "error": str(e)}

    # 🌊 Wave 1 动态调度：小批量 (<3) 智能串行确保 100% 缓存继承；大批量 (>=3) 1-token 点火预热后并发开火
    if len(valid_jobs) < 3:
        logger.info("🌊 [Wave 1] 待初评岗位数 %d < 3，启用智能串行调度（首任务预热，后任务100%%继承缓存）...", len(valid_jobs))
        await send_sse_msg(queue, "info", f"💡 当前批次岗位数 ({len(valid_jobs)} < 3)，启用智能串行评估以天然继承前缀缓存...")
        wave1_raw = []
        for it in valid_jobs:
            r = await _safe_eval_wrapper(it)
            wave1_raw.append(r)
    else:
        logger.info("🌊 [Wave 1] 待初评岗位数 %d >= 3，触发 1-token 轻量点火预热母本前缀...", len(valid_jobs))
        await send_sse_msg(queue, "info", "🔥 正在执行母本简历前缀轻量点火预热，为大批量并发就绪 KV Cache...")
        warm_res = await asyncio.to_thread(warmup_eval_cache, resume_text, preferences_text)
        if warm_res.get("success"):
            logger.info("🔥 [Wave 1] 点火完成！Prompt: %s (缓存: %s)，启动全量并发评估！", warm_res.get("prompt"), warm_res.get("cached"))
        wave1_raw = await asyncio.gather(*[_safe_eval_wrapper(it) for it in valid_jobs])

    # 🚪 Funnel Gate: 门禁判定与分流
    threshold = get_auto_eval_threshold()
    high_tier_jobs: list[dict] = []
    low_tier_jobs: list[dict] = []
    for r in wave1_raw:
        if not r.get("success"):
            failed_count += 1
            continue
        grade, score = r.get("grade", "F"), r.get("ai_score", 0)
        is_high = grade_meets_threshold(grade, threshold)
        (high_tier_jobs if is_high else low_tier_jobs).append(r)

    for r in low_tier_jobs:
        it, grade, score = r["item"], r["grade"], r["ai_score"]
        status_name = "清洗淘汰" if grade == "F" else "已完成初步评估"
        success_count += 1
        await send_sse_msg(queue, "success", f"✓ {it['job_id']} 初评就地归档 ({score}分/{grade}级，未达自动深评门槛，止步初评)", job_id=it["job_id"], job_updates={"followStatus": status_name, "aiScore": score, "grade": grade})

    await send_sse_msg(queue, "info", f"🚪 【漏斗门禁】初评完毕！🎯 筛选出 {len(high_tier_jobs)} 个优质岗进入深度定制轨道，⏹️ {len(low_tier_jobs)} 个普通岗已就地归档（0 算力浪费）。")
    await send_sse_msg(
        queue, "wave_status",
        f"Wave 1 完结 ({total_valid}/{total_valid}) ✓" if not high_tier_jobs else f"Wave 1 完结 ({total_valid}/{total_valid}) ✓ ➔ 准备进入 Wave 2",
        wave=1, total_waves=3, wave_name="初评",
        wave_current=total_valid, wave_total=total_valid, total_jobs=total_requested,
        is_wave_done=True,
        status_text="Wave 1 完结 ✓"
    )
    if not high_tier_jobs:
        logger.info("ℹ️ [WavePipeline] 本批次无达到门槛的优质岗位，波次流水线圆满结束")
        return success_count, failed_count, skipped_count

    # 🌊 Wave 2: 优质岗并发深度画像波次
    num_high = len(high_tier_jobs)
    w2_state = {"done": 0}
    w2_lock = asyncio.Lock()
    await send_sse_msg(queue, "info", f"🌊 【波次 2/3：深度画像】正在对 {num_high} 个优质岗位并发执行深度画像与能力审计...")
    await send_sse_msg(
        queue, "wave_status",
        f"Wave 1 完结 ✓ ➔ Wave 2 深度画像 (0/{num_high})",
        wave=2, total_waves=3, wave_name="深度画像",
        wave_current=0, wave_total=num_high, total_jobs=total_requested,
        status_text=f"Wave 1 完结 ✓ ➔ Wave 2 深度画像 (0/{num_high})"
    )
    wave2_sem = asyncio.Semaphore(3)

    async def _deep_eval_job(high_item: dict) -> dict:
        it = high_item["item"]
        jid, rid, company, job_title = it["job_id"], it["record_id"], it["company_name"], it["job_name"]
        eval_res = high_item["eval_result"]
        async with wave2_sem:
            logger.info("🧠 [Wave 2] 正在深度画像: %s - %s (%s)", company, job_title, jid)
            await send_sse_msg(queue, "progress", "🔥 [3/4] 触发高分轨！正在进行深度画像与能力审计...", job_id=jid, record_id=rid, sub_stage=3, total_stages=4, stage_title="深度画像中")
            full_jd = f"【岗位基本信息】\n薪资范围: {it['salary']} | 工作城市: {it['city']} | 经验要求: {it['experience']} | 学历要求: {it['education']}\n\n【岗位详情】\n{it['jd_text']}"
            if high_item.get("company_intel"):
                full_jd += f"\n\n【公司外部情报】\n{high_item['company_intel']}"
            first_stage_scores = {
                FIELD_RATING: high_item["grade"],
                FIELD_CORE_MATCH: eval_res.get("update_data", {}).get("核心-角色匹配"),
                FIELD_SALARY_MATCH: eval_res.get("update_data", {}).get("高权-薪资契合"),
                FIELD_AI_DETAIL: eval_res.get("rationales_text", ""),
            }
            start_t = time.time()
            deep_res, deep_usage = await asyncio.to_thread(deep_evaluate_resume, resume_text, full_jd, first_stage_scores)
            cost_s = time.time() - start_t
            extracted = deep_res.get("extracted_skills", [])
            extracted_str = "、".join(extracted) if isinstance(extracted, list) else str(extracted)
            ats_final = str(deep_res.get("ats_ability_analysis", "") or deep_res.get(FIELD_CORE_DICT, ""))
            if extracted_str:
                ats_final = f"【核心技能词条】{extracted_str}\n\n" + ats_final

            fields_to_update = {
                FIELD_DREAM_PIC: str(deep_res.get("dream_picture", "") or deep_res.get(FIELD_DREAM_PIC, "")),
                FIELD_CORE_DICT: ats_final, "简历逐行审计": str(deep_res.get("resume_audit", "")),
                FIELD_HIGH_LEV: str(deep_res.get("strong_fit_assessment", "") or deep_res.get(FIELD_HIGH_LEV, "")),
                FIELD_RED_FLAGS: str(deep_res.get("risk_red_flags", "") or deep_res.get(FIELD_RED_FLAGS, "")),
                FIELD_ACTION_PLAN: str(deep_res.get("deep_action_plan", "") or deep_res.get(FIELD_ACTION_PLAN, "")),
            }
            write_ok = await asyncio.to_thread(update_feishu_record, rid, fields_to_update, _ccfg.FEISHU_TABLE_ID_JOBS)
            if not write_ok:
                raise RuntimeError(f"飞书深度画像字段回写失败: {rid}")

            pt = deep_usage.get("prompt_tokens", 0) if deep_usage else 0
            ct = deep_usage.get("completion_tokens", 0) if deep_usage else 0
            cached = deep_usage.get("cached_tokens", 0) if deep_usage else 0
            cache_tag = f" (🔥命中缓存: {cached})" if cached > 0 else ""
            token_hint = f" [提示: {pt}{cache_tag} / 补全: {ct}]" if (pt or ct) else ""

            logger.info("  ✓ [%s - %s] 深度画像与审计完成%s (耗时 %.1fs)", company, job_title, token_hint, cost_s)
            await send_sse_msg(queue, "info", f"  ✓ [{company} - {job_title}] 深度画像与审计完成{token_hint} (耗时 {cost_s:.1f}s)", usage=deep_usage)
            async with w2_lock:
                w2_state["done"] += 1
                curr_w2 = w2_state["done"]
            await send_sse_msg(
                queue, "wave_status",
                f"Wave 1 完结 ✓ ➔ Wave 2 深度画像 ({curr_w2}/{num_high})",
                wave=2, total_waves=3, wave_name="深度画像",
                wave_current=curr_w2, wave_total=num_high, total_jobs=total_requested,
                status_text=f"Wave 1 完结 ✓ ➔ Wave 2 深度画像 ({curr_w2}/{num_high})"
            )
            return {**high_item, "deep_result": deep_res, "full_jd_info": full_jd}

    async def _safe_deep_eval_wrapper(high_item: dict) -> dict | None:
        try:
            return await _deep_eval_job(high_item)
        except Exception as e:
            jid = high_item["item"]["job_id"]
            logger.error("❌ [Wave 2 异常] 岗位 %s: %s", jid, e)
            await send_sse_msg(queue, "error", f"  ✗ {jid} 深度画像失败: {str(e)}", job_id=jid)
            return None

    # 🌊 Wave 2 动态调度：优质岗数 < 3 采用智能串行；优质岗数 >= 3 采用 1-token 深度画像点火预热后并发开火
    if num_high < 3:
        logger.info("🌊 [Wave 2] 优质岗数 %d < 3，采用智能串行深度画像调度...", num_high)
        await send_sse_msg(queue, "info", f"💡 优质岗位数 ({num_high} < 3)，启用智能串行画像以继承缓存...")
        wave2_raw = []
        for it in high_tier_jobs:
            res = await _safe_deep_eval_wrapper(it)
            wave2_raw.append(res)
    else:
        logger.info("🌊 [Wave 2] 优质岗数 %d >= 3，触发 1-token 深度画像点火预热...", num_high)
        await send_sse_msg(queue, "info", "🔥 正在执行深度画像母本前缀轻量点火预热...")
        warm_res = await asyncio.to_thread(warmup_deep_eval_cache, resume_text)
        if warm_res.get("success"):
            logger.info("🔥 [Wave 2] 点火完成！Prompt: %s (缓存: %s)，启动并发画像！", warm_res.get("prompt"), warm_res.get("cached"))
        wave2_raw = await asyncio.gather(*[_safe_deep_eval_wrapper(it) for it in high_tier_jobs])
    wave2_success = [it for it in wave2_raw if it is not None]
    failed_count += len(high_tier_jobs) - len(wave2_success)
    await send_sse_msg(
        queue, "wave_status",
        f"Wave 2 深度画像完结 ({len(wave2_success)}/{num_high}) ✓" if not wave2_success else f"Wave 2 深度画像完结 ({len(wave2_success)}/{num_high}) ✓ ➔ 准备进入 Wave 3",
        wave=2, total_waves=3, wave_name="深度画像",
        wave_current=len(wave2_success), wave_total=num_high, total_jobs=total_requested,
        is_wave_done=True,
        status_text="Wave 2 深度画像完结 ✓"
    )
    if not wave2_success:
        logger.warning("⚠️ [WavePipeline] 所有优质岗在深度画像阶段均异常中断")
        return success_count, failed_count, skipped_count

    # 🌊 Wave 3: 优质岗并发定制改写与高情商破冰波次
    num_rewrite = len(wave2_success)
    w3_state = {"done": 0}
    w3_lock = asyncio.Lock()
    await send_sse_msg(queue, "info", f"🌊 【波次 3/3：定制改写与破冰】正在为 {num_rewrite} 个优质岗位并发生成定制简历与高情商破冰语...")
    await send_sse_msg(
        queue, "wave_status",
        f"Wave 2 完结 ✓ ➔ Wave 3 定制改写与破冰 (0/{num_rewrite})",
        wave=3, total_waves=3, wave_name="定制改写与打招呼语",
        wave_current=0, wave_total=num_rewrite, total_jobs=total_requested,
        status_text=f"Wave 2 完结 ✓ ➔ Wave 3 定制改写 (0/{num_rewrite})"
    )
    wave3_sem = asyncio.Semaphore(3)

    async def _rewrite_and_greeting_job(item_ctx: dict) -> bool:
        it = item_ctx["item"]
        jid, rid, company, job_title = it["job_id"], it["record_id"], it["company_name"], it["job_name"]
        deep_res, full_jd = item_ctx["deep_result"], item_ctx["full_jd_info"]
        async with wave3_sem:
            logger.info("✍️ [Wave 3] 正在生成简历与破冰语: %s - %s (%s)", company, job_title, jid)
            await send_sse_msg(queue, "progress", "💬 [4/4] 正在并发重塑定制简历与高情商打招呼语...", job_id=jid, record_id=rid, sub_stage=4, total_stages=4, stage_title="定制改写中")
            start_t = time.time()
            (md_resume, rewrite_usage), (greeting, greeting_usage) = await asyncio.gather(
                asyncio.to_thread(process_resume_rewrite, full_jd, deep_res, job_title, "skill", resume_text),
                asyncio.to_thread(process_greeting_generation, full_jd, deep_res, resume_text, job_title),
            )
            cost_s = time.time() - start_t
            if not md_resume or not greeting:
                raise RuntimeError("AI 改写简历或打招呼语返回为空")

            fields_to_update = {
                "打招呼语": greeting, "AI改写JSON": convert_and_stitch_resume(md_resume),
                "跟进状态": STATUS_MANUAL_REVIEW,
            }
            write_ok = await asyncio.to_thread(update_feishu_record, rid, fields_to_update, _ccfg.FEISHU_TABLE_ID_JOBS)
            if not write_ok:
                raise RuntimeError(f"飞书改写字段回写失败: {rid}")

            pt_rew = rewrite_usage.get("prompt_tokens", 0) if rewrite_usage else 0
            ct_rew = rewrite_usage.get("completion_tokens", 0) if rewrite_usage else 0
            cached_rew = rewrite_usage.get("cached_tokens", 0) if rewrite_usage else 0

            pt_grt = greeting_usage.get("prompt_tokens", 0) if greeting_usage else 0
            ct_grt = greeting_usage.get("completion_tokens", 0) if greeting_usage else 0
            cached_grt = greeting_usage.get("cached_tokens", 0) if greeting_usage else 0

            tot_prompt = pt_rew + pt_grt
            tot_comp = ct_rew + ct_grt
            tot_cached = cached_rew + cached_grt
            cache_tag = f" (🔥命中缓存: {tot_cached})" if tot_cached > 0 else ""
            token_hint = f" [提示: {tot_prompt}{cache_tag} / 补全: {tot_comp}]" if (tot_prompt or tot_comp) else ""

            await send_sse_msg(
                queue,
                "info",
                f"  ✅ [{company} - {job_title}] 定制简历与打招呼语生成完成！{token_hint} 已更新为「{STATUS_MANUAL_REVIEW}」(耗时 {cost_s:.1f}s)",
                usage={"prompt": tot_prompt, "completion": tot_comp, "total": tot_prompt + tot_comp, "cached": tot_cached},
            )
            await send_sse_msg(queue, "success", f"✓ {jid} 全链路处理完成，已生成定制简历与打招呼语！", job_id=jid, job_updates={"followStatus": STATUS_MANUAL_REVIEW, "aiScore": item_ctx["ai_score"], "grade": item_ctx["grade"]})
            async with w3_lock:
                w3_state["done"] += 1
                curr_w3 = w3_state["done"]
            await send_sse_msg(
                queue, "wave_status",
                f"Wave 2 完结 ✓ ➔ Wave 3 定制改写与破冰 ({curr_w3}/{num_rewrite})",
                wave=3, total_waves=3, wave_name="定制改写与打招呼语",
                wave_current=curr_w3, wave_total=num_rewrite, total_jobs=total_requested,
                status_text=f"Wave 2 完结 ✓ ➔ Wave 3 定制改写 ({curr_w3}/{num_rewrite})"
            )
            return True

    async def _safe_wave3_wrapper(item_ctx: dict) -> bool:
        try:
            return await _rewrite_and_greeting_job(item_ctx)
        except Exception as e:
            jid = item_ctx["item"]["job_id"]
            logger.error("❌ [Wave 3 异常] 岗位 %s: %s", jid, e)
            await send_sse_msg(queue, "error", f"  ✗ {jid} 定制改写失败: {str(e)}", job_id=jid)
            return False

    # 🌊 Wave 3 动态调度：优质岗位数 < 3 采用智能串行改写；优质岗位数 >= 3 采用 1-token 改写母本点火预热后并发开火
    if num_rewrite < 3:
        logger.info("🌊 [Wave 3] 待改写岗位数 %d < 3，采用智能串行改写调度以天然继承前缀缓存...", num_rewrite)
        await send_sse_msg(queue, "info", f"💡 优质待改写岗位数 ({num_rewrite} < 3)，启用智能串行改写以继承缓存...")
        wave3_results = []
        for it in wave2_success:
            r = await _safe_wave3_wrapper(it)
            wave3_results.append(r)
    else:
        logger.info("🌊 [Wave 3] 待改写岗位数 %d >= 3，触发 1-token 改写母本前缀点火预热...", num_rewrite)
        await send_sse_msg(queue, "info", "🔥 正在执行定制改写母本前缀轻量点火预热...")
        warm_res = await asyncio.to_thread(warmup_rewrite_cache, resume_text)
        if warm_res.get("success"):
            logger.info("🔥 [Wave 3] 改写点火完成！Prompt: %s (缓存: %s)，启动全量并发改写！", warm_res.get("prompt"), warm_res.get("cached"))
        wave3_results = await asyncio.gather(*[_safe_wave3_wrapper(it) for it in wave2_success])
    wave3_success_count = sum(1 for ok in wave3_results if ok)
    success_count += wave3_success_count
    failed_count += len(wave2_success) - wave3_success_count

    await send_sse_msg(
        queue, "wave_status",
        f"Wave 3 定制改写完结 ({wave3_success_count}/{num_rewrite}) ✓",
        wave=3, total_waves=3, wave_name="定制改写与打招呼语",
        wave_current=wave3_success_count, wave_total=num_rewrite, total_jobs=total_requested,
        is_wave_done=True,
        status_text="Wave 3 定制改写完结 ✓"
    )

    logger.info("🎉 [WavePipeline] [%s] 波次流水线执行完毕！成功: %d，失败: %d，跳过: %d", task_id, success_count, failed_count, skipped_count)
    return success_count, failed_count, skipped_count
