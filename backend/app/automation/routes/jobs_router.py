"""
岗位处理与失败重试路由 (Jobs Router)
====================================
负责：
- 失败岗位单岗位图重启 (/retry-job)
- 岗位快照查询与看板呈现 (/jobs-snapshot)
- AI 诊断官 L3 失败原因分析 (/diagnose-failure)
- 失败岗位主动放弃与门牌回写 (/dismiss-failed-job)
- 失败岗位重试唤醒 (/retry-failed-job)
"""
import asyncio
import logging
import sqlite3
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.automation import run_snapshot as _rs
from app.automation import scheduler
from app.automation.full_auto import RAW_DB_PATH
from app.automation.snapshot_service import build_jobs_snapshot

logger = logging.getLogger(__name__)
router = APIRouter()


class RetryJobRequest(BaseModel):
    thread_id: str


_RETRY_BG_TASKS: set[asyncio.Task] = set()

_RETRY_INITIAL_KEYS = (
    "job_id", "record_id", "platform", "company_name", "job_name", "jd_text",
    "salary", "city", "experience", "education", "resume_text",
    "mass_resume_text", "preferences_text", "company_intel", "feishu_fields",
)


@router.post("/retry-job")
async def retry_single_job(req: RetryJobRequest):
    """失败岗位重试：读取该岗位 thread 的存量状态，按原始入参从头重跑单岗位流水线。

    【Q11 已标注保留】运维/应急端点：前端暂未接线（应急场景走 curl/脚本调用），非死代码，勿清理。
    """
    from app.automation import pipeline_broadcast as pb
    from app.automation.full_auto import _run_single_job_graph

    if not scheduler.pipeline_app:
        raise HTTPException(status_code=500, detail="自动化引擎未初始化")

    config = {"configurable": {"thread_id": req.thread_id}}
    state = await scheduler.pipeline_app.aget_state(config)
    if not state or not state.values:
        raise HTTPException(status_code=404, detail="找不到该岗位的流水线状态（可能已被清理），无法重试")
    if state.next:
        raise HTTPException(status_code=400, detail=f"该岗位当前停在 {state.next[0]} 断点等待处理，无需重试")

    initial_state = {k: state.values.get(k, "") for k in _RETRY_INITIAL_KEYS}
    if not initial_state.get("job_name"):
        raise HTTPException(status_code=404, detail="该岗位缺少基础信息，无法重试")

    cur = pb.get_current_pipeline()
    if cur.get("running") and cur.get("task_id"):
        broadcast_task_id = cur["task_id"]
        dedicated = False
    else:
        broadcast_task_id = f"pipeline_retry_{req.thread_id}_{uuid.uuid4().hex[:6]}"
        pb.create_pipeline_queue(broadcast_task_id)
        dedicated = True

    async def _runner():
        try:
            await _run_single_job_graph(initial_state, config, broadcast_task_id)
        except Exception as e:
            logger.error(f"岗位重试异常 {req.thread_id}: {e}", exc_info=True)
        finally:
            if dedicated:
                await pb.emit_end(broadcast_task_id, {"retry": req.thread_id})

    task = asyncio.create_task(_runner())
    _RETRY_BG_TASKS.add(task)
    task.add_done_callback(_RETRY_BG_TASKS.discard)

    return {
        "status": "success",
        "task_id": broadcast_task_id,
        "dedicated": dedicated,
        "message": "岗位流水线已重启，可订阅实时进度",
    }


@router.get("/jobs-snapshot")
async def jobs_snapshot():
    """全链路指挥中心本轮岗位快照。"""
    return await build_jobs_snapshot()


class DiagnoseFailureRequest(BaseModel):
    job_id: str


@router.post("/diagnose-failure")
async def diagnose_failure(req: DiagnoseFailureRequest):
    """AI 诊断官（L3）：对持续失败的岗位读日志+LLM 分析，产出死因/分类/修复建议/工单。"""
    from app.automation.diag_agent import diagnose_failure as _diag
    result = await _diag(req.job_id)
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail=result.get("message") or "诊断失败")
    return result


class DismissFailedJobRequest(BaseModel):
    job_id: str
    job_url: str | None = ""


