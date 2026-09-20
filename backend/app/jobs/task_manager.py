
import asyncio


class TaskEventManager:
    def __init__(self):
        # 建立 task_id 到 asyncio.Queue 的映射，用于 SSE 消息分发
        self._listeners: dict[str, asyncio.Queue] = {}

    def register_task(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners[task_id] = queue
        return queue

    def get_queue(self, task_id: str) -> asyncio.Queue:
        return self._listeners.get(task_id)

    def remove_task(self, task_id: str):
        if task_id in self._listeners:
            del self._listeners[task_id]

# 初始化全局单例
task_event_manager = TaskEventManager()
