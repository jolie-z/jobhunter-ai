"""
Agent 映射异步任务引擎 (app/api/resume_editor/agent_map_tasks.py)

Phase 4（任务书 2026-10-17 §Phase 4）：映射异步化——进度 / 取消 / 失败态闭环。
1. 独立映射线程池（GLM-P2-1）：worker 由 get_agent_map_executor() 承载
   （AGENT_MAP_EXECUTOR_WORKERS，环境变量 > settings.json > 默认 4），与 llm-gate
   闸门线程池物理隔离，互不挤占。
2. ContextVar 钩子契约全链路闭环（GLM3-P1-1）：平台循环内注入 on_retry / cancel_check，
   底层 govern_sync_call 自动感知——重试退避推 retry_wait 事件、取消旗在重试间生效，
   均无需侵入 map_platform 业务签名。
3. SSE 事件序列：platform_start / platform_done{platform,success,message,warnings,degraded}
   （失败载荷闭环：前端直接吃数据渲染失败态与退避文案，不依赖磁盘刷新）/
   retry_wait{platform,seconds,attempt} / complete{reports,master,cancelled}。
4. 协作取消：cancel 只立旗不杀线程，由 _cancel_check 在重试间与平台边界生效。
5. 任务台账延迟 5 分钟清理（沿用 app/tasks/state.py schedule_task_cleanup 模式），
   SSE 断开绝不杀任务，浏览器重连可回放历史事件。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import StreamingResponse

from app.core.llm_gate import DaemonThreadPoolExecutor
from app.core.llm_governed import current_llm_context
from app.core.llm_retry import TaskCancelledException
from resume_editor import agent_mapper as am

from .common import DATA_DIR

logger = logging.getLogger("agent_map_tasks")

# 任务台账保留窗口：结束后延迟清理，给 SSE 重连/进度查看留时间（与爬虫任务同口径）
TASK_TTL_SECONDS = 300
_MAX_EVENT_HISTORY = 200


def _to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return bool(v)


def is_agent_map_async_enabled() -> bool:
    """映射异步化总开关（熔断/回滚类）：settings.json 热控 > 环境变量 > 默认 True。"""
    try:
        from common.config import get_setting
        val = get_setting("AGENT_MAP_ASYNC_ENABLED")
        if val is not None:
            return _to_bool(val)
    except Exception as e:
        logger.warning("[agent_map_tasks] 读取 AGENT_MAP_ASYNC_ENABLED 失败: %s", e)
    env_val = os.getenv("AGENT_MAP_ASYNC_ENABLED")
    if env_val is not None:
        return _to_bool(env_val)
    return True


def _read_workers() -> int:
    """容量参数：环境变量 > settings.json > 默认 4（规范 §二.4 双轨）。"""
    raw = os.getenv("AGENT_MAP_EXECUTOR_WORKERS")
    if raw is None:
        try:
            from common.config import get_setting
            raw = get_setting("AGENT_MAP_EXECUTOR_WORKERS")
        except Exception:
            raw = None
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 4


_agent_map_executor: ThreadPoolExecutor | None = None
_agent_map_executor_lock = threading.Lock()


def get_agent_map_executor() -> ThreadPoolExecutor:
    """独立 agent-map 线程池（守护线程）：仅服务映射 worker，与 gate._executor 物理隔离。"""
    global _agent_map_executor
    if _agent_map_executor is None:
        with _agent_map_executor_lock:
            if _agent_map_executor is None:
                _agent_map_executor = DaemonThreadPoolExecutor(
                    max_workers=_read_workers(), thread_name_prefix="agent-map"
                )
    return _agent_map_executor


@dataclass
class AgentMapTask:
    task_id: str
    platforms: list[str]
    master: dict
    selected_modules: list[str] | None
    record_id: str | None
    loop: asyncio.AbstractEventLoop
    created_at: float = field(default_factory=time.time)
    status: str = "running"  # running | completed | cancelled | error
    cancel_requested: bool = False
    reports: dict = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    subscribers: set = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


_AGENT_MAP_TASKS: dict[str, AgentMapTask] = {}


def _emit(task: AgentMapTask, payload: dict) -> None:
    """线程安全推送 SSE 事件：历史留档（支持重连回放）+ 定向分发到订阅队列。"""
    line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    with task.lock:
        task.events.append(line)
        if len(task.events) > _MAX_EVENT_HISTORY:
            del task.events[: len(task.events) - _MAX_EVENT_HISTORY]
        subs = list(task.subscribers)
    for q in subs:
        try:
            task.loop.call_soon_threadsafe(q.put_nowait, line)
        except RuntimeError:
            pass  # 事件循环已关闭（进程收尾/测试结束），事件仍留档于历史


def _is_degraded(report: dict) -> bool:
    """是否发生了「降级为确定性规则映射」（Phase 3 兜底标记，前端渲染橙色警示态）。"""
    return any("降级" in str(w) for w in (report.get("warnings") or []))


def _finish(task: AgentMapTask, *, cancelled: bool, error: str | None = None) -> None:
    ok_all = all(
        isinstance(task.reports.get(p), dict) and task.reports[p].get("success")
        for p in task.platforms
    )
    payload: dict[str, Any] = {
        "type": "complete",
        "cancelled": cancelled,
        "success": bool(ok_all and not cancelled and error is None),
        "master": {
            "source": task.master.get("source"),
            "char_count": task.master.get("char_count"),
            "record_id": task.master.get("record_id"),
            "name": task.master.get("name"),
            "message": task.master.get("message"),
        },
        "reports": task.reports,
    }
    if error:
        payload["error"] = error
    task.status = "cancelled" if cancelled else ("error" if error else "completed")
    _emit(task, payload)
    _schedule_cleanup(task)


def _schedule_cleanup(task: AgentMapTask) -> None:
    """结束后延迟清理台账；loop 已关闭则立即清理（进程收尾/测试环境）。"""

    def _cleanup(task_id: str) -> None:
        _AGENT_MAP_TASKS.pop(task_id, None)

    try:
        task.loop.call_soon_threadsafe(
            lambda: task.loop.call_later(TASK_TTL_SECONDS, _cleanup, task.task_id)
        )
    except RuntimeError:
        _cleanup(task.task_id)


def missing_fields_report(platform: str, message: str | None) -> dict:
    """平台字段数据缺失/损坏时的统一失败报告（同步与异步路径共用）。"""
    return {"success": False, "platform": platform, "fields": [], "unfilled": [], "warnings": [], "message": message}


def load_fields_data(platform: str) -> tuple[dict | None, str | None]:
    """读取平台字段数据；返回 (data, None) 或 (None, 失败原因)。同步与异步路径共用。"""
    file_path = os.path.join(DATA_DIR, f"{platform}_fields.json")
    if not os.path.exists(file_path):
        return None, f"{platform} 字段数据不存在，请先采集"
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"{platform} 字段数据读取失败: {e}"


def _make_govern_hooks(task: AgentMapTask, platform: str) -> tuple:
    """
    构造当前平台的治理钩子（GLM3-P1-1 契约：on_retry / cancel_check）。
    工厂函数显式绑定 platform，杜绝循环内闭包晚绑定（B023）。
    """
    def _on_retry(_caller: str, attempt: int, delay: float, _ctx: dict) -> None:
        _emit(task, {
            "type": "retry_wait",
            "platform": platform,
            "seconds": round(float(delay), 1),
            "attempt": attempt,
        })

    def _cancel_check(_ctx: dict) -> bool:
        return task.cancel_requested

    return _on_retry, _cancel_check


def _run_mapping_task(task: AgentMapTask) -> None:
    """映射 worker（agent-map 线程池内执行）：串行平台循环 + ContextVar 钩子注入。"""
    _emit(task, {"type": "started", "platforms": list(task.platforms), "task_id": task.task_id})
    try:
        for platform in task.platforms:
            # 平台边界协作取消：立旗后未开跑的平台直接跳过
            if task.cancel_requested:
                _finish(task, cancelled=True)
                return

            _emit(task, {"type": "platform_start", "platform": platform})
            fields_data, err_msg = load_fields_data(platform)
            if fields_data is None:
                report = missing_fields_report(platform, err_msg)
            else:
                # ContextVar 钩子契约（GLM3-P1-1）：底层 govern_sync_call 自动感知，
                # 重试退避推 retry_wait 事件；取消旗在重试间由 TaskCancelledException 上抛
                on_retry, cancel_check = _make_govern_hooks(task, platform)
                token = current_llm_context.set({
                    "platform": platform,
                    "task_id": task.task_id,
                    "on_retry": on_retry,
                    "cancel_check": cancel_check,
                })
                try:
                    report = am.map_platform(
                        platform, fields_data, task.master, selected_modules=task.selected_modules
                    )
                except TaskCancelledException:
                    _finish(task, cancelled=True)
                    return
                finally:
                    current_llm_context.reset(token)
                if report.get("success"):
                    try:
                        am.save_report(platform, report, selected_modules=task.selected_modules)
                    except Exception as e:
                        logger.warning("[agent_map_tasks] %s 报告落盘失败（不影响内存报告）: %s", platform, e)

            task.reports[platform] = report
            _emit(task, {
                "type": "platform_done",
                "platform": platform,
                "success": bool(report.get("success")),
                "message": str(report.get("message") or "")[:200],
                "warnings": report.get("warnings") or [],
                "degraded": _is_degraded(report),
            })

        try:
            am.set_selected_master_record(task.record_id)
        except Exception as e:
            logger.warning("[agent_map_tasks] 主简历选择记忆失败: %s", e)
        # 最后一个（或唯一）平台执行期间收到取消：循环已自然结束，仍须以 cancelled 终态收尾
        _finish(task, cancelled=bool(task.cancel_requested))
    except Exception as e:
        logger.exception("[agent_map_tasks] 映射任务异常终止")
        _finish(task, cancelled=False, error=str(e)[:300])


async def start_mapping_task(
    platforms: list[str],
    master: dict,
    selected_modules: list[str] | None,
    record_id: str | None,
) -> str:
    """创建映射任务并提交独立线程池，秒回 task_id。"""
    task_id = str(uuid.uuid4())
    task = AgentMapTask(
        task_id=task_id,
        platforms=list(platforms),
        master=master,
        selected_modules=selected_modules,
        record_id=record_id,
        loop=asyncio.get_running_loop(),
    )
    _AGENT_MAP_TASKS[task_id] = task
    get_agent_map_executor().submit(_run_mapping_task, task)
    return task_id


def get_mapping_task(task_id: str) -> AgentMapTask | None:
    return _AGENT_MAP_TASKS.get(task_id)


def cancel_mapping_task(task_id: str) -> tuple[bool, str]:
    """协作取消：只立旗不杀线程，当前平台 LLM 调用照常收尾后停止。"""
    task = _AGENT_MAP_TASKS.get(task_id)
    if task is None:
        return False, "任务不存在或已过期"
    if task.status != "running":
        return True, f"任务已结束（{task.status}），无需取消"
    with task.lock:
        task.cancel_requested = True
    _emit(task, {"type": "cancel_requested", "task_id": task_id})
    return True, "已请求取消：将在当前请求收尾或平台边界生效"


async def stream_mapping_events(task_id: str):
    """SSE 事件流生成器：先回放历史（支持断线重连），再实时分发，2s 心跳保活。"""
    task = _AGENT_MAP_TASKS.get(task_id)
    if task is None:
        raise KeyError(task_id)

    queue: asyncio.Queue = asyncio.Queue()
    with task.lock:
        for line in task.events:
            queue.put_nowait(line)
        task.subscribers.add(queue)

    def _terminal(line: str) -> bool:
        # 唯一终态事件：complete（worker 异常亦封装为 complete + error 字段）；标记匹配与 app/tasks/router.py 同款
        return '"type": "complete"' in line or '"type":"complete"' in line

    try:
        while True:
            try:
                line = await asyncio.wait_for(queue.get(), timeout=2.0)
                yield line
                if _terminal(line):
                    break
            except asyncio.TimeoutError:
                yield f'data: {{"type": "heartbeat", "timestamp": "{time.strftime("%Y-%m-%dT%H:%M:%S")}"}}\n\n'
    except asyncio.CancelledError:
        # 客户端断开：只退订不杀任务（任务照常跑完，重连可回放）
        pass
    finally:
        with task.lock:
            task.subscribers.discard(queue)


def mapping_stream_response(task_id: str) -> StreamingResponse:
    """构造标准 SSE StreamingResponse（与任务书事件序列一致）。"""
    return StreamingResponse(
        stream_mapping_events(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
