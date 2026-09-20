import asyncio
import json
import logging
import re
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph

# 从现有模块复用核心评估逻辑
from ai_agents.ai_evaluator import evaluate_single_job
from ai_agents.engine_facade import process_greeting_generation, process_resume_rewrite
from app.automation.db import get_autopilot_config

# 引入我们刚才封装的 MCP / LangChain Tools
from app.automation.tools import (
    deliver_51job_job,
    deliver_boss_job,
    deliver_liepin_job,
    deliver_zhilian_job,
    update_feishu_status,
)
from app.core.feishu_utils import (
    extract_feishu_text,
    grade_meets_threshold,
    is_custom_record,
)
from app.core.utils import is_valid_greeting, sanitize_filename
from app.services.feishu_service import extract_record_id

logger = logging.getLogger(__name__)

# ==========================================
# 1. 定义状态 Schema (State)
# ==========================================
class JobApplicationState(TypedDict):
    """流水线中流转的全局状态"""

    # -- 基础输入信息 --
    job_id: str
    record_id: str
    platform: str
    company_name: str
    job_name: str
    jd_text: str
    salary: str
    city: str
    experience: str
    education: str
    job_url: str

    # 简历与偏好 (静态上下文)
    resume_text: str
    mass_resume_text: str # 海投简历（C-F 级打招呼语素材；未配置时由编排器回退为 resume_text）
    preferences_text: str
    company_intel: str

    # 飞书的完整 fields 数据 (包含链接、附件 token 等投递所需的物料)
    feishu_fields: dict[str, Any]

    # -- AI 处理过程产生的数据 --
    ai_score: float
    score: float
    grade: str # A, B, C 等
    diagnosis_dict: dict[str, Any] # 初评结果

    final_markdown: str # 改写后的简历
    greeting: str # 打招呼语

    # -- 流转控制 --
    status: str # 当前跟进状态
    messages: list[BaseMessage] # (可选) 记录 agent 的对话历史
    error: str | None
    stop_at_review: bool # 定时链路置 True：一律停在人工审批断点，投递交给 T2 海投/T3 精投定时发射
    pipeline_task_id: str # 本轮链路 ID（评估节点用它广播 排队中/打分中 子状态）


# ==========================================
# 1.5 评估并发闸门：同时发起的初评 LLM 请求数受 eval_concurrency 约束
# ==========================================
_eval_semaphore: asyncio.Semaphore | None = None


def _get_eval_semaphore() -> asyncio.Semaphore:
    """惰性创建全局评估信号量（大小取 autopilot 配置 eval_concurrency，默认 5）。"""
    global _eval_semaphore
    if _eval_semaphore is None:
        try:
            n = int(get_autopilot_config().get("eval_concurrency") or 5)
        except Exception:
            n = 5
        _eval_semaphore = asyncio.Semaphore(max(1, min(50, n)))
        logger.info(f"🚦 [LangGraph] 评估并发闸门初始化：最多 {max(1, min(50, n))} 个初评 LLM 请求同时进行")
    return _eval_semaphore


def reset_eval_semaphore():
    """配置面板修改 eval_concurrency 后调用：下一批评估按新值生效（在途的仍用旧闸门收尾）。"""
    global _eval_semaphore
    _eval_semaphore = None


# ==========================================
# 2. 编写节点函数 (Nodes)
# ==========================================

async def evaluate_node(state: JobApplicationState) -> dict[str, Any]:
    """
    大脑：AI 初评节点。
    复用原有的 evaluate_single_job。

    评估并发闸门：同时打到 LLM 的初评请求受 eval_concurrency 信号量约束——
    闸门忙时岗位广播「排队中」，拿到槽位后才广播「打分中」并真正发起请求。
    后续节点（深评/改写/话术/投递）不受此闸门限制，各岗位依然全并行推进。
    """
    logger.info(f"🧠 [LangGraph] 开始执行 evaluate_node 评估: {state['company_name']} - {state['job_name']}")

    job_data = {
        "record_id": state["record_id"],
        "platform": state["platform"],
        "company": state["company_name"],
        "job_title": state["job_name"],
        "jd_text": state["jd_text"],
        "salary": state["salary"],
        "city": state["city"],
        "experience": state["experience"],
        "education": state["education"],
    }

    sem = _get_eval_semaphore()
    pipeline_task_id = state.get("pipeline_task_id") or ""

    async def _emit_sub(sub_status: str):
        if not pipeline_task_id:
            return
        try:
            from app.automation import pipeline_broadcast as _pb
            await _pb.emit_job(
                pipeline_task_id,
                job_id=state.get("record_id") or state.get("job_id", ""),
                job_name=state.get("job_name", ""),
                node="evaluate_node",
                status="running",
                sub_status=sub_status,
                platform=state.get("platform", ""),
                company_name=state.get("company_name", ""),
                job_url=state.get("job_url", ""),
                salary=state.get("salary", ""),
                city=state.get("city", ""),
                education=state.get("education", ""),
                experience=state.get("experience", ""),
            )
        except Exception:
            pass

    if sem.locked():
        await _emit_sub("ai_eval_queued")
    async with sem:
        await _emit_sub("ai_eval")
        # 调用原有的评估逻辑（同步阻塞函数，丢到线程池避免卡死事件循环）
        result = await asyncio.to_thread(
            evaluate_single_job,
            job_data,
            state["resume_text"],
            state["company_intel"],
            state["preferences_text"],
        )

    if not result.get("success"):
        logger.error(f"⚠️ [LangGraph] 初评失败: {result.get('error')}")
        return {"error": result.get("error"), "status": "评估失败"}

    # 将初评结果回写飞书 (使用 Tool)
    await update_feishu_status.ainvoke({
        "record_id": state["record_id"],
        "updates": result["update_data"]
    })

    raw_score = result.get("ai_score", 0)
    intel = result.get("company_intel") or state.get("company_intel", "")
    return {
        "ai_score": raw_score,
        "score": raw_score,
        "grade": result.get("grade", "C"),
        "status": result.get("status", "待人工评估"),
        "diagnosis_dict": result["update_data"],
        "company_intel": intel,
    }


