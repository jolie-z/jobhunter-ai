"""
自动驾驶配置大屏与定时任务路由 (Config Router)
==============================================
负责：
- 自动驾驶全局配置读取与保存 (/config)
- 每日定时调度范围与节假日跳过 (/schedule-config)
- 节假日日历数据状态与热更新 (/holiday-data-status, /holiday-data-update)
- 海投通用打招呼语生成 (/generate-mass-greeting)
- 最近 50 条自动化运行日志 (/logs)
"""
import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.automation import scheduler
from app.automation.db import (
    get_autopilot_config,
    get_recent_autopilot_logs,
    update_autopilot_config,
)
from app.automation.schemas import AutopilotConfigSchema

logger = logging.getLogger(__name__)
router = APIRouter()


class ScheduleConfigBody(BaseModel):
    cron_time: str = "09:00"
    is_enabled: bool = True
    schedule_start_date: str = ""
    schedule_end_date: str = ""
    skip_non_workdays: bool = True


@router.get("/config")
async def get_config():
    """读取当前的自动驾驶配置"""
    config = get_autopilot_config()
    return {"status": "success", "data": config}


@router.post("/config")
async def save_config(req: AutopilotConfigSchema):
    """保存自动驾驶配置，并动态重置 Scheduler 定时任务。

    严格遵循 PATCH 语义：仅更新请求体中显式包含的字段（基于 model_fields_set 判断），
    未包含的字段传 None 保持库中现值，杜绝局部配置更新覆盖打招呼语、投递等级等核心资产。
    """
    fields = req.model_fields_set
    logger.info(f"[save_config] 收到配置更新请求，显式修改字段: {list(fields)}")

    update_success = update_autopilot_config(
        cron_time=req.cron_time if "cron_time" in fields else None,
        auto_deliver_grades=req.auto_deliver_grades if "auto_deliver_grades" in fields else None,
        auto_deliver_platforms=req.auto_deliver_platforms if "auto_deliver_platforms" in fields else None,
        is_enabled=req.is_enabled if "is_enabled" in fields else None,
        platform_configs=req.platform_configs if "platform_configs" in fields else None,
        batch_limit=req.batch_limit if "batch_limit" in fields else None,
        mass_apply_resume_id=req.mass_apply_resume_id if "mass_apply_resume_id" in fields else None,
        rewrite_base_resume_id=req.rewrite_base_resume_id if "rewrite_base_resume_id" in fields else None,
        mass_apply_max_headcount=req.mass_apply_max_headcount if "mass_apply_max_headcount" in fields else None,
        mass_apply_greeting=req.mass_apply_greeting if "mass_apply_greeting" in fields else None,
        greeting_platforms=req.greeting_platforms if "greeting_platforms" in fields else None,
    )
    if not update_success:
        raise HTTPException(status_code=500, detail="保存配置失败")

    if "cron_time" in fields or "is_enabled" in fields:
        current_cfg = get_autopilot_config()
        scheduler.update_scheduler_cron(current_cfg.get("cron_time", "09:00"), current_cfg.get("is_enabled", True))
    return {"status": "success", "message": "配置已保存，定时器已热更新"}


@router.post("/schedule-config")
async def save_schedule_config(body: ScheduleConfigBody):
    """保存每日定时调度（执行时间 + 总开关 + 日期范围 + 非工作日跳过）。"""
    if not re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", body.cron_time.strip()):
        raise HTTPException(status_code=400, detail="时间格式应为 HH:MM（24 小时制）")
    cron_time = body.cron_time.strip()
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    start_date = (body.schedule_start_date or "").strip()
    end_date = (body.schedule_end_date or "").strip()
    if (start_date and not date_pattern.match(start_date)) or (end_date and not date_pattern.match(end_date)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    if not update_autopilot_config(
        cron_time=cron_time,
        is_enabled=body.is_enabled,
        schedule_start_date=start_date,
        schedule_end_date=end_date,
        skip_non_workdays=body.skip_non_workdays,
    ):
        raise HTTPException(status_code=500, detail="保存失败：数据库写入异常，请重试")
    scheduler.update_scheduler_cron(cron_time, body.is_enabled)
    range_txt = ""
    if start_date or end_date:
        range_txt = f"（{start_date or '不限'} ~ {end_date or '不限'}）"
    skip_txt = "，自动跳过周末与法定节假日" if body.skip_non_workdays else ""
    msg = f"已生效：每天 {cron_time} 执行采集评估链路{range_txt}{skip_txt}" if body.is_enabled else "已关闭每日定时调度"
    return {"status": "success", "message": msg, "data": {"cron_time": cron_time, "is_enabled": body.is_enabled, "skip_non_workdays": body.skip_non_workdays}}


@router.get("/holiday-data-status")
async def get_holiday_data_status():
    """节假日数据覆盖状态。"""
    from app.services.holiday_calendar import get_holiday_data_status as _status
    return {"status": "success", "data": _status()}


@router.post("/holiday-data-update")
async def update_holiday_data():
    """一键升级节假日数据。"""
    from app.services.holiday_calendar import update_holiday_data as _update
    result = await asyncio.to_thread(_update)
    return {"status": "success" if result.get("updated") else "noop", "data": result}


@router.post("/generate-mass-greeting")
async def generate_mass_greeting():
    """用「海投简历 + A级岗位画像」生成通用海投打招呼语。"""
    from ai_agents.skill_greeting import run_skill_based_greeting
    from app.services.feishu_service import (
        get_active_resume_from_feishu,
        get_resume_text_by_id,
    )

    config = get_autopilot_config()
    mass_id = (config.get("mass_apply_resume_id") or "").strip()
    resume_text = ""
    if mass_id:
        resume_text = await asyncio.to_thread(get_resume_text_by_id, mass_id)
    if not resume_text:
        resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
    if not resume_text:
        raise HTTPException(status_code=400, detail="读不到简历内容，请先确认简历库")

    try:
        from app.strategy.service import get_global_jd_report
        jd_report = await get_global_jd_report() or ""
    except Exception:
        jd_report = ""
    if not jd_report:
        raise HTTPException(status_code=400, detail="还没有 A级岗位画像，请先生成")

    text, _ = await asyncio.to_thread(
        run_skill_based_greeting, jd_report, {}, resume_text, "A级岗位画像（海投通用）")
    text = (text or "").strip()
    if not text or text.startswith("❌"):
        raise HTTPException(status_code=502, detail=text[:200] or "模型返回空内容，请重试或更换模型")
    return {"status": "success", "greeting": text}


@router.get("/logs")
async def get_logs():
    """获取最近 50 条自动化运行日志"""
    logs = get_recent_autopilot_logs()
    return {"status": "success", "data": logs}
