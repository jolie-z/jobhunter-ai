"""
简历上传解析的 Redis 异步状态机。

表结构：Redis Hash (或 In-Memory Dict) task:{task_id}
状态流转：processing → ready / failed（failed 可经 retry 重回 processing）
进度字段（供 SSE 真进度透出）：
  stage           —— reading / desensitizing / structuring / finalizing
  stage_started_at—— 当前阶段开始时间（ISO，带时区）
  progress_chars  —— AI 结构化阶段的流式已生成字符数（其他阶段为 0）
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.error_messages import friendly_error
from app.services.redis_service import redis_service

logger = logging.getLogger("resume_upload_service")


# 僵尸任务判定阈值：超过该秒数仍 processing，视为进程重启丢失，自动标 failed
_ZOMBIE_TIMEOUT_SECONDS = 600  # 10 分钟

# 解析阶段文案（后端统一给 label，前端只管渲染；新增阶段需同步 upload_router 的透传）
STAGE_LABELS = {
    "reading": "读取并解析文档",
    "desensitizing": "隐私信息脱敏",
    "structuring": "AI 智能结构化",
    "finalizing": "生成智能排版",
}

async def create_task(filename: str) -> str:
    """创建一条 processing 状态的上传任务，返回 task_id。"""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "task_id": task_id,
        "filename": filename,
        "status": "processing",
        "stage": "reading",
        "stage_started_at": now,
        "progress_chars": 0,
        "created_at": now,
        "updated_at": now,
    }
    await redis_service.set_task(task_id, data)
    return task_id

async def get_task(task_id: str) -> dict[str, Any] | None:
    """读取任务详情。若卡在 processing 超过阈值，自动标 failed（僵尸自愈）。"""
    task = await redis_service.get_task(task_id)
    if not task:
        return None

    # 僵尸自愈
    if task.get("status") == "processing":
        updated_at = task.get("updated_at") or task.get("created_at")
        try:
            updated_dt = datetime.fromisoformat(updated_at)
            if (datetime.now(timezone.utc) - updated_dt).total_seconds() > _ZOMBIE_TIMEOUT_SECONDS:
                logger.warning(f"任务 {task_id} 处于 processing 超过 {_ZOMBIE_TIMEOUT_SECONDS}s，自动标记 failed")
                await update_task(task_id, status="failed", error_msg="解析任务异常中断（疑似服务重启），请重试")
                task["status"] = "failed"
                task["error_msg"] = "解析任务异常中断（疑似服务重启），请重试"
        except (ValueError, TypeError):
            pass

    return task

async def update_task(task_id: str, **fields: Any) -> None:
    """局部更新任务字段，自动刷新 updated_at。"""
    if not fields:
        return
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await redis_service.update_task(task_id, **fields)

async def _update_stage(task_id: str, stage: str) -> None:
    await update_task(
        task_id,
        stage=stage,
        stage_started_at=datetime.now(timezone.utc).isoformat(),
    )

async def _run_structuring(task_id: str, raw_markdown: str) -> tuple[dict, dict, str]:
    """脱敏 → LLM 结构化（含流式字数进度）→ 本地渲染。

    首次上传与失败重试共用的中段流水线，返回 (personal_info, structured, cleaned_md)。
    """
    from app.core.resume_parser import extract_and_truncate_personal_info
    from app.core.resume_structurer import json_to_markdown, parse_resume_to_json

    # Step 1: 脱敏（纯正则，毫秒级）
    await _update_stage(task_id, "desensitizing")
    personal_info, safe_text = extract_and_truncate_personal_info(raw_markdown)
    await update_task(task_id, personal_info=json.dumps(personal_info, ensure_ascii=False))

    # Step 2: AI 结构化（唯一一次大模型调用；progress_cb 在 worker 线程回调，
    # 这里用并行 poll 协程把线程安全计数器每 0.8s 刷进 Redis，供 SSE 透出真进度）
    await _update_stage(task_id, "structuring")
    progress = {"chars": 0}

    def on_delta(chars: int) -> None:
        progress["chars"] = chars

    llm_task = asyncio.create_task(
        parse_resume_to_json(safe_text, progress_cb=on_delta, strict=True)
    )

    async def _poll_progress() -> None:
        while not llm_task.done():
            if progress["chars"] > 0:
                await update_task(task_id, progress_chars=progress["chars"])
            await asyncio.sleep(0.8)

    poll_task = asyncio.create_task(_poll_progress())
    try:
        structured = await llm_task
    finally:
        poll_task.cancel()

    # Step 3: 本地渲染 0ms
    await _update_stage(task_id, "finalizing")
    cleaned_md = json_to_markdown(structured)
    return personal_info, structured, cleaned_md

async def run_parse_pipeline(task_id: str, file_path: str, filename: str) -> None:
    """后台解析流水线：本地解析 → 脱敏 → LLM 清洗 → 结构化 JSON。"""
    from app.core.document_parser import parse_document_to_markdown

    logger.info(f"[File: resume_upload_service.py -> Func: run_parse_pipeline] 开始解析任务 {task_id}")

    try:
        # Step 0: 物理读取与解析（markitdown 本地转换，无网络无模型）
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"找不到临时文件: {file_path}")

        await _update_stage(task_id, "reading")
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        raw_markdown = await parse_document_to_markdown(file_bytes, filename)
        await update_task(task_id, original_markdown=raw_markdown)

        personal_info, structured, cleaned_md = await _run_structuring(task_id, raw_markdown)

        # 原文快照（底稿）：原文件字节已在内存（临时文件阅后即焚前），落盘留存 + 挂 _meta
        # 失败只告警不阻塞解析主链路
        try:
            from app.services.resume_snapshot_service import save_snapshot

            with open(file_path, "rb") as f:
                source_bytes = f.read()
            structured = save_snapshot(task_id, source_bytes, filename, raw_markdown, structured)
        except Exception:
            logger.exception(f"[File: resume_upload_service.py -> Func: run_parse_pipeline] 快照留存失败（忽略）{task_id}")

        await update_task(task_id, cleaned_markdown=cleaned_md)

        # 将脱敏提取出的个人信息，挂载回结构化 JSON 中，供前端 V2 Store 直接消费渲染
        if isinstance(structured, dict):
            structured["personalInfo"] = personal_info

        await update_task(
            task_id,
            structured_json=json.dumps(structured, ensure_ascii=False),
            status="ready",
            error_msg=None,
        )
        logger.info(f"[File: resume_upload_service.py -> Func: run_parse_pipeline] ✅ 任务 {task_id} 解析成功")

    except Exception as e:
        logger.exception(f"[File: resume_upload_service.py -> Func: run_parse_pipeline] ❌ 任务 {task_id} 解析失败")
        await update_task(task_id, status="failed", error_msg=friendly_error(str(e)))
    finally:
        # 阅后即焚
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"[File: resume_upload_service.py -> Func: run_parse_pipeline] 🗑️ 已删除临时文件: {file_path}")

async def run_retry_pipeline(task_id: str, raw_markdown: str) -> None:
    """失败重试流水线：复用 Redis 中已存的 original_markdown，只跑脱敏 → 结构化 → 渲染。"""
    try:
        # 双保险：retry_upload 入口已重置过一次，这里再兜底防重复入口漏带
        await update_task(task_id, progress_chars=0)
        personal_info, structured, cleaned_md = await _run_structuring(task_id, raw_markdown)

        # 重试后覆盖快照的 parsed.json 与置信度（snapshot_id/task_id 不变，原件不重复拷贝），
        # 保证修正回流的比对基准与最终保存的内容一致
        try:
            from app.services.resume_snapshot_service import update_snapshot_parsed

            structured = update_snapshot_parsed(task_id, structured)
        except Exception:
            logger.exception(f"[File: resume_upload_service.py -> Func: run_retry_pipeline] 快照更新失败（忽略）{task_id}")

        await update_task(task_id, cleaned_markdown=cleaned_md)
        if isinstance(structured, dict):
            structured["personalInfo"] = personal_info
        await update_task(
            task_id,
            structured_json=json.dumps(structured, ensure_ascii=False),
            status="ready",
            error_msg=None,
        )
        logger.info(f"[File: resume_upload_service.py -> Func: run_retry_pipeline] ✅ 任务 {task_id} 重试成功")
    except Exception as e:
        logger.exception(f"[File: resume_upload_service.py -> Func: run_retry_pipeline] ❌ 任务 {task_id} 重试失败")
        await update_task(task_id, status="failed", error_msg=friendly_error(str(e)))