async def _emit_node_running(state: JobApplicationState, node_name: str, sub_status: str):
    """实时广播岗位进入具体子阶段的运行态（供导轨和卡片呈现秒级流转）"""
    pipeline_task_id = state.get("pipeline_task_id") or ""
    if not pipeline_task_id:
        return
    try:
        from app.automation import pipeline_broadcast as _pb
        score_val = state.get("score")
        if score_val is None:
            score_val = state.get("ai_score")
        await _pb.emit_job(
            pipeline_task_id,
            job_id=state.get("record_id") or state.get("job_id", ""),
            job_name=state.get("job_name", ""),
            node=node_name,
            status="running",
            sub_status=sub_status,
            platform=state.get("platform", ""),
            company_name=state.get("company_name", ""),
            job_url=state.get("job_url", ""),
            salary=state.get("salary", ""),
            city=state.get("city", ""),
            education=state.get("education", ""),
            experience=state.get("experience", ""),
            raw_job_id=state.get("raw_job_id", ""),
            grade=state.get("grade", ""),
            score=score_val,
        )
    except Exception:
        pass


async def rewrite_node(state: JobApplicationState) -> dict[str, Any]:
    """
    大脑：AI 深度改写节点 (针对 A/B 级)。
    复用原有的 deep_evaluate_resume 和 process_resume_rewrite。
    """
    logger.info("🧠 [LangGraph] 触发高潜简历深度改写 (rewrite_node)...")
    await _emit_node_running(state, "rewrite_node", "rewriting")

    jd_text = state["jd_text"]
    resume_text = state["resume_text"]
    job_name = state["job_name"]
    diagnosis_dict = state["diagnosis_dict"]

    # 1. 生成定制简历 (复用原有的 process_resume_rewrite，同步阻塞→线程池)
    print("   [Workflow] 开始改写简历...")
    md_resume, _ = await asyncio.to_thread(
        process_resume_rewrite,
        jd_text=jd_text,
        diagnosis_dict=diagnosis_dict,
        job_name=job_name,
        rewrite_mode="skill",
        original_resume_override=resume_text,
    )

    # 2. 生成打招呼语（同步阻塞→线程池）
    await _emit_node_running(state, "greeting_node", "greeting")
    greeting, _ = await asyncio.to_thread(
        process_greeting_generation, jd_text, diagnosis_dict, resume_text, job_name
    )
    if not is_valid_greeting(greeting):
        # 🚫 生成失败时引擎会返回「❌ AI 服务未配置」这类错误文本，严禁当欢迎语写进飞书发给 HR
        logger.error(f"❌ [rewrite_node] 定制打招呼语生成失败（非法内容已置空拦截）: {str(greeting)[:80]}")
        greeting = ""

    # 3. 智能物料处理：判定官方 Skill 还是自定义 Skill
    config = get_autopilot_config()
    skill_id = config.get("rewrite_skill_id") or ""
    official_skill_ids = {"official", "default", "resume_rewrite"}
    is_custom_skill = bool(skill_id and skill_id not in official_skill_ids)

    # 🌟 方案 A：「AI改写JSON」字段统一存结构化 V2 JSON（前端面板/PDF渲染/聊天交付三端直读），
    # markdown 仅作中间产物；解析失败时降级存 markdown 原文（下游均有 markdown 兼容解析）
    rewrite_v2 = None
    if md_resume and not md_resume.lstrip().startswith("❌"):
        try:
            from ai_agents.markdown_to_json import parse_markdown_to_json
            rewrite_v2 = await asyncio.to_thread(parse_markdown_to_json, md_resume)
            # 🌟 核心缝合：如果解析出的 V2 简历缺少 personalInfo，从飞书基准启用简历库拉取并缝合
            if rewrite_v2 and (not rewrite_v2.get("personalInfo") or not rewrite_v2.get("personalInfo", {}).get("name")):
                try:
                    from app.core.config import settings
                    from app.core.feishu_client import feishu_client
                    from app.services.feishu_service import get_active_resume_record_id
                    active_rid = await asyncio.to_thread(get_active_resume_record_id)
                    if active_rid:
                        active_rec = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, active_rid)
                        if active_rec:
                            raw_struct = active_rec.get("fields", {}).get("结构化数据", "")
                            if isinstance(raw_struct, list):
                                raw_struct = "".join([x.get("text", "") for x in raw_struct])
                            if raw_struct:
                                active_dict = json.loads(raw_struct)
                                rewrite_v2["personalInfo"] = active_dict.get("personalInfo", {})
                                if not rewrite_v2.get("education"):
                                    rewrite_v2["education"] = active_dict.get("education", [])
                except Exception as stitch_err:
                    logger.warning(f"[rewrite_node] 缝合基准个人信息异常: {stitch_err}")
        except Exception as parse_err:
            logger.warning(f"[rewrite_node] markdown→V2 解析失败，字段降级存 markdown 原文: {parse_err}")

    updates: dict[str, Any] = {
        "AI改写JSON": json.dumps(rewrite_v2, ensure_ascii=False) if rewrite_v2 is not None else md_resume,
        "打招呼语": greeting,
        "跟进状态": "简历人工复核" # 重点：状态标记为需复核
    }

    if rewrite_v2 is not None:
        try:
            from app.services.redis_service import redis_service
            raw_rid = state.get("record_id") or state.get("job_id") or ""
            clean_job_id = extract_record_id(raw_rid)
            if clean_job_id:
                await redis_service.set(f"cache:resume_ast:job:{clean_job_id}", rewrite_v2, expire_seconds=3600)
                logger.info(f"⚡ [rewrite_node] 已预热岗位简历 AST 缓存: clean_job_id={clean_job_id}")
        except Exception as cache_err:
            logger.debug(f"[rewrite_node] 预热简历 AST 缓存失败 (非致命): {cache_err}")

    # 官方标准 Skill：自动解析并渲染专属定制 PDF 与长图并挂载到飞书
    # 自定义多产物 Skill：清空 PDF 备份与图片保存，杜绝通用简历偷梁换柱，引导用户在定制面板确认生成
    if not is_custom_skill and rewrite_v2 is not None:
        try:
            from app.automation.materials import _render_custom_resume_materials
            from app.core.config import settings
            from app.core.feishu_client import feishu_client
            from app.services.feishu_service import get_active_resume_record_id

            parsed_json = rewrite_v2  # 复用上方已解析的 V2 结构，避免二次 LLM 解析

            # 补齐底料里的个人隐私数据 (姓名、电话、邮箱、城市)
            active_rid = await asyncio.to_thread(get_active_resume_record_id)
            if active_rid:
                rec = await feishu_client.get_record(settings.FEISHU_TABLE_ID_RESUMES, active_rid)
                if rec:
                    raw_s = rec.get("fields", {}).get("结构化数据", "")
                    if isinstance(raw_s, list):
                        raw_s = "".join([x.get("text", "") for x in raw_s])
                    if raw_s:
                        try:
                            orig_json = json.loads(raw_s)
                            if orig_json.get("personalInfo"):
                                if "personalInfo" not in parsed_json:
                                    parsed_json["personalInfo"] = {}
                                parsed_json["personalInfo"].update(orig_json["personalInfo"])
                        except Exception:
                            pass

            company = (state.get("company_name") or "").strip()
            job_title = (state.get("job_name") or "").strip()
            dynamic_raw = f"{company}_{job_title}".strip("_") if (company or job_title) else "专属定制简历"
            cleaned_name = sanitize_filename(dynamic_raw, "专属定制简历")

            mats = await _render_custom_resume_materials(parsed_json, cleaned_name)
            if mats:
                updates["PDF备份"] = [{"file_token": mats["pdf_token"], "name": f"{mats['name']}.pdf"}]
                updates["图片保存"] = [{"file_token": mats["img_token"], "name": f"{mats['name']}-长图.jpg"}]
                state["feishu_fields"]["PDF备份"] = updates["PDF备份"]
                state["feishu_fields"]["图片保存"] = updates["图片保存"]
                logger.info(f"📄 [rewrite_node] 官方Skill定制简历已自动渲染为 PDF/长图并挂载: {cleaned_name}.pdf")
            else:
                updates["PDF备份"] = []
                updates["图片保存"] = []
                state["feishu_fields"]["PDF备份"] = []
                state["feishu_fields"]["图片保存"] = []
        except Exception as e:
            logger.warning(f"⚠️ [rewrite_node] 定制简历自动渲染异常: {e}")
            updates["PDF备份"] = []
            updates["图片保存"] = []
            state["feishu_fields"]["PDF备份"] = []
            state["feishu_fields"]["图片保存"] = []
    else:
        # 自定义 Skill：清空旧物料
        updates["PDF备份"] = []
        updates["图片保存"] = []
        state["feishu_fields"]["PDF备份"] = []
        state["feishu_fields"]["图片保存"] = []
        logger.info(f"📂 [rewrite_node] 使用自定义技能 ({skill_id})，已作废清空通用旧物料，等待用户在定制面板确认生成")

    # 同步到飞书
    await update_feishu_status.ainvoke({
        "record_id": state["record_id"],
        "updates": updates
    })

    logger.info("✅ [LangGraph] 深度改写完成，请求老板审批！")
    return {
        "final_markdown": md_resume,
        "greeting": greeting,
        "status": "简历人工复核"
    }


