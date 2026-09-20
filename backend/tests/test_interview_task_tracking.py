import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.websockets import WebSocketState


@pytest.mark.asyncio
async def test_speech_task_tracking_and_cancel():
    """测试面试官后台 TTS 协程追踪机制以及取消逻辑"""
    active_speech_tasks = set()

    def spawn_speech_task(coro):
        task = asyncio.create_task(coro)
        active_speech_tasks.add(task)
        task.add_done_callback(active_speech_tasks.discard)
        return task

    def cancel_all_speech_tasks():
        canceled_count = 0
        for t in list(active_speech_tasks):
            if not t.done():
                t.cancel()
                canceled_count += 1
        active_speech_tasks.clear()
        return canceled_count

    # 模拟一个长时间挂起的 TTS 协程
    async def dummy_tts():
        await asyncio.sleep(10)

    # 派发两个任务
    t1 = spawn_speech_task(dummy_tts())
    t2 = spawn_speech_task(dummy_tts())

    assert len(active_speech_tasks) == 2
    assert not t1.done()
    assert not t2.done()

    # 模拟收到 interrupt 抢话打断或断开连接
    canceled = cancel_all_speech_tasks()
    assert canceled == 2
    assert len(active_speech_tasks) == 0

    # 确保任务确实被取消
    await asyncio.sleep(0.01)
    assert t1.cancelled()
    assert t2.cancelled()
