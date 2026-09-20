import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("pipeline_delivery_config_router")
logger.setLevel(logging.INFO)

router = APIRouter()


class GreetingConfigBody(BaseModel):
    greeting_platforms: dict[str, bool] | None = None
    mass_apply_greeting: str | None = None
    prompt_mode: str | None = None
    custom_prompt: str | None = None


class ReviewConfigBody(BaseModel):
    mass_apply_max_headcount: int | None = None


class DeliveryConfigBody(BaseModel):
    auto_deliver_platforms: list[str] | None = None
    auto_deliver_grades: list[str] | None = None
    mass_deliver_time: str | None = None
    custom_deliver_mode: str | None = None
    custom_deliver_time: str | None = None
    delivery_timeout_sec: int | None = None
    batch_limit: int | None = None


@router.get("/greeting-config")
async def get_greeting_config_endpoint():
    """获取打招呼语生成规则配置：生成平台开关、海投通用打招呼语、当前基准简历、Prompt模式与内容"""
    from app.automation.db import get_autopilot_config
    from app.core.config import settings
    from app.services.feishu_service import get_active_resume_meta

    cfg = get_autopilot_config()
    greeting_platforms = cfg.get("greeting_platforms") or {
        "boss": True,
        "liepin": True,
        "zhilian": True,
        "51job": False,
    }
    mass_apply_greeting = cfg.get("mass_apply_greeting") or ""
    prompt_mode = cfg.get("greeting_prompt_mode", "official") or "official"
    custom_prompt = cfg.get("custom_greeting_prompt", "") or ""

    official_prompt = ""
    skill_file_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "ai_agents",
        "skills",
        "greeting_writer.md",
    )
    if os.path.exists(skill_file_path):
        try:
            with open(skill_file_path, encoding="utf-8") as f:
                official_prompt = f.read()
        except Exception:
            pass

    active_resume = await asyncio.to_thread(get_active_resume_meta)

    prompt_rules = [
        "🎯 固定开场白（一字不差）:「您好，认真看了贵公司岗位JD，核心胜任力我是全覆盖的，简单做个自我介绍方便您快速匹配:」",
        "🚫 严禁 AI 腥味虚词套话: 禁用「可能匹配、了解、协助、参与过、较高、大量」等模糊词，只以 100% 实打实的事实和数据支撑",
        "⚡ 2-3 条硬核量化子弹点: 用数字列表直截了当罗列具体项目战果、核心技术栈与业务溢价",
        "📌 固定结尾与字数红线: 严格控制在 150-250 字内（绝对不超过 300 字），结尾一字不差:「这是我的简历，期待和您有关于岗位的深度沟通。」",
    ]

    opening_template = "您好，认真看了贵公司岗位JD，核心胜任力我是全覆盖的，简单做个自我介绍方便您快速匹配:"
    closing_template = "这是我的简历，期待和您有关于岗位的深度沟通。"

    return {
        "code": 0,
        "data": {
            "model_name": settings.OPENAI_MODEL or "mimo-v2.5-pro",
            "greeting_platforms": greeting_platforms,
            "mass_apply_greeting": mass_apply_greeting,
            "prompt_mode": prompt_mode,
            "custom_prompt": custom_prompt,
            "official_prompt": official_prompt,
            "active_resume": active_resume,
            "prompt_rules": prompt_rules,
            "opening_template": opening_template,
            "closing_template": closing_template,
        },
    }


@router.post("/greeting-config")
async def save_greeting_config_endpoint(body: GreetingConfigBody):
    """保存打招呼语规则设置（生成平台开关、海投通用话术、Prompt模式与自定义Prompt）

    严格 PATCH：只写本面板负责的字段，其余字段传 None 保持库中现值，
    避免跨面板保存时用旧快照互相覆盖。
    """
    from app.automation.db import update_autopilot_config

    gp = body.greeting_platforms
    mag = body.mass_apply_greeting
    pm = body.prompt_mode
    cp = body.custom_prompt

    if not update_autopilot_config(
        mass_apply_greeting=mag,
        greeting_platforms=gp,
        greeting_prompt_mode=pm,
        custom_greeting_prompt=cp,
    ):
        raise HTTPException(status_code=500, detail="保存配置失败：数据库写入异常，请重试")
    return {"code": 0, "msg": "打招呼语规则设置已保存生效"}