@router.post("/dismiss-failed-job")
async def dismiss_failed_job(req: DismissFailedJobRequest):
    """用户主动放弃执行失败的岗位。"""
    logger.info(f"🗑️ [dismiss_failed_job] 收到放弃失败岗位请求: job_id={req.job_id}")
    job_id = str(req.job_id or "")
    is_raw = job_id.startswith("raw_")

    feishu_note = ""
    if not is_raw and job_id:
        feishu_ok = False
        try:
            from app.services.feishu_service import update_feishu_record
            feishu_ok = await asyncio.to_thread(
                update_feishu_record, job_id, {"跟进状态": "已放弃投递"})
        except Exception as e:
            logger.warning(f"⚠️ [dismiss_failed_job] 回写飞书「已放弃投递」异常: {e}")
        if feishu_ok:
            feishu_note = "飞书跟进状态改为「已放弃投递」"
        else:
            logger.warning(f"⚠️ [dismiss_failed_job] 飞书回写未生效（可能飞书中无此记录或网络受阻），继续执行本地销账与移出: job_id={job_id}")
            feishu_note = "已移出看板并标记放弃"

    _rs.dismiss_job(job_id)
    _rs.remove_delivery_failure(job_id)
    if is_raw:
        try:
            rowid = int(job_id.replace("raw_", ""))
            with sqlite3.connect(RAW_DB_PATH) as conn:
                conn.execute("UPDATE raw_jobs SET process_status = '已放弃' WHERE rowid = ?", (rowid,))
                conn.commit()
            logger.info(f"✅ [dismiss_failed_job] 已更新 SQLite raw_{rowid} 状态为已放弃")
        except Exception as e:
            logger.warning(f"更新 SQLite 已放弃异常: {e}")
    elif req.job_url:
        try:
            with sqlite3.connect(RAW_DB_PATH) as conn:
                conn.execute("UPDATE raw_jobs SET process_status = '已放弃' WHERE job_link = ?", (req.job_url,))
                conn.commit()
        except Exception as e:
            logger.warning(f"更新 SQLite 已放弃异常: {e}")
    return {
        "status": "success",
        "message": f"岗位 {job_id} 已放弃：{feishu_note}，不会再被自动投递",
    }


class RetryFailedJobRequest(BaseModel):
    job_id: str
    job_url: str | None = ""
    pipeline_task_id: str | None = ""


@router.post("/retry-failed-job")
async def retry_failed_job(req: RetryFailedJobRequest):
    """用户手动对执行失败的岗位进行重试。"""
    logger.info(f"⚡ [retry_failed_job] 重试失败岗位: job_id={req.job_id}, url={req.job_url}")
    _rs.undismiss_job(req.job_id)
    if not str(req.job_id).startswith("raw_"):
        _rs.remove_delivery_failure(req.job_id)
        _rs.mark_job_retrying(req.job_id)

        async def _do_delivery_retry(job_id: str, job_url: str):
            from app.automation.scheduler import _resume_job_delivery
            try:
                ok, msg = await _resume_job_delivery(job_id)
                if ok:
                    logger.info(f"✅ [retry_failed_job] 重试投递成功: job_id={job_id}, {msg}")
                    _rs.remove_delivery_failure(job_id)
                else:
                    logger.warning(f"❌ [retry_failed_job] 重试投递仍受阻: job_id={job_id}, error={msg}")
                    from app.core.feishu_utils import extract_feishu_text as _txt
                    from app.core.feishu_utils import extract_job_grade
                    from app.services.feishu_service import (
                        TABLE_ID,
                        get_job_record_from_feishu,
                    )
                    rec = await asyncio.to_thread(get_job_record_from_feishu, job_id, TABLE_ID)
                    fields = (rec or {}).get("fields", {})
                    _rs.record_delivery_failure(
                        job_id=job_id,
                        error=msg,
                        company=_txt(fields.get("公司名称", "")),
                        job_name=_txt(fields.get("岗位名称", "")),
                        platform=_txt(fields.get("招聘平台", "")) or "zhilian",
                        job_url=job_url or _txt(fields.get("岗位链接", "")),
                        grade=extract_job_grade(fields)
                    )
                    try:
                        from app.automation.self_heal import (
                            append_heal_log,
                            run_self_heal,
                        )
                        heal = await run_self_heal(_txt(fields.get("招聘平台", "")) or "zhilian", msg)
                        append_heal_log(job_id, heal)
                    except Exception as heal_e:
                        logger.warning(f"[retry_failed_job] 自愈动作异常: {heal_e}")
            except Exception as ex:
                logger.error(f"❌ [retry_failed_job] 重试执行异常: job_id={job_id}, ex={ex}")
                try:
                    from app.core.feishu_utils import extract_feishu_text as _txt
                    from app.core.feishu_utils import extract_job_grade
                    from app.services.feishu_service import (
                        TABLE_ID,
                        get_job_record_from_feishu,
                    )
                    rec = await asyncio.to_thread(get_job_record_from_feishu, job_id, TABLE_ID)
                    fields = (rec or {}).get("fields", {})
                    _rs.record_delivery_failure(
                        job_id=job_id,
                        error=f"重试执行异常: {str(ex)[:120]}",
                        company=_txt(fields.get("公司名称", "")),
                        job_name=_txt(fields.get("岗位名称", "")),
                        platform=_txt(fields.get("招聘平台", "")) or "zhilian",
                        job_url=job_url or _txt(fields.get("岗位链接", "")),
                        grade=extract_job_grade(fields)
                    )
                except Exception:
                    _rs.record_delivery_failure(
                        job_id=job_id,
                        error=f"重试执行异常: {str(ex)[:120]}",
                        job_url=job_url,
                    )
            finally:
                _rs.unmark_job_retrying(job_id)

        asyncio.create_task(_do_delivery_retry(req.job_id, req.job_url or ""))
        return {"status": "success", "message": f"岗位 {req.job_id} 已重新拉起自动投递引擎进行重试"}
    else:
        from app.automation.full_auto import run_single_job_pipeline_async
        raw_id = req.job_id.replace("raw_", "")
        _rs.mark_job_retrying(req.job_id)

        async def _do_raw_retry(raw_rowid, task_id, job_id):
            try:
                await run_single_job_pipeline_async(
                    record_id="",
                    raw_rowid=raw_rowid,
                    pipeline_task_id=task_id
                )
            finally:
                _rs.unmark_job_retrying(job_id)

        asyncio.create_task(_do_raw_retry(raw_id, req.pipeline_task_id or None, req.job_id))
        return {"status": "success", "message": f"岗位 {req.job_id} 已重新拉起流水线进行重试"}


