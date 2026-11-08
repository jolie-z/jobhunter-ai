"""51job 底部信号 / 陈旧游标回归测试（2026-10-31）。

事故链：
1. 旧采集器守卫裸 return（退出码 0）→ 控制器把失败页当成功推进 → last_page=122；
2. 10-31 从 121 页开始，页面加载超时，超时文案里的“无任何岗位数据”被控制器
   子串匹配成 hit_bottom；
3. 台账 hit_bottom=True → exhausted_at 立即写入 → 条件被 TTL 跳过 7 天。

本文件锁定：
- 只认结构化哨兵 [[HIT_BOTTOM]] / [[PAGE_LOAD_FAILED]]，不再匹配人类文案；
- 非首页 + 0 入库的“到底”判为陈旧游标，不标记抓尽，游标重置为 0；
- 页面加载失败按失败轮处理，非首页同时重置游标；
- 派发前对越界游标做硬校验。
"""
import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest

import app.api.routes.crawlers as crawlers
import app.session.registry as registry
import app.session.scrape_sessions as ss


def _load_controller():
    subdir, mod_name = crawlers._PLATFORM_STOP_MODULES["51job"]
    mod_dir = f"{crawlers.PROJECT_ROOT}/{subdir}"
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)
    return importlib.import_module(mod_name)


def _load_collector():
    subdir, _ = crawlers._PLATFORM_STOP_MODULES["51job"]
    mod_dir = f"{crawlers.PROJECT_ROOT}/{subdir}"
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)
    return importlib.import_module("51job_collector")


class _FakeSearchPage:
    """只实现 navigate_to_target_page 用到的 3 个方法。"""

    def __init__(self, click_ok=False, raise_eval=False):
        self.click_ok = click_ok
        self.raise_eval = raise_eval

    def evaluate(self, _js):
        if self.raise_eval:
            raise RuntimeError("page crashed")
        return self.click_ok

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, *_a, **_k):
        pass


def test_collector_emits_hit_bottom_when_next_disabled(capsys):
    mod = _load_collector()
    assert mod.navigate_to_target_page(_FakeSearchPage(click_ok=False), 2, []) is False
    assert "[[HIT_BOTTOM]]" in capsys.readouterr().out


def test_collector_emits_page_load_failed_on_nav_exception(capsys):
    mod = _load_collector()
    assert mod.navigate_to_target_page(_FakeSearchPage(raise_eval=True), 2, []) is False
    assert "[[PAGE_LOAD_FAILED]]" in capsys.readouterr().out


# ─── 1.5 真实空结果 vs 加载失败（复审 P1） ───

def test_confirmed_empty_search_is_hit_bottom():
    """API 已应答且 items=[] + total=0：真实 0 命中，必须判到底，否则永不抓尽。"""
    mod = _load_collector()
    data = [{"resultbody": {"job": {"items": [], "totalCount": 0}}}]
    assert mod._is_confirmed_empty_search(data) is True
    assert mod._empty_result_marker(data) == "[[HIT_BOTTOM]]"


def test_missing_api_data_is_page_load_failed():
    mod = _load_collector()
    assert mod._is_confirmed_empty_search([]) is False
    assert mod._empty_result_marker([]) == "[[PAGE_LOAD_FAILED]]"


def test_empty_items_with_positive_total_is_not_bottom():
    """API 说还有结果但 items 为空：更像解析异常/风控，不是真底部。"""
    mod = _load_collector()
    data = [{"resultbody": {"job": {"items": [], "totalCount": 100}}}]
    assert mod._is_confirmed_empty_search(data) is False
    assert mod._empty_result_marker(data) == "[[PAGE_LOAD_FAILED]]"


def test_empty_items_without_job_node_is_not_bottom():
    mod = _load_collector()
    data = [{"resultbody": {"other": {}}}]
    assert mod._is_confirmed_empty_search(data) is False
    assert mod._empty_result_marker(data) == "[[PAGE_LOAD_FAILED]]"


