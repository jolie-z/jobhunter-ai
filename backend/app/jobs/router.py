from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.cache import JobCache
from app.jobs import action_service, service
from app.jobs.schemas import (
    AIPolishRequest,
    BatchDeleteRequest,
    CheckAiArtifactsRequest,
    JobImportConfirmRequest,
    JobImportImageRequest,
    JobImportParseRequest,
    JobImportTextRequest,
    SaveManualResumeRequest,
    UpdateGreetingRequest,
    UpdateJobStatusRequest,
    UpdateReviewCommentsRequest,
)


def _import_error_response(e: Exception) -> HTTPException:
    """极速录入异常 → HTTP 状态码：视觉未配置 400（弹配置引导）、硬缺失 422（弹回补料）、查重命中 409（可 force 放行）。"""
    if isinstance(e, service.VisionNotConfiguredError):
        from common.config import missing_guide_text
        return HTTPException(status_code=400, detail={
            "code": "vision_not_configured",
            "message": missing_guide_text(e.missing, "截图识别"),
            "missing": e.missing,
        })
    if isinstance(e, service.InvalidJobFieldsError):
        return HTTPException(status_code=422, detail={
            "message": f"存在必须提供的字段缺失（{('、'.join(e.missing))}），请补充后重试",
            "missing": e.missing,
        })
    if isinstance(e, service.DuplicateJobError):
        return HTTPException(status_code=409, detail={
            "message": "疑似与已有岗位重复，确认非重复后可强制录入",
            "existing": e.existing,
        })
    return HTTPException(status_code=500, detail=str(e))

# 统一初始化 Router，设置正确的 Tag
router = APIRouter(tags=["Jobs Workspace"])

@router.get("/api/jobs")
@router.get("/jobs")
async def get_all_jobs(force: bool = False):
    """获取所有岗位列表，供沉浸工作台渲染使用。?force=1 时绕过缓存直连飞书（手动硬刷新）"""
    try:
        jobs = await service.fetch_and_clean_all_jobs(force=force)
        return {"items": jobs, "status": "success"}
    except HTTPException:
        # 底层（如飞书分页护栏的 502）已携带明确状态码，原样透传，不被兜底重包装成 500
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取岗位列表失败: {str(e)}")

@router.post("/api/jobs/refresh-cache")
async def refresh_jobs_cache():
    """清空岗位列表内存缓存。
    飞书数据被外部直接改动（如已下架归档脚本）后调用，
    使下一次 /api/jobs 立即拉取最新数据，而不必等 1 小时缓存过期。"""
    JobCache.clear()
    return {"status": "success", "message": "岗位缓存已清空"}

