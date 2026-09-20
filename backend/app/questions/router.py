from fastapi import APIRouter, HTTPException

from app.questions import service
from app.questions.schemas import (
    AddResumeQACardRequest,
    ShredInterviewRequest,
    UpdateQuestionRequest,
)

router = APIRouter()
compat_router = APIRouter()

@router.get("")
async def list_questions():
    return await service.list_questions()

@router.put("/{record_id}")
async def update_question(record_id: str, payload: UpdateQuestionRequest):
    try:
        fields = {}
        if payload.mastery_status is not None:
            fields["掌握状态"] = payload.mastery_status
        if payload.golden_answer is not None:
            fields["我的黄金答案"] = payload.golden_answer
        if payload.ai_demo is not None:
            fields["AI示范"] = payload.ai_demo

        return await service.update_question(record_id, fields)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{record_id}")
async def delete_question(record_id: str):
    try:
        return await service.delete_question(record_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{record_id}/increment")
async def increment_drill_count(record_id: str):
    try:
        return await service.increment_drill_count(record_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@compat_router.post("/api/jobs/add_resume_qa_card")
async def add_resume_qa_card(payload: AddResumeQACardRequest):
    try:
        return await service.add_qa_card_service(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@compat_router.post("/api/jobs/shred_interview")
async def shred_interview(payload: ShredInterviewRequest):
    """面经粉碎机：面试流水账 → 提取真题 → 去重入库专属面经库"""
    try:
        return await service.shred_interview_service(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
