"""转发协程误判 / 孤儿清理回归测试（超抓事故根因修复）。

背景：旧版转发协程把 120s 空闲超时当「子任务已结束」，而平台爬虫翻页防风控
休眠（180~400s）期间不发任何事件，被误判结束 → 编排层并发二次派发 → 超抓超 limit。

覆盖：
- 子任务存活时，长静默由心跳保活，不误判；heartbeat 不转发进主流程
- 子任务真实结束后排空队列残留事件再退出（task_done）
- 极端 hang 走兜底超时退出（fallback），主流程不永久挂起
- controller 翻页大休眠会调心跳钩子报平安
- 清孤儿 _reap_orphan_scrapers 对未结束任务拉急刹且限时返回
- 编排层派发前有「平台无未结束任务」防御（静态断言）
"""
import asyncio
import importlib
import json
import sys

import pytest

import app.api.routes.crawlers as crawlers
from app.tasks.state import task_queues


def _load_controller(platform: str):
    """以与生产相同的 sys.path hack 载入控制器（sys.modules 同一对象，flag 互通）。"""
    subdir, mod_name = crawlers._PLATFORM_STOP_MODULES[platform]
    mod_dir = f"{crawlers.PROJECT_ROOT}/{subdir}"
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)
    return importlib.import_module(mod_name)


def _put(queue_name: str, payload: dict):
    task_queues[queue_name].put_nowait(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")


def _drain(queue_name: str) -> list:
    q = task_queues[queue_name]
    out = []
    while not q.empty():
        out.append(json.loads(q.get_nowait().replace("data: ", "", 1)))
    return out


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    task_queues.clear()
    crawlers.running_platform_tasks.clear()
    for p in ("boss", "liepin", "51job", "zhilian"):
        mod = _load_controller(p)
        mod.set_stop_flag(False)
        if hasattr(mod, "set_heartbeat_hook"):
            mod.set_heartbeat_hook(None)


def test_heartbeat_keeps_forwarder_alive_and_not_forwarded(monkeypatch):
    """核心回归：子任务存活时超过兜底阈值的静默由心跳保活，转发协程等到 complete 才退出；
    heartbeat 不转发进主流程。"""
    monkeypatch.setattr(crawlers, "_FORWARD_FALLBACK_TIMEOUT_S", 0.5)

    async def scenario():
        task_queues["sub"] = asyncio.Queue()
        task_queues["master"] = asyncio.Queue()

        async def fake_sub():
            _put("sub", {"type": "progress", "total_inserted": 1})
            for _ in range(6):  # 6*0.2=1.2s 静默，超过兜底 0.5s，靠心跳保活
                await asyncio.sleep(0.2)
                _put("sub", {"type": "heartbeat"})
            _put("sub", {"type": "complete"})

        sub_task = asyncio.create_task(fake_sub())
        reason = await crawlers._forward_subtask_events("sub", "51job", "master", sub_task=sub_task)
        await sub_task
        return reason

    reason = asyncio.run(scenario())
    assert reason == "complete"
    events = _drain("master")
    assert [e["type"] for e in events] == ["progress"]  # 心跳不进主流程
    assert events[0]["platform"] == "51job"
    assert events[0]["stage"] == "scraping"


def test_forwarder_drains_queue_after_task_done(monkeypatch):
    """子任务真实结束（即便没发结束帧）：排空队列残留事件后退出。"""
    monkeypatch.setattr(crawlers, "_FORWARD_FALLBACK_TIMEOUT_S", 5.0)

    async def scenario():
        task_queues["sub"] = asyncio.Queue()
        task_queues["master"] = asyncio.Queue()

        async def fake_sub():
            _put("sub", {"type": "progress", "total_inserted": 1})
            _put("sub", {"type": "progress", "total_inserted": 2})

        sub_task = asyncio.create_task(fake_sub())
        return await crawlers._forward_subtask_events("sub", "boss", "master", sub_task=sub_task)

    reason = asyncio.run(scenario())
    assert reason == "task_done"
    assert [e["total_inserted"] for e in _drain("master")] == [1, 2]


def test_forwarder_fallback_on_silent_hang(monkeypatch):
    """极端 hang：兜底超时退出，主流程不永久挂起（孤儿清理会接管急刹）。"""
    monkeypatch.setattr(crawlers, "_FORWARD_FALLBACK_TIMEOUT_S", 0.3)

    async def scenario():
        task_queues["sub"] = asyncio.Queue()
        task_queues["master"] = asyncio.Queue()

        async def fake_hang():
            await asyncio.sleep(5)

        sub_task = asyncio.create_task(fake_hang())
        crawlers._track_platform_task("liepin", sub_task)
        reason = await crawlers._forward_subtask_events("sub", "liepin", "master", sub_task=sub_task)
        sub_task.cancel()
        return reason

    reason = asyncio.run(scenario())
    assert reason == "fallback"
    assert _drain("master") == []


def test_countdown_sleep_pings_heartbeat_hook():
    """controller 翻页大休眠期间会调心跳钩子报平安。"""
    for platform in ("51job", "boss", "liepin"):
        mod = _load_controller(platform)
        calls = []
        mod.set_heartbeat_hook(lambda: calls.append(1))
        try:
            mod.countdown_sleep(2)
        finally:
            mod.set_heartbeat_hook(None)
        assert calls, f"{platform} countdown_sleep 未触发心跳钩子"


def test_reap_orphan_scrapers_pulls_stop_flag():
    """清孤儿：对未结束任务拉急刹且限时返回（不 hang）。"""
    import app.automation.full_auto as fa

    async def scenario():
        async def fake():
            await asyncio.sleep(5)

        t = asyncio.create_task(fake())
        crawlers._track_platform_task("51job", t)
        await fa._reap_orphan_scrapers("pipeline_reap_test", timeout=0.2)
        alive_after = not t.done()
        t.cancel()
        return alive_after

    alive_after = asyncio.run(scenario())
    assert alive_after  # fake 任务不观察 flag，超时后仍存活，但 reap 必须限时返回
    assert _load_controller("51job").GLOBAL_STOP_FLAG is True  # 急刹确实拉下


def test_full_auto_has_double_dispatch_guard():
    """编排层静态断言：派发前检查平台无未结束任务 + 收尾清孤儿在位。"""
    import app.automation.full_auto as fa
    src = open(fa.__file__, encoding="utf-8").read()
    assert "running_platform_tasks" in src
    assert "_reap_orphan_scrapers" in src
    assert "本轮放弃新派发以避免并发超抓" in src
