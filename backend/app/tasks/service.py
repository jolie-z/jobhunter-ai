"""批量 AI 任务引擎（兼容薄壳）。

唯一实现在 app.tasks.executor.run_batch_ai_task；本模块只保留同名入口与
中央台账别名导出，供 chatops（app.api.routes.chatops / app.core.chatops_tools）
继续 import。历史上一度存在两套并行引擎（首页按钮走 executor，聊天助手走本
模块的内联实现），两者已漂移且需双处维护，2026-09 起合并：任务逻辑只改
executor，这里不再实现任何任务细节。
"""

import asyncio
import sys
from pathlib import Path

# Fix sys path to allow importing legacy modules（历史副作用：ai_agents 等顶层
# 模块依赖此路径设置，保留在模块顶部以保证导入顺序安全）
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR.parent))
sys.path.insert(0, str(BASE_DIR))

# 中央台账别名：chatops 以 `from app.tasks.service import task_status` 消费，
# 现在与 executor/全系统共用的 state.py 注册表是同一份（原先本模块私有字典
# 导致 chatops 写入的状态引擎读不到、引擎写的状态 chatops 查不到）
from app.tasks.executor import (  # noqa: E402
    run_batch_ai_task as _engine_run_batch_ai_task,
)
from app.tasks.state import GLOBAL_TASK_STATE, task_status  # noqa: E402, F401


async def run_batch_ai_task(
    task_id: str,
    task_type: str,
    job_ids: list[str],
    queue: asyncio.Queue,
    scheduled_at: str | None = None
):
    """兼容入口：委托唯一引擎 executor.run_batch_ai_task。

    引擎会从传入的 task_status 注册表读取本任务的台账（调用方需先注册，
    参照 app.api.routes.chatops 中 batch_task_status[task_id] = {...} 的用法），
    并尊重全局串行锁（与首页批量任务共用同一条队列，避免浏览器争抢）。
    """
    await _engine_run_batch_ai_task(task_id, task_type, job_ids, queue, scheduled_at)


# 兼容导出：历史上 send_sse_msg 曾被这里定义，外部若有零散引用不至于断
from app.tasks.executor import send_sse_msg  # noqa: F401,E402
