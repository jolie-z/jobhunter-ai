"""条件队列回归测试（2026-10-30 重构）。

覆盖：
1. 台账写入/读取统一使用标准条件 key（平台映射值只用于搜索）
2. hit_bottom / 连续 0 新增 / TTL 的抓尽状态机
3. 队列公平轮巡排序
4. 续抓页码：hit_bottom 归零、下次从第 1 页重开
5. 配置保存去重、单跑 override 尊重 limit=0
"""
import asyncio
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# controller 模块导入时会初始化 OpenAI client；测试环境给一个 dummy key
os.environ.setdefault("OPENAI_API_KEY", "test")
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.pipeline as pipeline_mod
import app.session.scrape_sessions as ss
from app.automation import scrape_runner
from app.pipeline.router import router


@pytest.fixture()
def ledger_db(tmp_path, monkeypatch):
    db = str(tmp_path / "ledger.db")
    monkeypatch.setattr(ss, "DB_PATH", db)
    monkeypatch.setattr(ss, "EXHAUSTION_TTL_SECONDS", 7 * 24 * 3600)
    ss.init_scrape_sessions_table()
    return db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "DB_PATH", str(tmp_path / "pipe.db"))
    monkeypatch.setattr(pipeline_mod, "_initialized", False)
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


# ─── 1. 台账 key 统一 ───

def test_standard_key_progress_visible(ledger_db):
    """标准 key 写入后，标准 key 能读到；映射 key 不再被写入。"""
    ss.report_condition_round("AI产品经理", "广州", "15-20K", "zhilian", 194, None)
    assert ss.get_condition_progress("AI产品经理", "广州", "15-20K", "zhilian") == (194, 0)
    assert ss.get_condition_progress("AI产品经理", "广州", "15K-25K", "zhilian") == (0, 0)


def test_dispatch_passes_original_condition_to_ledger(monkeypatch):
    """分发层把平台原生参数用于搜索，把原始条件用于台账 key。"""
    import app.api.routes.crawlers as crawlers_mod

    captured = {}

    async def fake_task(*args, **kwargs):
        captured["keyword"] = args[2]
        captured["salary"] = args[3]
        captured["start_page"] = args[4]
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(crawlers_mod, "_run_zhilian_task", fake_task)
    monkeypatch.setattr(ss, "get_last_page", lambda *a, **k: 0)
    monkeypatch.setattr(ss, "update_last_page", lambda *a, **k: None)

    async def run():
        await crawlers_mod.run_dispatch_collect(
            keyword="AI产品经理", city="广州", salary="15-20K", target_jobs=3,
            platforms=["zhilian"], master_task_id=None,
        )
        await asyncio.sleep(0.05)

    try:
        asyncio.run(run())
    finally:
        crawlers_mod._platform_running_tasks.pop("zhilian", None)
        crawlers_mod.running_platform_tasks.pop("zhilian", None)

    assert captured["salary"] == "15K-25K"        # 平台原生参数（用于搜索）
    assert captured["ledger_salary"] == "15-20K"  # 台账原始条件
    assert captured["ledger_keyword"] == "AI产品经理"
    assert captured["ledger_city"] == "广州"
    assert captured["start_page"] == 1            # last_page=0 → 从第 1 页开始


def test_dispatch_resumes_from_touched_page(monkeypatch):
    """非 51job 平台也从 last_page 重扫（不是 last_page+1），补回页内提前停的页尾。"""
    import app.api.routes.crawlers as crawlers_mod

    captured = {}

    async def fake_task(*args, **kwargs):
        captured["start_page"] = args[4]
        return {}

    monkeypatch.setattr(crawlers_mod, "_run_boss_task", fake_task)
    monkeypatch.setattr(ss, "get_last_page", lambda *a, **k: 7)
    monkeypatch.setattr(ss, "update_last_page", lambda *a, **k: None)

    async def run():
        await crawlers_mod.run_dispatch_collect(
            keyword="AI产品经理", city="广州", salary="15-20K", target_jobs=3,
            platforms=["boss"], master_task_id=None,
        )
        await asyncio.sleep(0.05)

    try:
        asyncio.run(run())
    finally:
        crawlers_mod._platform_running_tasks.pop("boss", None)
        crawlers_mod.running_platform_tasks.pop("boss", None)

    assert captured["start_page"] == 7


