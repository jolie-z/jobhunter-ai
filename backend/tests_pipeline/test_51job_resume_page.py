"""51job 续抓页码回写回归测试。

背景：旧版 _run_and_track 回写的是任务「起始页」而非本轮实际到达的最后一页，
导致下个任务从 起始页+1 开始重爬上次已抓的所有页（满屏「已在库跳过」+ 每页
250~400s 翻页休眠），51job 每次任务巨慢。

修复语义：51job 回写「最后触碰页码」（末页可能因抓满目标/急停未扫完），
下次派发直接从该页重爬兜底（start_page == last_page，而非 last_page + 1）。
其余平台未返回真实页码，保持旧行为不回归。

覆盖：
- run_task 从第 1 页爬到第 6 页，返回 last_touched=6
- _run_and_track 优先用爬虫返回的真实末页回写；拿不到时兜底 start_page
- 派发时 51job 从 last_page 原页起步（=6），其余平台保持 last_page+1（=7）
"""
import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest

import app.api.routes.crawlers as crawlers
import app.session.salary_mapper as sm
import app.session.scrape_sessions as ss
from app.tasks.state import task_queues


def _load_controller(platform: str):
    """以与生产相同的 sys.path hack 载入控制器（sys.modules 同一对象，flag 互通）。"""
    subdir, mod_name = crawlers._PLATFORM_STOP_MODULES[platform]
    mod_dir = f"{crawlers.PROJECT_ROOT}/{subdir}"
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)
    return importlib.import_module(mod_name)


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


class _DummyProc:
    """假子进程：run_task 只会对它调 wait() 与读 returncode（输出解析已被 monkeypatch 掉）。"""

    returncode = 0

    def wait(self):
        return 0


def test_target_reached_sigterm_not_reported_as_failure(monkeypatch, capsys):
    """目标达成后主动 SIGTERM（returncode=-15）是正常收工，不得误报环境熔断。

    2026-10-30 真机日志：51job 成功入库 1/1 后紧接着打印「采集器异常退出（退出码:
    -15）」，让成功抓取看起来像失败。terminated_by_controller=True 时不得走熔断分支。
    """
    mod = _load_controller("51job")

    class _TerminatedProc(_DummyProc):
        returncode = -15

    def fake_output(process, target_jobs, total_inserted, current_page, on_page_done, skip_state=None, on_skip=None):
        return target_jobs, False, 100, True, False  # 本页直接达标（collector 随后被 SIGTERM）

    monkeypatch.setattr(mod, "_build_crawler_cmd", lambda *a, **k: ["true"])
    monkeypatch.setattr(mod, "_process_crawler_output", fake_output)
    monkeypatch.setattr(mod, "countdown_sleep", lambda n: None)
    # 外审 R2-P1（C3）：popen_hidden 在 subprocess_utils 内部用真实 subprocess——
    # 必须替换入口本身（同 test_51job_bottom_signal_2026_10_31.py），否则拿到的是
    # returncode=0 的真实进程，returncode=-15 分支从未执行，沦为假绿灯
    monkeypatch.setattr(mod, "popen_hidden", lambda *a, **k: _TerminatedProc())
    monkeypatch.setattr(ss, "report_condition_round", lambda *a, **k: None)

    total, _ = mod.run_task("AI应用", "广州", 1, 1, "15-20K")
    assert total == 1
    assert "采集器退出" not in capsys.readouterr().out


def test_global_stop_sigterm_not_reported_as_failure(monkeypatch, capsys):
    """用户急刹（未达标 + 主动 SIGTERM）同样是控制方终止，不得误报环境熔断。

    修复前：GLOBAL_STOP 路径 _safe_terminate → returncode=-15 且 total_inserted <
    target_jobs → 打印「采集器异常退出（多为环境守卫拒绝/浏览器未就绪）」，把用户
    主动停止误归因为环境故障。terminated_by_controller 标志必须覆盖该路径。
    """
    mod = _load_controller("51job")

    class _TerminatedProc(_DummyProc):
        returncode = -15

    def fake_output(process, target_jobs, total_inserted, current_page, on_page_done, skip_state=None, on_skip=None):
        return 0, False, 100, True, False  # 用户急刹：本页 0 入库，控制器主动 SIGTERM

    monkeypatch.setattr(mod, "_build_crawler_cmd", lambda *a, **k: ["true"])
    monkeypatch.setattr(mod, "_process_crawler_output", fake_output)
    monkeypatch.setattr(mod, "countdown_sleep", lambda n: None)
    # 外审 R2-P1（C3）：同上——必须替换 popen_hidden 入口本身
    monkeypatch.setattr(mod, "popen_hidden", lambda *a, **k: _TerminatedProc())
    monkeypatch.setattr(ss, "report_condition_round", lambda *a, **k: None)

    total, last_touched = mod.run_task("AI应用", "广州", 1, 5, "15-20K")
    assert total == 0
    assert last_touched == 1  # 本页已处理完（急刹），续抓从该页重爬
    assert "采集器退出" not in capsys.readouterr().out