async def quick_greeting_node(state: JobApplicationState) -> dict[str, Any]:
    """
    对 C/B 级岗位装配海投通用打招呼语，准备直接投递。
    只认人工配置的「海投通用打招呼语」：为空时直接挂回「海投人工复核」，
    🚫 禁止 LLM 现场编造通用话术（无人工把关即自动投出，HR 会收到 AI 临时瞎编内容）。
    """
    logger.info("⚡ [LangGraph] C/B 级，装配通用话术 (quick_greeting_node)...")
    await _emit_node_running(state, "quick_greeting_node", "greeting")

    config = get_autopilot_config()
    greeting = (config.get("mass_apply_greeting") or "").strip()
    if not is_valid_greeting(greeting):
        logger.error("⛔ [LangGraph] 未配置有效的「海投通用打招呼语」，岗位转「海投人工复核」，禁止现场生成通用话术")
        try:
            await update_feishu_status.ainvoke({
                "record_id": state["record_id"],
                "updates": {"跟进状态": "海投人工复核"}
            })
        except Exception as e:
            logger.warning(f"⚠️ [quick_greeting_node] 回写复核门牌异常: {e}")
        return {"greeting": "", "status": "海投人工复核"}

    logger.info("💬 [LangGraph] 使用配置的海投打招呼语，跳过现场生成")

    # 门牌跟随安检结果预写：过闸才挂「待投递」；过不了挂「海投人工复核」等老板审。
    # 否则断点等待期间岗位带着「待投递」门牌，会被每日定时发射波次当作已放行岗位误捞投出。
    gate_ok, gate_reason = evaluate_delivery_gate(state)
    if not gate_ok:
        logger.info(f"🛑 [LangGraph] {state.get('job_name')} 预检未过投递安检（{gate_reason}），预写「海投人工复核」等待老板审批")
    f_fields = state.get("feishu_fields", {})
    existing_greeting = extract_feishu_text(f_fields.get("打招呼语", "")).strip()
    effective_greeting = existing_greeting or greeting
    platform_raw = (state.get("platform") or extract_feishu_text(f_fields.get("招聘平台", ""))).lower()
    need_pdf = not bool(f_fields.get("PDF备份") or f_fields.get("PDF 备份"))
    need_image = "boss" in platform_raw and not bool(f_fields.get("图片保存"))
    material_ready = not (need_pdf or need_image)
    updates: dict[str, Any] = {}
    if not existing_greeting:
        updates["打招呼语"] = greeting

    # 按需补充海投物料（如果尚未挂载通用海投简历）
    if need_pdf or need_image:
        try:
            import os
            # 单测环境下若未 mock 物料渲染且未配置无头渲染，安全跳过真实浏览器启动以避免测试挂起
            in_test_env = bool(os.environ.get("PYTEST_CURRENT_TEST"))
            from app.automation.materials import (
                _render_mass_resume_materials,
                resolve_mass_resume_id,
            )
            is_mocked = hasattr(_render_mass_resume_materials, "assert_called") or type(_render_mass_resume_materials).__name__ in ("MagicMock", "AsyncMock", "Mock")
            if in_test_env and not is_mocked:
                logger.info("🧪 [quick_greeting_node] 单测环境检测到缺物料且未 Mock 渲染，安全保留待复核状态，不拉起真实 Playwright")
            else:
                target_mass_id = await resolve_mass_resume_id(config)
                if target_mass_id:
                    logger.info(
                        f"🎨 [quick_greeting_node] 为岗位【{state.get('job_name')}】提前按需挂载海投物料 "
                        f"(target_mass_id={target_mass_id}, need_pdf={need_pdf}, need_image={need_image})..."
                    )
                    mats = await _render_mass_resume_materials(target_mass_id, need_image=need_image)
                    if mats and (not need_pdf or mats.get("pdf_token")) and (not need_image or mats.get("img_token")):
                        material_ready = True
                        logger.info(f"✅ [quick_greeting_node] 岗位【{state.get('job_name')}】海投物料已就绪: pdf={bool(mats.get('pdf_token'))}, img={bool(mats.get('img_token'))}")
                    if mats and need_pdf and mats.get("pdf_token"):
                        updates["PDF备份"] = [{"file_token": mats["pdf_token"], "name": f"{mats['name']}.pdf"}]
                    if mats and need_image and mats.get("img_token"):
                        updates["图片保存"] = [{"file_token": mats["img_token"], "name": f"{mats['name']}-长图.jpg"}]
                    if "PDF备份" in updates:
                        state["feishu_fields"]["PDF备份"] = updates["PDF备份"]
                    if "图片保存" in updates:
                        state["feishu_fields"]["图片保存"] = updates["图片保存"]
        except Exception as e:
            logger.warning(f"⚠️ [quick_greeting_node] 海投物料按需挂载异常: {e}")

    updates["跟进状态"] = "待投递" if gate_ok and material_ready else "海投人工复核"

    await update_feishu_status.ainvoke({
        "record_id": state["record_id"],
        "updates": updates
    })

    return {"greeting": effective_greeting, "status": updates["跟进状态"]}


