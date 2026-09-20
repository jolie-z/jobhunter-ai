import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.tasks.executor import run_batch_ai_task
from app.tasks.schemas import BatchTaskRequest
from app.tasks.state import GLOBAL_TASK_STATE, task_queues, task_status

router = APIRouter()

@router.post("/batch-process")
async def batch_process(payload: BatchTaskRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    print(f"\n👉 [后端] 收到批量任务请求，类型: {payload.task_type}，数量: {len(payload.job_ids)}")
    if payload.task_type not in ["evaluate", "rewrite", "deep_evaluate", "deliver", "mass_apply", "approve"]:
        raise HTTPException(
            status_code=400,
            detail="task_type 必须是 'evaluate'、'rewrite'、'deep_evaluate'、'deliver'、'mass_apply' 或 'approve'"
        )

    if not payload.job_ids:
        raise HTTPException(
            status_code=400,
            detail="job_ids 不能为空"
        )

    task_id = str(uuid.uuid4())
    GLOBAL_TASK_STATE["current_task_id"] = task_id
    task_queues[task_id] = asyncio.Queue()

    task_status[task_id] = {
        "status": "pending",
        "task_type": payload.task_type,
        # 浅拷贝登记本批岗位：批量删除据此拦截运行中任务（B13），避免 executor 内重绑定改写请求体
        "job_ids": list(payload.job_ids),
        "total": len(payload.job_ids),
        "completed": 0,
        "created_at": datetime.now().isoformat()
    }

    # 核心：使用 BackgroundTasks 将其放入后台，绝不阻塞当前请求
    background_tasks.add_task(
        run_batch_ai_task,
        task_id=task_id,
        task_type=payload.task_type,
        job_ids=payload.job_ids,
        queue=task_queues[task_id],
        scheduled_at=payload.scheduled_at
    )

    return {
        "status": "started",
        "task_id": task_id,
        "message": f"批量任务已启动，共 {len(payload.job_ids)} 个岗位"
    }

@router.get("/status")
def get_task_status(task_id: str | None = None):
    """短轮询接口：查询当前是否有后台任务正在执行，支持无参自动探活"""
    is_proc = GLOBAL_TASK_STATE.get("is_processing", False)
    current_tid = GLOBAL_TASK_STATE.get("current_task_id")
    target_id = task_id or current_tid or GLOBAL_TASK_STATE.get("last_completed_task_id")

    res: dict[str, Any] = {
        "is_processing": is_proc,
        "current_task_id": current_tid,
    }
    if target_id and target_id in task_status:
        res["task"] = task_status[target_id]
        res["task_id"] = target_id
    return res

@router.get("/logs")
async def task_logs(task_id: str):
    if task_id not in task_queues:
        raise HTTPException(
            status_code=404,
            detail=f"任务 {task_id} 不存在或已过期"
        )

    channel = task_queues[task_id]
    from app.tasks.state import TaskChannel
    if isinstance(channel, TaskChannel):
        queue = channel.subscribe()
    else:
        queue = channel

    async def event_generator():
        try:
            yield f'data: {{"type": "connected", "message": "已连接到任务日志流", "task_id": "{task_id}"}}\n\n'

            while True:
                try:
                    # 🌟 缩短超时至 2s：更及时地发送心跳，防止 SSE 连接因空闲被代理/浏览器切断
                    message = await asyncio.wait_for(queue.get(), timeout=2.0)
                    is_terminal_message = any(
                        marker in message
                        for marker in (
                            '"type": "end"',
                            '"type":"end"',
                            '"type": "complete"',
                            '"type":"complete"',
                            '"type": "terminated"',
                            '"type":"terminated"',
                        )
                    )
                    if is_terminal_message:
                        yield message
                        break
                    yield message
                except asyncio.TimeoutError:
                    # 2 秒内无新日志 → 发送心跳保持连接存活
                    yield f'data: {{"type": "heartbeat", "timestamp": "{datetime.now().isoformat()}"}}\n\n'
                except asyncio.CancelledError:
                    # 客户端临时断开时保留通道，允许浏览器 EventSource 自动重连后继续消费进度
                    print(f"🔌 [SSE] 客户端断开连接 ({task_id})")
                    break
        except Exception as e:
            # 🌟 异常只影响当前连接的推流，不向外传播
            print(f"❌ [SSE] 任务 {task_id} 推流异常: {e}")
            yield f'data: {{"type": "error", "message": "日志推送异常: {str(e)}"}}\n\n'
        finally:
            if isinstance(channel, TaskChannel):
                channel.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
