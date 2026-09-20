"""
简历上传解析的 Redis 异步状态机。

表结构：Redis Hash (或 In-Memory Dict) task:{task_id}
状态流转：processing → ready / failed（failed 可经 retry 重回 processing）
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.redis_service import redis_service

logger = logging.getLogger("resume_upload_service")

# 僵尸任务判定阈值：超过该秒数仍 processing，视为进程重启丢失，自动标 failed
_ZOMBIE_TIMEOUT_SECONDS = 600  # 10 分钟

async def create_task(filename: str) -> str:
    """创建一条 processing 状态的上传任务，返回 task_id。"""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "task_id": task_id,
        "filename": filename,
        "status": "processing",
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

async def run_parse_pipeline(task_id: str, file_path: str, filename: str) -> None:
    """后台解析流水线：本地解析 → 脱敏 → LLM 清洗 → 结构化 JSON。"""
    from app.core.document_parser import parse_document_to_markdown
    from app.core.resume_parser import (
        extract_and_truncate_personal_info,
    )
    from app.core.resume_structurer import json_to_markdown, parse_resume_to_json

    logger.info(f"[File: resume_upload_service.py -> Func: run_parse_pipeline] 开始解析任务 {task_id}")

    try:
        # Step 0: 物理读取与解析
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"找不到临时文件: {file_path}")

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        raw_markdown = await parse_document_to_markdown(file_bytes, filename)
        await update_task(task_id, original_markdown=raw_markdown)

        # Step 1: 脱敏
        personal_info, safe_text = extract_and_truncate_personal_info(raw_markdown)
        await update_task(task_id, personal_info=json.dumps(personal_info, ensure_ascii=False))

        # Step 2: 结构化 JSON (唯一一次大模型调用)
        structured = await parse_resume_to_json(safe_text)

        # Step 3: 将 JSON 降维反向格式化为前端期望的 Markdown (纯代码 0ms 组装)
        cleaned_md = json_to_markdown(structured)
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
        await update_task(task_id, status="failed", error_msg=str(e))
    finally:
        # 阅后即焚
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"[File: resume_upload_service.py -> Func: run_parse_pipeline] 🗑️ 已删除临时文件: {file_path}")
