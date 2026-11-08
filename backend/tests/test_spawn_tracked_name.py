"""_spawn_tracked(name=) 回归（2026-11-03 清洗泵整轮未启动事故）。

事故链：8c80c0d9 把泵启动从 asyncio.create_task 换成 _spawn_tracked 包装时，
调用侧遗留的 name= kwarg 使其每次抛 TypeError，被抓取启动回调的「不阻断」
try/except 静默吞掉——0.4.2 流式清洗泵整轮失效，退化回抓完再批量清洗。
本测试锁定：name kwarg 必须被接受并落到任务名上（排查即靠任务名在日志失位发现）。
"""
import asyncio

import pytest

from app.automation.pipeline_orchestrator import _BACKGROUND_TASKS, _spawn_tracked


@pytest.mark.asyncio
async def test_spawn_tracked_accepts_name_kwarg():
    done = asyncio.Event()
    release = asyncio.Event()

    async def _work():
        done.set()
        # 外审 R2-P1（C3）：必须真正"存活一段时间"——_work 立即结束的话，
        # 3.10/3.11 下 discard 回调会先于主协程恢复执行，断言必挂
        await release.wait()

    task = _spawn_tracked(_work(), name="cleaning_pump_test_1234")
    try:
        assert task.get_name() == "cleaning_pump_test_1234"
        await asyncio.wait_for(done.wait(), timeout=5)
        assert task in _BACKGROUND_TASKS  # 存活期间在强引用集合里
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_spawn_tracked_without_name_still_works():
    async def _noop():
        pass

    task = _spawn_tracked(_noop())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
    finally:
        await task
