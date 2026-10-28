import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ai_agents.engine_facade import (
    process_resume_rewrite_detailed,
    resolve_rewrite_engine,
)
from ai_agents.skills.skill_contract import get_skill_contract
from app.core.feishu_client import (
    feishu_client,  # re-export：旧测试 patch.object(router.feishu_client) 兼容
)
from app.jobs.task_manager import task_event_manager
from app.services.feishu_service import extract_record_id
from app.strategy.skill_rewrite_preflight import preflight_skill_rewrite
from app.strategy.skill_rewrite_service import (
    SkillRewriteEngineError,
    SkillRewriteError,
    SkillRewriteGuardError,
    SkillRewritePersistenceError,
    SkillRewriteValidationError,
    _diagnosis_stage_message,
    _guard_parsed_resume,
    _load_job_diagnosis,
    _parse_result_has_error,
    _resolve_feishu_record_id_sync,
    run_skill_rewrite_pipeline,
)

logger = logging.getLogger("strategy_skill_agent_router")
logger.setLevel(logging.INFO)

router = APIRouter()


class TestSkillRewriteRequest(BaseModel):
    job_id: str
    jd_text: str
    job_name: str
    skill_id: str | None = None
    include_diagnosis: bool = True


class SkillRewriteAndSaveRequest(BaseModel):
    job_id: str = ""
    jd_text: str = ""
    job_name: str = ""
    resume_record_id: str | None = None
    skill_id: str | None = None
    include_diagnosis: bool = True


# 兼容旧测试/外部脚本的私有 helper 导入面；实现已收敛到 skill_rewrite_service。
__all__ = [
    "router",
    "TestSkillRewriteRequest",
    "SkillRewriteAndSaveRequest",
    "feishu_client",
    "_diagnosis_stage_message",
    "_guard_parsed_resume",
    "_load_job_diagnosis",
    "_parse_result_has_error",
    "_resolve_feishu_record_id_sync",
]


@router.post("/test_skill_rewrite")
async def test_skill_rewrite_api(payload: TestSkillRewriteRequest):
    """单独测试 Skill 改写（不归档、不写回），返回 markdown/usage/artifacts 供检查。"""
    try:
        diagnosis_dict: dict = {}
        if payload.include_diagnosis:
            try:
                _, diagnosis_dict = await _load_job_diagnosis(extract_record_id(payload.job_id))
            except Exception as e:
                logger.warning(f"test_skill_rewrite_api 无法读取诊断报告: {e}")

        result = await asyncio.to_thread(
            process_resume_rewrite_detailed,
            jd_text=payload.jd_text,
            diagnosis_dict=diagnosis_dict,
            job_name=payload.job_name,
            rewrite_mode="skill",
            skill_id=payload.skill_id or "",
            include_diagnosis=payload.include_diagnosis,
        )
        return {
            "status": "success",
            "data": {
                "markdown": result.markdown,
                "usage": result.usage,
                "artifacts": result.artifacts,
                "partial": result.partial,
                "artifact_count": result.artifact_count,
                "expected_artifact_count": result.expected_artifact_count,
                "result_kind": result.result_kind,
                "engine": result.engine,
            },
        }
    except Exception as e:
        logger.exception(f"test_skill_rewrite error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skill_rewrite_preflight")