@pytest.fixture(autouse=True)
def _reset_stop_flag():
    mod = _load_controller()
    mod.set_stop_flag(False)
    yield
    mod.set_stop_flag(False)


class _Proc:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


# ─── 1. 结构化哨兵 ───

def test_process_output_only_trusts_structured_bottom_sentinel():
    mod = _load_controller()

    out = mod._process_crawler_output(
        _Proc(["[[HIT_BOTTOM]]\n"]), 5, 0, 1, None
    )
    assert out == (0, True, 0, False, False)


def test_process_output_only_trusts_structured_load_failed_sentinel():
    mod = _load_controller()

    out = mod._process_crawler_output(
        _Proc(["[[PAGE_LOAD_FAILED]]\n"]), 5, 0, 121, None
    )
    assert out == (0, False, 0, False, True)


def test_old_timeout_copy_no_longer_means_hit_bottom():
    """旧文案“无任何岗位数据”不得再触发底部（10-31 误判根因）。"""
    mod = _load_controller()

    out = mod._process_crawler_output(
        _Proc(["      ⚠️ 页面加载超时，可能网络卡顿或该关键词无任何岗位数据。\n"]),
        5, 0, 121, None,
    )
    assert out == (0, False, 0, False, False)


# ─── 2. run_task：陈旧游标 / 加载失败 ───

def test_suspicious_bottom_on_resume_page_does_not_mark_hit_bottom(monkeypatch):
    mod = _load_controller()
    captured = {}

    monkeypatch.setattr(mod, "_build_crawler_cmd", lambda *a, **k: ["true"])
    monkeypatch.setattr(mod, "popen_hidden", lambda *a, **k: _Proc([]))
    monkeypatch.setattr(mod, "_process_crawler_output", lambda *a, **k: (0, True, 0, False, False))
    monkeypatch.setattr(mod, "countdown_sleep", lambda n: None)

    def fake_report(*_a, **k):
        captured.update(k)

    monkeypatch.setattr(ss, "report_condition_round", fake_report)

    meta = {}
    total, last = mod.run_task("AI应用", "广州", 121, 5, "15-20K", result_meta=meta)

    assert total == 0
    assert last == 0
    assert meta["hit_bottom"] is False
    assert meta["stale_cursor"] is True
    assert meta["last_page"] == 0
    assert captured.get("hit_bottom") is False


def test_page_load_failure_on_resume_page_resets_cursor(monkeypatch):
    mod = _load_controller()
    captured = {}

    monkeypatch.setattr(mod, "_build_crawler_cmd", lambda *a, **k: ["true"])
    monkeypatch.setattr(mod, "popen_hidden", lambda *a, **k: _Proc([]))
    monkeypatch.setattr(mod, "_process_crawler_output", lambda *a, **k: (0, False, 0, False, True))
    monkeypatch.setattr(mod, "countdown_sleep", lambda n: None)
    monkeypatch.setattr(ss, "report_condition_round", lambda *_a, **k: captured.update(k))

    meta = {}
    total, last = mod.run_task("AI应用", "广州", 121, 5, "15-20K", result_meta=meta)

    assert total == 0
    assert meta["page_load_failed"] is True
    assert meta["stale_cursor"] is True
    assert meta["last_page"] == 0
    assert meta["success"] is False
    assert captured.get("success") is False


# ─── 3. 派发前越界游标校验 ───

def test_resume_start_page_resets_out_of_range_cursor(monkeypatch):
    monkeypatch.setattr(ss, "get_last_page", lambda *a, **k: 121)
    monkeypatch.setattr(ss, "get_condition_state", lambda *a, **k: {"predicted": 644, "last_page": 121})
    monkeypatch.setattr(registry, "resolve_platform", lambda p: SimpleNamespace(resume_mode="rescan_last"))

    assert crawlers._resume_start_page("51job", "AI产品经理", "广州", "15-20K") == 1


