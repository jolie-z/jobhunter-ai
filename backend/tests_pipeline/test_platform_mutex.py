"""平台级「抓取 ↔ 投递」互斥（platform_mutex）回归测试。

背景（2026-10-29 Windows 0.4.0 沙箱事故）：抓取器与投递引擎共用同平台同端口的 Edge，
此前无任何互斥——09:00 定时链路抓取撞上手动投递批次，猎聘抓取器把投递正在上传简历的
标签页导航走（生效列表 [] 假失败），51job 同浏览器高频抓详情触发风控滑块。
"""

import asyncio

import pytest

from app.automation import platform_mutex


def setup_function(_):
    platform_mutex.reset_for_test()


def teardown_function(_):
    platform_mutex.reset_for_test()


def test_normalize_platform_aliases():
    """workflow 的混杂口径与调度侧规范键统一收敛"""
    assert platform_mutex.normalize_platform("boss") == "boss"
    assert platform_mutex.normalize_platform("BOSS直聘") == "boss"
    assert platform_mutex.normalize_platform("猎聘") == "liepin"
    assert platform_mutex.normalize_platform("Liepin") == "liepin"
    assert platform_mutex.normalize_platform("前程无忧") == "51job"
    assert platform_mutex.normalize_platform("智联") == "zhilian"
    assert platform_mutex.normalize_platform("智联招聘") == "zhilian"
    assert platform_mutex.normalize_platform("zhilian") == "zhilian"
    assert platform_mutex.normalize_platform("xiaohongshu") == ""
    assert platform_mutex.normalize_platform("") == ""
    assert platform_mutex.normalize_platform(None) == ""


def test_normalize_platform_containment_matching():
    """外审 round1 P1：workflow 的 platform 是子串口径，别名无法穷举——
    精确未命中时双向包含匹配兜底，杜绝静默旁路互斥"""
    assert platform_mutex.normalize_platform("猎聘网") == "liepin"
    assert platform_mutex.normalize_platform("BOSS直聘-杭州") == "boss"
    assert platform_mutex.normalize_platform("51job前程无忧") == "51job"
    assert platform_mutex.normalize_platform("智联招聘(中国)") == "zhilian"
    assert platform_mutex.normalize_platform("去猎聘看看") == "liepin"
    # 完全无关的标签仍返回空串（闸门直通，行为与旧版一致）
    assert platform_mutex.normalize_platform("小红书图文") == ""
    # 空串/空白必须先于包含匹配守卫："" 对任意别名 `text in alias` 恒真，不守卫会误归 boss
    assert platform_mutex.normalize_platform("   ") == ""
    assert platform_mutex.normalize_platform("\t") == ""


async def test_acquire_release_roundtrip_and_snapshot():
    tok = await platform_mutex.acquire_delivery("zhilian", owner="rec1")
    assert tok and tok.startswith("rec1#"), "acquire 返回唯一 token"
    assert platform_mutex.is_delivery_busy("zhilian") is True
    assert platform_mutex.is_delivery_busy("智联招聘") is True  # 别名同键
    assert platform_mutex.is_scrape_busy("zhilian") is False
    assert platform_mutex.busy_snapshot() == {"zhilian": {"scrape": None, "deliver": tok, "preflight": None, "aux": None}}

    await platform_mutex.release_delivery("zhilian", owner="rec1", token=tok)
    assert platform_mutex.is_delivery_busy("zhilian") is False
    assert platform_mutex.busy_snapshot() == {}


async def test_scrape_blocked_while_delivery_busy_then_skips_on_timeout():
    """事故主场景：投递进行中，同平台抓取限时等待后仍忙 → 拒绝（跳过本轮派发）"""
    assert await platform_mutex.acquire_delivery("liepin", owner="rec1") is not None

    ok = await platform_mutex.acquire_scrape("liepin", owner="spider_1", timeout_s=0.05)
    assert ok is None, "投递在飞时抓取不应获得登记"

    # 别的平台不受影响
    assert await platform_mutex.acquire_scrape("zhilian", owner="spider_2", timeout_s=0.05) is not None


async def test_delivery_blocked_while_scrape_busy_then_skips_on_timeout():
    """反向场景：抓取进行中，同平台投递限时等待后仍忙 → 拒绝（按 [环境] 暂时性失败出列）"""
    tok = await platform_mutex.acquire_scrape("51job", owner="spider_1")
    assert tok

    ok = await platform_mutex.acquire_delivery("前程无忧", owner="rec1", timeout_s=0.05)
    assert ok is None

    await platform_mutex.release_scrape("51job", owner="spider_1", token=tok)
    assert await platform_mutex.acquire_delivery("51job", owner="rec1", timeout_s=0.05) is not None


