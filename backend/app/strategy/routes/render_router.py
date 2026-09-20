import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.core.pdf_renderer import render_resume_image, render_resume_pdf
from app.services.feishu_service import extract_record_id
from app.services.redis_service import redis_service
from app.strategy import service
from app.strategy.schemas import (
    FormatMarkdownRequest,
    PreviewPdfDirectRequest,
    ResumePdfRequest,
)
from app.strategy.service import _safe_extract_avatar_url

logger = logging.getLogger("strategy_render_router")
logger.setLevel(logging.INFO)

DEFAULT_FRONTEND_BASE = "http://localhost:3000"

router = APIRouter()


def _resolve_resume_request_source(request: ResumePdfRequest):
    if not request.source and ("/" in request.record_id or "-rec" in request.record_id):
        request.source = "job"


def _build_resume_url(request: ResumePdfRequest) -> str:
    frontend_base = getattr(settings, "FRONTEND_BASE_URL", DEFAULT_FRONTEND_BASE)
    url = f"{frontend_base}/print/resume?record_id={request.record_id}"
    if request.source:
        url += f"&source={request.source}"
    if request.template and request.template != "classic":
        template = request.template if request.template in ("classic", "color", "color_v2") else "classic"
        url += f"&template={template}"
    return url


def _build_file_prefix(request: ResumePdfRequest) -> str:
    if request.company or request.job_title:
        prefix = f"{request.company or ''}_{request.job_title or ''}".strip("_")
        prefix = prefix[:20] if len(prefix) > 20 else prefix
        if prefix:
            return prefix
    return f"resume_{request.record_id}"


async def _update_record_attachments(
    client, request: ResumePdfRequest, attachments: list, attachment_type: str
) -> bool:
    clean_id = extract_record_id(request.record_id)
    if request.source == "job":
        fields_map = {"pdf": "PDF备份", "image": "图片保存"}
        return await client.update_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=clean_id,
            fields={fields_map.get(attachment_type, "PDF备份"): attachments},
        )

    fields_map = {"pdf": "pdf_file", "image": "简历图片"}
    return await client.update_record(
        table_id=settings.FEISHU_TABLE_ID_RESUMES,
        record_id=clean_id,
        fields={fields_map.get(attachment_type, "pdf_file"): attachments},
    )