def test_port_lock_busy_exit_is_neutral_skip(monkeypatch, capsys):
    """跨进程端口锁被对端实例持有（退出码 75）→ 中性跳过，不打印环境熔断。"""
    mod = _load_controller("51job")

    class _BusyProc(_DummyProc):
        returncode = mod.PORT_LOCK_BUSY_EXIT_CODE

    def fake_output(process, target_jobs, total_inserted, current_page, on_page_done, skip_state=None, on_skip=None):
        return total_inserted, False, 100, False, False

    monkeypatch.setattr(mod, "_build_crawler_cmd", lambda *a, **k: ["true"])
    monkeypatch.setattr(mod, "_process_crawler_output", fake_output)
    monkeypatch.setattr(mod, "countdown_sleep", lambda n: None)
    # popen_hidden 在 subprocess_utils 内部用真实 subprocess，必须替换入口本身，
    # 否则拿到的是真实 `true` 进程（returncode=0），75 分支永远不进、循环空转。
    monkeypatch.setattr(mod, "popen_hidden", lambda *a, **k: _BusyProc())
    monkeypatch.setattr(ss, "report_condition_round", lambda *a, **k: None)

    total, _ = mod.run_task("AI应用", "广州", 1, 5, "15-20K")
    out = capsys.readouterr().out
    assert total == 0
    assert "另一个 JobHunter 实例" in out
    assert "采集器退出" not in out


def test_run_task_reports_last_touched_page(monkeypatch):
    """核心回归：模拟从第 1 页爬到第 6 页（每页入库 2 个，目标 12），
    run_task 必须返回 last_touched=6，供编排层回写。"""
    mod = _load_controller("51job")

    pages_done = []

    def fake_output(process, target_jobs, total_inserted, current_page, on_page_done, skip_state=None, on_skip=None):
        pages_done.append(current_page)
        return total_inserted + 2, False, 100, False, False  # 每页入库 2 个，未到底

    monkeypatch.setattr(mod, "_build_crawler_cmd", lambda *a, **k: ["true"])
    monkeypatch.setattr(mod, "_process_crawler_output", fake_output)
    monkeypatch.setattr(mod, "countdown_sleep", lambda n: None)
    monkeypatch.setattr(mod, "subprocess", SimpleNamespace(
        Popen=lambda *a, **k: _DummyProc(), PIPE=-1, STDOUT=-2))
    monkeypatch.setattr(ss, "report_condition_round", lambda *a, **k: None)

    total, last_touched = mod.run_task("AI应用", "广州", 1, 12, "15-20K")
    assert pages_done == [1, 2, 3, 4, 5, 6]
    assert total == 12
    assert last_touched == 6


def test_run_and_track_writes_real_final_page_or_fallback(monkeypatch):
    """回写优先级：爬虫返回真实末页 → 写真实值；返回 None → 兜底写起始页（旧行为）。"""
    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda kw, c, s, p, lp: calls.append((p, lp)))

    async def scenario():
        async def returns_final():
            return 6

        async def returns_none():
            return None

        await crawlers._run_and_track(returns_final(), "t1", "AI应用", "广州", "15-20K", "51job", 1)
        await crawlers._run_and_track(returns_none(), "t2", "AI应用", "广州", "15-20K", "51job", 3)

    asyncio.run(scenario())
    assert calls == [("51job", 6), ("51job", 3)]


def test_dispatch_all_platforms_start_from_last_touched_page(monkeypatch):
    """续抓起点：last_page=6 时所有平台都从第 6 页重扫。

    采集器拿到小 target 后会在页内提前停，留下未扫页尾；原页重扫能自愈。
    hit_bottom 时仍由 _run_and_track 归零，不会退化成越过末页空转。
    """
    monkeypatch.setattr(ss, "get_last_page", lambda kw, c, s, p: 6)
    monkeypatch.setattr(ss, "get_condition_state", lambda kw, c, s, p: {"predicted": 0, "last_page": 6})
    monkeypatch.setattr(ss, "update_last_page", lambda *a, **k: None)
    monkeypatch.setattr(sm, "map_salary", lambda s, p: s)
    monkeypatch.setattr(sm, "adapt_keyword", lambda k, p: k)

    async def fake_51(*a, **k):
        return 6

    async def fake_boss(*a, **k):
        return None

    monkeypatch.setattr(crawlers, "_run_51job_task", fake_51)
    monkeypatch.setattr(crawlers, "_run_boss_task", fake_boss)
    monkeypatch.setattr(crawlers, "_track_platform_task", lambda p, t: None)

    async def scenario():
        tasks = await crawlers.run_dispatch_collect(
            keyword="AI应用", city="广州", salary="15-20K", target_jobs=10,
            platforms=["51job", "boss"], master_task_id=None,
        )
        await asyncio.sleep(0.05)  # 等 stub 子任务跑完，避免悬空 task 告警
        return {t["platform"]: t["start_page"] for t in tasks}

    start_pages = asyncio.run(scenario())
    assert start_pages["51job"] == 6  # 原页重爬兜底
    assert start_pages["boss"] == 6   # 非 51job 同样原页重扫，补回页内提前停的页尾
