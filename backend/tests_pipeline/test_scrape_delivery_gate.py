"""抓取任务闸门（crawlers._run_*_task × platform_mutex）回归测试。

事故场景（2026-10-29）：投递进行中抓取抢同一浏览器。现在 _run_*_task 在拉起引擎前
先过 platform_mutex 闸门，投递在飞时限时等待，超时跳过本轮派发并向 SSE 队列广播
跳过原因 + 结束帧（前端不悬挂、续抓页码不污染）。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.api.routes.crawlers import (
    _platform_running_tasks,
    _push_scrape_skipped,
    _run_51job_task,
    _run_liepin_task,
    _run_zhilian_task,
    _SCRAPE_GATE_TIMEOUT_S,
)
from app.automation import platform_mutex
from app.tasks.state import task_queues


def setup_function(_):
    platform_mutex.reset_for_test()
    task_queues.clear()


def teardown_function(_):
    platform_mutex.reset_for_test()
    task_queues.clear()


def _drain(queue) -> list[str]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


async def test_zhilian_task_skipped_when_delivery_busy():
    """投递在飞 + 闸门拒绝 → 任务不入引擎、推 error 帧、登记与投递登记均不误清。

    关键回归点：run_dispatch_collect 派发前预写 _platform_running_tasks[platform]=task_id，
    跳过路径若不进 finally 清理，手动 /run 与 /dispatch 会永久 409（登记泄漏）。
    """
    assert await platform_mutex.acquire_delivery("zhilian", owner="rec_inflight") is not None
    task_id = "spider_zhilian_gatetest"
    task_queues[task_id] = asyncio.Queue()
    _platform_running_tasks["zhilian"] = task_id  # 模拟派发方的预写登记

    async def _deny(*a, **k):
        return False

    # _run_zhilian_task 内部 `from app.automation import platform_mutex` 取的是同一模块对象，
    # patch 模块属性即可命中闸门调用
    with patch("app.automation.platform_mutex.acquire_scrape", side_effect=_deny):
        await _run_zhilian_task(task_id, "北京", "AI产品", "15-20K", 1, 3)

    frames = _drain(task_queues[task_id])
    assert any('"type": "error"' in f and "正在投递中" in f for f in frames), f"应广播跳过原因: {frames}"
    assert frames[-1].strip() == 'data: {"type": "end"}', "跳过路径必须补发结束帧防前端悬挂"
    assert not platform_mutex.is_scrape_busy("zhilian"), "闸门未放行不得残留抓取登记"
    assert _platform_running_tasks.get("zhilian") != task_id, "跳过路径必须清理派发方预写的登记"
    assert platform_mutex.is_delivery_busy("zhilian") is True, "在飞投递登记不被误清"


async def test_zhilian_task_gate_released_after_engine_path():
    """闸门放行路径：抓取引擎以假身代替（绝不真拉浏览器），验证结束后释放抓取登记"""
    task_id = "spider_zhilian_gatetest2"
    task_queues[task_id] = asyncio.Queue()

    # 与 _run_zhilian_task 运行时一致：引擎模块位于 zhilian_scraper/ 子目录，先补 sys.path
    zhilian_dir = str(_BACKEND_DIR / "zhilian_scraper")
    if zhilian_dir not in sys.path:
        sys.path.insert(0, zhilian_dir)
    import zhilian_nl_controller

    async def _fake_scrape(**kwargs):
        return None

    async def _allow(*a, **k):
        return True

    with patch("app.automation.platform_mutex.acquire_scrape", side_effect=_allow), \
         patch.object(zhilian_nl_controller, "process_zhilian_scraping_request", side_effect=_fake_scrape):
        with patch("app.automation.platform_mutex.release_scrape") as mock_rel:
            await _run_zhilian_task(task_id, "北京", "AI产品", "15-20K", 1, 3)

    assert mock_rel.called, "finally 必须释放抓取登记"
    assert not platform_mutex.is_scrape_busy("zhilian")


async def test_push_scrape_skipped_no_queue_no_crash():
    """队列不存在（理论上不应发生）时不得抛异常击穿任务收尾"""
    await _push_scrape_skipped("no_such_task", "智联招聘", " 正在投递中")


async def _assert_deny_path(task_id, platform_key, runner, cn):
    """闸门拒绝路径通用断言：不残留登记、清理派发预写、不推进续抓页码、广播原因 + 结束帧"""
    assert await platform_mutex.acquire_delivery(platform_key, owner="rec_inflight") is not None
    task_queues[task_id] = asyncio.Queue()
    _platform_running_tasks[platform_key] = task_id

    async def _deny(*a, **k):
        return False

    with patch("app.automation.platform_mutex.acquire_scrape", side_effect=_deny), \
         patch("app.session.scrape_sessions.update_last_page") as mock_ulp:
        await runner()

    frames = _drain(task_queues[task_id])
    assert any('"type": "error"' in f and "正在投递中" in f for f in frames), f"应广播跳过原因: {frames}"
    assert frames[-1].strip() == 'data: {"type": "end"}', "跳过路径必须补发结束帧防前端悬挂"
    assert not platform_mutex.is_scrape_busy(platform_key)
    assert _platform_running_tasks.get(platform_key) != task_id, "跳过路径必须清理派发方预写的登记"
    assert mock_ulp.call_count == 0, "拒绝路径不得回写续抓页码（非51job平台回写start_page会永久漏一页）"


async def test_liepin_task_skipped_when_delivery_busy():
    await _assert_deny_path(
        "spider_liepin_gatetest", "liepin",
        lambda: _run_liepin_task("spider_liepin_gatetest", "北京", "AI产品", "15-20K", 1, 3),
        "猎聘",
    )


async def test_51job_task_skipped_when_delivery_busy():
    await _assert_deny_path(
        "spider_51job_gatetest", "51job",
        lambda: _run_51job_task("spider_51job_gatetest", "北京", "AI产品", "15-20K", 1, 3),
        "51job",
    )


def test_scrape_gate_timeout_constant_is_short_for_manual_path():
    """闸门内等待窗取短值（2 分钟）：手动 /run 点击不该静默干等 10 分钟"""
    assert _SCRAPE_GATE_TIMEOUT_S <= 180