# ─── 2. 抓尽状态机 ───

def test_hit_bottom_marks_exhausted_and_ttl_reopens(ledger_db):
    # 9/10 ≥ 80%：真实抓尽仍应立即落账（低进度 hit_bottom 由下方用例锁定为不落账）
    ss.report_condition_round("K", "广州", "不限", "boss", 9, 10, hit_bottom=True)
    assert ss.is_condition_exhausted("K", "广州", "不限", "boss") is True

    conn = sqlite3.connect(ledger_db)
    old = (datetime.now() - timedelta(seconds=ss.EXHAUSTION_TTL_SECONDS + 60)).isoformat()
    conn.execute("UPDATE scrape_sessions SET exhausted_at=? WHERE keyword='K'", (old,))
    conn.commit()
    conn.close()

    assert ss.is_condition_exhausted("K", "广州", "不限", "boss") is False
    state = ss.get_condition_state("K", "广州", "不限", "boss")
    assert state["exhausted"] is False
    assert state["no_new_rounds"] == 0


def test_hit_bottom_low_progress_does_not_exhaust(ledger_db):
    """低进度 hit_bottom 不落抓尽：陈旧游标/页面加载失败也会触发底部信号。

    2026-10-31 51job 事故：last_page=121 越界，条件只抓了 66/644 就被标记抓尽，
    随后被 TTL 跳过 7 天。进度不足 80% 时只累加 no_new_rounds，等连续 0 新增
    兜底或分子追平分母后再落账。
    """
    ss.report_condition_round("K_low", "广州", "不限", "51job", 0, 10, hit_bottom=True)
    state = ss.get_condition_state("K_low", "广州", "不限", "51job")
    assert state["scraped"] == 0
    assert state["exhausted"] is False
    assert state["no_new_rounds"] == 1


def test_hit_bottom_with_inserts_still_exhausts(ledger_db):
    """到底页即使有新增也应抓尽：hit_bottom 优先于 inserted>0 的重开分支。"""
    ss.report_condition_round("K8", "广州", "不限", "boss", 9, 10, hit_bottom=True)
    state = ss.get_condition_state("K8", "广州", "不限", "boss")
    assert state["scraped"] == 9
    assert state["exhausted"] is True


def test_ttl_env_override_expires(ledger_db, monkeypatch):
    """TTL 环境变量覆盖生效：0 秒时抓尽状态立即过期重开。"""
    monkeypatch.setattr(ss, "EXHAUSTION_TTL_SECONDS", 0)
    ss.report_condition_round("K9", "广州", "不限", "boss", 9, 10, hit_bottom=True)
    assert ss.is_condition_exhausted("K9", "广州", "不限", "boss") is False


def test_ttl_reopen_resets_last_page(ledger_db):
    """TTL 重开必须从第 1 页开始，否则会从越过的末页继续抓空页。"""
    ss.report_condition_round("K7", "广州", "不限", "boss", 9, 10, hit_bottom=True)
    ss.update_last_page("K7", "广州", "不限", "boss", 18)

    conn = sqlite3.connect(ledger_db)
    old = (datetime.now() - timedelta(seconds=ss.EXHAUSTION_TTL_SECONDS + 60)).isoformat()
    conn.execute("UPDATE scrape_sessions SET exhausted_at=? WHERE keyword='K7'", (old,))
    conn.commit()
    conn.close()

    state = ss.get_condition_state("K7", "广州", "不限", "boss")
    assert state["exhausted"] is False
    assert state["last_page"] == 0
    assert ss.get_last_page("K7", "广州", "不限", "boss") == 0


