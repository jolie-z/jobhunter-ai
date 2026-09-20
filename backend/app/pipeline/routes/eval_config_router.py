import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.pipeline.routes.feishu_status_router import _ACTIVE_RESUME_META_CACHE

logger = logging.getLogger("pipeline_eval_config_router")
logger.setLevel(logging.INFO)

router = APIRouter()


class EvalConfigBody(BaseModel):
    concurrency: int | None = None
    threshold: str | None = None
    weights: dict[str, float] | None = None
    enable_company_search: bool | None = None


class EvalPreferenceBody(BaseModel):
    record_id: str | None = None
    type: str | None = "核心加分"
    rule: str
    status: str | None = "启用"


class ActivateResumeBody(BaseModel):
    record_id: str


class SetMassApplyResumeBody(BaseModel):
    record_id: str


class RewriteConfigBody(BaseModel):
    skill_id: str | None = None
    include_diagnosis: bool | None = None


@router.get("/eval-config")
async def get_eval_config_endpoint():
    """获取 AI 初评全部配置：模型名、并发通道、流转阈值、8维权重、企业背调开关、基准简历与求职偏好矩阵"""
    from app.automation.db import get_autopilot_config
    from app.core.config import settings
    from app.services.feishu_service import get_active_resume_meta, get_all_resumes_meta
    from app.strategy import service as strat_service

    autopilot_cfg = get_autopilot_config()
    concurrency = autopilot_cfg.get("eval_concurrency", 5)
    enable_company_search = autopilot_cfg.get("enable_company_search", True)
    mass_apply_resume_id = (autopilot_cfg.get("mass_apply_resume_id") or "").strip()

    active_resume = await asyncio.to_thread(get_active_resume_meta)
    all_resumes = await asyncio.to_thread(get_all_resumes_meta)

    mass_apply_resume = next((r for r in all_resumes if r.get("record_id") == mass_apply_resume_id), None)
    if not mass_apply_resume and active_resume:
        mass_apply_resume = active_resume

    weights = await strat_service.get_weights_service()

    all_prefs = await strat_service.get_preferences_service()
    threshold = "A"
    bonus_preferences = []
    for p in all_prefs:
        if p.get("type") == "自动化阈值":
            threshold = p.get("rule", "A")
        else:
            bonus_preferences.append(p)

    return {
        "code": 0,
        "data": {
            "model_name": settings.OPENAI_MODEL or "mimo-v2.5-pro",
            "base_url": settings.OPENAI_BASE_URL or "",
            "concurrency": concurrency,
            "threshold": threshold,
            "enable_company_search": enable_company_search,
            "tavily_configured": bool(settings.TAVILY_API_KEY),
            "active_resume": active_resume,
            "mass_apply_resume_id": mass_apply_resume_id,
            "mass_apply_resume": mass_apply_resume,
            "all_resumes": all_resumes,
            "weights": weights,
            "preferences": bonus_preferences,
        },
    }


