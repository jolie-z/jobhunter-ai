import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Annotated

import aiofiles
import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.core.resume_parser import (
    assemble_final_markdown,
    extract_and_truncate_personal_info,
)

logger = logging.getLogger("strategy_upload_router")
logger.setLevel(logging.INFO)

TASK_NOT_FOUND_MSG = "任务不存在"

ALLOWED_FILE_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 4 * 1024 * 1024  # 4MB

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB

router = APIRouter()


def _sanitize_filename(name: str) -> str:
    """白名单清洗上传文件名：剥离路径成分、替换非法字符、限制长度，防止落盘异常与路径注入"""
    name = os.path.basename((name or "").strip())
    name = re.sub(r"[^\w.\-]+", "_", name).strip("._")
    return (name or "resume")[:80]


def _build_ready_response(task: dict, resp: dict) -> dict:
    personal_info = json.loads(task.get("personal_info") or "{}")
    cleaned_md = task.get("cleaned_markdown") or ""
    structured_json = json.loads(task.get("structured_json") or "{}")
    resp.update({
        "personal_info": personal_info,
        "cleaned_markdown": cleaned_md,
        "structured_json": structured_json,
        "full_markdown": assemble_final_markdown(personal_info, cleaned_md),
    })
    return resp


@router.post(
    "/upload_resume_vision",
    responses={
        400: {"description": "Error 400"},
        413: {"description": "Error 413"},
    },
)
async def upload_resume_vision(file: Annotated[UploadFile, File(...)]):
    """简历上传：校验 + markitdown转Markdown + 入本地DB + 异步解析（秒回 task_id）。

    前端拿到 task_id 后轮询 /upload_status/{task_id} 获取解析结果。
    解析结果不直接落飞书，需用户在 UI 确认后走 /save。
    """
    if file.content_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}。仅支持 PDF / DOC / DOCX",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（{len(file_bytes) / (1024 * 1024):.1f}MB），最大支持 {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )
    if not file_bytes:
        raise HTTPException(status_code=400, detail="空文件")

    raw_filename = file.filename or "resume.pdf"
    filename = _sanitize_filename(raw_filename)
    logger.info(
        f"[upload_resume_vision] 收到简历文件: {raw_filename!r} -> 清洗为 {filename!r}, "
        f"大小: {len(file_bytes) / (1024 * 1024):.2f}MB, 类型: {file.content_type}"
    )

    from app.services.resume_upload_service import create_task, run_parse_pipeline

    task_id = await create_task(filename)

    upload_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{task_id}_{filename}"

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_bytes)

    logger.info(f"[upload_resume_vision] 已落盘至 {file_path}，解除阻塞秒回 task_id={task_id}")
    asyncio.create_task(run_parse_pipeline(task_id, str(file_path), filename))

    return {"status": "processing", "task_id": task_id, "filename": filename}


@router.get("/upload_stream/{task_id}", responses={404: {"description": "Error 404"}})
async def get_upload_stream(task_id: str):
    """SSE 接口：主动推送简历解析结果。"""
    from app.services.resume_upload_service import get_task

    async def event_generator():
        poll_count = 0
        max_polls = 900
        while True:
            task = await get_task(task_id)
            if not task:
                yield {"event": "error", "data": json.dumps({"detail": TASK_NOT_FOUND_MSG})}
                break

            status = task.get("status")
            if status == "processing":
                poll_count += 1
                if poll_count > max_polls:
                    yield {"event": "error", "data": json.dumps({"detail": "解析等待超时，请重新上传"})}
                    break
                yield {"event": "ping", "data": "processing"}
                await asyncio.sleep(1)
                continue

            resp = {"status": status, "filename": task.get("filename")}

            if status == "ready":
                resp = _build_ready_response(task, resp)
                yield {"event": "message", "data": json.dumps(resp, ensure_ascii=False)}
                break

            elif status == "failed":
                resp["error"] = task.get("error_msg") or "解析失败"
                yield {"event": "message", "data": json.dumps(resp, ensure_ascii=False)}
                break

    return EventSourceResponse(event_generator())