def test_consecutive_zero_new_exhausts(ledger_db):
    for _ in range(ss.NO_NEW_EXHAUST_ROUNDS):
        ss.report_condition_round("K2", "广州", "不限", "boss", 0, None, success=True)
    assert ss.is_condition_exhausted("K2", "广州", "不限", "boss") is True


def test_failed_rounds_do_not_exhaust(ledger_db):
    for _ in range(ss.NO_NEW_EXHAUST_ROUNDS + 2):
        ss.report_condition_round("K3", "广州", "不限", "boss", 0, None, success=False)
    assert ss.is_condition_exhausted("K3", "广州", "不限", "boss") is False


def test_new_insert_reopens_exhausted(ledger_db):
    ss.report_condition_round("K4", "广州", "不限", "boss", 0, None, hit_bottom=True)
    assert ss.is_condition_exhausted("K4", "广州", "不限", "boss") is True
    ss.report_condition_round("K4", "广州", "不限", "boss", 1, None, success=True)
    assert ss.is_condition_exhausted("K4", "广州", "不限", "boss") is False


def test_list_progress_includes_exhausted(ledger_db):
    ss.report_condition_round("K6", "广州", "不限", "boss", 0, None, hit_bottom=True)
    row = next(r for r in ss.list_condition_progress() if r["keyword"] == "K6")
    assert row["exhausted"] is True


# ─── 3. 公平轮巡排序 ───

def test_zhilian_page_marker_only_matches_protocol_lines():
    """智联续抓页码只认采集器协议行，普通日志里的“第 N 页”不得污染。"""
    import sys
    from pathlib import Path

    zhilian_dir = Path(__file__).resolve().parents[1] / "zhilian_scraper"
    if str(zhilian_dir) not in sys.path:
        sys.path.insert(0, str(zhilian_dir))
    import zhilian_nl_controller as z

    assert z._parse_page_marker("🔄 [瀑布流滚动] 正在向下滑动加载新岗位 (第 3 批)...") == 3
    assert z._parse_page_marker("🎯 正在通过 URL 直达跳转到指定的起始页: 第 4 页 (http://x)") == 4
    assert z._parse_page_marker("🔄 页面疑似卡死 (目标第 5 页无反应)，执行【URL直达刷新】") == 5
    assert z._parse_page_marker("⏩ [极速跃迁] 第 6 批 (10/10 岗位均已在库)") == 6
    assert z._parse_page_marker("随便一条日志：第 99 页") is None
    assert z._parse_page_marker("🏁 [抓尽收工] 连续 20 批均无新增岗位") is None


def test_order_active_conditions_oldest_first():
    rows = [
        (0, "a", "", "", {"last_run": "2026-10-30T10:00:00"}),
        (1, "b", "", "", {"last_run": ""}),
        (2, "c", "", "", {"last_run": "2026-10-29T10:00:00"}),
    ]
    assert [r[0] for r in scrape_runner._order_active_conditions(rows)] == [1, 2, 0]


def test_worker_splits_budget_across_all_conditions(ledger_db, monkeypatch):
    """cap=3、3 个条件：每个条件至少分到 1 条，而不是队首吃满。"""
    import app.api.routes.crawlers as crawlers_mod
    from app.automation import abort as abort_mod
    from app.automation import pipeline_broadcast as pb
    from app.automation import platform_mutex

    queue = [
        {"keyword": "条件A", "city": "广州", "salary": "15-20K"},
        {"keyword": "条件B", "city": "广州", "salary": "15-20K"},
        {"keyword": "条件C", "city": "广州", "salary": "15-20K"},
    ]
    dispatched = []
    counter = {"inserted": 0}

    async def fake_dispatch(*, keyword, city, salary, target_jobs, platforms, master_task_id, platform_search):
        dispatched.append((keyword, target_jobs))
        counter["inserted"] += 1
        ss.report_condition_round(keyword, city, salary, platforms[0], 1, None, success=True)

    async def _ok(*a, **k):
        return True

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(crawlers_mod, "run_dispatch_collect", fake_dispatch)
    monkeypatch.setattr(crawlers_mod, "running_platform_tasks", {})
    monkeypatch.setattr(platform_mutex, "wait_delivery_clear", _ok)
    monkeypatch.setattr(pb, "emit_log", _noop)
    monkeypatch.setattr(abort_mod, "is_aborted", lambda: False)
    monkeypatch.setattr(abort_mod, "is_platform_aborted", lambda _p: False)

    asyncio.run(
        scrape_runner._run_platform_condition_worker(
            "boss",
            pipeline_task_id="t",
            queue=queue,
            budgets={"boss": 3},
            default_city="广州",
            default_salary="15-20K",
            start_rowid=0,
            count_new=lambda: {"BOSS直聘": counter["inserted"]},
            emit_scraped_jobs=_noop,
            budget_label="剩余预算",
        )
    )

    assert [k for k, _ in dispatched] == ["条件A", "条件B", "条件C"]
    assert [t for _, t in dispatched] == [1, 1, 1]


