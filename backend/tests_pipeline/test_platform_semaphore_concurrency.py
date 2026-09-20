"""
D3 并发守卫回归测试：PlatformSemaphore 平台级互斥
==================================================
验证投递引擎的并发护栏：
1. 同平台并发请求互斥（第二请求必须等待）
2. 超时强制解锁（卡死请求不阻塞后续投递）
3. 不同平台互不干扰
"""
import asyncio
import time

import pytest

from app.automation.platform_semaphore import (
    DeliveryTimeoutError,
    PlatformSemaphore,
)


def test_same_platform_requests_are_serialized():
    """同平台两个并发请求：必须串行执行，第二请求等待第一请求释放锁"""
    sem = PlatformSemaphore()
    order = []

    async def work(tag: str, hold: float):
        async with sem.acquire_with_timeout("boss", timeout_seconds=10):
            order.append(f"{tag}:start")
            await asyncio.sleep(hold)
            order.append(f"{tag}:end")

    async def run():
        await asyncio.gather(work("A", 0.3), work("B", 0.1))

    asyncio.run(run())
    # 串行：A 完整执行完 B 才开始（或反过来），绝无交错
    assert order[0].endswith("start") and order[1].endswith("end"), f"出现并发交错: {order}"
    assert order[2] == "B:start" and order[3] == "B:end", f"执行顺序异常: {order}"


def test_stuck_holder_does_not_block_forever():
    """持锁方卡死：等待方超时收到 DeliveryTimeoutError，且锁被强制释放可复用"""
    sem = PlatformSemaphore()

    async def run():
        # 1. 持锁方持有 30s（模拟卡死）
        ctx = sem.acquire_with_timeout("51job", timeout_seconds=30)
        await ctx.__aenter__()

        # 2. 等待方 1s 超时
        got_timeout = False
        try:
            async with sem.acquire_with_timeout("51job", timeout_seconds=1):
                pass
        except DeliveryTimeoutError:
            got_timeout = True
        assert got_timeout, "等待方未触发超时异常"

        # 3. 超时后锁被强制释放，第三个请求可立即获得
        acquired_quickly = False
        try:
            async with asyncio.timeout(2):
                async with sem.acquire_with_timeout("51job", timeout_seconds=1):
                    acquired_quickly = True
        except (DeliveryTimeoutError, asyncio.TimeoutError):
            pass
        assert acquired_quickly, "强制解锁后新请求仍拿不到锁"

        # 清理：释放最初持锁方（超时解锁已把内部计数推高，直接退出）
        try:
            await ctx.__aexit__(None, None, None)
        except Exception:
            pass

    asyncio.run(run())


def test_platforms_are_isolated():
    """不同平台互不干扰：boss 被锁住时 zhilian 可立即获取"""
    sem = PlatformSemaphore()

    async def run():
        async with sem.acquire_with_timeout("boss", timeout_seconds=5):
            assert sem.is_locked("boss")
            assert "zhilian" in sem.get_unlocked_platforms()
            async with sem.acquire_with_timeout("zhilian", timeout_seconds=2):
                pass
        assert not sem.is_locked("boss")

    asyncio.run(run())