async def manual_review_node(state: JobApplicationState) -> dict[str, Any]:
    """
    节点，用于作为老板审批的断点。
    - 精投岗 (A/B级或有定制简历)：跟进状态写为「简历人工复核」
    - 海投大厂拦截/其他需审海投岗：跟进状态写为「海投人工复核」
    """
    is_custom = bool(
        state.get("final_markdown")
        or is_custom_record(state.get("feishu_fields") or {})
        or state.get("grade", "").upper() in ("A", "B")
    )
    target_status = "简历人工复核" if is_custom else "海投人工复核"
    logger.info(f"👨‍💻 [LangGraph] 岗位进入待老板审批断点: {state.get('job_name')} ({target_status})")
    try:
        await update_feishu_status.ainvoke({
            "record_id": state["record_id"],
            "updates": {"跟进状态": target_status}
        })
    except Exception as e:
        logger.warning(f"⚠️ [manual_review_node] 同步状态异常: {e}")
    return {"status": target_status}


_delivery_serial_lock = asyncio.Lock()

# P3 加固：投递在飞岗位登记表。手动「立即发射」、定时波次、图状态机恢复三条链路
# 最终都会汇聚到 delivery_node，此处按 record_id 互斥，防止同一岗位被两条链路
# 同时投递导致 HR 收到重复打招呼语。串行锁只防浏览器打架，防不了重复发射。
_delivery_inflight_lock = asyncio.Lock()
_DELIVERY_INFLIGHT_RECORD_IDS: set[str] = set()