@router.get("/deep-eval-config")
async def get_deep_eval_config_endpoint():
    """获取深度评估规则配置：基准简历、全部可用简历、6大诊断模块、防编造铁律与轻量化Prompt架构"""
    from app.core.config import settings
    from app.services.feishu_service import get_active_resume_meta, get_all_resumes_meta

    active_resume = await asyncio.to_thread(get_active_resume_meta)
    all_resumes = await asyncio.to_thread(get_all_resumes_meta)

    modules = [
        {
            "key": "ats_ability_analysis",
            "name": "01·ATS 词频与硬技能提取",
            "icon": "🎯",
            "desc": "提取 JD 明确要求的 Must-Have 与 Nice-to-Have 技能列表，执行词汇重合度比对，并列出严禁在改写中凭空注入的缺失项硬约束。",
        },
        {
            "key": "resume_audit",
            "name": "02·简历逐行合规审计",
            "icon": "🔍",
            "desc": "按个人总结、技能、项目、工作分段审计主张与证据，标出 ✅安全 / ⚠️谨慎 / ❌高风险，并为绝对化表述提供安全措辞降噪建议。",
        },
        {
            "key": "dream_picture",
            "name": "03·理想画像与能力信号",
            "icon": "🌟",
            "desc": "提炼目标岗位业务面试官最关心的 3 个核心能力信号与理想人选特质。",
        },
        {
            "key": "strong_fit_assessment",
            "name": "04·高杠杆匹配点",
            "icon": "🚀",
            "desc": "挖掘候选人最硬核、最能溢价打动用人部门的王牌经验与商业战果。",
        },
        {
            "key": "risk_red_flags",
            "name": "05·致命硬伤与后果推演",
            "icon": "⚠️",
            "desc": "预判面试官会发难的核心质疑点与技术短板，推演初筛被刷风险。",
        },
        {
            "key": "deep_action_plan",
            "name": "06·破局行动计划与时间桶任务",
            "icon": "📋",
            "desc": "制定针对本岗位的定制改写策略、向候选人索取关键技术细节清单，并生成 [半天/1天/3天/1周] 具体可交付的技能补强任务与预期匹配度提升。",
        },
    ]

    anti_hallucination_rules = [
        "只审计简历中实际写明的内容，严禁凭空脑补",
        "量化数据若无评估方法说明一律标记 ⚠️谨慎",
        "绝对化表述 (100%/零失误/彻底/精通) 一律标记 ⚠️谨慎并给出降级措辞",
        "缺失技能严禁以任何形式在后续改写中造假编造",
    ]

    return {
        "code": 0,
        "data": {
            "model_name": settings.OPENAI_MODEL or "mimo-v2.5-pro",
            "temperature": 0.2,
            "active_resume": active_resume,
            "all_resumes": all_resumes,
            "modules": modules,
            "anti_hallucination_rules": anti_hallucination_rules,
        },
    }


@router.post("/activate-resume")
async def activate_resume_endpoint(body: ActivateResumeBody):
    """排他性激活指定的基准简历，供 AI 初评与深度评估实时锚定"""
    from app.services.feishu_service import get_active_resume_meta, get_all_resumes_meta
    from app.strategy.service import activate_target_resume

    await asyncio.to_thread(activate_target_resume, body.record_id)
    active_resume = await asyncio.to_thread(get_active_resume_meta)
    all_resumes = await asyncio.to_thread(get_all_resumes_meta)
    _ACTIVE_RESUME_META_CACHE["ts"] = 0.0
    _ACTIVE_RESUME_META_CACHE["value"] = active_resume
    return {
        "code": 0,
        "msg": f"已成功切换当前基准简历为：{active_resume.get('title', '')}",
        "data": {
            "active_resume": active_resume,
            "all_resumes": all_resumes,
        },
    }


@router.post("/set-mass-apply-resume")
async def set_mass_apply_resume_endpoint(body: SetMassApplyResumeBody):
    """设置海投专属简历（C-F级海投通道生成 PDF 附件投递用）"""
    from app.automation.db import update_autopilot_config
    from app.services.feishu_service import get_active_resume_meta, get_all_resumes_meta

    logger.info(f"📑 [Pipeline] 设置海投专属简历: record_id={body.record_id}")

    update_autopilot_config(mass_apply_resume_id=body.record_id)
    all_resumes = await asyncio.to_thread(get_all_resumes_meta)
    target = next((r for r in all_resumes if r.get("record_id") == body.record_id), None)
    if not target:
        target = await asyncio.to_thread(get_active_resume_meta)

    return {
        "code": 0,
        "msg": f"海投专属简历已设置为：{target.get('title', '默认简历') if target else '默认简历'}",
        "data": {
            "mass_apply_resume_id": body.record_id,
            "mass_apply_resume": target,
            "all_resumes": all_resumes,
        },
    }