@router.get("/api/jobs/{job_id}/detail")
@router.get("/api/jobs/{job_id}")
async def get_job_detail(job_id: str):
    """按需拉取单个岗位完整字段（含岗位详情/AI改写JSON等大文本）。
    列表接口已瘦身，详情字段在此获取；兼容纯 record_id 与"平台-recXXX"复合 ID。"""
    import logging
    _log = logging.getLogger(__name__)
    _log.info(f"🔍 [get_job_detail] 请求岗位详情: job_id={job_id}")
    try:
        job = await service.fetch_job_detail_service(job_id)
        has_greeting = bool(job and job.get("greeting_msg"))
        _log.info(f"✅ [get_job_detail] 成功拉取岗位: job_id={job_id}, job_name={job.get('job_name') if job else ''}, has_greeting={has_greeting}")
        return {"status": "success", "code": 0, "data": job}
    except ValueError as e:
        _log.warning(f"⚠️ [get_job_detail] 岗位未找到: job_id={job_id}, err={e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _log.error(f"❌ [get_job_detail] 获取岗位详情失败: job_id={job_id}, err={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取岗位详情失败: {str(e)}")

@router.post("/api/jobs/check-ai-artifacts")
async def check_ai_artifacts(payload: CheckAiArtifactsRequest):
    """批量检测岗位是否已存在 AI 产物（深度评估/简历改写/打招呼语）。

    主页列表接口裁掉了大文本字段（record_normalizer.DETAIL_ONLY_FIELDS），
    前端列表数据判断不了这三类产物，批量派发前按记录回源飞书补查，
    供前端「重复发起二次确认」门禁使用（AI初评看综合评级，列表自带，不在此查）。
    门禁属省 Token 的软确认：单条记录读取失败按无产物返回（全 False），不阻断派发。"""
    import asyncio
    import logging

    from app.core.feishu_utils import extract_feishu_text
    from app.services import feishu_service

    logger = logging.getLogger(__name__)

    # 与 executor._handle_deep_evaluate 回写的六字段同口径
    DEEP_EVAL_FIELDS = (
        "理想画像与能力信号", "核心能力词典", "简历逐行审计",
        "高杠杆匹配点", "致命硬伤与毒点", "破局行动计划",
    )
    sem = asyncio.Semaphore(8)  # 礼貌限并发，避免大批量选中时打爆飞书 QPS

    async def _check(raw_id: str) -> tuple[str, dict[str, bool]]:
        rid = feishu_service.extract_record_id(raw_id)
        _MISSING = {"has_deep_eval": False, "has_rewrite": False, "has_greeting": False}
        try:
            async with sem:
                rec = await asyncio.to_thread(
                    feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID
                )
            fields = (rec or {}).get("fields", {})
            return rid, {
                "has_deep_eval": any(extract_feishu_text(fields.get(f, "")).strip() for f in DEEP_EVAL_FIELDS),
                "has_rewrite": bool(extract_feishu_text(fields.get("AI改写JSON", "")).strip()),
                "has_greeting": bool(extract_feishu_text(fields.get("打招呼语", "")).strip()),
            }
        except Exception as e:  # fail-open 契约自持：单条异常不拖垮整批（当前 get_job_record_from_feishu 自吞异常，此处防其未来变化）
            logger.warning(f"⚠️ [check-ai-artifacts] 记录 {rid} 读取异常，按无产物处理: {e}")
            return rid, dict(_MISSING)

    pairs = await asyncio.gather(*(_check(rid) for rid in payload.record_ids))
    return {"status": "success", "data": dict(pairs)}

@router.post("/api/jobs/import/parse")
@router.post("/import/parse")
async def parse_import_payload(payload: JobImportParseRequest):
    """极速录入第一步：解析不落库。图文可同传（视觉打底、文本覆盖），返回规整字段 + 质量警示（含查重预检），
    供 Web 确认补全页展示硬/软缺失、链接缺失与疑似重复。"""
    try:
        fields = await service.parse_job_from_sources(payload.raw_text, payload.images_base64)
    except service.VisionNotConfiguredError as e:
        raise _import_error_response(e)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")

    warnings = service.assess_parse_quality(fields)
    warnings["duplicate"] = await service.find_duplicate_job(fields)
    return {"status": "success", "fields": fields, "warnings": warnings}


@router.post("/api/jobs/import/confirm")
@router.post("/import/confirm")
async def confirm_import_payload(payload: JobImportConfirmRequest):
    """极速录入第二步：确认落库（唯一写入口，服务端二次校验+查重兜底）。
    硬缺失 422、查重命中 409（force_duplicate=true 放行）；成功返回回执与多维表格复核链接。"""
    try:
        data = await service.confirm_job_import(payload.fields, payload.force_duplicate)
    except (service.InvalidJobFieldsError, service.DuplicateJobError) as e:
        raise _import_error_response(e)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"极速录入失败: {str(e)}")

    return {
        "status": "success",
        "message": "已录入飞书",
        "data": data,
        "review_url": service.build_job_review_url(data.get("record_id", "")),
        "summary": service.format_job_import_summary(data),
    }


@router.post("/api/jobs/import/text")
@router.post("/import/text") # 新规范的短路径前缀
async def import_job_from_text(payload: JobImportTextRequest):
    """极速录入（旧一步式接口，聊天/脚本兼容）：文本解析 → 硬校验 → 查重 → 落库。
    硬缺失 422、查重命中 409，交互端请优先用 /parse + /confirm 两步接口。"""
    try:
        data = await service.import_job_from_text_service(payload.raw_text)
        print("====== 🎉 极速录入全流程完美收官！ ======\n")
        return {
            "status": "success",
            "message": "AI 解析并录入飞书成功！",
            "data": data
        }
    except (service.InvalidJobFieldsError, service.DuplicateJobError) as e:
        raise _import_error_response(e)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"❌ 致命错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"极速录入失败: {str(e)}")


@router.post("/api/jobs/import/image")
@router.post("/import/image") # 新规范的短路径前缀
async def import_job_from_images(payload: JobImportImageRequest):
    """极速多图录入（旧一步式接口，聊天/脚本兼容）：视觉解析 → 硬校验 → 查重 → 落库。"""
    if not payload.images_base64:
        raise HTTPException(status_code=400, detail="没有接收到图片数据")
    try:
        data = await service.import_job_from_images_service(payload.images_base64)
        print("====== 🎉 多图极速录入完美收官！ ======\n")
        return {"status": "success", "message": "图片解析并录入飞书成功！", "data": data}
    except service.VisionNotConfiguredError as e:
        raise _import_error_response(e)
    except (service.InvalidJobFieldsError, service.DuplicateJobError) as e:
        raise _import_error_response(e)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"❌ 多图解析致命错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"图片解析失败: {str(e)}")

@router.post("/ai_polish")
@router.post("/api/ai_polish")
async def ai_polish(payload: AIPolishRequest):
    """AI 局部润色"""
    try:
        # 🌟 修改为调用 action_service
        polished = await action_service.ai_polish_service(payload)
        return {"polished_text": polished}
    except ValueError as e:
        return {"polished_text": payload.selected_text, "error": str(e)}

@router.put("/api/update_job_status")
@router.put("/update_job_status")
async def update_job_status(payload: UpdateJobStatusRequest):
    """工作台：拖拽更新岗位状态"""
    try:
        # 🌟 修改为调用 action_service
        pure_record_id = await action_service.update_job_status_service(payload.job_id, payload.status)
        return {
            "status": "success",
            "message": f"成功更新跟进状态为: {payload.status}",
            "job_id": pure_record_id,
            "updated_status": payload.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新跟进状态时发生错误: {str(e)}")

from app.jobs.schemas import SaveLiveFieldsRequest, UpdateScheduleRequest  # noqa: E402


@router.put("/api/update_interview_schedule")
@router.put("/update_interview_schedule")
async def update_interview_schedule(payload: UpdateScheduleRequest):
    """更新面试日程并自动获取高德导航链接"""
    try:
        result = await action_service.update_interview_schedule_service(payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/api/save_live_fields")
@router.put("/save_live_fields")
async def save_live_fields(payload: SaveLiveFieldsRequest):
    """防抖自动保存现场面试记录和简历QA"""
    try:
        result = await action_service.save_live_fields_service(payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



from pydantic import BaseModel  # noqa: E402


class UpdateJobResumeRequest(BaseModel):
    job_id: str | None = None
    record_id: str | None = None
    resume_data: str
    current_status: str | None = None  # 支持透传当前状态，避免额外查表开销

@router.put("/api/update_job_resume")
async def update_job_resume(payload: UpdateJobResumeRequest):
    target_id = payload.job_id or payload.record_id
    if not target_id:
        raise HTTPException(status_code=422, detail="缺少必需字段: job_id 或 record_id")
    import logging
    _log = logging.getLogger(__name__)
    _log.info(f"💾 [update_job_resume] 保存岗位简历: target_id={target_id}, resume_len={len(payload.resume_data)}")

    # 🛡️ 终态保护：若岗位已处于已投递、已放弃、清洗淘汰等终态，仅更新简历物料，严禁倒流为「简历人工复核」
    cur_status = (payload.current_status or "").strip()
    if not cur_status:
        try:
            from app.core.config import settings
            from app.core.feishu_utils import extract_feishu_text, extract_record_id
            from app.services.feishu_service import get_job_record_from_feishu
            pure_rid = extract_record_id(target_id)
            rec = await asyncio.to_thread(get_job_record_from_feishu, pure_rid, settings.FEISHU_TABLE_ID_JOBS)
            if rec and isinstance(rec.get("fields"), dict):
                cur_status = extract_feishu_text(rec["fields"].get("跟进状态", "")).strip()
        except Exception as e:
            _log.warning(f"获取岗位当前跟进状态异常(fail-safe): {e}")

    from app.core.feishu_utils import is_terminal_or_post_delivery_status
    fields_to_update: dict[str, Any] = {"AI改写JSON": payload.resume_data}
    if is_terminal_or_post_delivery_status(cur_status):
        _log.info(f"🛡️ [update_job_resume] 岗位 {target_id} 当前为终态/投递后状态({cur_status})，仅保存简历内容，不倒流跟进状态")
    else:
        fields_to_update["跟进状态"] = "简历人工复核"

    return await action_service.update_job_field(
        target_id,
        fields_to_update,
    )

@router.put("/api/update_review_comments")
async def update_review_comments(payload: UpdateReviewCommentsRequest):
    return await action_service.update_job_field(payload.job_id, {"我的复核": payload.comments})

@router.put("/api/update_greeting")
async def update_greeting(payload: UpdateGreetingRequest):
    return await action_service.update_job_field(payload.job_id, {"打招呼语": payload.greeting})

@router.post("/api/jobs/batch-delete")
async def batch_delete_jobs(payload: BatchDeleteRequest):
    return await action_service.batch_delete_jobs(payload.job_ids)

@router.get("/api/jobs/{job_id}/transcript")
async def get_job_transcript(job_id: str):
    return await action_service.get_job_transcript(job_id)

from app.jobs.schemas import SaveTranscriptRequest  # noqa: E402


@router.post("/api/save_transcript")
@router.post("/save_transcript")
async def save_transcript(payload: SaveTranscriptRequest):
    try:
        return await action_service.save_transcript_action(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

import asyncio  # noqa: E402
import json  # noqa: E402

from fastapi import BackgroundTasks  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from app.agents.interview_prep_agent import InterviewPrepAgent  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.jobs.schemas import InterviewPrepRequest  # noqa: E402
from app.services.feishu_service import (  # noqa: E402
    extract_record_id,
    update_feishu_record,
)


@router.post("/api/jobs/interview-prep")
@router.post("/interview-prep")
async def generate_interview_prep(payload: InterviewPrepRequest, background_tasks: BackgroundTasks):
    """🤖 AI 面试辅导报告生成（NDJSON 流式）：结束后通过后台任务异步落盘飞书"""
    pure_record_id = extract_record_id(payload.job_id) if payload.job_id else ""
    agent = InterviewPrepAgent()

    async def sync_stream():
        report_content = ""
        async for chunk in agent.generate_report_stream(
            payload.resume_text,
            payload.job_description,
            payload.company_name,
        ):
            yield chunk
            try:
                event = json.loads(chunk.strip())
                if event.get("type") == "result":
                    report_content = event.get("content", "")
            except Exception:
                pass

        if report_content and pure_record_id:
            def _save():
                print(f"📝 [Background] 准备落盘飞书 record_id={pure_record_id}")
                try:
                    success = update_feishu_record(
                        record_id=pure_record_id,
                        fields_to_update={"面试辅导报告": report_content},
                        table_id=settings.FEISHU_TABLE_ID_JOBS,
                    )
                    if success:
                        print(f"✅ [Background] 飞书落盘成功: {pure_record_id}")
                    else:
                        print(f"❌ [Background] 飞书落盘失败: {pure_record_id}")
                except Exception as save_err:
                    print(f"❌ [Background] 飞书同步异常: {save_err}")

            # 引入 asyncio.to_thread 包装以避免阻塞事件循环，放入 BackgroundTasks
            background_tasks.add_task(asyncio.to_thread, _save)

    return StreamingResponse(sync_stream(), media_type="application/x-ndjson")

@router.post("/api/save_manual_resume")
@router.post("/save_manual_resume")
async def save_manual_resume(payload: SaveManualResumeRequest):
    try:
        return await action_service.save_manual_resume_action(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from app.jobs.schemas import QAEvaluateRequest  # noqa: E402


@router.post("/qa_evaluate")
@router.post("/api/qa_evaluate")
async def qa_evaluate(payload: QAEvaluateRequest):
    try:
        return await action_service.evaluate_qa_action(payload)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 🌟 多智能体 SSE 流式重构路由
# ==========================================
from fastapi import Query  # noqa: E402

from app.jobs.task_manager import task_event_manager  # noqa: E402


@router.get("/api/agents/logs")
async def stream_task_logs(task_id: str = Query(..., description="异步任务唯一ID")):
    """
    📡 标准的 SSE 长连接流式日志闭推通道
    前端通过 EventSource('/api/agents/logs?task_id=xxx') 订阅此接口，接收实时 Trace 链路日志
    """
    queue = task_event_manager.get_queue(task_id)
    if not queue:
        raise HTTPException(status_code=404, detail="未找到对应的活动任务流，请确认任务是否已过期或未启动")

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield "data: {\"type\": \"close\", \"message\": \"Stream connection closed gracefully.\"}\n\n"
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                queue.task_done()
        except asyncio.CancelledError:
            print(f"📡 [SSE Event] 前端用户主动断开了 task_id={task_id} 的 EventSource 连接")
        finally:
            task_event_manager.remove_task(task_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ==========================================
# 🌟 V2 Editor 结构化 JSON PDF/图片 导出
# ==========================================
import time  # noqa: E402

from app.core.config import BASE_DIR  # noqa: E402
from app.core.feishu_client import feishu_client  # noqa: E402
from app.core.pdf_renderer import render_resume_pdf  # noqa: E402
from app.jobs.schemas import JobResumePdfRequest  # noqa: E402
from app.services.export_service import upload_file_to_feishu_async  # noqa: E402

TEMP_DATA_DIR = BASE_DIR / "temp_print_data"
TEMP_DATA_DIR.mkdir(exist_ok=True)

@router.get("/api/jobs/temp-data/{job_id}")
async def get_temp_data(job_id: str):
    from app.services.feishu_service import extract_record_id
    pure_record_id = extract_record_id(job_id)
    file_path = TEMP_DATA_DIR / f"{pure_record_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Temp data not found")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    return data

@router.post("/api/jobs/resume-pdf")
async def export_v2_resume_pdf(payload: JobResumePdfRequest):
    from app.services.feishu_service import extract_record_id
    pure_record_id = extract_record_id(payload.job_id)

    # 🌟 修复 URI Too Long: 将数据存入临时文件
    file_path = TEMP_DATA_DIR / f"{pure_record_id}.json"
    file_path.write_text(json.dumps(payload.resume_data_v2, ensure_ascii=False), encoding="utf-8")

    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000")
    url = f"{frontend_base}/print/job-resume?job_id={pure_record_id}&use_temp=1"
    if payload.template and payload.template != "classic":
        template = payload.template if payload.template in ("classic", "color", "color_v2") else "classic"
        url += f"&template={template}"
    print(f">>> 🚀 [Playwright] V2结构化渲染 PDF，URL: {url}")

    pdf_bytes = await render_resume_pdf(url, page_size=payload.page_size)
    temp_pdf = BASE_DIR / f"v2_resume_{pure_record_id}_{int(time.time())}.pdf"
    temp_pdf.write_bytes(pdf_bytes)

    try:
        token = await upload_file_to_feishu_async(temp_pdf)
        update_fields = {"PDF备份": [{"file_token": token}]}
        msg = "PDF 已通过 Playwright 无损生成并同步至飞书"

        await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=pure_record_id,
            fields=update_fields,
        )

        return {"status": "success", "message": msg, "export_type": "pdf", "record_id": pure_record_id}
    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
        if temp_pdf.exists():
            try:
                temp_pdf.unlink()
            except OSError:
                pass

@router.post("/api/jobs/resume-images")
async def export_v2_resume_images(payload: JobResumePdfRequest):
    from app.services.feishu_service import extract_record_id
    pure_record_id = extract_record_id(payload.job_id)

    # 🌟 修复 URI Too Long: 将数据存入临时文件
    file_path = TEMP_DATA_DIR / f"{pure_record_id}.json"
    file_path.write_text(json.dumps(payload.resume_data_v2, ensure_ascii=False), encoding="utf-8")

    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000")
    url = f"{frontend_base}/print/job-resume?job_id={pure_record_id}&use_temp=1"
    if payload.template and payload.template != "classic":
        template = payload.template if payload.template in ("classic", "color", "color_v2") else "classic"
        url += f"&template={template}"
    print(f">>> 🚀 [Playwright] V2结构化渲染 高清长图，URL: {url}")

    from app.core.pdf_renderer import render_resume_image
    image_bytes = await render_resume_image(url)

    temp_image = BASE_DIR / f"v2_resume_{pure_record_id}_{int(time.time())}.jpg"
    temp_image.write_bytes(image_bytes)

    try:
        token = await upload_file_to_feishu_async(temp_image)

        update_fields = {"图片保存": [{"file_token": token}]}
        msg = "已生成 1 张高清长图并同步至飞书"

        await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=pure_record_id,
            fields=update_fields,
        )

        return {"status": "success", "message": msg, "export_type": "image", "record_id": pure_record_id}
    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
        if temp_image.exists():
            try:
                temp_image.unlink()
            except OSError:
                pass