async def delivery_node(state: JobApplicationState) -> dict[str, Any]:
    """
    动作：执行最终投递节点（入口守卫 + 内层执行）。
    无论是因为 C 级自动流转过来的，还是因为 A 级人工审批后流转过来的，都在此执行投递。
    严格采用平台串行锁，杜绝多平台多浏览器并发抢占；同一岗位并发命中时拦截重复发射。
    """
    record_id_raw = str(state.get("record_id") or "")
    rid = extract_record_id(record_id_raw) or record_id_raw
    if rid:
        async with _delivery_inflight_lock:
            if rid in _DELIVERY_INFLIGHT_RECORD_IDS:
                logger.warning(f"⛔ [LangGraph] 岗位 {rid} 正在另一条投递链路执行中，拦截本次重复发射")
                return {"error": f"岗位 {rid} 正在另一条投递链路执行中（防重复发射拦截），请稍后在失败台账确认投递结果"}
            _DELIVERY_INFLIGHT_RECORD_IDS.add(rid)
    try:
        return await _delivery_node_inner(state)
    finally:
        if rid:
            _DELIVERY_INFLIGHT_RECORD_IDS.discard(rid)


async def _delivery_node_inner(state: JobApplicationState) -> dict[str, Any]:
    logger.info("🚀 [LangGraph] 进入 delivery_node，准备发射！")
    fresh_record_id = extract_record_id(state.get("record_id") or state.get("job_id") or "")
    from app.automation import abort as abort_mod
    if fresh_record_id and abort_mod.is_job_delivery_cancelled(fresh_record_id):
        logger.warning(f"🛑 [LangGraph] 岗位 {fresh_record_id} 在准备发射前已被用户取消投递，立即拦截")
        abort_mod.clear_job_delivery_cancelled(fresh_record_id)
        return {"error": "[用户主动终止] 在指挥中心手动终止投递流程"}

    await _emit_node_running(state, "delivery_node", "delivering")

    fields = state.get("feishu_fields") or {}

    # 审批后可能有人刚在定制工作台保存了简历；图状态里的旧快照不能决定投递通道。
    # 发射前重新读取飞书，确保 AI改写JSON、专属附件和打招呼语来自同一份最新记录。

    # 空或仅含展示字段的输入是本地/旁路调用的兼容格式；真实编排状态会携带
    # 投递字段快照，只有存在这些字段时才做刷新，避免 mock 误触真实 API。
    refresh_keys = {"跟进状态", "综合评级 (A-F)", "AI改写JSON", "PDF备份", "PDF 备份", "图片保存", "打招呼语", "招聘平台"}
    if fresh_record_id.startswith("rec") and refresh_keys.intersection(fields):
        has_snapshot_platform = bool(state.get("platform") or extract_feishu_text(fields.get("招聘平台", "")))
        has_snapshot_decision = ("PDF备份" in fields or "PDF 备份" in fields or state.get("final_markdown") or state.get("is_custom") is not None)
        can_fallback_snapshot = has_snapshot_platform and has_snapshot_decision

        try:
            from app.core.config import settings
            from app.services.feishu_service import get_job_record_from_feishu

            fresh_record = await asyncio.to_thread(get_job_record_from_feishu, fresh_record_id, settings.FEISHU_TABLE_ID_JOBS)
            if fresh_record and isinstance(fresh_record.get("fields"), dict):
                fields = fresh_record["fields"]
                state["feishu_fields"] = fields
            else:
                if can_fallback_snapshot:
                    logger.warning(f"⚠️ [delivery_node] 发射前读取飞书记录({fresh_record_id})未获取到数据，降级沿用传入上下文快照继续发射")
                else:
                    return {"error": "投递前无法读取飞书岗位最新字段，已阻止发射以避免精投/海投通道误判"}
        except Exception as e:
            if can_fallback_snapshot:
                logger.warning(f"⚠️ [delivery_node] 发射前刷新飞书岗位字段网络异常({fresh_record_id}): {e}，降级沿用已有快照继续发射")
            else:
                logger.error(f"⛔ [delivery_node] 发射前刷新飞书岗位字段失败且快照不完整，已阻止发射: {e}")
                return {"error": "投递前无法确认飞书岗位最新字段，已阻止发射，请重试"}

    # 组装投递 Tool 需要的参数（兼容飞书无空格与带空格的历史字段名）
    pdf_attachments = fields.get("PDF备份") or fields.get("PDF 备份") or []
    file_token = (pdf_attachments[0].get("file_token", "") if pdf_attachments else "") or state.get("file_token", "")

    company = (state.get("company_name") or extract_feishu_text(fields.get("公司名称", "")) or "").strip()
    job_title = (state.get("job_name") or extract_feishu_text(fields.get("岗位名称", "")) or "").strip()

    # 🌟 规范物料命名：精投强制命名为「公司名_岗位名」（如 广州翰特_数字化产品经理）；海投统一为「我的简历」
    dynamic_raw = f"{company}_{job_title}".strip("_") if (company or job_title) else "专属定制简历"
    cleaned_name = sanitize_filename(dynamic_raw, "专属定制简历")

    # 🌟 精海投双轨鲁棒判定（统一口径 is_custom_record：AI改写JSON / 评级AB），
    # 叠加状态机显式传入的 is_custom 与 final_markdown，保证与批量编排预扫描、CLI 取数三处口径一致
    feishu_pdf_name = (pdf_attachments[0].get("name", "") if pdf_attachments else "").replace(".pdf", "")

    is_custom = bool(
        state.get("is_custom")
        or (str(state.get("grade", "")).upper() in ("A", "B"))
        or state.get("final_markdown")
        or is_custom_record(fields)
    )
    is_mass = not is_custom
    pdf_name = "我的简历" if is_mass else (
        (state.get('pdf_filename', '') or '').replace('.pdf', '')
        or (feishu_pdf_name if feishu_pdf_name and "通用" not in feishu_pdf_name else "")
        or cleaned_name
    )

    job_link_obj = fields.get("岗位链接", {})
    job_url = (job_link_obj.get("link", "") if isinstance(job_link_obj, dict) else str(job_link_obj)) or state.get("job_url", "")

    greeting = state.get("greeting") or extract_feishu_text(fields.get("打招呼语", ""))

    # 从飞书「图片保存」字段提取图片简历附件（优先使用 state 中显式传入的 image_items）
    image_items = state.get("image_items") or []
    if not image_items:
        image_attachments = fields.get("图片保存", []) or []
        if isinstance(image_attachments, list):
            for att in image_attachments:
                if not isinstance(att, dict):
                    continue
                token = att.get("file_token", "")
                if token:
                    image_items.append({"token": token, "name": att.get("name", "image.jpg")})

    # 51job 无打招呼机制，不强制要求；智联投递后需发起微聊私信，打招呼语是必填物料
    platform_raw = state.get("platform", "")
    is_51job = "51job" in platform_raw.lower() or "前程无忧" in platform_raw
    is_zhilian = "智联" in platform_raw or "zhilian" in platform_raw.lower()
    is_liepin = "猎聘" in platform_raw or "liepin" in platform_raw.lower()
    is_boss = "boss" in platform_raw.lower()

    # 海投岗位防呆自愈补料：若海投岗位缺 PDF、缺图片或缺打招呼语，现场极速装配挂载
    if is_mass and (not file_token or (is_boss and not image_items) or not greeting):
        try:
            logger.info("🛡️ [LangGraph] 检测到海投岗位物料缺失，触发即时自愈装配...")
            from app.automation.materials import (
                _render_mass_resume_materials,
                resolve_mass_resume_id,
            )
            config = get_autopilot_config()
            target_mass_id = await resolve_mass_resume_id(config)
            if target_mass_id:
                mats = await _render_mass_resume_materials(target_mass_id, need_image=is_boss)
                if mats:
                    logger.info(
                        f"🛡️ [delivery_node] 即时补料完成 (target={target_mass_id}, need_image={is_boss}, "
                        f"pdf={bool(mats.get('pdf_token'))}, img={bool(mats.get('img_token'))})"
                    )
                    file_token = file_token or mats.get("pdf_token")
                    # 长图只装配给 BOSS：透传 need_image=is_boss 后非 BOSS 的 mats 天然无 img_token，
                    # 此处严禁裸取 mats["img_token"]，否则 KeyError 会中断整个自愈块（连招呼语兜底都被跳过）
                    if is_boss and not image_items and mats.get("img_token"):
                        image_items = [{"token": mats["img_token"], "name": f"{mats['name']}-长图.jpg"}]
                    if not greeting:
                        # 打招呼语只认人工配置的「海投通用打招呼语」，缺失就留空交给下方门禁拦截失败，禁止现场编造兜底
                        greeting = (config.get("mass_apply_greeting") or "").strip()
        except Exception as e:
            logger.warning(f"⚠️ [delivery_node] 海投即时补料异常: {e}")

    # 🚫 打招呼语合法性校验：拦截生成失败的错误文本（如「❌ AI 服务未配置」）被当欢迎语发给 HR，
    # 同时兜底拦截历史脏数据（此前版本曾把错误文本/海投通用语写进「打招呼语」字段）
    if greeting and not is_valid_greeting(greeting):
        logger.error(f"❌ [LangGraph] 打招呼语物料非法（疑似生成失败错误文本），已拦截: {str(greeting)[:60]}")
        return {"error": "[物料] 打招呼语为非法内容（疑似生成失败的错误文本），已拦截，请人工修正飞书「打招呼语」字段后重试"}

    if not job_url or (not is_51job and not greeting):
        logger.error("❌ 投递数据不全，缺少链接或打招呼语")
        return {"error": "投递数据不全，缺少链接或打招呼语"}

    # 投递网关强物料校验（防呆拦截）
    if (is_zhilian or is_51job or is_liepin) and not file_token:
        err_msg = "❌ 缺少 PDF 简历附件：该岗位为定制改写岗，请前往【定制面板】确认并生成 PDF 附件后再发射投递"
        logger.error(err_msg)
        return {"error": err_msg}

    if is_boss and not image_items:
        err_msg = "❌ 缺少图片简历附件：BOSS 直聘必须使用长图简历物料，请前往【定制面板】确认并生成简历图片后再发射投递"
        logger.error(err_msg)
        return {"error": err_msg}

    batch_mass_uploaded = bool(state.get("batch_mass_uploaded", False))
    retry_greeting_only = bool(state.get("retry_greeting_only", False))
    job_data = {
        "record_id": state["record_id"],
        "job_url": job_url,
        "file_token": file_token,
        "pdf_name": pdf_name,
        "temp_pdf_name": pdf_name,
        "greeting": greeting,
        "job_title": job_title,
        "company": company,
        "image_items": image_items,
        "mass_apply": is_mass,
        "batch_mass_uploaded": batch_mass_uploaded,
        "retry_greeting_only": retry_greeting_only,
    }

    platform = state["platform"].lower()

    # 1. 获取锁前取消检查
    if fresh_record_id and abort_mod.is_job_delivery_cancelled(fresh_record_id):
        logger.warning(f"🛑 [LangGraph] 岗位 {fresh_record_id} 在获取锁前已被用户取消投递，拦截执行")
        abort_mod.clear_job_delivery_cancelled(fresh_record_id)
        return {"error": "[用户主动终止] 在指挥中心手动终止投递流程"}

    # 严格串行投递：获取全局浏览器互斥锁，确保单平台单岗位依次投递，避免多浏览器并发打架
    async with _delivery_serial_lock:
        logger.info(f"🔒 [LangGraph] 已获取投递互斥锁，开始执行 [{platform}] 投递...")

        # 2. 获取锁后检查是否在排队期间被取消
        if fresh_record_id and abort_mod.is_job_delivery_cancelled(fresh_record_id):
            logger.warning(f"🛑 [LangGraph] 岗位 {fresh_record_id} 在排队期间已被用户取消投递，拦截唤起浏览器")
            abort_mod.clear_job_delivery_cancelled(fresh_record_id)
            return {"error": "[用户主动终止] 在指挥中心手动终止投递流程"}

        try:
            if "boss" in platform:
                res = await deliver_boss_job.ainvoke({"job_data": job_data})
            elif "猎聘" in platform or "liepin" in platform:
                res = await deliver_liepin_job.ainvoke({"job_data": job_data})
            elif "51job" in platform or "前程无忧" in platform:
                res = await deliver_51job_job.ainvoke({"job_data": job_data})
            elif "智联" in platform or "zhilian" in platform:
                res = await deliver_zhilian_job.ainvoke({"job_data": job_data})
            else:
                res = f"⚠️ 未知平台 {platform}，无法自动投递"
        except Exception as e:
            res = f"❌ 投递异常中断: {str(e)[:100]}"
        finally:
            # 无论正常退出还是异常中断，均清理本岗取消标记
            was_cancelled = bool(fresh_record_id and abort_mod.is_job_delivery_cancelled(fresh_record_id))
            if fresh_record_id:
                abort_mod.clear_job_delivery_cancelled(fresh_record_id)

        # 🌟 关键归因补丁：若执行期间下达了取消指令，但在取消生效前 Tool 实际已成功送达（✅），
        # 必须保留真实成功结果，避免把已投出的岗位误写为失败导致二次重复投递；仅在执行未成功时覆写为用户主动终止
        if was_cancelled:
            if str(res).startswith("✅") and "微聊受阻" not in str(res):
                logger.info(f"ℹ️ [LangGraph] 岗位 {fresh_record_id} 执行期间虽收到取消指令，但实际已投递成功，保留成功结果")
            else:
                logger.warning(f"🛑 [LangGraph] 岗位 {fresh_record_id} 执行未成功且命中取消指令，统一归因为用户主动终止")
                res = "❌ [用户主动终止] 在指挥中心手动终止投递流程"

        logger.info(f"🎯 [LangGraph] 投递 Tool 执行结果: {res}")

    # 严格根据协议前缀判断投递成功，杜绝“成功”子串匹配导致的逻辑地雷
    if str(res).startswith("✅") and "微聊受阻" not in str(res):
        # 🌟 双保险：除各引擎自身的成功清空外，编排层落「已投递」时同步清空历史失败日志，
        # 杜绝登录态残留等旧账把真实送达的打招呼语误判成「未送达」
        await update_feishu_status.ainvoke({
            "record_id": state["record_id"],
            "updates": {"跟进状态": "已投递", "自动投递失败日志": ""}
        })
        return {"status": "已投递"}
    else:
        # 投递失败时，后端同步将飞书的「跟进状态」写入为「投递失败」，并回写失败日志与本地台账
        from app.automation import run_snapshot as _rs
        from app.services import feishu_service
        try:
            _rs.record_delivery_failure(
                job_id=state["record_id"],
                error=str(res),
                company=state.get("company_name", ""),
                job_name=state.get("job_name", ""),
                platform=state.get("platform", "zhilian"),
                job_url=state.get("job_url", ""),
                grade=state.get("grade", "D"),
            )
        except Exception as e_rs:
            logger.warning(f"⚠️ [LangGraph] 记录本地失败台账异常 (不阻断主流程): {e_rs}")
        try:
            await asyncio.to_thread(
                feishu_service.mark_job_delivery_failed,
                state["record_id"],
                str(res)
            )
        except Exception as e:
            logger.warning(f"⚠️ [LangGraph] 回写飞书投递失败状态异常 (不阻断主流程): {e}")
        return {"error": res}