@router.get("/upload_status/{task_id}", responses={404: {"description": "Error 404"}})
async def get_upload_status(task_id: str):
    """轮询简历上传解析状态（保留作为降级备用）。"""
    from app.services.resume_upload_service import get_task

    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND_MSG)

    status = task["status"]
    resp = {"status": status, "filename": task.get("filename")}

    if status == "ready":
        personal_info = json.loads(task.get("personal_info") or "{}")
        cleaned_md = task.get("cleaned_markdown") or ""
        structured_json = json.loads(task.get("structured_json") or "{}")
        resp.update({
            "personal_info": personal_info,
            "cleaned_markdown": cleaned_md,
            "structured_json": structured_json,
            "full_markdown": assemble_final_markdown(personal_info, cleaned_md),
        })
    elif status == "failed":
        resp["error"] = task.get("error_msg") or "解析失败"

    return resp


@router.post(
    "/retry_upload/{task_id}",
    responses={
        400: {"description": "Error 400"},
        404: {"description": "Error 404"},
    },
)
async def retry_upload(task_id: str):
    """重试失败的解析任务（复用 Redis 中已存的 original_markdown，不重读本地文件）。"""
    from app.services.resume_upload_service import get_task, update_task

    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=TASK_NOT_FOUND_MSG)
    if task["status"] != "failed":
        raise HTTPException(status_code=400, detail="仅 failed 状态的任务可重试")

    raw_markdown = task.get("original_markdown") or ""
    if not raw_markdown.strip():
        raise HTTPException(status_code=400, detail="原始文档文本缺失，无法重试，请重新上传文件")

    await update_task(task_id, status="processing", error_msg=None)

    async def retry_pipeline(tid: str, md: str):
        try:
            p_info, s_text = extract_and_truncate_personal_info(md)
            await update_task(tid, personal_info=json.dumps(p_info, ensure_ascii=False))

            from app.core.resume_structurer import (
                json_to_markdown,
                parse_resume_to_json,
            )

            structured = await parse_resume_to_json(s_text)
            cleaned_md = json_to_markdown(structured)

            await update_task(tid, cleaned_markdown=cleaned_md)
            await update_task(
                tid,
                structured_json=json.dumps(structured, ensure_ascii=False),
                status="ready",
                error_msg=None,
            )
        except Exception as e:
            await update_task(tid, status="failed", error_msg=str(e))

    asyncio.create_task(retry_pipeline(task_id, raw_markdown))
    return {"status": "processing", "task_id": task_id}


@router.post(
    "/upload_avatar",
    responses={
        400: {"description": "Error 400"},
        413: {"description": "Error 413"},
        500: {"description": "Error 500"},
    },
)
async def upload_avatar(record_id: Annotated[str, Form(...)], file: Annotated[UploadFile, File(...)]):
    """上传头像并保存至多维表格对应的简历记录中"""
    if not record_id.startswith("rec"):
        raise HTTPException(status_code=400, detail="该简历尚未同步到飞书（本地草稿），请先「保存并同步」再上传照片")

    if file.content_type and file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400, detail=f"不支持的图片类型: {file.content_type}，仅支持 JPG/PNG/WEBP/GIF/BMP"
        )
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="空文件")
    if len(file_bytes) > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=413, detail=f"图片过大（{len(file_bytes) / (1024 * 1024):.1f}MB），最大支持 5MB"
        )

    try:
        filename = file.filename
        file_token = await feishu_client.upload_bitable_attachment(file_bytes, filename)

        token = await feishu_client.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/{record_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        payload = {"fields": {"照片": [{"file_token": file_token}]}}

        async with httpx.AsyncClient() as client:
            resp = await client.put(url, headers=headers, json=payload, timeout=15)
            data = resp.json()
            if resp.status_code == 200 and data.get("code") == 0:
                return {"status": "success", "file_token": file_token}
            raise ValueError(f"更新多维表格失败: {data.get('msg')}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"照片上传失败: {str(e)}")


@router.get("/avatar/{file_token}", responses={500: {"description": "Error 500"}})
async def get_avatar(file_token: str):
    """通过 file_token 代理获取飞书图片流，解决前端跨域和鉴权问题"""
    try:
        token = await feishu_client.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="无法从飞书获取图片")

            content_type = resp.headers.get("Content-Type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取头像失败: {str(e)}")
