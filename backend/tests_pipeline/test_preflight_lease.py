"""preflight 短租约（platform_mutex.preflight_lease）回归测试（外审 round3 P1）。

背景：预检 DOM 登录判定（check_login_with_fallback 跨域时 page.get 导航）在
delivery_gate/scrape_gate 之外发生，"守卫检查通过 → 判定执行"之间存在 TOCTOU 窗，
在飞引擎可在此窗口登记开跑，被预检把标签页导航走（原猎聘症状的理论复现路径）。
修复：判定段套 preflight_lease——短暂持有本平台登记（秒级），对侧在飞登记使租约
等待超时 → 放弃导航直接判定。本文件验证租约的四种时序组合。
"""

import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pytest

from app.automation import platform_mutex


def setup_function(_):
    platform_mutex.reset_for_test()


def teardown_function(_):
    platform_mutex.reset_for_test()


async def test_lease_acquired_when_opposite_side_idle():
    """对侧无在飞：租约立即获得，判定段执行，退出后登记清零"""
    executed = False
    async with platform_mutex.preflight_lease("zhilian"):
        assert platform_mutex._state("zhilian")["preflight"] is not None, "租约期间应持有独立 preflight 槽"
        executed = True
    assert executed
    assert platform_mutex._state("zhilian")["preflight"] is None, "租约退出必须释放"
    assert platform_mutex.busy_snapshot() == {}


async def test_lease_skips_navigation_when_delivery_inflight():
    """核心场景：投递在飞，预检租约等待超时 → yield False，调用方放弃导航直接判定。

    超时前投递释放 → 租约仍可获得。用短 wait_timeout_s 压缩测试时长。
    """
    tok1 = await platform_mutex.acquire_delivery("zhilian", owner="rec_inflight")
    lease_results = []

    async def release_later():
        await asyncio.sleep(0.05)
        await platform_mutex.release_delivery("zhilian", owner="rec_inflight", token=tok1)
        return True

    async def run_lease():
        async with platform_mutex.preflight_lease("zhilian", wait_timeout_s=5) as ok:
            lease_results.append(ok)
            assert platform_mutex._state("zhilian")["preflight"] is not None

    released, _ = await asyncio.gather(release_later(), run_lease())
    assert released is True
    assert lease_results == [True], "投递释放后租约应被唤醒获得（引擎只多等，不误跳过）"


async def test_lease_gives_up_when_delivery_stays_busy():
    """对侧持续在飞：租约等待超时 yield False，调用方跳过导航；对侧登记不受影响"""
    tok2 = await platform_mutex.acquire_delivery("zhilian", owner="rec_inflight")
    lease_results = []

    async with platform_mutex.preflight_lease("zhilian", wait_timeout_s=0.05) as ok:
        lease_results.append(ok)

    assert lease_results == [False], "对侧持续在飞时租约应超时放弃"
    assert platform_mutex._state("zhilian")["preflight"] is None, "超时放弃不得残留租约登记"
    assert platform_mutex.is_delivery_busy("zhilian") is True, "放弃路径不得误清对侧登记"
    await platform_mutex.release_delivery("zhilian", owner="rec_inflight", token=tok2)


async def test_lease_deliver_kind_blocks_scrape_inflight():
    """投递逐岗预检的 deliver 类租约：抓取在飞时同样超时放弃导航"""
    tok3 = await platform_mutex.acquire_scrape("liepin", owner="spider_1")

    async with platform_mutex.preflight_lease("liepin", wait_timeout_s=0.05) as ok:
        assert ok is False

    assert platform_mutex.is_scrape_busy("liepin") is True, "超时放弃不得影响引擎抓取登记"
    await platform_mutex.release_scrape("liepin", owner="spider_1", token=tok3)


async def test_lease_unmanaged_platform_passthrough():
    """未纳管平台直通不登记"""
    async with platform_mutex.preflight_lease("xiaohongshu") as ok:
        assert ok is True
    assert platform_mutex.busy_snapshot() == {}


async def test_lease_releases_on_exception():
    """判定段抛异常租约也必须释放（CM finally 保证）"""
    with pytest.raises(RuntimeError):
        async with platform_mutex.preflight_lease("zhilian") as ok:
            assert ok is True
            raise RuntimeError("判定崩溃")
    assert not platform_mutex.is_scrape_busy("zhilian")