class ResendGreetingRequest(BaseModel):
    job_id: str
    job_url: str | None = ""


@router.post("/resend-greeting")
async def resend_greeting(req: ResendGreetingRequest):
    """用户在「已投递」Tab 手动点击补发打招呼语（直接执行，向前端即时返回结果反馈）。"""
    logger.info(f"💬 [resend_greeting] 手动单独补发打招呼语: job_id={req.job_id}")
    from app.automation.delivery_tasks import _resume_job_delivery
    _rs.mark_job_retrying(req.job_id)
    try:
        ok, msg = await _resume_job_delivery(req.job_id)
        if ok:
            _rs.remove_delivery_failure(req.job_id)
            return {"status": "success", "message": "专属打招呼语已成功送达 HR 微聊！"}
        else:
            return {"status": "error", "message": f"打招呼语补发未成功: {msg}"}
    except Exception as e:
        logger.error(f"❌ [resend_greeting] 补发打招呼语执行异常: job_id={req.job_id}, ex={e}", exc_info=True)
        return {"status": "error", "message": f"补发打招呼语执行异常: {str(e)[:80]}"}
    finally:
        _rs.unmark_job_retrying(req.job_id)


class BatchRetryFailedJobsRequest(BaseModel):
    job_ids: list[str] = Field(..., min_length=1, max_length=50, description="需要批量重试的岗位 ID 列表")


@router.post("/batch-retry-failed-jobs")
async def batch_retry_failed_jobs(req: BatchRetryFailedJobsRequest):
    """用户在「执行失败」Tab 批量勾选岗位并触发重试（接入标准编排引擎，防并发与防风控）。"""
    from app.automation.services.batch_retry_service import (
        batch_retry_failed_jobs_service,
    )
    return await batch_retry_failed_jobs_service(req.job_ids)


class BatchDismissFailedJobsRequest(BaseModel):
    job_ids: list[str] = Field(..., min_length=1, max_length=50, description="需要批量放弃的岗位 ID 列表")


@router.post("/batch-dismiss-failed-jobs")
async def batch_dismiss_failed_jobs(req: BatchDismissFailedJobsRequest):
    """用户在「执行失败」Tab 批量勾选岗位并主动放弃（持久化先行，移出指挥中心看板）。"""
    from app.automation.services.batch_retry_service import (
        batch_dismiss_failed_jobs_service,
    )
    return await batch_dismiss_failed_jobs_service(req.job_ids)
