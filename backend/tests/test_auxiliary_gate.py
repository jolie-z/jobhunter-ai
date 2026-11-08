"""辅助浏览器操作闸门（auxiliary_gate）回归测试——死链预检 & 存活检测接入互斥。

外审 round4 R9 收口：评估期死链预检（link_precheck）与存活检测批次
（job_table_hygiene._liveness_worker）与抓取/投递引擎共用同平台浏览器，
接入 platform_mutex 后与引擎完全互斥；闸门被引擎占用时按「无法判定 /
整批取消」收场（两个调用方既有语义，无破坏性副作用）。
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.automation import link_precheck, platform_mutex


def setup_function(_):
    platform_mutex.reset_for_test()


def teardown_function(_):
    platform_mutex.reset_for_test()


async def test_precheck_boss_returns_none_when_delivery_inflight():
    """投递在飞（持续超等待上限）→ BOSS 死链预检不碰浏览器，返回 None（保留岗位）"""
    assert await platform_mutex.acquire_delivery("boss", owner="rec_inflight") is not None

    def _boom(job_url):
        raise AssertionError("引擎在飞时死链预检不得触碰浏览器")

    with patch.object(platform_mutex, "AUXILIARY_WAIT_TIMEOUT_S", 0.05), \
         patch.object(link_precheck, "check_boss_link_sync", _boom):
        verdict = await link_precheck.precheck_boss_link("https://zhipin.com/job/xxx.html")

    assert verdict is None, "闸门拒绝应按「无法判定」返回 None"
    assert platform_mutex.is_delivery_busy("boss") is True, "在飞投递登记不受影响"
    assert platform_mutex._state("boss")["aux"] is None, "aux 位不得残留（超时放弃路径）"


async def test_precheck_boss_normal_path_acquires_and_releases():
    """无引擎在飞：预检正常执行并返回判定结果，闸门进出平衡"""
    with patch.object(link_precheck, "check_boss_link_sync", return_value=True):
        verdict = await link_precheck.precheck_boss_link("https://zhipin.com/job/ok.html")

    assert verdict is True
    assert platform_mutex.busy_snapshot() == {}, "闸门必须释放，不得残留登记"


async def test_precheck_zhilian_skips_when_scrape_inflight():
    """抓取在飞 → 智联死链预检同样零浏览器接触"""
    assert await platform_mutex.acquire_scrape("zhilian", owner="spider_1") is not None

    def _boom(job_url):
        raise AssertionError("抓取在飞时死链预检不得触碰浏览器")

    with patch.object(platform_mutex, "AUXILIARY_WAIT_TIMEOUT_S", 0.05), \
         patch.object(link_precheck, "check_zhilian_link_sync", _boom):
        verdict = await link_precheck.precheck_zhilian_link("https://www.zhaopin.com/jobdetail/x.htm")

    assert verdict is None
    assert platform_mutex._state("zhilian")["aux"] is None


async def test_precheck_empty_url_short_circuits():
    """空链接直接 False（死链），不进闸门不占登记"""
    assert await link_precheck.precheck_boss_link("") is False
    assert await link_precheck.precheck_zhilian_link("") is False
    assert platform_mutex.busy_snapshot() == {}


async def test_auxiliary_gate_waiter_wakes_on_engine_release():
    """引擎先占 → 辅助闸门限时等待 → 引擎释放后被唤醒获得（只多等，不误杀）"""
    tok = await platform_mutex.acquire_scrape("boss", owner="spider_1")
    gate_results = []

    async def release_later():
        await asyncio.sleep(0.05)
        await platform_mutex.release_scrape("boss", owner="spider_1", token=tok)
        return True

    async def run_aux():
        async with platform_mutex.auxiliary_gate("boss", owner="aux:1", wait_timeout_s=5) as ok:
            gate_results.append(ok)
            assert platform_mutex._state("boss")["aux"] is not None

    released, _ = await asyncio.gather(release_later(), run_aux())
    assert released is True
    assert gate_results and gate_results[0], "引擎释放后辅助闸门应被唤醒获得"


async def test_liveness_batch_cancelled_when_delivery_inflight():
    """存活检测：投递在飞（持续超 90s 等待上限——测试用 patch 短路）→ 整批取消，
    状态置 aborted、岗位保留（不写飞书不标 SQLite）"""
    from app.services import job_table_hygiene as hygiene

    assert await platform_mutex.acquire_delivery("zhilian", owner="rec_inflight") is not None

    async def _deny(*a, **k):
        return False

    with patch.object(platform_mutex, "acquire_auxiliary", side_effect=_deny):
        hygiene._liveness_state.update(running=True, platform="zhilian", total=3, done=0,
                                       alive=0, dead=0, unknown=0, aborted="",
                                       started_epoch=hygiene.time.time(), finished_epoch=0.0, log=[])
        await hygiene._liveness_worker([{"record_id": "r1"}, {"record_id": "r2"}, {"record_id": "r3"}], "zhilian")

    state = hygiene._liveness_state
    assert state["running"] is False
    assert "投递进行中" in state["aborted"] and "岗位全部保留" in state["aborted"]
    assert state["done"] == 0, "整批取消：一条都不应被检测"


async def test_liveness_batch_holds_gate_across_items_and_releases():
    """存活检测正常路径：批级持锁（跑完才释放），期间引擎闸门拿不到。

    外审 R2-P1（C1）：不得 Mock acquire_auxiliary/release_auxiliary——自我 Mock
    架空互斥槽，「期间引擎拿不到」与「跨条共用同一 token」从未被真实验证；
    样本须 ≥2 条以验证跨条持锁。检测函数跑在同步线程（_run_tracked_thread），
    用 threading.Event 与主协程握手稳定出持锁窗口。
    """
    import threading

    from app.services import job_table_hygiene as hygiene

    jobs = [{"record_id": f"r{i}", "job_link": f"https://x/{i}"} for i in range(2)]
    seen_tokens: list = []
    second_started = threading.Event()
    probe_done = threading.Event()

    def _fake_detect(page, link):
        token = platform_mutex._state(platform_mutex.normalize_platform("liepin"))["aux"]
        seen_tokens.append(token)
        if len(seen_tokens) == 2:
            # 第二条开检后挂起，等主协程在批级持锁窗口内完成引擎闸门探针
            second_started.set()
            probe_done.wait(timeout=5)
        return (True, "")

    async def _fake_feishu_update(*a, **k):
        return None

    with patch("app.core.feishu_client.feishu_client") as fake_client, \
         patch.object(hygiene, "_liveness_script") as fake_script, \
         patch("random.uniform", return_value=0.0):
        fake_client.update_record = _fake_feishu_update
        fake_script.return_value = type("M", (), {
            "get_platform_browser": staticmethod(lambda p: object()),
            "check_zhilian_link": staticmethod(lambda page, link: (None, "mocked")),
            "check_liepin_link": staticmethod(_fake_detect),
        })()
        task = asyncio.create_task(hygiene._liveness_worker(jobs, "liepin"))
        await asyncio.wait_for(asyncio.to_thread(second_started.wait), timeout=5)
        held_token = platform_mutex._state(platform_mutex.normalize_platform("liepin"))["aux"]
        engine_token = await platform_mutex.acquire_delivery("liepin", owner="engine", timeout_s=0.05)
        probe_done.set()
        await task

    assert len(seen_tokens) == 2 and all(seen_tokens), "两条样本都必须在持锁期内执行"
    assert seen_tokens[0] == seen_tokens[1] == held_token, "批级持锁：跨条共用同一真实 token"
    assert engine_token is None, "批级持锁期间引擎投递闸门必须拿不到"
    assert not platform_mutex.is_aux_busy("liepin"), "批次结束必须真实释放闸门"
    assert hygiene._liveness_state["running"] is False
    assert hygiene._liveness_state["alive"] == 2


# ==========================================
# round1-P1/P2 处置补充用例
# ==========================================

async def test_aux_inflight_blocks_engine_gates_both_ways():
    """round1-P2 双向证据：aux 批级持有期间，deliver/scrape 闸门均被阻塞等待（超时拒绝）。

    外审 R3-P1-3 修正：不得把被测原语自身 patch 成常量函数（自我 Mock 假绿灯，
    真实互斥阻塞分支从未执行）——直接调用真实 acquire_scrape/acquire_delivery，
    走 _BLOCKERS 矩阵的等待超时路径。"""
    aux_token = await platform_mutex.acquire_auxiliary("zhilian", owner="liveness:zhilian")
    assert aux_token, "空闲态 aux 必须立即获取成功"
    try:
        # 闸门等待引擎清场的路径——aux 在飞时应阻塞到超时
        ok_scrape = await platform_mutex.acquire_scrape("zhilian", owner="spider_1", timeout_s=0.05)
        ok_deliver = await platform_mutex.acquire_delivery("zhilian", owner="rec1", timeout_s=0.05)

        assert ok_scrape is None, "aux 持有时抓取闸门必须等待（超时拒绝）"
        assert ok_deliver is None, "aux 持有时投递闸门必须等待（超时拒绝）"
        assert platform_mutex._state("zhilian")["aux"] == aux_token, "aux 登记不受等待者影响"
    finally:
        await platform_mutex.release_auxiliary("zhilian", owner="liveness:zhilian", token=aux_token)


async def test_build_checked_batch_skips_all_when_engine_inflight():
    """round1-P1 批级预探：投递在飞 → build_checked_batch 整批跳过预检（岗位全保留、
    零逐条等待——不经历 N×90s）"""
    from app.automation import link_precheck

    assert await platform_mutex.acquire_delivery("boss", owner="rec_inflight") is not None
    jobs = [
        {"platform": "BOSS直聘", "feishu_fields": {"岗位链接": {"link": "https://zhipin.com/a"}}, "_created_time": 2},
        {"platform": "BOSS直聘", "feishu_fields": {"岗位链接": {"link": "https://zhipin.com/b"}}, "_created_time": 1},
    ]

    def _boom(url):
        raise AssertionError("批级预探拒绝后不得逐条进闸门（否则 N×90s）")

    logs = []

    async def fake_emit(task_id, msg, level="info"):
        logs.append(msg)

    with patch.object(link_precheck, "precheck_boss_link", _boom), \
         patch("app.automation.pipeline_broadcast.emit_log", fake_emit):
        selected = await link_precheck.build_checked_batch(jobs, batch_limit=2, pipeline_task_id="t1")

    assert len(selected) == 2, "整批保留"
    assert any("跳过其链接预检" in m or "跳过链接预检" in m for m in logs)


async def test_build_checked_batch_normal_when_idle():
    """引擎空闲：批级预探放行，逐条预检照常执行（死链剔除语义不变）"""
    from app.automation import link_precheck

    jobs = [
        {"platform": "BOSS直聘", "feishu_fields": {"岗位链接": {"link": "https://zhipin.com/dead"}},
         "_created_time": 2, "record_id": "r1", "company_name": "x", "job_name": "y"},
        {"platform": "BOSS直聘", "feishu_fields": {"岗位链接": {"link": "https://zhipin.com/alive"}},
         "_created_time": 1},
    ]

    async def fake_precheck(url):
        return False if "dead" in url else True

    async def noop_update(*a, **k):
        return None

    async def fake_emit(task_id, msg, level="info"):
        pass

    with patch.object(link_precheck, "precheck_boss_link", fake_precheck), \
         patch("app.services.feishu_service.update_feishu_record", noop_update), \
         patch("app.automation.pipeline_broadcast.emit_log", fake_emit):
        selected = await link_precheck.build_checked_batch(jobs, batch_limit=2, pipeline_task_id="t1")

    assert len(selected) == 1
    assert "alive" in str(selected[0]["feishu_fields"])


def test_aux_owner_is_required():
    """round1-P2：aux 便捷函数 owner 必填（传空 owner 释放会被 _release 拒绝——
    收紧为签名必填后编译期即拦截，这里验证签名）"""
    import inspect
    sig = inspect.signature(platform_mutex.acquire_auxiliary)
    params = list(sig.parameters.values())
    assert params[1].name == "owner" and params[1].default is inspect.Parameter.empty, \
        "owner 必须是无默认值参数（防空 owner 登记→释放被拒→泄漏）"
    sig2 = inspect.signature(platform_mutex.release_auxiliary)
    params2 = list(sig2.parameters.values())
    assert params2[1].name == "owner" and params2[1].default is inspect.Parameter.empty


async def test_liveness_release_survives_cancelled_body():
    """round1-P1-4 取消安全：inner 体被取消（模拟 uvicorn 收尾取消孤儿协程）时，
    aux 槽仍被释放（shield 保证），引擎可立即获取。

    外审 R3-P1-4 修正：不得 patch acquire_auxiliary（自我 Mock 假绿灯——槽从未被
    真实置位，「已清空」断言全部空洞）——走真实获取，先证明 aux 已置位，取消后再证
    释放；收尾 release_delivery 必须携带 token（空 token 是 no-op，会泄漏登记）。"""
    from app.services import job_table_hygiene as hygiene

    async def _hang_inner(*a, **k):
        await asyncio.sleep(30)

    with patch.object(platform_mutex, "release_auxiliary", side_effect=platform_mutex.release_auxiliary) as spy_rel, \
         patch.object(hygiene, "_liveness_worker_inner", _hang_inner):
        task = asyncio.create_task(hygiene._liveness_worker([{"record_id": "r1"}], "zhilian"))
        await asyncio.sleep(0.05)
        assert platform_mutex.is_aux_busy("zhilian"), "真实 acquire 必须已置位 aux 槽"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert spy_rel.called, "取消路径必须执行释放"
    assert platform_mutex._state("zhilian")["aux"] is None, "aux 槽必须已清空（shield 保证）"
    # 引擎可立即获取
    deliver_token = await platform_mutex.acquire_delivery("zhilian", owner="rec1", timeout_s=0.05)
    assert deliver_token, "aux 已释放，投递闸门必须立即可获取"
    await platform_mutex.release_delivery("zhilian", owner="rec1", token=deliver_token)


# ==========================================
# round2 处置补充用例
# ==========================================

async def test_precheck_is_pure_nonblocking_when_engine_inflight():
    """round2-P1-1' 核心回归：批中引擎占用（入口预探之后的 TOCTOU）→ 逐条预检
    零等待立即返回 None——即使引擎持续在飞 100 条也绝不出现 N×90s（实测本用例
    即时返回为证）"""
    import time as _t
    assert await platform_mutex.acquire_delivery("boss", owner="rec_inflight") is not None

    t0 = _t.monotonic()
    verdict = await link_precheck.precheck_boss_link("https://zhipin.com/mid.html")
    elapsed = _t.monotonic() - t0

    assert verdict is None
    assert elapsed < 1.0, f"非阻塞预探必须立即返回（实测 {elapsed:.2f}s），绝不 90s 死等"


async def test_precheck_holds_aux_until_thread_finishes():
    """round2-P1-3' 核心回归：aux 位持有到同步检测线程自然结束——线程运行期间
    引擎闸门无法进入（38s 残留窗口从机制上关闭）"""
    import asyncio as _aio

    release_flag = _aio.Event()
    inside_aux = _aio.Event()

    async def run_precheck():
        def _slow_sync(url):
            # 模拟慢同步检测：3s 后才返回（>6s 旧熔断值）
            import time as _time
            _time.sleep(0.3)
            return True
        with patch.object(link_precheck, "check_boss_link_sync", _slow_sync):
            return await link_precheck.precheck_boss_link("https://zhipin.com/slow.html")

    task = _aio.create_task(run_precheck())
    # 等到线程真正开跑（aux 已持有）
    await _aio.sleep(0.1)
    aux_held = platform_mutex._state("boss")["aux"] is not None
    # 线程未结束期间，引擎闸门必须被阻塞
    engine_ok = await platform_mutex.acquire_delivery("boss", owner="rec1", timeout_s=0.05)
    verdict = await task
    aux_after = platform_mutex._state("boss")["aux"] is not None

    assert aux_held, "检测线程运行期间 aux 必须持有"
    assert engine_ok is None, "线程结束前引擎闸门不得进入（38s 窗口关闭的机制保证）"
    assert verdict is True
    assert not aux_after, "线程结束后 aux 释放"


async def test_precheck_cancel_still_releases_aux():
    """round5-P1-1 修正：precheck 协程被取消后，aux 持有到线程真正结束才释放——
    取消不再提前放锁（旧契约「cancel 后立即清槽」已被评审裁定为撞页窗，作废）。"""
    import asyncio as _aio
    import threading

    started = threading.Event()
    finish = threading.Event()

    def _hang(url):
        started.set()
        finish.wait(5)
        return True

    try:
        with patch.object(link_precheck, "check_boss_link_sync", _hang):
            task = _aio.create_task(link_precheck.precheck_boss_link("https://zhipin.com/hang.html"))
            await _aio.wait_for(_aio.to_thread(started.wait), timeout=2)
            assert platform_mutex._state("boss")["aux"] is not None
            task.cancel()
            try:
                await task
            except _aio.CancelledError:
                pass

            # 协程已取消，但线程被 finish 卡住——aux 必须仍然持有
            assert platform_mutex._state("boss")["aux"] is not None, \
                "线程未结束前 aux 不得释放（round5-P1-1：取消不放锁）"
            finish.set()
            for _ in range(200):
                if platform_mutex._state("boss")["aux"] is None:
                    break
                await _aio.sleep(0.01)
    finally:
        finish.set()

    assert platform_mutex._state("boss")["aux"] is None, "线程结束后回调必须释放 aux"


async def test_build_checked_batch_skips_only_busy_platform():
    """round2-P2 按平台分别跳过：boss 存活检测在飞只跳过 boss 预检，zhilian 照常"""
    from app.automation import link_precheck

    assert await platform_mutex.acquire_auxiliary("boss", owner="liveness:boss") is not None
    jobs = [
        {"platform": "BOSS直聘", "feishu_fields": {"岗位链接": {"link": "https://zhipin.com/a"}},
         "_created_time": 2},
        {"platform": "智联招聘", "feishu_fields": {"岗位链接": {"link": "https://zhaopin.com/b"}},
         "_created_time": 1},
    ]

    calls = []

    async def fake_precheck_zhilian(url):
        calls.append(url)
        return True

    def _boom_boss(url):
        raise AssertionError("boss 在飞时 boss 岗位不得进闸门")

    async def noop_emit(task_id, msg, level="info"):
        pass

    with patch.object(link_precheck, "precheck_zhilian_link", fake_precheck_zhilian), \
         patch.object(link_precheck, "precheck_boss_link", _boom_boss), \
         patch("app.automation.pipeline_broadcast.emit_log", noop_emit):
        selected = await link_precheck.build_checked_batch(jobs, batch_limit=2, pipeline_task_id="t1")

    assert len(selected) == 2
    assert calls == ["https://zhaopin.com/b"], "zhilian 不受 boss 在飞影响，照常预检"


def test_acquire_auxiliary_timeout_runtime_read():
    """round2-P2：acquire_auxiliary 的 timeout_s=None 运行时读常量（patch 可生效）"""
    import inspect
    sig = inspect.signature(platform_mutex.acquire_auxiliary)
    assert sig.parameters["timeout_s"].default is None


# ==========================================
# round3 处置补充用例
# ==========================================

async def test_stale_release_cannot_clobber_new_holder():
    """round3-P1-2 核心回归：同名 owner 的旧批延迟释放不得误清新批的锁（token 隔离）。
    场景：liveness:zhilian 旧批被取消后 shielded release 迟到；新批已持 aux。"""
    tok_old = await platform_mutex.acquire_auxiliary("zhilian", owner="liveness:zhilian")
    # 模拟旧批取消但释放迟到：先手动模拟新批拿锁——旧批必须先释放才能让新批进，
    # 因此真实竞态是「旧 release 在飞行中 + 新 acquire 已插入」。直接验证 token 校验：
    # 1) 模拟旧 release 延迟执行（此刻新批尚未获取）
    await platform_mutex.release_auxiliary("zhilian", owner="liveness:zhilian", token=tok_old)
    # 2) 新批获取（同名 owner，不同 token）
    tok_new = await platform_mutex.acquire_auxiliary("zhilian", owner="liveness:zhilian")
    assert tok_new and tok_new != tok_old, "同名 owner 两次获取 token 必须不同"
    # 3) 旧 release 再来一次（模拟迟到/重复调用）：token 已失效，不得清掉新批
    await platform_mutex.release_auxiliary("zhilian", owner="liveness:zhilian", token=tok_old)
    assert platform_mutex._state("zhilian")["aux"] == tok_new, "旧 token 释放不得清掉新持有者"
    await platform_mutex.release_auxiliary("zhilian", owner="liveness:zhilian", token=tok_new)
    assert platform_mutex._state("zhilian")["aux"] is None


async def test_precheck_cancel_thread_still_running_engine_blocked():
    """round5-P1-1 终版回归（替换 round3 的旧契约）：线程 sleep 1s，cancel 后立即
    以 0.1s 超时 acquire_delivery 必须失败；线程结束后才成功。

    证明 done-callback 挂在底层线程 future 上（shield 保护），不是挂在被 cancel
    的协程等待上——后者会立即触发回调、在线程仍跑时放锁。"""
    import asyncio as _aio
    import threading

    thread_alive = threading.Event()
    thread_can_finish = threading.Event()

    def _slow(url):
        thread_alive.set()
        thread_can_finish.wait(5)
        return True

    try:
        with patch.object(link_precheck, "check_boss_link_sync", _slow):
            task = _aio.create_task(link_precheck.precheck_boss_link("https://zhipin.com/cancel.html"))
            await _aio.wait_for(_aio.to_thread(thread_alive.wait), timeout=2)
            assert platform_mutex._state("boss")["aux"] is not None
            task.cancel()
            try:
                await task
            except _aio.CancelledError:
                pass

            assert platform_mutex._state("boss")["aux"] is not None, \
                "取消后线程仍在跑：aux 必须继续持有"
            blocked = await platform_mutex.acquire_delivery("boss", owner="rec1", timeout_s=0.1)
            assert blocked is None, "线程结束前引擎闸门必须进不来（R9 撞页窗关闭）"

            thread_can_finish.set()
            for _ in range(200):
                if platform_mutex._state("boss")["aux"] is None:
                    break
                await _aio.sleep(0.01)
            assert platform_mutex._state("boss")["aux"] is None, "线程结束后回调必须释放 aux"

            acquired = await platform_mutex.acquire_delivery("boss", owner="rec1", timeout_s=0.5)
            assert acquired is not None, "线程结束后引擎必须能进入"
            await platform_mutex.release_delivery("boss", owner="rec1", token=acquired)
    finally:
        thread_can_finish.set()


async def test_aux_release_wakes_engine_waiter():
    """round5-P1-2 回归：run_with_aux 释放 aux 时 notify_all 必须唤醒等待中的引擎。

    旧实现先同步清槽再 create_task(_release)，_release 见槽已空早退、notify_all
    永不执行——等待者只能等满 120/300s 超时。这里 aux 约 0.3s 后释放，引擎 1s
    超时的 acquire 必须被立即唤醒（<0.7s），而不是等满超时。"""
    import asyncio as _aio

    def _short(url):
        import time as _time
        _time.sleep(0.3)
        return True

    with patch.object(link_precheck, "check_boss_link_sync", _short):
        precheck = _aio.create_task(
            link_precheck.precheck_boss_link("https://zhipin.com/wake.html"))
        for _ in range(200):
            if platform_mutex._state("boss")["aux"] is not None:
                break
            await _aio.sleep(0.005)
        assert platform_mutex._state("boss")["aux"] is not None, "预检应先持有 aux"

        loop = _aio.get_running_loop()
        t0 = loop.time()
        tok = await platform_mutex.acquire_delivery("boss", owner="rec1", timeout_s=1.0)
        elapsed = loop.time() - t0

        assert tok is not None, "aux 释放后等待者必须被唤醒获得登记"
        assert elapsed < 0.7, f"释放必须 notify_all 立即唤醒（实测 {elapsed:.2f}s，不得等满 1s）"
        await platform_mutex.release_delivery("boss", owner="rec1", token=tok)
        assert await precheck is True


async def test_liveness_cancel_holds_aux_until_detection_thread_finishes():
    """round5-P1-3 回归：存活检测取消时若同步判定线程仍在跑，aux 必须持有到线程
    结束；期间引擎闸门进不来，线程结束后才放行。"""
    import asyncio as _aio
    import threading

    from app.services import job_table_hygiene as hygiene

    started = threading.Event()
    finish = threading.Event()

    def _slow(page, link):
        started.set()
        finish.wait(5)
        return (True, "")

    script = type("M", (), {
        "get_platform_browser": staticmethod(lambda p: object()),
        "check_zhilian_link": staticmethod(lambda page, link: (None, "mocked")),
        "check_liepin_link": staticmethod(_slow),
    })()

    try:
        with patch.object(hygiene, "_liveness_script", return_value=script), \
             patch("app.core.feishu_client.feishu_client") as fake_client, \
             patch("random.uniform", return_value=0.0):
            fake_client.update_record = lambda *a, **k: _aio.sleep(0)
            task = _aio.create_task(hygiene._liveness_worker(
                [{"record_id": "r1", "job_link": "https://x/1"}], "liepin"))
            await _aio.wait_for(_aio.to_thread(started.wait), timeout=2)
            assert platform_mutex.is_aux_busy("liepin")

            task.cancel()
            await _aio.sleep(0.05)  # 让取消抵达批次收尾（正在等线程）
            assert platform_mutex.is_aux_busy("liepin"), "检测线程未结束，aux 不得释放"
            blocked = await platform_mutex.acquire_delivery("liepin", owner="rec1", timeout_s=0.1)
            assert blocked is None, "线程结束前引擎闸门必须进不来"

            finish.set()
            try:
                await task
            except _aio.CancelledError:
                pass
    finally:
        finish.set()

    assert not platform_mutex.is_aux_busy("liepin"), "线程结束后 aux 必须释放"
    tok = await platform_mutex.acquire_delivery("liepin", owner="rec1", timeout_s=0.5)
    assert tok is not None
    await platform_mutex.release_delivery("liepin", owner="rec1", token=tok)


def test_liveness_max_hold_below_delivery_gate_timeout():
    """round4-P1-2''' / round5-P2：批级硬顶必须小于投递闸门 300s 超时——
    一批持锁期间同平台投递至多撞 1 次超时，重试预算不被一批耗尽。"""
    from app.services import job_table_hygiene as hygiene
    assert hygiene.LIVENESS_MAX_HOLD_SECONDS < platform_mutex.DELIVERY_WAIT_SCRAPE_TIMEOUT_S


def test_liveness_batch_deadline_stops_and_preserves():
    """round3-P1-3' 批时长硬顶：deadline 到点未检的岗位整体保留（返回剩余列表）"""
    from app.services import job_table_hygiene as hygiene

    jobs = [{"record_id": f"r{i}", "job_link": f"https://x/{i}"} for i in range(5)]
    remaining = asyncio.new_event_loop().run_until_complete(
        hygiene._liveness_worker_inner(jobs, "liepin",
                                       dict(hygiene._liveness_state, log=[]),
                                       deadline=hygiene.time.time() - 1))
    assert len(remaining) == 5, "deadline 已过：全部岗位未检测、整体保留"