@router.get("/rewrite-config")
async def get_rewrite_config_endpoint():
    """获取简历改写规则配置：可用技能列表、当前选中的 Skill、带入深度体检诊断开关、核心 Prompt 红线等"""
    from ai_agents.skills.skill_loader import get_skill_manager
    from app.automation.db import get_autopilot_config

    manager = get_skill_manager()
    skills_list = manager.list_skills()
    rewrite_skills = [
        s for s in skills_list if not s.get("id", "").startswith("greeting_") and s.get("id") != "greeting_writer"
    ]

    cfg = get_autopilot_config()
    current_skill_id = cfg.get("rewrite_skill_id") or manager.current_skill_id or "resume_rewrite"
    include_diagnosis = cfg.get("rewrite_include_diagnosis", True)

    prompt_rules = [
        "🚫 严禁 AI 腥味黑话（自动拦截赋能、闭环、抓手、对齐、拉通、助力等 12+ 虚词）",
        "🏢 工作经历全量保留（原简历多少段工作经历，最终 100% 完整保留对应段落，不裁剪时间线）",
        "💎 五要素子弹点公式（强动词 + 技术对象 + 约束难点 + 解决方案 + 机制成果）",
        "🏷️ 三档证据强度标注（行末标注 [稳] / [需补证] / [补证后可用]，辅助面试防拷问）",
    ]

    return {
        "code": 0,
        "data": {
            "current_skill_id": current_skill_id,
            "skills": rewrite_skills,
            "include_diagnosis": include_diagnosis,
            "prompt_rules": prompt_rules,
        },
    }


@router.post("/rewrite-config")
async def save_rewrite_config_endpoint(body: RewriteConfigBody):
    """保存简历改写规则设置（Skill ID、带入诊断开关）——严格 PATCH，只写本面板字段"""
    from ai_agents.skills.skill_loader import get_skill_manager
    from app.automation.db import update_autopilot_config

    if body.skill_id:
        try:
            manager = get_skill_manager()
            manager.set_current_skill(body.skill_id)
        except Exception:
            pass

    if not update_autopilot_config(
        rewrite_skill_id=body.skill_id,
        rewrite_include_diagnosis=body.include_diagnosis,
    ):
        raise HTTPException(status_code=500, detail="保存配置失败：数据库写入异常，请重试")
    return {"code": 0, "msg": "简历改写规则已保存生效"}


@router.post("/eval-config")
async def save_eval_config_endpoint(body: EvalConfigBody):
    """批量更新初评配置（并发数、流转阈值、8维权重、背调开关）——严格 PATCH，只写本面板字段"""
    from app.automation import workflow as _wf
    from app.automation.db import update_autopilot_config
    from app.strategy import service as strat_service
    from app.strategy.schemas import PreferenceUpsertRequest

    if not update_autopilot_config(
        eval_concurrency=max(1, min(20, body.concurrency)) if body.concurrency is not None else None,
        enable_company_search=body.enable_company_search,
    ):
        raise HTTPException(status_code=500, detail="保存配置失败：数据库写入异常，请重试")

    _wf.reset_eval_semaphore()

    if body.weights:
        await strat_service.update_weights_service(body.weights)

    if body.threshold:
        all_prefs = await strat_service.get_preferences_service()
        existing_thresh = next((p for p in all_prefs if p.get("type") == "自动化阈值"), None)
        await strat_service.upsert_preference_service(
            PreferenceUpsertRequest(
                record_id=existing_thresh.get("record_id") if existing_thresh else None,
                type="自动化阈值",
                rule=body.threshold,
                status="启用",
            )
        )

    return {"code": 0, "msg": "AI 初评规则与权重已保存生效"}


@router.post("/eval-preferences")
async def upsert_eval_preference_endpoint(body: EvalPreferenceBody):
    """新增或修改单条加分偏好"""
    from app.strategy import service as strat_service
    from app.strategy.schemas import PreferenceUpsertRequest

    rec_id = await strat_service.upsert_preference_service(
        PreferenceUpsertRequest(
            record_id=body.record_id,
            type=body.type or "核心加分",
            rule=body.rule.strip(),
            status=body.status or "启用",
        )
    )
    return {"code": 0, "msg": "偏好规则已更新", "data": {"record_id": rec_id}}


@router.delete("/eval-preferences/{record_id}")
async def delete_eval_preference_endpoint(record_id: str):
    """删除指定偏好规则"""
    from app.strategy import service as strat_service

    await strat_service.delete_preference_service(record_id)
    return {"code": 0, "msg": "偏好规则已删除"}
