"""原文快照与修正回流路由：对照原文抽屉的数据源 + 错题本查看。"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services import resume_snapshot_service as snapshot_service

logger = logging.getLogger("snapshot_router")

router = APIRouter()


@router.get("/resume_snapshot/{snapshot_id}")
async def get_resume_snapshot(snapshot_id: str):
    """读取快照元数据与原文中间文本（对照原文抽屉数据源）。"""
    try:
        snap = snapshot_service.get_snapshot(snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not snap:
        raise HTTPException(status_code=404, detail="快照不存在（该简历可能早于快照功能上传）")
    return {"status": "success", "data": snap}


@router.get("/resume_snapshot/{snapshot_id}/file")
async def download_resume_snapshot_file(snapshot_id: str):
    """下载原始上传文件（阅后即焚前的留存件）。"""
    try:
        file_info = snapshot_service.get_snapshot_file(snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not file_info:
        raise HTTPException(status_code=404, detail="原件不存在")
    path, filename = file_info
    return FileResponse(path, filename=filename)


@router.get("/resume_corrections")
async def list_resume_corrections(limit: int = 100):
    """修正回流错题本（初始解析 vs 用户修正）。"""
    return {"status": "success", "data": snapshot_service.list_corrections(limit=limit)}
