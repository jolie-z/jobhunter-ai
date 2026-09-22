import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.strategy import service
from app.strategy.schemas import (
    AtsAlignRequest,
    CompressWorkRequest,
    FilterProjectsRequest,
    GlobalDiagnosisRequest,
    GrillExperienceRequest,
    GrillSuggestionRequest,
    InitialDraftRequest,
    ResetResumeRequest,
    SyncBasicModuleRequest,
)

logger = logging.getLogger("strategy_ai_router")
logger.setLevel(logging.INFO)

router = APIRouter()


class FillResumeFromMarkdownRequest(BaseModel):
    markdown_content: str
    job_id: str | None = None


class GenerateGreetingRequest(BaseModel):
    job_id: str
    jd_text: str = ""
    job_name: str = ""
    resume_text: str = ""


@router.post("/grill_experience")
async def grill_experience(payload: GrillExperienceRequest):
    """接收用户的某段简历经历，并进行深度拷问 (Grill)。

    通过 LLM 进行多轮对话，最终生成 STAR 法则格式的重写建议。
    """
    logger.info(f"[grill_experience] 收到前端请求，当前轮次: {payload.current_turn}")
    try:
        result = await service.grill_experience_service(payload)
        return {"code": 200, "status": "success", "data": result}
    except Exception as e:
        logger.exception(f"[grill_experience] 报错: {e}")
        return {"code": 500, "status": "error", "message": str(e)}