def test_worker_stops_after_all_zero_new(ledger_db, monkeypatch):
    """全部条件 0 新增时每个只跑一次就收工，不因 cap 未耗尽而死循环。"""
    import app.api.routes.crawlers as crawlers_mod
    from app.automation import abort as abort_mod
    from app.automation import pipeline_broadcast as pb
    from app.automation import platform_mutex

    queue = [
        {"keyword": "条件A", "city": "广州", "salary": "15-20K"},
        {"keyword": "条件B", "city": "广州", "salary": "15-20K"},
    ]
    dispatched = []

    async def fake_dispatch(*, keyword, city, salary, target_jobs, platforms, master_task_id, platform_search):
        dispatched.append(keyword)
        ss.report_condition_round(keyword, city, salary, platforms[0], 0, None, success=True)

    async def _ok(*a, **k):
        return True

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(crawlers_mod, "run_dispatch_collect", fake_dispatch)
    monkeypatch.setattr(crawlers_mod, "running_platform_tasks", {})
    monkeypatch.setattr(platform_mutex, "wait_delivery_clear", _ok)
    monkeypatch.setattr(pb, "emit_log", _noop)
    monkeypatch.setattr(abort_mod, "is_aborted", lambda: False)
    monkeypatch.setattr(abort_mod, "is_platform_aborted", lambda _p: False)

    asyncio.run(
        scrape_runner._run_platform_condition_worker(
            "boss",
            pipeline_task_id="t",
            queue=queue,
            budgets={"boss": 2},
            default_city="广州",
            default_salary="15-20K",
            start_rowid=0,
            count_new=lambda: {"BOSS直聘": 0},
            emit_scraped_jobs=_noop,
            budget_label="剩余预算",
        )
    )

    assert dispatched == ["条件A", "条件B"]


# ─── 4. 续抓页码 ───

def test_zero_last_page_restarts_at_one(ledger_db):
    ss.update_last_page("K5", "广州", "不限", "boss", 0)
    assert ss.get_last_page("K5", "广州", "不限", "boss") == 0


def test_run_and_track_hit_bottom_resets_page(monkeypatch):
    import app.api.routes.crawlers as crawlers_mod

    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda *a: calls.append(a))

    async def fake():
        return {"last_page": 0, "hit_bottom": True}

    asyncio.run(crawlers_mod._run_and_track(fake(), "t", "K", "广州", "不限", "boss", 5))
    assert calls and calls[-1][-1] == 0


def test_run_and_track_failed_round_keeps_start_page(monkeypatch):
    """失败轮（success=False）不能把 last_page 推进到崩溃页，下一轮从起点重扫。"""
    import app.api.routes.crawlers as crawlers_mod

    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda *a: calls.append(a))

    async def fake():
        return {"last_page": 9, "hit_bottom": False, "success": False}

    asyncio.run(crawlers_mod._run_and_track(fake(), "t", "K", "广州", "不限", "boss", 5))
    assert calls and calls[-1][-1] == 5