# ==========================================
# 3. 路由与建图 (Graph Setup)
# ==========================================

def route_after_evaluate(state: JobApplicationState) -> str:
    """
    条件路由：初评后动态分流
    动态读取用户在「AI 初评」抽屉里配置的流转阀门/自动化阈值（A / B / C 级），
    🌟 判定式与批量初评漏斗（wave_pipeline）完全同阈值：等级达标 **或** 分数达标均进精投定制轨，
    杜绝「初评漏斗放行的 70 分 C 级岗在自动链路里被降级进海投轨」的双标。
    - 达到阈值 -> 进入 rewrite_node 进行深度画像、简历重构与专属话术；
    - 未达阈值 -> 统一进入 quick_greeting_node 装配海投通用 PDF 简历与打招呼语。
    """
    if state.get("error"):
        return END

    grade = state.get("grade", "C").upper()

    from ai_agents.ai_evaluator import get_auto_eval_threshold
    threshold = get_auto_eval_threshold()

    is_custom_track = grade_meets_threshold(grade, threshold)

    if is_custom_track:
        logger.info(f"🎯 [LangGraph] 岗位评级 {grade} 达到精投阀门 {threshold}，流转至精投定制轨 (rewrite_node)")
        return "rewrite_node"
    else:
        logger.info(f"⚡ [LangGraph] 岗位评级 {grade} 未达精投阀门 {threshold}，流转至海投物料轨 (quick_greeting_node)")
        return "quick_greeting_node"