async def skill_rewrite_preflight_api(payload: SkillRewriteAndSaveRequest):
    """执行前预检：产物数量/类型、是否含简历、将加载的上下文、token 预估。"""
    try:
        report = await preflight_skill_rewrite(payload)
        return {"status": "success", "data": report}
    except SkillRewriteError as e:
        logger.error(f"skill_rewrite_preflight 失败: {e}")
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"skill_rewrite_preflight error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skill_rewrite_and_save")
async def skill_rewrite_and_save_api(payload: SkillRewriteAndSaveRequest):
    """正式版 Skill 简历改写（解析 + 对账 + 归档 + 写回完全共用流水线）。"""
    try:
        outcome = await run_skill_rewrite_pipeline(payload)
        return {
            "status": "success",
            "data": {
                "parsed_json": outcome.parsed_json,
                "markdown": outcome.markdown,
                "usage": outcome.usage,
                "partial": outcome.partial,
                "artifact_count": outcome.artifact_count,
                "expected_artifact_count": outcome.expected_artifact_count,
                "engine": outcome.engine,
                "result_kind": outcome.result_kind,
                "has_resume_output": outcome.has_resume_output,
                "final_artifact": outcome.final_artifact,
                "archive_error": outcome.archive_error,
            },
        }
    except SkillRewriteError as e:
        logger.error(f"skill_rewrite_and_save 失败: {e}")
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"skill_rewrite_and_save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skill_rewrite_async")
async def skill_rewrite_async_api(payload: SkillRewriteAndSaveRequest):
    """异步启动 Skill 改写智能体，立即返回 task_id，并通过 /skill_agent_logs 开启 SSE 实时推演流。"""
    task_id = f"skill_task_{uuid.uuid4().hex[:12]}"
    queue = task_event_manager.register_task(task_id)
    # 推演跑在 asyncio.to_thread 工作线程里，asyncio.Queue 非线程安全——
    # 必须经由事件循环的 call_soon_threadsafe 投递（直接 put_nowait 在非调试模式下
    # 不报错但事件可能长期滞留，看板表现为「连上后一动不动」，2026-10-09 用户报修）
    loop = asyncio.get_running_loop()

    def push_event(event: dict):
        event.setdefault("timestamp", time.time())
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            logger.warning(f"事件循环已关闭，丢弃任务 {task_id} 的尾事件: {event.get('type')}")

    def push_close():
        # 哨兵必须与事件走同一条 call_soon_threadsafe 队列：否则极快任务里
        # 直接 put_nowait(None) 可能先于已调度的 complete/error 入队，前端少收终局载荷。
        try:
            loop.call_soon_threadsafe(queue.put_nowait, None)
        except RuntimeError:
            pass

    async def _run_skill_worker():
        try:
            engine = resolve_rewrite_engine(payload.skill_id or "")
            contract = get_skill_contract(payload.skill_id or "")
            result_kind = contract.get("output_kind", "resume")
            push_event({
                "type": "init",
                "task_id": task_id,
                "engine": engine,
                "result_kind": result_kind,
                "has_resume_output": bool(contract.get("has_resume_output", result_kind == "resume")),
                "expected_artifacts": contract.get("expected_artifact_count", 0),
                "message": "🚀 正在初始化 Skill 智能体改写任务...",
                "job_name": payload.job_name,
                "skill_id": payload.skill_id or "default",
            })

            def on_agent_event(event_type: str, data: dict):
                push_event({"type": event_type, **data})

            outcome = await run_skill_rewrite_pipeline(payload, on_event=on_agent_event)

            status = "partial" if outcome.partial else "success"
            is_resume = outcome.result_kind == "resume"
            if outcome.partial:
                if outcome.expected_artifact_count > 0:
                    message = (
                        f"⚠️ 部分完成（{outcome.artifact_count}/"
                        f"{outcome.expected_artifact_count} 份产物），"
                        + ("已写回简历库" if is_resume else "产物已归档")
                    )
                else:
                    message = f"⚠️ 部分完成（{outcome.artifact_count} 份产物），产物已归档"
            elif is_resume:
                message = "🎉 改写与多产物归档全部完成！"
            else:
                message = "🎉 技能执行完成，产物已归档到产物库"

            push_event({
                "type": "complete",
                "status": status,
                "message": message,
                "data": {
                    "parsed_json": outcome.parsed_json,
                    "markdown": outcome.markdown,
                    "usage": outcome.usage,
                    "partial": outcome.partial,
                    "artifact_count": outcome.artifact_count,
                    "expected_artifact_count": outcome.expected_artifact_count,
                    "engine": outcome.engine,
                    "result_kind": outcome.result_kind,
                    "has_resume_output": outcome.has_resume_output,
                    "final_artifact": outcome.final_artifact,
                    "archive_error": outcome.archive_error,
                    "persisted": outcome.persisted,
                },
            })

        except SkillRewriteGuardError as e:
            push_event({
                "type": "error",
                "detail": str(e),
                "message": f"❌ 改写产物完整性校验未通过，已保留原简历数据: {e}",
            })
        except SkillRewriteValidationError as e:
            push_event({
                "type": "error",
                "detail": str(e),
                "message": f"❌ {e}",
            })
        except (SkillRewriteEngineError, SkillRewritePersistenceError) as e:
            push_event({
                "type": "error",
                "detail": str(e),
                "message": f"❌ 改写失败: {e}",
            })
        except Exception as e:
            logger.exception(f"Async skill worker error: {e}")
            push_event({
                "type": "error",
                "detail": str(e),
                "message": f"❌ 智能体推演异常: {e}",
            })
        finally:
            push_close()

    asyncio.create_task(_run_skill_worker())

    return {
        "status": "success",
        "task_id": task_id,
        "message": "Skill 智能体推演任务已成功创建，请连接 SSE 日志流。",
    }


@router.get("/skill_agent_logs")
async def skill_agent_logs_api(task_id: str = Query(..., description="异步改写任务ID")):
    """Skill 智能体 SSE 实时推演日志流"""
    queue = task_event_manager.get_queue(task_id)
    if not queue:
        raise HTTPException(status_code=404, detail="未找到对应的活动任务流，请确认任务是否已过期或未启动")

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield 'data: {"type": "close", "message": "Stream closed."}\n\n'
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                queue.task_done()
        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled for task {task_id}")
        finally:
            task_event_manager.remove_task(task_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