def test_run_and_track_legacy_int_result(monkeypatch):
    """兼容旧式 int 返回（51job 旁路/测试替身）。"""
    import app.api.routes.crawlers as crawlers_mod

    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda *a: calls.append(a))

    async def fake():
        return 6

    asyncio.run(crawlers_mod._run_and_track(fake(), "t", "K", "广州", "不限", "boss", 3))
    assert calls and calls[-1][-1] == 6


def test_run_and_track_none_result_keeps_start(monkeypatch):
    """None/异常返回不推进页码，保留本轮起点。"""
    import app.api.routes.crawlers as crawlers_mod

    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda *a: calls.append(a))

    async def fake():
        return None

    asyncio.run(crawlers_mod._run_and_track(fake(), "t", "K", "广州", "不限", "boss", 3))
    assert calls and calls[-1][-1] == 3


def test_run_and_track_empty_dict_keeps_start(monkeypatch):
    """预运行崩溃/空 result_meta：不推进页码，保留本轮起点。"""
    import app.api.routes.crawlers as crawlers_mod

    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda *a: calls.append(a))

    async def fake():
        return {}

    asyncio.run(crawlers_mod._run_and_track(fake(), "t", "K", "广州", "不限", "boss", 3))
    assert calls and calls[-1][-1] == 3


def test_run_and_track_missing_success_advances(monkeypatch):
    """dict 缺 success 键时按成功处理，推进真实末页。"""
    import app.api.routes.crawlers as crawlers_mod

    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda *a: calls.append(a))

    async def fake():
        return {"last_page": 8, "hit_bottom": False}

    asyncio.run(crawlers_mod._run_and_track(fake(), "t", "K", "广州", "不限", "boss", 3))
    assert calls and calls[-1][-1] == 8


def test_boss_controller_reports_with_ledger_key(monkeypatch):
    """controller 层必须用 ledger_keyword/ledger_salary 写台账，而不是平台映射值。"""
    import boss_scraper.boss_nl_controller as boss

    recorded = {}
    monkeypatch.setattr(boss, "_run_single_page", lambda *a, **k: (0, True, 0, None, False))

    def fake_report(keyword, city, salary, platform, inserted, predicted=None, **kwargs):
        recorded.update(
            {"keyword": keyword, "city": city, "salary": salary, "platform": platform, **kwargs}
        )

    monkeypatch.setattr(ss, "report_condition_round", fake_report)
    boss.run_task(
        "AI产品经理", "广州", 1, 1, "15K-25K",
        ledger_keyword="AI产品经理", ledger_city="广州", ledger_salary="15-20K",
    )

    assert recorded["keyword"] == "AI产品经理"
    assert recorded["salary"] == "15-20K"
    assert recorded["platform"] == "boss"


def test_boss_target_zero_does_not_report(monkeypatch):
    """target<=0 不是抓取轮次，不能回报台账（否则连续空跑会误判抓尽）。"""
    import boss_scraper.boss_nl_controller as boss

    called = []
    monkeypatch.setattr(ss, "report_condition_round", lambda *a, **k: called.append(1))

    assert boss.run_task("AI产品经理", "广州", 1, 0, "不限") == 0
    assert not called


def test_zhilian_controller_reports_with_ledger_key(monkeypatch):
    """智联 controller 也必须用 ledger 条件写台账（原 P0 的智联分支）。"""
    import zhilian_scraper.zhilian_nl_controller as zhilian

    class _DummyProc:
        returncode = 0

        def wait(self):
            return 0

    recorded = {}
    monkeypatch.setattr(zhilian, "popen_hidden", lambda *a, **k: _DummyProc())
    monkeypatch.setattr(zhilian, "_handle_process_stdout", lambda *a, **k: (0, 0, False, 3))
    monkeypatch.setattr(zhilian, "GLOBAL_STOP_FLAG", False)

    def fake_report(keyword, city, salary, platform, inserted, predicted=None, **kwargs):
        recorded.update(
            {"keyword": keyword, "city": city, "salary": salary, "platform": platform, **kwargs}
        )

    monkeypatch.setattr(ss, "report_condition_round", fake_report)

    meta = {}
    zhilian.run_task(
        "AI产品经理", "广州", 3, 1, "15K-25K",
        ledger_keyword="AI产品经理", ledger_city="广州", ledger_salary="15-20K",
        result_meta=meta,
    )

    assert recorded["salary"] == "15-20K"
    assert recorded["platform"] == "zhilian"
    assert meta["last_page"] == 3
    assert meta["hit_bottom"] is False