@router.post("/grill_experience_stream")
async def grill_experience_stream(payload: GrillExperienceRequest):
    """Grill 深度拷问 SSE 流式版（旧 REST 端点保留兼容，前端逐步切换）。

    事件：stage(模型已响应) → progress(已生成字数) → final(完整解析结果) / error(友好文案)。
    """
    logger.info(f"[grill_experience_stream] 收到前端流式请求，当前轮次: {payload.current_turn}")

    async def event_generator():
        try:
            async for event in service.grill_experience_stream_service(payload):
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"], ensure_ascii=False),
                }
        except Exception as e:
            logger.exception(f"[grill_experience_stream] 流式管道异常: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"message": "服务异常，请稍后重试"}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@router.post("/sync_basic_module")
async def sync_basic_module(payload: SyncBasicModuleRequest):
    """基础模块的 AI 联动更新"""
    logger.info(f"[sync_basic_module] 收到请求，模块: {payload.module_title}")
    try:
        result = await service.sync_basic_module_service(payload)
        return {"code": 200, "status": "success", "data": result}
    except Exception as e:
        return {"code": 500, "status": "error", "message": str(e)}


@router.post("/generate_jd_report")
async def generate_jd_report():
    """读取 A 级岗位生成并缓存能力要求报告"""
    logger.info("[generate_jd_report] 开始生成全局 A 级 JD 能力报告")
    try:
        result = await service.generate_jd_report_service()
        return {"code": 200, "status": "success", "data": result}
    except Exception as e:
        logger.exception(f"[generate_jd_report] 报错: {e}")
        return {"code": 500, "status": "error", "message": str(e)}


@router.get("/get_jd_report")
async def get_jd_report():
    """获取已生成的全局能力要求报告"""
    try:
        report = await service.get_global_jd_report()
        return {"code": 200, "status": "success", "data": report}
    except Exception as e:
        logger.exception(f"[get_jd_report] 报错: {e}")
        return {"code": 500, "status": "error", "message": str(e)}


@router.post("/ats_align")
async def ats_align_experience(payload: AtsAlignRequest):
    """ATS 靶向预诊断与微改写

    基于 A 级岗位画像，对单条经历进行术语平替和 ATS 关键词锚定
    """
    try:
        data = await service.ats_align_experience_service(payload)
        return {"code": 200, "status": "success", "data": data}
    except Exception as e:
        logger.exception(f"[ats_align_experience] 发生异常: {e}")
        return {"code": 500, "status": "error", "message": str(e)}


@router.post("/filter_projects", responses={500: {"description": "Error 500"}})
async def filter_projects_api(payload: FilterProjectsRequest):
    """AI 项目经历智能删减"""
    try:
        data = await service.filter_projects_service(payload)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.exception(f"filter_projects error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compress_work_experience", responses={500: {"description": "Error 500"}})
async def compress_work_experience_api(payload: CompressWorkRequest):
    """AI 工作经历战略折叠"""
    try:
        data = await service.compress_work_experience_service(payload)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.exception(f"compress_work_experience error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/initial_draft", responses={500: {"description": "Error 500"}})
async def generate_initial_draft(payload: InitialDraftRequest):
    """生成初始简历草稿"""
    try:
        data = await service.generate_initial_draft_service(payload)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.exception(f"initial_draft error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/global_diagnosis", responses={500: {"description": "Error 500"}})
async def global_diagnosis_api(payload: GlobalDiagnosisRequest):
    """AI 全局诊断：输出建议卡片"""
    try:
        data = await service.global_diagnosis_service(payload)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.exception(f"global_diagnosis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/grill_suggestion", responses={500: {"description": "Error 500"}})
async def grill_suggestion(payload: GrillSuggestionRequest):
    """Step 3 入口：分析全量简历 + JD，输出「哪些经历值得深度拷问」的建议列表。"""
    logger.info("[grill_suggestion] 收到前端深度拷问建议请求")
    try:
        data = await service.grill_suggestion_service(payload)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.exception(f"[grill_suggestion] 报错: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset_resume", responses={500: {"description": "Error 500"}})
async def reset_resume(payload: ResetResumeRequest):
    """撤销/重置：清空当前岗位的「AI改写JSON」字段（精修简历），并返回简历库中【启用】状态的原始简历。

    注意：仅清空此字段，不触碰其它字段。
    """
    logger.info(f"[reset_resume] 收到重置请求 job_id={payload.job_id}")
    try:
        from app.core.config import settings
        from app.core.feishu_client import feishu_client
        from app.services.feishu_service import (
            extract_record_id,
            get_active_resume_from_feishu,
        )

        pure_record_id = extract_record_id(payload.job_id)

        # 1. 清空飞书岗位表的「AI改写JSON」字段
        success = await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=pure_record_id,
            fields={"AI改写JSON": ""},
        )
        if not success:
            raise HTTPException(status_code=500, detail="清空飞书字段失败")

        from app.services.redis_service import redis_service
        await redis_service.delete(f"cache:resume_ast:job:{pure_record_id}")

        # 2. 从简历库拉取当前「启用」的原始简历
        original_resume = await asyncio.to_thread(get_active_resume_from_feishu)

        return {
            "status": "success",
            "message": "已重置为原始简历",
            "original_resume": original_resume,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[reset_resume] 报错: {e}")
        raise HTTPException(status_code=500, detail=f"重置失败: {str(e)}")


@router.post("/fill_resume_from_markdown")
async def fill_resume_from_markdown_api(payload: FillResumeFromMarkdownRequest):
    """一键将任意 Markdown 结构化转换为标准 ResumeDataV2 JSON，并缝合个人隐私数据"""
    try:
        from ai_agents.markdown_to_json import parse_markdown_to_json
        from app.core.config import settings
        from app.core.feishu_client import feishu_client

        if not payload.markdown_content or not payload.markdown_content.strip():
            raise HTTPException(status_code=400, detail="Markdown 内容不能为空")

        logger.info(
            f"🧩 [白盒化追踪] 开始将 Markdown 内容转换为结构化 ResumeDataV2 JSON (长度: {len(payload.markdown_content)})"
        )
        parsed_json = await asyncio.to_thread(parse_markdown_to_json, payload.markdown_content)

        # 缝合个人隐私数据
        original_personal_info = {}
        try:
            import httpx

            token = await feishu_client.get_tenant_access_token()
            if token:
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                payload_search = {
                    "filter": {
                        "conjunction": "and",
                        "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}],
                    }
                }
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, headers=headers, json=payload_search, timeout=10)
                    if resp.status_code == 200:
                        items = resp.json().get("data", {}).get("items", [])
                        if items:

                            def _safe_extract_text(field_val):
                                if not field_val:
                                    return ""
                                if isinstance(field_val, list):
                                    return "".join([
                                        str(item.get("text", "")) if isinstance(item, dict) else str(item)
                                        for item in field_val
                                    ])
                                return str(field_val)

                            raw_text = _safe_extract_text(items[0].get("fields", {}).get("结构化数据", ""))
                            if raw_text:
                                data_dict = json.loads(raw_text)
                                original_personal_info = data_dict.get("personalInfo", {})
        except Exception as e:
            logger.warning(f"无法拉取飞书个人信息进行缝合: {e}")

        if not original_personal_info:
            original_personal_info = {
                "name": "未填写",
                "phone": "未填写",
                "email": "未填写",
                "location": "未填写",
            }

        if "personalInfo" not in parsed_json or not parsed_json["personalInfo"]:
            parsed_json["personalInfo"] = original_personal_info
        else:
            parsed_json["personalInfo"].update(original_personal_info)

        logger.info(f"✅ [白盒化追踪] Markdown 回填解析完成，模块数: {len(parsed_json.get('moduleOrder', []))}")
        return {"status": "success", "data": {"parsed_json": parsed_json}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"fill_resume_from_markdown error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _safe_extract_text(field_val) -> str:
    if not field_val:
        return ""
    if isinstance(field_val, list):
        return "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in field_val])
    return str(field_val)


def _get_first_text(fields: dict, keys: list[str], default: str = "") -> str:
    for k in keys:
        val = _safe_extract_text(fields.get(k, ""))
        if val:
            return val
    return default


KNOWN_RESUME_PLACEHOLDERS = {"请使用您的默认简历内容。", "默认简历", "placeholder", "test_resume"}


@router.post("/generate_greeting_and_save")
async def generate_greeting_and_save_api(payload: GenerateGreetingRequest):
    """单独生成打招呼语并保存到飞书"""
    try:
        from ai_agents.engine_facade import process_greeting_generation
        from app.core.config import settings
        from app.core.feishu_client import feishu_client
        from app.services.feishu_service import extract_record_id
        from app.strategy.config_service import get_active_resume_text_async

        clean_id = extract_record_id(payload.job_id)
        record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, clean_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"未找到对应岗位记录 (ID: {clean_id})")

        fields = record.get("fields", {})
        job_name = (payload.job_name or "").strip() or _get_first_text(fields, ["岗位名称", "title"], "目标岗位")
        jd_text = (payload.jd_text or "").strip() or _get_first_text(fields, ["岗位JD", "jd"], "")

        resume_text = (payload.resume_text or "").strip()
        is_placeholder = not resume_text or resume_text in KNOWN_RESUME_PLACEHOLDERS

        if is_placeholder:
            logger.info("🔍 [generate_greeting_and_save] 未提供有效 resume_text (或为占位符)，尝试从飞书拉取当前启用母本简历...")
            try:
                fetched_resume = await get_active_resume_text_async()
            except Exception as e:
                logger.exception(f"拉取飞书母本简历失败: {e}")
                raise HTTPException(
                    status_code=502,
                    detail=f"拉取飞书母本简历失败，飞书服务暂时不可达: {e}",
                )

            if not fetched_resume or not fetched_resume.strip():
                raise HTTPException(
                    status_code=400,
                    detail="未找到已激活的母本简历。请前往「配置大盘 - 简历库」设置并激活一份母本简历后再试。",
                )
            resume_text = fetched_resume

        high_leverage = _safe_extract_text(fields.get("高杠杆匹配点", ""))
        ai_detail = _safe_extract_text(fields.get("AI评估详情", ""))

        diagnosis_dict = {
            "综合评级": _safe_extract_text(fields.get("综合评级 (A-F)", "")),
            "AI评估详情": ai_detail,
            "高杠杆匹配点": high_leverage,
            "核心能力词典": _safe_extract_text(fields.get("核心能力词典", "")),
            "strong_fit_assessment": high_leverage,
            "dream_picture": ai_detail,
        }

        logger.info(f"🚀 [generate_greeting_and_save] 开始为 {job_name} 生成打招呼语 (简历字数: {len(resume_text)}, JD字数: {len(jd_text)})...")
        greeting, usage = await asyncio.to_thread(
            process_greeting_generation,
            jd_text=jd_text,
            diagnosis_dict=diagnosis_dict,
            resume_text=resume_text,
            job_name=job_name,
        )

        success = await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=clean_id,
            fields={"打招呼语": greeting},
        )
        if not success:
            logger.error(f"generate_greeting_and_save: 保存到飞书失败 (clean_id={clean_id})")
            raise HTTPException(status_code=502, detail=f"打招呼语生成成功，但回写飞书保存失败 (clean_id={clean_id})")

        return {"status": "success", "data": {"greeting": greeting, "usage": usage}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"generate_greeting_and_save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
