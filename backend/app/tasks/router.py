import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.tasks.executor import run_batch_ai_task
from app.tasks.schemas import BatchTaskRequest
from app.tasks.state import (
    GLOBAL_TASK_STATE,
    request_batch_stop,
    task_queues,
    task_status,
)

logger = logging.getLogger(__name__)

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

    # 批量互斥（2026-11-02 审计 P2-15）：已有批量在跑/排队时拒绝新批量（此前可无限
    # 排队且排队即覆盖 current_task_id，/status 无参轮询从此指向 pending 新任务）
    if GLOBAL_TASK_STATE.get("is_processing"):
        raise HTTPException(
            status_code=409,
            detail="已有批量任务正在执行，请等待完成或先停止",
        )

    task_id = str(uuid.uuid4())
    # current_task_id 延迟到 executor 真正持锁启动时才写入（原版排队即覆盖运行中任务的指针）
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

@router.post("/stop/{task_id}")
async def stop_batch_task(task_id: str):
    """停止批量任务（2026-11-02 审计 P2-15）：置停止标志，批量循环每岗检查后优雅收尾。

    已完成/不存在的任务返回 404；受理后循环在当前岗位边界退出，已完成部分照常统计。
    """
    from app.tasks.state import task_status as _ts
    info = _ts.get(task_id)
    if not info or info.get("status") not in ("pending", "running"):
        raise HTTPException(status_code=404, detail="任务不存在或已结束")
    if not request_batch_stop(task_id):
        raise HTTPException(status_code=409, detail="该任务不是当前运行中的批量任务")
    return {"status": "stopping", "task_id": task_id, "message": "停止指令已受理，将在当前岗位边界退出"}


@router.get("/status")
def get_task_status(task_id: str | None = None):
    """短轮询接口：查询当前是否有后台任务正在执行，支持无参自动探活。

    background 字段聚合三类「系统被谁占用」信号，供前端横幅感知并发撞车风险：
    - activities: 定时投递等后台批量活动登记（此前对前端完全不可见）
    - pipeline:   全链路自动化运行态（定时侦察/手动全链路共用）
    - llm_gate:   LLM 闸门实时水位（并发槽/令牌/429 冷却窗）
    """
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

    try:
        from app.tasks.state import get_background_activities
        activities = get_background_activities()
    except Exception:
        activities = []
    try:
        from app.automation import pipeline_broadcast as pb
        pipeline_state = pb.get_current_pipeline()
    except Exception:
        pipeline_state = {"task_id": None, "running": False}
    try:
        from app.core.llm_gate import get_llm_gate
        gate_stats: dict[str, Any] = get_llm_gate().stats()
    except Exception:
        gate_stats = {}

    res["background"] = {
        "activities": activities,
        "pipeline": pipeline_state,
        "llm_gate": gate_stats,
    }
    return res

def _make_expired_stream(task_id: str):
    """expired 任务 SSE 生成器工厂（模块级供单测直驱；端点内部亦用此实现）。"""
    async def expired_stream():
        expired = json.dumps(
            {
                "type": "end",
                "reason": "task_expired",
                "message": f"任务 {task_id} 不存在或已过期（后端可能已重启）",
            },
            ensure_ascii=False,
        )
        yield f"data: {expired}\n\n"
        # 2026-11-05 重连风暴根治：不能直接 return 关流——浏览器 EventSource 规范
        # 对「流正常结束」的响应是自动重连（非客户端 close()），前端任一未处理
        # end 帧的消费者都会陷入 ~40s 周期的 expired 重连风暴（当日事故：旧任务
        # pipeline_794db003 每分钟 1.5 次命中本分支刷屏）。这里保持连接常驻 +
        # 心跳保活，把「过期任务」钉死为单次语义：帧已送达，连接不再产生任何
        # 新事件，客户端处理 end 帧后主动 close，未处理的也只会挂一条哑连接。
        yield ": heartbeat\n\n"
        while True:
            await asyncio.sleep(15)
            yield ": heartbeat\n\n"

    return expired_stream()


@router.get("/logs")
async def task_logs(task_id: str):
    if task_id not in task_queues:
        # G1（2026-10-31 事故）：后端重启会清空内存任务队列，前端仍持旧 task_id 重连时
        # EventSource 拿不到 404 状态码，只会按 onerror 无限重连。改为下发终态事件
        # （type=end + reason=task_expired）让前端既有「end 即收尾清理」逻辑立即生效。
        logger.warning("[SSE] 任务日志流请求命中过期任务: task_id=%s（队列已随重启清空），下发 task_expired 终态", task_id)
        return StreamingResponse(
            _make_expired_stream(task_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
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
