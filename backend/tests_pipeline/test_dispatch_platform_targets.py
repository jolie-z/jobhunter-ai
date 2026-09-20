"""run_dispatch_collect 按平台下发独立目标（防小 limit 平台超抓）

背景：全链路预算制下，同一关键词轮内每个平台必须按自己的剩余预算抓取，
而不是所有平台统一按最大预算抓。platform_targets 未指定的平台回退统一 target_jobs。
"""
import asyncio

import app.api.routes.crawlers as crawlers
import app.session.scrape_sessions as scrape_sessions


def test_platform_targets_dispatch(monkeypatch):
    captured = {}

    def make_stub(platform):
        async def stub(*args, **kwargs):
            captured[platform] = args
        return stub

    monkeypatch.setattr(crawlers, "_run_boss_task", make_stub("boss"))
    monkeypatch.setattr(crawlers, "_run_liepin_task", make_stub("liepin"))
    monkeypatch.setattr(crawlers, "_run_51job_task", make_stub("51job"))
    monkeypatch.setattr(crawlers, "_run_zhilian_task", make_stub("zhilian"))
    monkeypatch.setattr(crawlers, "_run_xhs_task", make_stub("xiaohongshu"))
    # 避免测试写真实续抓页码
    monkeypatch.setattr(scrape_sessions, "update_last_page", lambda *a, **k: None)

    async def go():
        subs = await crawlers.run_dispatch_collect(
            keyword="自动化测试词", city="广州", salary="不限", target_jobs=20,
            platforms=["boss", "liepin", "51job"], master_task_id=None,
            platform_targets={"boss": 5, "liepin": 20},
        )
        await asyncio.sleep(0.05)  # 让 create_task 的桩任务跑完，避免悬挂任务
        return subs

    subs = asyncio.run(go())
    by_platform = {s["platform"]: s["target_jobs"] for s in subs}
    assert by_platform["boss"] == 5    # 小预算平台按自己的预算
    assert by_platform["liepin"] == 20
    assert by_platform["51job"] == 20  # 未指定 → 回退统一 target_jobs

    # 子任务实际收到的目标参数（最后一个位置参数）与预算一致
    assert captured["boss"][-1] == 5
    assert captured["liepin"][-1] == 20
    assert captured["51job"][-1] == 20


def test_manual_mode_single_target(monkeypatch):
    """手动模式不传 platform_targets：所有平台统一 target_jobs（行为不变）"""
    captured = {}

    async def boss_stub(*args, **kwargs):
        captured["boss"] = args

    async def liepin_stub(*args, **kwargs):
        captured["liepin"] = args

    monkeypatch.setattr(crawlers, "_run_boss_task", boss_stub)
    monkeypatch.setattr(crawlers, "_run_liepin_task", liepin_stub)
    monkeypatch.setattr(scrape_sessions, "update_last_page", lambda *a, **k: None)

    async def go():
        subs = await crawlers.run_dispatch_collect(
            keyword="手动模式", city="广州", salary="不限", target_jobs=15,
            platforms=["boss", "liepin"], master_task_id=None,
        )
        await asyncio.sleep(0.05)
        return subs

    subs = asyncio.run(go())
    assert all(s["target_jobs"] == 15 for s in subs)
    assert captured["boss"][-1] == 15
    assert captured["liepin"][-1] == 15
