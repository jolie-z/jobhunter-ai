"""浏览器生命周期单一实现测试（2026-10-31 猎聘 9226 事故）。

事故：猎聘 Cookie 文件存在时预检直接放行，不执行浏览器就绪检查；9226 上
一个“TCP 可达但 CDP 不可用/无 page tab”的监听者让 DrissionPage 等满 30s 后
抛 BrowserConnectError，整轮 0 条。

本文件锁定 ensure_browser_ready_sync 的契约：
- 端口空闲 → 拉起 + 等端口 + 保证 page tab；
- 在飞（allow_restart=False）→ 只读探活，绝不 close/verify；
- 端口被陌生 profile 占用 → fail-closed，绝不 close；
- CDP alive 但 0 page tab → 补建/失败，不能直接放行；
- zombie → 身份校验通过才优雅重启。
"""
from types import SimpleNamespace

import app.session.browser as browser
import app.session.cdp_probe as cdp_probe
import app.session.health_checker as health_checker
import engine_guard


def _cfg(**over):
    base = {
        "name": "liepin",
        "display_name": "猎聘",
        "port": 9226,
        "profile_dir": "/tmp/fake-liepin-profile",
        "login_check_url": "https://c.liepin.com/",
        "auth_url": "https://www.liepin.com/login",
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_port_down_launches_and_ensures_page_tab(monkeypatch):
    cfg = _cfg()
    calls = {"launch": 0, "tab": 0}
    monkeypatch.setattr(health_checker, "probe_port", lambda *a, **k: False)
    monkeypatch.setattr(browser, "launch_edge", lambda c: calls.__setitem__("launch", calls["launch"] + 1))
    monkeypatch.setattr(browser, "_wait_for_port", lambda *a, **k: True)
    monkeypatch.setattr(browser, "_ensure_page_tab_sync", lambda c: (calls.__setitem__("tab", calls["tab"] + 1) or "page_tab_created"))

    ok, reason = browser.ensure_browser_ready_sync(cfg)

    assert (ok, reason) == (True, "launched")
    assert calls == {"launch": 1, "tab": 1}


def test_in_flight_is_read_only_and_never_verifies(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(health_checker, "probe_port", lambda *a, **k: True)
    monkeypatch.setattr(cdp_probe, "probe_cdp_channel", lambda *a, **k: "alive")

    def _boom(*_a, **_k):
        raise AssertionError("在飞期间不得做身份校验/关闭/拉起")

    monkeypatch.setattr(engine_guard, "verify_browser_identity", _boom)
    monkeypatch.setattr(browser, "close_edge", _boom)
    monkeypatch.setattr(browser, "launch_edge", _boom)
    monkeypatch.setattr(browser, "_ensure_page_tab_sync", _boom)

    ok, reason = browser.ensure_browser_ready_sync(cfg, allow_restart=False)

    assert (ok, reason) == (True, "in_flight_alive")


def test_foreign_profile_fails_closed_without_killing(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(health_checker, "probe_port", lambda *a, **k: True)
    monkeypatch.setattr(cdp_probe, "probe_cdp_channel", lambda *a, **k: "alive")
    monkeypatch.setattr(
        engine_guard, "verify_browser_identity",
        lambda *a, **k: (False, "端口占用者与预期 profile 不符"),
    )

    def _boom(*_a, **_k):
        raise AssertionError("陌生 profile 不得被 close/launch")

    monkeypatch.setattr(browser, "close_edge", _boom)
    monkeypatch.setattr(browser, "launch_edge", _boom)

    ok, reason = browser.ensure_browser_ready_sync(cfg)

    assert ok is False
    assert reason.startswith("port_busy_foreign")


def test_alive_but_no_page_tab_is_not_ready(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(health_checker, "probe_port", lambda *a, **k: True)
    monkeypatch.setattr(cdp_probe, "probe_cdp_channel", lambda *a, **k: "alive")
    monkeypatch.setattr(engine_guard, "verify_browser_identity", lambda *a, **k: (True, "profile_match"))
    monkeypatch.setattr(browser, "_ensure_page_tab_sync", lambda c: None)

    ok, reason = browser.ensure_browser_ready_sync(cfg)

    assert (ok, reason) == (False, "no_page_tab")


def test_sibling_profile_zombie_is_not_killed(monkeypatch):
    """同产品桌面版浏览器 CDP 坏了：只允许复用，不允许按端口 close_edge 误杀。"""
    cfg = _cfg()
    monkeypatch.setattr(health_checker, "probe_port", lambda *a, **k: True)
    monkeypatch.setattr(cdp_probe, "probe_cdp_channel", lambda *a, **k: "zombie")
    monkeypatch.setattr(engine_guard, "verify_browser_identity", lambda *a, **k: (True, "sibling_profile_match"))

    def _boom(*_a, **_k):
        raise AssertionError("桌面版 sibling 不得被 close/launch")

    monkeypatch.setattr(browser, "close_edge", _boom)
    monkeypatch.setattr(browser, "launch_edge", _boom)

    ok, reason = browser.ensure_browser_ready_sync(cfg)

    assert (ok, reason) == (False, "sibling_browser_unhealthy_refused")


def test_zombie_restarts_only_after_identity_pass(monkeypatch):
    cfg = _cfg()
    calls = {"close": 0, "launch": 0}
    monkeypatch.setattr(health_checker, "probe_port", lambda *a, **k: True)
    monkeypatch.setattr(cdp_probe, "probe_cdp_channel", lambda *a, **k: "zombie")
    monkeypatch.setattr(engine_guard, "verify_browser_identity", lambda *a, **k: (True, "profile_match"))
    monkeypatch.setattr(browser, "close_edge", lambda c: calls.__setitem__("close", calls["close"] + 1))
    monkeypatch.setattr(browser, "launch_edge", lambda c: calls.__setitem__("launch", calls["launch"] + 1))
    monkeypatch.setattr(browser, "_wait_for_port_release", lambda *a, **k: True)
    monkeypatch.setattr(browser, "_wait_for_port", lambda *a, **k: True)
    monkeypatch.setattr(browser, "_ensure_page_tab_sync", lambda c: "alive")

    ok, reason = browser.ensure_browser_ready_sync(cfg)

    assert (ok, reason) == (True, "zombie_restarted")
    assert calls == {"close": 1, "launch": 1}


def test_page_tab_check_rejects_zero_tab_browser(monkeypatch):
    """_ensure_page_tab_sync：已有 page tab 返回 alive；补建失败返回 None。"""
    cfg = _cfg()
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_INTERVAL_S", 0)
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_DEADLINE_S", 0)

    class _Resp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp([{"type": "page"}]))
    assert browser._ensure_page_tab_sync(cfg) == "alive"

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp([]))
    monkeypatch.setattr(requests, "put", lambda *a, **k: None)
    assert browser._ensure_page_tab_sync(cfg) is None


def test_page_tab_probe_retries_transient_timeout(monkeypatch):
    """2026-10-31 事故回归：冷启动 /json 首响应超时必须重试，不能一击判死。

    当天 51job(9227)/智联(9250) 并发冷启动时 GET /json 读超时（timeout=2），
    单次探测返回 None → no_page_tab → 平台整轮未抓取。
    """
    cfg = _cfg()
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_INTERVAL_S", 0)

    class _Resp:
        def json(self):
            return [{"type": "page"}]

    import requests

    calls = {"get": 0, "put": 0}

    def _flaky_get(*a, **k):
        calls["get"] += 1
        if calls["get"] == 1:
            raise requests.exceptions.ReadTimeout("read timed out")
        return _Resp()

    monkeypatch.setattr(requests, "get", _flaky_get)
    monkeypatch.setattr(requests, "put", lambda *a, **k: calls.__setitem__("put", calls["put"] + 1))

    assert browser._ensure_page_tab_sync(cfg) == "alive"
    assert calls == {"get": 2, "put": 0}


def test_page_tab_probe_fail_closed_after_all_attempts(monkeypatch):
    """预算耗尽仍不可达 → 维持 None（no_page_tab），fail-closed 不放松。"""
    cfg = _cfg()
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_INTERVAL_S", 0)
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_DEADLINE_S", 0)

    import requests

    calls = {"get": 0, "put": 0}

    def _dead_get(*a, **k):
        calls["get"] += 1
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "get", _dead_get)
    monkeypatch.setattr(requests, "put", lambda *a, **k: calls.__setitem__("put", calls["put"] + 1))

    assert browser._ensure_page_tab_sync(cfg) is None
    assert calls["get"] == 1  # 截止时间为 0：首次失败立即判死
    assert calls["put"] == 0


def test_page_tab_probe_keeps_retrying_within_deadline(monkeypatch):
    """2026-10-31 晚间回归：51job/智联 Edge 冷启动 /json 首响应实测 >10s（profile
    ~1GB、磁盘余量 <6Gi），8s 重试窗不够——窗口内必须持续重试直到应答。"""
    cfg = _cfg()
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_INTERVAL_S", 0)
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_DEADLINE_S", 30)

    class _Resp:
        def json(self):
            return [{"type": "page"}]

    import requests

    calls = {"get": 0}

    def _slow_boot_get(*a, **k):
        calls["get"] += 1
        if calls["get"] < 12:  # 前 11 次都超时（模拟 ~11×2s 冷启动）
            raise requests.exceptions.ReadTimeout("read timed out")
        return _Resp()

    monkeypatch.setattr(requests, "get", _slow_boot_get)
    monkeypatch.setattr(requests, "put", lambda *a, **k: None)

    assert browser._ensure_page_tab_sync(cfg) == "alive"
    assert calls["get"] == 12


def test_page_tab_created_after_put(monkeypatch):
    """0 tab → PUT 补建一次 → 复查到 tab 返回 page_tab_created。

    外审 R2-P1（C1）：原 _put 桩不落 tab，「补建生效」路径（page_tab_created 返回值）
    从未被执行——补建生效与补建无效两个分支都必须真实验证。
    """
    cfg = _cfg()
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_INTERVAL_S", 0)
    monkeypatch.setattr(browser, "_PAGE_TAB_PROBE_DEADLINE_S", 0)

    class _Resp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    import requests

    calls = {"put": 0}
    state = {"tabs": []}

    def _get(*a, **k):
        return _Resp(state["tabs"])

    def _put(*a, **k):
        calls["put"] += 1

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "put", _put)
    assert browser._ensure_page_tab_sync(cfg) is None  # PUT 后仍是 0 tab
    assert calls["put"] == 1  # 补建只做一次，绝不放大成 tab 风暴

    # 补建真正生效（PUT 落地 tab）：同一调用内的复查路径必须返回 page_tab_created
    def _put_creates(*a, **k):
        calls["put"] += 1
        state["tabs"] = [{"type": "page"}]

    monkeypatch.setattr(requests, "put", _put_creates)
    state["tabs"] = []  # 重新回到 0 tab 场景
    assert browser._ensure_page_tab_sync(cfg) == "page_tab_created"
    assert calls["put"] == 2

    # 已有 tab：不再补建
    assert browser._ensure_page_tab_sync(cfg) == "alive"
    assert calls["put"] == 2
