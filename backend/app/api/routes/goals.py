# app/api/routes/goals.py
"""
求职目标 API 路由 - 目标设定/查询/更新/结束。
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.goal_service import (
    finish_goals,
    get_current_goals,
    start_goals,
    update_goals,
)

router = APIRouter()


class StartGoalsRequest(BaseModel):
    start_date: str | None = None
    daily_deliver_target: int = Field(default=10, ge=1, le=100)
    daily_crawl_target: int = Field(default=50, ge=1, le=500)
    weekly_interview_target: int = Field(default=3, ge=0, le=30)
    a_grade_deadline_hours: int = Field(default=24, ge=1, le=168)
    total_offer_target: int = Field(default=1, ge=1, le=20)
    plan_days: int = Field(default=60, ge=7, le=365)
    report_time_daily: str = "21:00"
    report_time_weekly: str = "09:00"
    report_time_monthly: str = "09:00"
    report_enabled_daily: bool = True
    report_enabled_weekly: bool = True
    report_enabled_monthly: bool = True
    feishu_receive_id: str = ""


class UpdateGoalsRequest(BaseModel):
    daily_deliver_target: int | None = Field(default=None, ge=1, le=100)
    daily_crawl_target: int | None = Field(default=None, ge=1, le=500)
    weekly_interview_target: int | None = Field(default=None, ge=0, le=30)
    a_grade_deadline_hours: int | None = Field(default=None, ge=1, le=168)
    total_offer_target: int | None = Field(default=None, ge=1, le=20)
    plan_days: int | None = Field(default=None, ge=7, le=365)
    report_time_daily: str | None = None
    report_time_weekly: str | None = None
    report_time_monthly: str | None = None
    report_enabled_daily: bool | None = None
    report_enabled_weekly: bool | None = None
    report_enabled_monthly: bool | None = None
    feishu_receive_id: str | None = None


@router.post("/start")
async def api_start_goals(req: StartGoalsRequest):
    """开始求职 - 设定目标。"""
    try:
        result = start_goals(req.model_dump(exclude_none=True))
        return {"code": 0, "data": result}
    except Exception as e:
        return {"code": 1, "msg": f"设定失败: {str(e)}", "data": None}


@router.get("/current")
async def api_get_goals():
    """获取当前目标 + 实时进度。"""
    try:
        result = get_current_goals()
        if result is None:
            return {"code": 0, "data": None, "msg": "尚未设定求职目标"}
        return {"code": 0, "data": result}
    except Exception as e:
        return {"code": 1, "msg": f"查询失败: {str(e)}", "data": None}


@router.put("/update")
async def api_update_goals(req: UpdateGoalsRequest):
    """更新目标参数。"""
    try:
        params = req.model_dump(exclude_none=True)
        if not params:
            return {"code": 1, "msg": "无更新内容", "data": None}
        result = update_goals(params)
        if result is None:
            return {"code": 1, "msg": "尚未设定求职目标，请先调用 /start", "data": None}
        return {"code": 0, "data": result}
    except Exception as e:
        return {"code": 1, "msg": f"更新失败: {str(e)}", "data": None}


@router.post("/finish")
async def api_finish_goals():
    """找到工作了 - 结束求职，触发终报。"""
    try:
        result = finish_goals()
        if result is None:
            return {"code": 1, "msg": "尚未设定求职目标", "data": None}

        # 异步触发终报发送（不阻塞响应）
        try:
            import asyncio

            from app.services.report_feishu import send_final_report
            asyncio.create_task(send_final_report())
        except Exception:
            pass  # 飞书未配置时静默跳过

        return {"code": 0, "data": result, "msg": "恭喜！终报已触发发送。"}
    except Exception as e:
        return {"code": 1, "msg": f"操作失败: {str(e)}", "data": None}