def test_all_preflight_navigation_wrapped_in_lease():
    """结构断言（外审 round3-P1 验证要求）：preflight.py 中所有会导航的
    check_login_with_fallback 调用必须都位于 preflight_lease 上下文内——
    用源码顺序检查：每个裸调用点与其前最近的 lease 行必须配对出现。"""
    import inspect

    from app.session import preflight

    src = inspect.getsource(preflight)
    lines = src.splitlines()
    call_idx = [i for i, l in enumerate(lines)
                if "check_login_with_fallback, config" in l]
    assert call_idx, "未找到 check_login_with_fallback 调用点（源码结构变了？）"
    for i in call_idx:
        window = "\n".join(lines[max(0, i - 12):i])
        assert "preflight_lease" in window, (
            f"preflight.py 第 {i + 1} 行附近的 check_login_with_fallback 未包在 preflight_lease 内：\n{window}")


async def test_engine_slot_not_clobbered_by_lease():
    """round4-P1-2 核心回归：引擎持 scrape 槽时，预检租约（独立 preflight 槽）超时放弃，
    不得覆盖引擎登记、不得令对侧投递闸门提前放行"""
    tok4 = await platform_mutex.acquire_scrape("zhilian", owner="engine-task")
    lease_results = []

    async with platform_mutex.preflight_lease("zhilian", wait_timeout_s=0.05) as ok:
        lease_results.append(ok)

    assert lease_results == [False], "引擎 scrape 槽被占时预检租约必须超时放弃"
    assert platform_mutex._state("zhilian")["scrape"] == tok4, "引擎登记不得被覆盖"
    assert await platform_mutex.acquire_delivery("zhilian", owner="rec1", timeout_s=0.05) is None, \
        "投递闸门必须仍被引擎阻塞（预检未产生任何放行副作用）"

    await platform_mutex.release_scrape("zhilian", owner="engine-task", token=tok4)
async def test_lease_and_lease_mutually_exclusive():
    """两个 preflight 租约同平台互斥（阻塞矩阵含 preflight 自身）"""
    async with platform_mutex.preflight_lease("zhilian", wait_timeout_s=5) as first:
        assert first is True
        async with platform_mutex.preflight_lease("zhilian", wait_timeout_s=0.05) as second:
            assert second is False, "同平台第二个预检租约应等待超时放弃"


async def test_engine_waits_for_preflight_lease():
    """反向：预检租约持有期间，引擎闸门等待（最多租约剩余秒级窗口），租约释放后获得"""
    import contextlib

    lease_held = asyncio.Event()
    gate_results = []

    async def hold_lease():
        async with platform_mutex.preflight_lease("zhilian", wait_timeout_s=1) as ok:
            lease_held.set()
            await asyncio.sleep(0.1)
            return ok

    async def run_gate():
        await lease_held.wait()
        ok = await platform_mutex.acquire_delivery("zhilian", owner="rec1", timeout_s=5)
        gate_results.append(ok)

    lease_ok, _ = await asyncio.gather(hold_lease(), run_gate())
    assert lease_ok is True
    assert gate_results and gate_results[0], "租约释放后引擎闸门应获得登记（引擎只多等秒级）"


def test_empty_owner_release_rejected():
    """round4-P1-2：空 owner 强制清零通道已封死——拒绝并告警，不得误清在飞登记"""
    import asyncio as _aio

    async def _scenario():
        tok5 = await platform_mutex.acquire_delivery("zhilian", owner="rec_inflight")
        assert tok5, "获取返回 token"
        await platform_mutex.release_delivery("zhilian", owner="rec_inflight", token="")  # 空 token no-op
        assert platform_mutex.is_delivery_busy("zhilian") is True, "空 token 不得清掉在飞登记"
        await platform_mutex.release_delivery("zhilian", owner="rec_inflight", token=tok5)
        assert platform_mutex.is_delivery_busy("zhilian") is False, "正确 token 释放成功"
    _aio.new_event_loop().run_until_complete(_scenario())


def test_all_preflight_navigation_consumes_lease_false():
    """round4-P1-1 结构断言升级：preflight.py 所有 check_login_with_fallback 调用点必须
    (a) 位于 preflight_lease...as <var> 上下文内，且 (b) 上下文内有对 leased 布尔的消费
    （if not leased / if not ok 分支）——防止租约超时后仍硬闯导航。"""
    import inspect

    from app.session import preflight

    src = inspect.getsource(preflight)
    lines = src.splitlines()
    call_idx = [i for i, l in enumerate(lines) if "check_login_with_fallback, config" in l]
    assert call_idx, "未找到 check_login_with_fallback 调用点（源码结构变了？）"
    for i in call_idx:
        window = "\n".join(lines[max(0, i - 14):i + 2])
        assert "preflight_lease" in window, f"调用点(源码行{i+1})未包在 preflight_lease 内"
        assert ("as leased" in window or "as ok" in window), \
            f"调用点(源码行{i+1})的租约未接收 yielded 布尔（as leased/as ok）"
        assert ("if not leased" in window or "if not ok" in window), \
            f"调用点(源码行{i+1})未消费 False 分支（if not leased/ok）"