async def test_waiter_wakes_on_release():
    """持锁方释放后，限时等待中的对方应被唤醒并成功获得登记"""
    tok = await platform_mutex.acquire_delivery("zhilian", owner="rec1")

    async def release_later():
        await asyncio.sleep(0.05)
        await platform_mutex.release_delivery("zhilian", owner="rec1", token=tok)
        return True

    async def wait_as_scrape():
        return await platform_mutex.acquire_scrape("zhilian", owner="spider_1", timeout_s=5)

    released, acquired = await asyncio.gather(release_later(), wait_as_scrape())
    assert released is True
    assert acquired, "持锁方释放后等待方应被唤醒获得登记"
    assert platform_mutex.is_scrape_busy("zhilian") is True


async def test_wait_delivery_clear_true_and_false():
    tok = await platform_mutex.acquire_delivery("boss", owner="rec1")
    assert await platform_mutex.wait_delivery_clear("boss", timeout_s=0.05) is False

    await platform_mutex.release_delivery("boss", owner="rec1", token=tok)
    assert await platform_mutex.wait_delivery_clear("boss", timeout_s=0.05) is True


async def test_gate_context_manager_releases_on_success_and_exception():
    async with platform_mutex.scrape_gate("liepin", owner="spider_1") as ok:
        assert ok is not None
        assert platform_mutex.is_scrape_busy("liepin") is True
    assert platform_mutex.is_scrape_busy("liepin") is False

    with pytest.raises(RuntimeError):
        async with platform_mutex.delivery_gate("liepin", owner="rec1") as ok:
            assert ok is not None
            raise RuntimeError("引擎崩溃")
    assert platform_mutex.is_delivery_busy("liepin") is False, "异常路径也必须释放登记"


async def test_gate_yield_false_when_blocked():
    tok = await platform_mutex.acquire_delivery("zhilian", owner="rec1")
    async with platform_mutex.scrape_gate("zhilian", owner="spider_1", timeout_s=0.05) as ok:
        assert ok is False, "闸门拒绝路径 yield False（bool 契约）"
    # 未获得登记时不得误释放持锁方的登记
    assert platform_mutex.is_delivery_busy("zhilian") is True
    await platform_mutex.release_delivery("zhilian", owner="rec1", token=tok)


async def test_release_with_mismatched_token_is_noop():
    """token 校验（round3-P1-2 终版）：token 不匹配拒绝、空 token no-op（防误清在飞登记）"""
    tok = await platform_mutex.acquire_delivery("zhilian", owner="rec1")
    await platform_mutex.release_delivery("zhilian", owner="rec1", token="rec1#fake")
    assert platform_mutex.is_delivery_busy("zhilian") is True, "token 不匹配不得释放"
    await platform_mutex.release_delivery("zhilian", owner="rec1", token="")  # 空 token：no-op
    assert platform_mutex.is_delivery_busy("zhilian") is True, "空 token 不得清掉在飞登记"
    await platform_mutex.release_delivery("zhilian", owner="rec1", token=tok)
    assert platform_mutex.is_delivery_busy("zhilian") is False


async def test_unmanaged_platform_passthrough():
    """未纳管平台（小红书等）不设防：恒放行、无登记"""
    assert await platform_mutex.acquire_scrape("xiaohongshu", owner="t1") is True
    assert await platform_mutex.acquire_delivery("xiaohongshu", owner="rec1") is True
    assert platform_mutex.busy_snapshot() == {}


async def test_same_kind_concurrent_acquire_blocked():
    """round4-P1-3 自身互斥：同平台同种类第二个获取者必须等待/超时拒绝——
    单槽不允许覆盖（否则第一个仍在飞时槽被第二个提前清空，对侧可进入撞车）。
    token 隔离语义由 test_stale_release_cannot_clobber_new_holder 覆盖。"""
    tok1 = await platform_mutex.acquire_delivery("zhilian", owner="rec1")
    assert tok1
    tok2 = await platform_mutex.acquire_delivery("zhilian", owner="rec2", timeout_s=0.05)
    assert tok2 is None, "同 kind 二次获取必须被自身互斥拒绝（单槽不覆盖）"
    assert platform_mutex._state("zhilian")["deliver"] == tok1, "第一持有者的 token 不被覆盖"
    await platform_mutex.release_delivery("zhilian", owner="rec1", token=tok1)
    tok3 = await platform_mutex.acquire_delivery("zhilian", owner="rec2", timeout_s=0.05)
    assert tok3, "第一持有者释放后第二获取者应获得（不同 token）"
    await platform_mutex.release_delivery("zhilian", owner="rec2", token=tok3)
    assert platform_mutex.is_delivery_busy("zhilian") is False