@router.get(
    "/resume-data/{record_id}",
    responses={
        404: {"description": "Error 404"},
        500: {"description": "Error 500"},
    },
)
async def get_resume_data(record_id: str, source: str | None = None):
    """供 Print 页面调用的接口，获取特定记录的简历 JSON AST (支持 Redis/内存缓存加速)"""
    try:
        clean_id = extract_record_id(record_id)
        cache_key = f"cache:resume_ast:{source or 'resume'}:{clean_id}"

        # 1. 优先读取 Redis / 内存缓存 (毫秒级响应)
        cached = await redis_service.get(cache_key)
        if cached and isinstance(cached, dict):
            logger.info(f"[get_resume_data] ⚡ 命中简历 AST 缓存: key={cache_key}, clean_id={clean_id}")
            return {"status": "success", "data": cached, "cached": True}

        # 2. 未命中缓存，穿透到飞书多维表格
        table_id = settings.FEISHU_TABLE_ID_JOBS if source == "job" else settings.FEISHU_TABLE_ID_RESUMES
        logger.info(f"[get_resume_data] 🌐 未命中缓存，从飞书多维表格读取: table_id={table_id}, clean_id={clean_id}")
        record = await feishu_client.get_record(table_id, clean_id)
        if not record:
            raise HTTPException(status_code=404, detail="Resume record not found")

        fields = record.get("fields", {})

        def _safe_extract_text(field_val):
            if not field_val:
                return "{}"
            if isinstance(field_val, list):
                return "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in field_val])
            return str(field_val)

        if source == "job":
            ast_json = _safe_extract_text(fields.get("AI改写JSON", "{}"))
        else:
            ast_json = _safe_extract_text(fields.get("结构化数据", "{}"))

        if not ast_json.strip():
            ast_json = "{}"

        try:
            resume_data = json.loads(ast_json)
        except json.JSONDecodeError:
            resume_data = {}

        avatar_url = _safe_extract_avatar_url(fields.get("照片"))
        if avatar_url:
            resume_data["avatar_url"] = avatar_url

        # 3. 异步回写缓存 (TTL 30分钟)
        if resume_data:
            await redis_service.set(cache_key, resume_data, expire_seconds=1800)
            logger.info(f"[get_resume_data] 💾 已缓存简历 AST (TTL=1800s): key={cache_key}")

        return {"status": "success", "data": resume_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching resume data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume-pdf", responses={500: {"description": "Error 500"}})
async def generate_resume_pdf(request: ResumePdfRequest):
    """渲染简历为 PDF 并上传到飞书"""
    try:
        _resolve_resume_request_source(request)
        if not extract_record_id(request.record_id).startswith("rec"):
            raise HTTPException(status_code=400, detail="该简历尚未同步到飞书（本地草稿），请先「保存并同步」")
        url = _build_resume_url(request)
        pdf_bytes = await render_resume_pdf(url, page_size=request.page_size)

        prefix = _build_file_prefix(request)
        file_name = f"{prefix}.pdf"

        token = await feishu_client.upload_bitable_attachment(pdf_bytes, file_name)
        if not token:
            raise HTTPException(status_code=500, detail="Failed to upload PDF to Feishu")

        success = await _update_record_attachments(feishu_client, request, [{"file_token": token}], "pdf")
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update record with PDF attachment")

        return {"status": "success", "message": "PDF 已生成并保存至飞书"}
    except Exception as e:
        logger.exception(f"Error generating PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume-images", responses={500: {"description": "Error 500"}})
async def generate_resume_images(request: ResumePdfRequest):
    """渲染简历为一张高清长图，并上传到飞书"""
    try:
        _resolve_resume_request_source(request)
        if not extract_record_id(request.record_id).startswith("rec"):
            raise HTTPException(status_code=400, detail="该简历尚未同步到飞书（本地草稿），请先「保存并同步」")
        url = _build_resume_url(request)
        image_bytes = await render_resume_image(url)

        prefix = _build_file_prefix(request)
        file_name = f"{prefix}_长图.jpg"

        token = await feishu_client.upload_bitable_attachment(image_bytes, file_name)
        if not token:
            raise HTTPException(status_code=500, detail="Failed to upload Image to Feishu")

        success = await _update_record_attachments(feishu_client, request, [{"file_token": token}], "image")
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update record with Image attachments")

        return {"status": "success", "message": "成功截取 1 张高清长图并保存至飞书"}
    except Exception as e:
        logger.exception(f"Error generating resume images: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/format_markdown")
async def format_markdown(payload: FormatMarkdownRequest):
    """基础模块的 AI 自动排版（Markdown）"""
    logger.info(f"[format_markdown] 收到请求，模块: {payload.module_title}")
    try:
        result = await service.format_markdown_service(payload)
        return {"code": 200, "status": "success", "data": result}
    except Exception as e:
        return {"code": 500, "status": "error", "message": str(e)}


@router.post("/preview-pdf-direct", responses={500: {"description": "Error 500"}})
async def preview_pdf_direct(request: PreviewPdfDirectRequest):
    """Directly render a PDF from dirty JSON data using Playwright, without saving to Feishu."""
    try:
        preview_id = str(uuid.uuid4())
        await redis_service.set_task(f"preview_{preview_id}", request.resume_data, expire_seconds=300)

        frontend_base = getattr(settings, "FRONTEND_BASE_URL", DEFAULT_FRONTEND_BASE)
        url = f"{frontend_base}/print/resume?preview_id={preview_id}"
        if request.template and request.template != "classic":
            template = request.template if request.template in ("classic", "color", "color_v2") else "classic"
            url += f"&template={template}"

        pdf_bytes = await render_resume_pdf(url, page_size=request.page_size)
        return Response(content=pdf_bytes, media_type="application/pdf")
    except Exception as e:
        logger.exception(f"Error generating direct PDF preview: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/preview-data/{preview_id}",
    responses={
        404: {"description": "Error 404"},
        500: {"description": "Error 500"},
    },
)
async def get_preview_data(preview_id: str):
    """Called by the Next.js PrintResumePage server component to fetch the dirty JSON for rendering."""
    try:
        data = await redis_service.get_task(f"preview_{preview_id}")
        if not data:
            raise HTTPException(status_code=404, detail="Preview data expired or not found")

        return {"status": "success", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching preview data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