def evaluate_delivery_gate(state: JobApplicationState) -> tuple[bool, str]:
    """投递前安检闸门：安检1 大厂规模拦截 + 安检2 等级/平台免审白名单。

    供 route_before_delivery（决定路由走向）与 quick_greeting_node（决定预写门牌）共用，
    保证飞书「跟进状态」与状态机实际走向永远一致。
    返回 (是否放行, 拦截原因)。
    """
    config = get_autopilot_config()
    grade = (state.get("grade") or "C").upper()

    # 1. 海投大厂门槛拦截：C-F 海投路径上，若公司规模下限 ≥ 门槛 (默认 1000 人)，不放行
    is_mass_track = not bool(
        state.get("final_markdown")
        or is_custom_record(state.get("feishu_fields") or {})
    )
    if is_mass_track:
        try:
            threshold = int(config.get("mass_apply_max_headcount", 1000) or 1000)
            fields = state.get("feishu_fields") or {}
            size_txt = extract_feishu_text(fields.get("公司规模", ""))
            m = re.search(r"(\d+)", size_txt or "")
            if m and int(m.group(1)) >= threshold:
                return False, f"公司规模 {size_txt} ≥ 门槛 {threshold}"
        except Exception as e:
            logger.warning(f"[LangGraph] 海投门槛校验异常: {e}")

    # 2. 平台与等级免审白名单判定
    platform = (state.get("platform") or "").lower()
    platform_key = ""
    if "boss" in platform:
        platform_key = "boss"
    elif "猎聘" in platform or "liepin" in platform:
        platform_key = "liepin"
    elif "智联" in platform or "zhilian" in platform:
        platform_key = "zhilian"
    elif "51job" in platform or "前程无忧" in platform:
        platform_key = "51job"
    elif "小红书" in platform or "xiaohongshu" in platform:
        platform_key = "xiaohongshu"

    auto_deliver_platforms = config.get("auto_deliver_platforms", ["boss", "liepin", "51job", "zhilian"])
    if platform_key not in auto_deliver_platforms:
        return False, f"平台 {platform_key or platform or '未知'} 未开启自动投递"

    auto_grades = config.get("auto_deliver_grades", ["C", "D", "F"])
    if grade not in auto_grades:
        return False, f"评级 {grade} 未在自动投递等级白名单中 (配置: {auto_grades})"

    return True, ""