def test_resume_start_page_keeps_valid_cursor(monkeypatch):
    monkeypatch.setattr(ss, "get_last_page", lambda *a, **k: 5)
    monkeypatch.setattr(ss, "get_condition_state", lambda *a, **k: {"predicted": 644, "last_page": 5})
    monkeypatch.setattr(registry, "resolve_platform", lambda p: SimpleNamespace(resume_mode="rescan_last"))

    assert crawlers._resume_start_page("51job", "AI产品经理", "广州", "15-20K") == 5


def test_resume_start_page_honors_next_page_mode(monkeypatch):
    monkeypatch.setattr(ss, "get_last_page", lambda *a, **k: 5)
    monkeypatch.setattr(ss, "get_condition_state", lambda *a, **k: {"predicted": 0})
    monkeypatch.setattr(registry, "resolve_platform", lambda p: SimpleNamespace(resume_mode="next_page"))

    assert crawlers._resume_start_page("boss", "AI产品经理", "广州", "15-20K") == 6


def test_resume_start_page_uses_state_last_page_after_ttl_reopen(monkeypatch):
    """TTL 重开会在 get_condition_state 内把 last_page 归零，必须用返回态而不是旧值。"""
    monkeypatch.setattr(ss, "get_last_page", lambda *a, **k: 18)
    monkeypatch.setattr(ss, "get_condition_state", lambda *a, **k: {"predicted": 644, "last_page": 0})
    monkeypatch.setattr(registry, "resolve_platform", lambda p: SimpleNamespace(resume_mode="rescan_last"))

    assert crawlers._resume_start_page("51job", "AI产品经理", "广州", "15-20K") == 1


# ─── 4. _run_and_track：stale_cursor 优先归零 ───

def test_run_and_track_stale_cursor_forces_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(ss, "update_last_page", lambda kw, c, s, p, lp: calls.append((p, lp)))

    async def returns_stale():
        return {"last_page": 0, "hit_bottom": False, "stale_cursor": True, "success": True}

    asyncio.run(crawlers._run_and_track(
        returns_stale(), "t1", "AI应用", "广州", "15-20K", "51job", 121
    ))

    assert calls == [("51job", 0)]


# ─── 5. 采集器智能等待与 API 优先放行（2026-11-01） ───

def test_has_valid_api_data_with_items():
    mod = _load_collector()
    data = [{"resultbody": {"job": {"items": [{"jobName": "AI工程师"}]}}}]
    assert mod._has_valid_api_data(data) is True


def test_has_valid_api_data_with_confirmed_empty():
    mod = _load_collector()
    data = [{"resultbody": {"job": {"items": [], "totalCount": 0}}}]
    assert mod._has_valid_api_data(data) is True


def test_has_valid_api_data_with_malformed_data():
    mod = _load_collector()
    assert mod._has_valid_api_data([]) is False
    assert mod._has_valid_api_data([{}]) is False
    assert mod._has_valid_api_data([{"resultbody": {}}]) is False


class _MockPageWithSelector:
    def __init__(self, selector_ok=True):
        self.selector_ok = selector_ok

    def wait_for_selector(self, selector, timeout=0):
        if not self.selector_ok:
            raise RuntimeError("timeout")


def test_wait_for_search_ready_api_first(capsys):
    mod = _load_collector()
    data = [{"resultbody": {"job": {"items": [{"jobName": "测试"}]}}}]
    # 模拟 DOM 选择器永远超时的极端情况，验证 API 优先放行
    mock_page = _MockPageWithSelector(selector_ok=False)
    ready = mod._wait_for_search_ready(mock_page, data, target_page=1, timeout_ms=500)
    assert ready is True
    assert "优先放行数据处理" in capsys.readouterr().out


def test_wait_for_search_ready_timeout():
    mod = _load_collector()
    mock_page = _MockPageWithSelector(selector_ok=False)
    ready = mod._wait_for_search_ready(mock_page, [], target_page=1, timeout_ms=200)
    assert ready is False

