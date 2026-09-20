from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.feishu_client import schedule_job_cache_patch

# 🌟 修复：多引入一个 extract_record_id 清洗工具
from app.services.feishu_service import (
    extract_record_id,
    get_full_active_resume_from_feishu,
    update_feishu_record,
)

router = APIRouter()

@router.put("/update_job_status")
async def update_job_status(request: Request):
    """供前端看板拖拽调用的状态同步接口"""
    try:
        data = await request.json()
        raw_record_id = data.get("record_id")
        status = data.get("status")

        if not raw_record_id or not status:
            return JSONResponse(status_code=400, content={"status": "error", "message": "缺少 record_id 或 status 参数"})

        # 🌟 核心修复：把脏 ID (如 boss-123-recXXX) 清洗为纯净的 recXXX
        real_record_id = extract_record_id(raw_record_id)
        success = update_feishu_record(real_record_id, {"跟进状态": status})

        if success:
            schedule_job_cache_patch(real_record_id)
            return {"status": "success", "message": "状态已同步至飞书"}
        else:
            return JSONResponse(status_code=500, content={"status": "error", "message": "飞书记录更新失败"})

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.put("/update_interview_schedule")
async def update_interview_schedule(request: Request):
    """供前端更新面试时间的接口"""
    try:
        data = await request.json()
        raw_record_id = data.get("record_id")
        interview_time = data.get("interview_time")

        if raw_record_id and interview_time:
            real_record_id = extract_record_id(raw_record_id)
            success = update_feishu_record(real_record_id, {"面试时间": str(interview_time)})
            if success:
                schedule_job_cache_patch(real_record_id)
                return {"status": "success", "message": "面试时间已同步"}
        return JSONResponse(status_code=400, content={"status": "error", "message": "参数不完整或更新失败"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# 🌟 提前预判修复：补齐前端“保存我的复核”所需的接口
@router.put("/update_review_comments")
async def update_review_comments(request: Request):
    try:
        data = await request.json()
        raw_record_id = data.get("job_id")
        comments = data.get("comments")

        if raw_record_id and comments is not None:
            real_record_id = extract_record_id(raw_record_id)
            success = update_feishu_record(real_record_id, {"我的复核": str(comments)})
            if success:
                return {"status": "success", "message": "复核意见已同步"}
        return JSONResponse(status_code=400, content={"status": "error", "message": "更新复核失败"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# 🌟 提前预判修复：补齐前端“保存打招呼语”所需的接口
@router.put("/update_greeting")
async def update_greeting(request: Request):
    try:
        data = await request.json()
        raw_record_id = data.get("job_id")
        greeting = data.get("greeting")

        if raw_record_id and greeting is not None:
            real_record_id = extract_record_id(raw_record_id)
            success = update_feishu_record(real_record_id, {"打招呼语": str(greeting)})
            if success:
                return {"status": "success", "message": "打招呼语已同步"}
        return JSONResponse(status_code=400, content={"status": "error", "message": "更新打招呼语失败"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.get("/get_active_resume")
async def get_active_resume():
    """供前端拉取最新简历"""
    try:
        resume_content = get_full_active_resume_from_feishu()
        if resume_content:
            return {"status": "success", "data": resume_content}
        return JSONResponse(status_code=404, content={"status": "error", "message": "未找到有效的启用简历"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
