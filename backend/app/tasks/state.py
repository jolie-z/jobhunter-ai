import asyncio
from datetime import datetime
from typing import Any

GLOBAL_TASK_STATE: dict[str, Any] = {
    "is_processing": False,
    "current_task_id": None,
    "last_completed_task_id": None,
}

task_status: dict[str, Any] = {}
global_task_lock = asyncio.Lock()

# 批量任务停止标志（2026-11-02 审计 P2-15）：executor/wave 批量链此前不查任何终止
# 状态，一经启动只能等跑完（期间阻塞所有后续批量）。BATCH_STOP_REQUESTED 由 stop
# 端点置位、批量循环每岗检查；置位同时记录目标 task_id，防止误停后续新任务
BATCH_STOP_REQUESTED: dict[str, Any] = {"requested": False, "task_id": None}


def request_batch_stop(task_id: str) -> bool:
    """请求停止批量任务（CR-B3-R1 修正；CR-B3-R2-P2 合并双分支）：运行中校验
    current_task_id，pending（已建队列、尚未持锁）直接受理——executor 启动入口
    检查标志拒绝启动。两态任一命中即置位。"""
    is_running = GLOBAL_TASK_STATE.get("current_task_id") == task_id
    is_pending = (task_status.get(task_id) or {}).get("status") == "pending"
    if not (is_running or is_pending):
        return False
    BATCH_STOP_REQUESTED["requested"] = True
    BATCH_STOP_REQUESTED["task_id"] = task_id
    return True


def is_batch_stop_requested(task_id: str) -> bool:
    return bool(BATCH_STOP_REQUESTED.get("requested")) and BATCH_STOP_REQUESTED.get("task_id") == task_id


def clear_batch_stop() -> None:
    BATCH_STOP_REQUESTED["requested"] = False
    BATCH_STOP_REQUESTED["task_id"] = None

# 后台定时任务活动登记：T2/T3 定时投递等后台批量此前对前端完全不可见（不建 SSE 队列、
# 不置 GLOBAL_TASK_STATE），用户在并发撞车时无从知晓系统正被谁占用。key 唯一对应一类
# 后台活动，running=False 即注销；/api/tasks/status 聚合后供前端横幅提示。
BACKGROUND_ACTIVITIES: dict[str, dict[str, Any]] = {}


def set_background_activity(key: str, running: bool, *, label: str = "", detail: str = "") -> None:
    """登记/更新/注销一条后台活动（线程安全仅指 dict 单操作，注册方自证串行调用）。"""
    if not running:
        BACKGROUND_ACTIVITIES.pop(key, None)
        return
    entry = BACKGROUND_ACTIVITIES.get(key) or {
        "key": key,
        "label": label or key,
        "started_at": datetime.now().isoformat(),
    }
    if label:
        entry["label"] = label
    if detail:
        entry["detail"] = detail
    BACKGROUND_ACTIVITIES[key] = entry


def get_background_activities() -> list[dict[str, Any]]:
    return [dict(v) for v in BACKGROUND_ACTIVITIES.values()]


class TaskChannel(asyncio.Queue):
    """广播型任务日志管道：
    1. 保持与 asyncio.Queue 完全相同的 API (put, put_nowait, get 等)，100% 兼容既有业务代码；
    2. 支持多连接同时订阅（Fan-Out）：多个浏览器标签页连接同一个任务时，各自分发全量消息，杜绝消息被单消费者截胡；
    3. 保留近期历史回放：新标签页连入或网络重连时，立刻回放最近消息，防止页面空白。
    """
    def __init__(self, maxsize: int = 0):
        super().__init__(maxsize=maxsize)
        self._subscribers: set[asyncio.Queue] = set()
        self._history: list[str] = []
        self._max_history = 50

    async def put(self, item: str):
        self._record(item)
        await super().put(item)
        for q in list(self._subscribers):
            try:
                await q.put(item)
            except Exception:
                pass

    def put_nowait(self, item: str):
        self._record(item)
        super().put_nowait(item)
        for q in list(self._subscribers):
            try:
                q.put_nowait(item)
            except Exception:
                pass

    def _record(self, item: str):
        self._history.append(item)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    def subscribe(self, sub_queue: asyncio.Queue | None = None) -> asyncio.Queue:
        """为每一个 SSE 连接创建专属的订阅者队列（支持传入已有队列，避免对象分家）"""
        sub = sub_queue if sub_queue is not None else asyncio.Queue()
        # 回放近期历史，保证新打开的标签页立刻呈现最新进度
        for item in self._history:
            sub.put_nowait(item)
        self._subscribers.add(sub)
        return sub

    def clear_history(self) -> None:
        """清空回放历史（「继续任务」受理时调用）。

        阻塞轮的 stage blocked / end(outcome=blocked) 帧绝不能回放给重连的前端：
        前端 SSE 对 end 帧一律断连，回放的旧 end 会把刚切回 running 的连接立刻掐断，
        后续恢复事件全部丢失，形成「后端已恢复、前端永久暂停」死锁（2026-11-03 事故）。"""
        self._history.clear()

    def unsubscribe(self, sub: asyncio.Queue):
        self._subscribers.discard(sub)


class TaskQueueDict(dict):
    """确保所有存入 task_queues 的队列自动升级为 TaskChannel 广播通道"""
    def __setitem__(self, key, value):
        if isinstance(value, TaskChannel):
            super().__setitem__(key, value)
        elif isinstance(value, asyncio.Queue):
            channel = TaskChannel()
            channel.subscribe(value)
            super().__setitem__(key, channel)
        else:
            super().__setitem__(key, value)


task_queues: dict[str, Any] = TaskQueueDict()


def schedule_task_cleanup(task_id: str, delay_seconds: int = 300):
    """任务结束延迟清理内存台账：task_status/task_queues 只增不减，长期运行会缓慢泄漏。

    延迟 5 分钟是为了给前端 SSE 重连/进度查看留窗口；过期后查询会得到既有的
    「任务不存在或已过期」404 口径。供所有爬虫与清洗任务在 finally 块中调用。
    """
    def _cleanup():
        task_status.pop(task_id, None)
        task_queues.pop(task_id, None)

    try:
        asyncio.get_running_loop().call_later(delay_seconds, _cleanup)
    except RuntimeError:
        pass  # 无运行中的事件循环时跳过（正常请求路径不会发生）
