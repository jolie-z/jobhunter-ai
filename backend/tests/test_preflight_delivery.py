"""批次级投递预检 ensure_delivery_platforms_ready 单测（2026-10-08）。

全 mock（探活/拉起/登录判定/Cookie 注入/飞书通知），不真开浏览器、不真发飞书。
覆盖：拉起路径、僵尸自愈重启、等待窗口内扫码恢复（CDP 实时判定）、超时跳过。

⚠️ 2026-10-23 修复：曾有 3 个用例只把 check_liepin_login_evidence mock 成 False 而
漏桩 liepin_session——_judge_with_injection 会真调 liepin_session.inject_cookies_if_needed()
→ ChromiumPage 在 9226 端口无浏览器时被 DrissionPage 自动拉起猎聘 Edge 并导航
www/c.liepin.com（全量跑时真模块已被其他测试文件导入缓存，import 必成功；单独跑时
靠 import 失败侥幸跳过，故表现为「全量跑必拉起浏览器 + 用例 flaky」）。
凡触发注入分支的用例，必须经 _stub_liepin_session 打桩。
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.session import preflight
from app.session.models import SessionState, SessionStatus


def test_ensure_liepin_import_path_adds_scraper_dir(monkeypatch):
    """安装版预检跑在 scraper 目录入 sys.path 之前，裸 import liepin_session 必失败。

    2026-10-30 真机：投递预检日志 `No module named 'liepin_session'`，Cookie 注入
    自愈分支从未执行。此用例锁定路径注入（append 语义，不抢占 sys.path[0]）。
    """
    scraper_dir = str(_BACKEND_ROOT / "liepin_scraper")
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != scraper_dir])
    preflight._ensure_liepin_import_path()
    assert scraper_dir in sys.path


def _status(state: SessionState, message: str = "test") -> SessionStatus:
    return SessionStatus(platform="test", state=state, message=message)


def _cfg(name: str = "liepin"):
    cfg = MagicMock()
    cfg.name = name
    cfg.display_name = name
    cfg.port = 9226
    cfg.profile_dir = "/fake/profile"
    return cfg


def _stub_liepin_session(monkeypatch, inject_result: bool = False) -> dict:
    """打桩 liepin_session 模块：inject_cookies_if_needed 返回固定结果并计数。

    preflight._judge_with_injection 经 `import liepin_session` 惰性导入真引擎；
    全量跑时真模块已在 sys.modules 缓存（其他测试文件先导入），必须整体替换，
    否则真引擎的 ChromiumPage 会在 9226 端口无浏览器时自动拉起猎聘 Edge。
    """
    calls = {"n": 0}

    class _FakeLiepinSession:
        @staticmethod
        def inject_cookies_if_needed():
            calls["n"] += 1
            return inject_result

    monkeypatch.setitem(sys.modules, "liepin_session", _FakeLiepinSession)
    return calls


@pytest.fixture
def fast_wait(monkeypatch):
    """等待窗口与轮询全部缩到最短，测试不真等；并清空 TTL 成功缓存防用例串扰。"""
    monkeypatch.setattr(preflight, "_wait_seconds", lambda: 1)
    monkeypatch.setattr(preflight, "_poll_seconds", lambda: 1)
    monkeypatch.setattr("app.automation.abort.is_aborted", lambda: False)
    preflight._ready_cache.clear()


@pytest.fixture(autouse=True)
def clear_ready_cache():
    """TTL 成功缓存与失败冷却都是模块级状态：用例前后清空，杜绝跨用例串扰。"""
    preflight._ready_cache.clear()
    preflight._notready_until.clear()
    yield
    preflight._ready_cache.clear()
    preflight._notready_until.clear()


@pytest.fixture(autouse=True)
def _stub_browser_lifecycle(monkeypatch):
    """浏览器生命周期已下沉到 browser.ensure_browser_ready_sync（2026-10-31）。

    投递预检测试聚焦登录判定/等待窗口，统一打桩浏览器就绪；生命周期本身由
    tests/test_browser_lifecycle_2026_10_31.py 覆盖。需要特定重启路径的用例
    可在用例内再次 monkeypatch 覆盖本桩。
    """
    monkeypatch.setattr(
        preflight, "ensure_browser_ready_sync",
        lambda cfg, **k: (True, "alive"),
    )


@pytest.mark.asyncio
async def test_browser_down_launches_then_login_ok(monkeypatch, fast_wait):
    """浏览器未运行 → 自动拉起 → 登录实证通过 → 平台可用。"""
    launched = []
    monkeypatch.setattr(
        preflight, "ensure_browser_ready_sync",
        lambda cfg, **k: (launched.append(cfg.name) or (True, "launched")),
    )
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: True)

    res = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert res == {"liepin": True}
    assert launched == ["liepin"]


@pytest.mark.asyncio
async def test_zombie_browser_restarts_once(monkeypatch, fast_wait):
    """端口通但 CDP 通道僵死 → 生命周期层优雅重启（51job 2026-10-08 事故路径）。

    具体 probe/close/launch 序列由 test_browser_lifecycle_2026_10_31.py 覆盖；
    本用例确认投递预检确实调用了生命周期入口并继续走登录判定。
    """
    calls = []
    monkeypatch.setattr(
        preflight, "ensure_browser_ready_sync",
        lambda cfg, **k: (calls.append(cfg.name) or (True, "zombie_restarted")),
    )
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: True)
    monkeypatch.setattr(preflight, "asyncio", preflight.asyncio)  # 保持引用
    monkeypatch.setattr(preflight.asyncio, "sleep", _fast_sleep)

    res = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert res == {"liepin": True}
    assert calls == ["liepin"]


@pytest.mark.asyncio
async def test_wait_window_recovers_via_cdp_live_judgement(monkeypatch, fast_wait):
    """登录失效 → 注入救不回 → 飞书通知 + 等待窗口；窗口内复检走 check_liepin_login_evidence
    （端口 UP 时 CDP 直读内存 cookie）→ 用户扫码即时感知恢复。"""
    # 三次实证判定：初判失效 → 注入后复测仍失效（才进等待窗口）→ 窗口内复检恢复
    evidence_results = iter([False, False, True])
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: next(evidence_results))
    inject_calls = _stub_liepin_session(monkeypatch, inject_result=False)
    notify = AsyncMock()
    monkeypatch.setattr(preflight, "_notify_login_needed", notify)

    res = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert res == {"liepin": True}
    notify.assert_awaited_once()  # 注入未恢复 → 进过等待窗口，发过一条飞书汇总
    assert inject_calls["n"] == 1  # 注入真实被尝试且仅一次（打桩防真拉起浏览器）


@pytest.mark.asyncio
async def test_wait_window_timeout_skips_platform(monkeypatch, fast_wait):
    """等待超时仍未登录 → 平台不可用（调用方跳过其岗位，保留「待投递」）。"""
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    inject_calls = _stub_liepin_session(monkeypatch, inject_result=False)
    monkeypatch.setattr(preflight, "_notify_login_needed", AsyncMock())

    res = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert res == {"liepin": False}
    assert inject_calls["n"] == 1  # 超时前注入被尝试且仅一次（打桩防真拉起浏览器）


@pytest.mark.asyncio
async def test_dom_platforms_use_check_login_with_fallback(monkeypatch, fast_wait):
    """非猎聘平台走 check_login_with_fallback（DOM+cookie 兜底），判定 DEGRADED/HEALTHY 放行。"""
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(
        preflight, "check_login_with_fallback",
        lambda cfg, page_factory=None: _status(SessionState.DEGRADED, "cookie 兜底"),
    )

    res = await preflight.ensure_delivery_platforms_ready(["boss"])
    assert res == {"boss": True}


@pytest.mark.asyncio
async def test_ttl_cache_skips_reprobe_within_window(monkeypatch, fast_wait):
    """成功 TTL 缓存：TTL 内同平台二次调用免重探（delivery_node 逐岗接线的成本保障）。"""
    lifecycle_calls = {"n": 0}
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(
        preflight, "ensure_browser_ready_sync",
        lambda cfg, **k: (lifecycle_calls.__setitem__("n", lifecycle_calls["n"] + 1) or (True, "alive")),
    )
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: True)

    res1 = await preflight.ensure_delivery_platforms_ready(["liepin"])
    res2 = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert res1 == {"liepin": True}
    assert res2 == {"liepin": True}
    assert lifecycle_calls["n"] == 1  # 第二次命中缓存，未再走生命周期探活


@pytest.mark.asyncio
async def test_liepin_evidence_fail_tries_injection_before_wait(monkeypatch, fast_wait):
    """猎聘实证失效 → 先尝试本地 Cookie 注入一次 → 注入后实证恢复 → 直接就绪（不进等待窗口）。"""
    evidence_results = iter([False, True])  # 首判失效 → 注入后复测恢复
    inject_calls = {"n": 0}
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: next(evidence_results))
    notify = AsyncMock()
    monkeypatch.setattr(preflight, "_notify_login_needed", notify)

    class _FakeLiepinSession:
        @staticmethod
        def inject_cookies_if_needed():
            inject_calls["n"] += 1
            return True

    monkeypatch.setitem(sys.modules, "liepin_session", _FakeLiepinSession)

    res = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert res == {"liepin": True}
    assert inject_calls["n"] == 1
    notify.assert_not_awaited()  # 注入恢复 → 不进等待窗口、不发飞书


@pytest.mark.asyncio
async def test_liepin_injection_fails_once_then_waits(monkeypatch, fast_wait):
    """注入也救不回（JSON 失效）→ 只注入一次，进等待窗口，超时跳过。"""
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    notify = AsyncMock()
    monkeypatch.setattr(preflight, "_notify_login_needed", notify)

    inject_calls = {"n": 0}

    class _FakeLiepinSession:
        @staticmethod
        def inject_cookies_if_needed():
            inject_calls["n"] += 1
            return False

    monkeypatch.setitem(sys.modules, "liepin_session", _FakeLiepinSession)

    res = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert res == {"liepin": False}
    assert inject_calls["n"] == 1  # 每轮预检至多注入一次（等待窗口轮询不再重复注入）
    notify.assert_awaited_once()


async def _fast_sleep(_):
    return None


@pytest.mark.asyncio
async def test_single_job_cancel_breaks_wait_window_fast(monkeypatch, fast_wait):
    """单岗「终止投递」在预检等待窗口内快速生效（2026-10-30 工单）。

    病灶：等待循环只认全局终止，单岗取消要等窗口自然到期（真机实测 3 分 52 秒）。
    锁定：cancel_check 恒为 True 时必须在首次检查（1 秒内）退出；终止打断的等待
    不登记 30s 未就绪冷却，用户可立即重新发起投递。
    """
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    _stub_liepin_session(monkeypatch, inject_result=False)
    notify = AsyncMock()
    monkeypatch.setattr(preflight, "_notify_login_needed", notify)

    started = time.monotonic()
    res = await preflight.ensure_delivery_platforms_ready(
        ["liepin"], cancel_check=lambda: True, wait_s=300,
    )
    elapsed = time.monotonic() - started

    assert res == {"liepin": False}
    assert elapsed < 5, f"收到单岗终止后不得干等等待窗口（实际 {elapsed:.1f}s）"
    notify.assert_awaited_once()
    assert "liepin" not in preflight._notready_until, "终止打断不登记冷却，便于用户立即重试"


@pytest.mark.asyncio
async def test_cancel_check_not_passed_keeps_old_timeout_behaviour(monkeypatch, fast_wait):
    """不传 cancel_check（定时波次/批量链路）时保持旧语义：等满窗口并登记冷却。"""
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    _stub_liepin_session(monkeypatch, inject_result=False)
    monkeypatch.setattr(preflight, "_notify_login_needed", AsyncMock())

    res = await preflight.ensure_delivery_platforms_ready(["liepin"], wait_s=0)

    assert res == {"liepin": False}
    assert preflight._notready_until.get("liepin"), "正常超时必须登记冷却，防逐岗串行阻塞"


@pytest.mark.asyncio
async def test_notready_cooldown_skips_wait_window(monkeypatch, fast_wait):
    """失败冷却（CR R1 P2）：未就绪判定后 30s 内重复调用直接失败——
    不再进等待窗口、不再发飞书，防逐岗串行长阻塞。"""
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    inject_calls = _stub_liepin_session(monkeypatch, inject_result=False)
    notify = AsyncMock()
    monkeypatch.setattr(preflight, "_notify_login_needed", notify)

    r1 = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert r1 == {"liepin": False}
    r2 = await preflight.ensure_delivery_platforms_ready(["liepin"])
    assert r2 == {"liepin": False}
    notify.assert_awaited_once()  # 第二次处于冷却期：直接失败，不发通知不进等待窗口
    assert inject_calls["n"] == 1  # 第二次冷却短路不再注入（打桩防真拉起浏览器）


@pytest.mark.asyncio
async def test_cancel_at_deadline_boundary_skips_cooldown(monkeypatch, fast_wait):
    """取消落在 deadline 交界/最后一轮复检期间：步骤 4 登记冷却前复判终止，仍按取消收尾。

    wait_s=0 让循环一次都不执行，模拟「窗口刚好耗尽」；若步骤 4 不复判，
    取消标记会被 30s 冷却挡住，用户立即重试会被误拦。
    """
    monkeypatch.setattr(preflight, "probe_port", lambda port, timeout=2.0: True)
    monkeypatch.setattr(preflight, "check_liepin_login_evidence", lambda: False)
    _stub_liepin_session(monkeypatch, inject_result=False)
    monkeypatch.setattr(preflight, "_notify_login_needed", AsyncMock())

    res = await preflight.ensure_delivery_platforms_ready(
        ["liepin"], cancel_check=lambda: True, wait_s=0,
    )

    assert res == {"liepin": False}
    assert "liepin" not in preflight._notready_until, "边界取消不得登记冷却"