def route_before_delivery(state: JobApplicationState) -> str:
    """
    条件路由：投递前的自动化大盘校验
    1. 安检闸门未通过（大厂规模 / 等级或平台不在免审白名单）-> manual_review_node 挂「待老板审批」
    2. 闸门通过后的发射时机：
       - 手动立即模式 -> delivery_node 调起浏览器立即投递
       - 定时链路模式 (stop_at_review) -> END：飞书保持「待投递」，由每日两波定时发射统一拉起
    """
    if state.get("error"):
        return END

    gate_ok, gate_reason = evaluate_delivery_gate(state)
    if not gate_ok:
        logger.info(f"🛑 [LangGraph] {state.get('job_name')} 未过投递安检（{gate_reason}），进入「待老板审批」断点...")
        return "manual_review_node"

    if state.get("stop_at_review"):
        logger.info(f"📦 [LangGraph] 定时链路模式：{state.get('job_name')} 普通海投免审通过，飞书保留「待投递」就绪态，等待定时发射")
        return END

    logger.info(f"🚦 [LangGraph] {(state.get('grade') or 'C').upper()} 级命中自动投递白名单且规模合规，立即放行自动投递！")
    return "delivery_node"

def build_pipeline_graph() -> StateGraph:
    """构建完整的全自动流水线状态机"""

    workflow = StateGraph(JobApplicationState)

    # 注册节点
    workflow.add_node("evaluate_node", evaluate_node)
    workflow.add_node("rewrite_node", rewrite_node)
    workflow.add_node("quick_greeting_node", quick_greeting_node)
    workflow.add_node("manual_review_node", manual_review_node)
    workflow.add_node("delivery_node", delivery_node)

    # 设定起始点
    workflow.set_entry_point("evaluate_node")

    # 设定初评后的条件路由
    workflow.add_conditional_edges(
        "evaluate_node",
        route_after_evaluate,
        {
            "rewrite_node": "rewrite_node",
            "quick_greeting_node": "quick_greeting_node",
            END: END
        }
    )

    # 生成话术/精修简历后，都进入发车前的安检路由
    workflow.add_conditional_edges(
        "quick_greeting_node",
        route_before_delivery,
        {
            "delivery_node": "delivery_node",
            "manual_review_node": "manual_review_node",
            END: END
        }
    )

    workflow.add_conditional_edges(
        "rewrite_node",
        route_before_delivery,
        {
            "delivery_node": "delivery_node",
            "manual_review_node": "manual_review_node",
            END: END
        }
    )

    # 如果进入了人工审批断点，审批后则去投递
    workflow.add_edge("manual_review_node", "delivery_node")

    # 投递节点执行完就结束
    workflow.add_edge("delivery_node", END)

    return workflow

# 你可以在外部模块（如 FastAPI 启动时）这样编译并运行它：
# async def get_compiled_graph():
#     from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
#     # 使用 SQLite 持久化保存断点状态
#     memory = AsyncSqliteSaver.from_conn_string("checkpoints.db")
#
#     # 关键所在：在进入 manual_review_node 前强制中断！这就是留给老板人工审批的断点。
#     app = build_pipeline_graph().compile(
#         checkpointer=memory,
#         interrupt_before=["manual_review_node"]
#     )
#     return app