def test_collector_bottom_markers_match_controllers():
    """collector 的到底信号是 controller 的隐式契约，改信号必须同步改 controller。

    51job 自 2026-10-31 起改用结构化哨兵，不再依赖人类可读文案（旧“无任何岗位数据”
    同时出现在超时提示里，曾把网络抖动误判成平台到底）。
    """
    root = Path(__file__).resolve().parents[1]
    checks = {
        "boss_scraper/boss_collector.py": ["无数据返回，可能已到底部"],
        "51job_scraper/51job_collector.py": ["[[HIT_BOTTOM]]", "[[PAGE_LOAD_FAILED]]"],
        "zhilian_scraper/zhilian_collector.py": ["到达最后一页/底部", "抓尽收工"],
        "liepin_scraper/liepin_crawler.py": ["未截获到包含"],
    }
    for rel, markers in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{rel} missing bottom marker: {marker}"


def test_liepin_ambiguous_bottom_keeps_page(monkeypatch):
    """猎聘到底信号可能是验证码：台账和页码都不能当确认到底，页码保留真实末页。"""
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    import liepin_scraper.liepin_nl_controller as liepin

    class _DummyProc:
        returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr(liepin, "popen_hidden", lambda *a, **k: _DummyProc())
    monkeypatch.setattr(liepin, "_process_crawler_output", lambda *a, **k: (0, True, 0))
    monkeypatch.setattr(liepin, "countdown_sleep", lambda n: None)
    monkeypatch.setattr(liepin, "GLOBAL_STOP_FLAG", False)
    monkeypatch.setattr(ss, "report_condition_round", lambda *a, **k: None)

    meta = {}
    liepin.run_task("AI产品经理", "广州", 5, 1, "15-20K", result_meta=meta)

    assert meta["hit_bottom"] is False   # 台账/页码口径一致：不当确认到底
    assert meta["last_page"] == 5        # 保留真实末页，不归零重扫
    assert meta["success"] is True


# ─── 5. 配置去重 / limit 解析 ───

def test_save_config_dedupes(client):
    body = {
        "keywords": [
            {"keyword": "AI产品经理", "city": "广州", "salary": "15-20K"},
            {"keyword": "ai产品经理", "city": "广州", "salary": "15-20K"},  # 大小写重复
            {"keyword": "AI产品经理", "city": "深圳", "salary": "15-20K"},  # 城市不同，保留
        ],
        "platforms": {},
        "default_city": "",
        "default_salary": "",
    }
    r = client.put("/api/pipeline/scrape-config", json=body)
    assert r.status_code == 200
    saved = client.get("/api/pipeline/scrape-config").json()["data"]["keywords"]
    assert len(saved) == 2
    assert saved[0]["keyword"] == "AI产品经理"
    assert saved[1]["city"] == "深圳"


def test_resolve_limits_explicit_all_off_does_not_fall_back():
    cfg = {"platforms": {"boss": {"enabled": True, "limit": 0}, "zhilian": {"enabled": False, "limit": 3}}}
    assert scrape_runner._resolve_platform_limits(cfg, {"platforms": ["boss"], "target_jobs": 5}) == {}


def test_resolve_limits_falls_back_only_without_platform_section():
    assert scrape_runner._resolve_platform_limits(
        {}, {"platforms": ["boss", "liepin"], "target_jobs": 5}
    ) == {"boss": 5, "liepin": 5}


def test_resolve_limits_override_respects_zero():
    cfg = {"platforms": {"boss": {"enabled": True, "limit": 0}, "zhilian": {"enabled": True, "limit": 3}}}
    assert scrape_runner._resolve_platform_limits(cfg, {}, override_limit=3) == {"zhilian": 3}