@router.get("/review-config")
async def get_review_config_endpoint():
    """获取待审批配置：大公司海投门槛人数、待审批岗位流与物料齐备状态"""
    from app.automation.db import get_autopilot_config
    from app.services.feishu_service import get_pending_review_jobs_from_feishu

    cfg = get_autopilot_config()
    mass_apply_max_headcount = cfg.get("mass_apply_max_headcount", 1000)
    auto_deliver_grades = cfg.get("auto_deliver_grades", ["C", "D", "F"])

    pending_jobs = await asyncio.to_thread(get_pending_review_jobs_from_feishu)

    return {
        "code": 0,
        "data": {
            "mass_apply_max_headcount": mass_apply_max_headcount,
            "auto_deliver_grades": auto_deliver_grades,
            "pending_jobs": pending_jobs,
        },
    }


@router.post("/review-config")
async def save_review_config_endpoint(body: ReviewConfigBody):
    """保存待审批规则（大公司海投门槛人数等）——严格 PATCH，只写本面板字段"""
    from app.automation.db import update_autopilot_config

    headcount = body.mass_apply_max_headcount

    if not update_autopilot_config(
        mass_apply_max_headcount=int(headcount) if headcount is not None else None,
    ):
        raise HTTPException(status_code=500, detail="保存配置失败：数据库写入异常，请重试")
    return {"code": 0, "msg": "待审批规则设置已保存生效"}


@router.get("/delivery-config")
async def get_delivery_config_endpoint():
    """获取自动投递规则（目标平台、双轨定时时间、超时熔断秒数、物料搭载审计流水）"""
    from app.automation.db import get_autopilot_config
    from app.services.feishu_service import get_delivered_jobs_from_feishu

    cfg = get_autopilot_config()
    delivered_jobs = await asyncio.to_thread(get_delivered_jobs_from_feishu)

    return {
        "code": 0,
        "data": {
            "auto_deliver_platforms": cfg.get("auto_deliver_platforms", ["boss", "liepin", "51job", "zhilian"]),
            "auto_deliver_grades": cfg.get("auto_deliver_grades", ["C", "D", "F"]),
            "mass_deliver_time": cfg.get("mass_deliver_time", "09:30"),
            "custom_deliver_mode": cfg.get("custom_deliver_mode", "immediate"),
            "custom_deliver_time": cfg.get("custom_deliver_time", "14:00"),
            "delivery_timeout_sec": cfg.get("delivery_timeout_sec", 45),
            "batch_limit": cfg.get("batch_limit", 20),
            "delivered_jobs": delivered_jobs,
        },
    }


@router.post("/delivery-config")
async def save_delivery_config_endpoint(body: DeliveryConfigBody):
    """保存自动投递规则设置——严格 PATCH，只写本面板字段"""
    from app.automation import scheduler as _auto_sched
    from app.automation.db import update_autopilot_config

    if body.auto_deliver_grades is not None:
        valid_grades = [
            g
            for g in dict.fromkeys(str(g).upper() for g in body.auto_deliver_grades)
            if g in ("A", "B", "C", "D", "F")
        ]
        if not valid_grades:
            raise HTTPException(status_code=400, detail="自动投递等级至少需勾选一项（A-F）")
    else:
        valid_grades = None
    mass_time = body.mass_deliver_time
    custom_mode = body.custom_deliver_mode
    custom_time = body.custom_deliver_time
    timeout_sec = body.delivery_timeout_sec
    batch_limit = body.batch_limit
    if timeout_sec is not None:
        timeout_sec = max(5, min(300, int(timeout_sec or 45)))
    if batch_limit is not None:
        batch_limit = max(1, min(500, int(batch_limit or 20)))

    if not update_autopilot_config(
        auto_deliver_grades=valid_grades,
        auto_deliver_platforms=body.auto_deliver_platforms,
        batch_limit=batch_limit,
        mass_deliver_time=mass_time,
        custom_deliver_mode=custom_mode,
        custom_deliver_time=custom_time,
        delivery_timeout_sec=int(timeout_sec) if timeout_sec is not None else None,
    ):
        raise HTTPException(status_code=500, detail="保存配置失败：数据库写入异常，请重试")

    _auto_sched.update_delivery_schedules()
    return {"code": 0, "msg": "自动投递规则设置已保存生效"}
