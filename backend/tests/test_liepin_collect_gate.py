"""猎聘采集门双判据 + Cookie 自愈回写测试（2026-09-27 双判据批）。

覆盖两段引擎侧改动：
1. nl_controller.process_liepin_scraping_request 的采集门——原「Cookie 文件硬门」
   改为 liepin_collect_ready 双判据（文件 OR Edge profile 登录实证）；
2. liepin_crawler 的自愈回写——profile 登录确认后把浏览器 cookie 以 playwright
   兼容格式原子回写 COOKIE_FILE（expiry→expires 映射、sameSite 归一、bool 化）。
"""
import asyncio
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
LIEPIN_DIR = BACKEND_DIR / "liepin_scraper"


def _load_crawler_module():
    """liepin_crawler 模块级 import DrissionPage，测试环境用桩模块替代。

    外审 R2-P1（C2）：桩写入 sys.modules 必须用后恢复——否则按字母序紧随其后的
    test_liepin_delivery_fixes.py 会拿到残缺桩（破坏 HAS_ENGINE 门禁或遮蔽真实库）。
    """
    dp_backup = sys.modules.get("DrissionPage")
    injected = False
    dp = sys.modules.get("DrissionPage")
    if dp is None or not hasattr(getattr(dp, "ChromiumOptions", None), "set_local_port"):
        stub = types.ModuleType("DrissionPage")

        class _FakeOptions:
            def __getattr__(self, name):
                def _noop(*a, **k):
                    return self

                return _noop

        stub.ChromiumPage = object
        stub.ChromiumOptions = _FakeOptions
        sys.modules["DrissionPage"] = stub
        injected = True
    try:
        spec = importlib.util.spec_from_file_location("liepin_crawler_under_test", LIEPIN_DIR / "liepin_crawler.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["liepin_crawler_under_test"] = mod
        spec.loader.exec_module(mod)
    finally:
        if injected:
            if dp_backup is None:
                sys.modules.pop("DrissionPage", None)
            else:
                sys.modules["DrissionPage"] = dp_backup
    return mod


def _load_nl_controller():
    if str(LIEPIN_DIR) not in sys.path:
        sys.path.insert(0, str(LIEPIN_DIR))
    import liepin_nl_controller as nlc
    return nlc


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakePage:
    def __init__(self, raw):
        self._raw = raw

    def cookies(self, all_info=False, all_domains=False):
        return self._raw


# ==========================================
# cookie 字段映射（DrissionPage → playwright 兼容格式）
# ==========================================

crawler = _load_crawler_module()


def test_dump_maps_fields_and_normalizes():
    raw = [
        {"name": "lt_auth", "value": "v1", "domain": ".liepin.com", "path": "/",
         "expires": 4102444800.5, "httpOnly": 1, "secure": 1, "sameSite": "Lax"},
        {"name": "sid", "value": "v2", "domain": ".liepin.com", "path": "/",
         "expires": None, "httpOnly": 0, "secure": 0, "sameSite": "no_restriction"},
        {"name": "expiry_keyed", "value": "v3", "domain": ".liepin.com", "path": "/",
         "expiry": 4102444800, "httpOnly": 1, "secure": 0, "sameSite": "Strict"},
        {"name": "", "value": "skip-empty-name"},
        "not-a-dict",
    ]
    out = crawler._dump_cookies_drissionpage_to_playwright(_FakePage(raw))

    assert len(out) == 3
    assert out[0]["httpOnly"] is True and out[0]["secure"] is True
    assert out[0]["expires"] == 4102444800.5 and out[0]["sameSite"] == "Lax"
    # expires None → -1；sameSite 不在 {Lax, Strict, None} 内归一为 Lax
    assert out[1]["expires"] == -1
    assert out[1]["httpOnly"] is False and out[1]["sameSite"] == "Lax"
    # DrissionPage 部分版本以 expiry 为过期键名：双键兼容，防过期时间静默丢失退化为 -1
    assert out[2]["expires"] == 4102444800 and out[2]["sameSite"] == "Strict"


def test_self_heal_writes_atomically(monkeypatch, tmp_path):
    target = tmp_path / "liepin_cookies.json"
    monkeypatch.setattr(crawler, "COOKIE_FILE", str(target))
    raw = [
        {"name": "lt_auth", "value": "v1", "domain": ".liepin.com", "path": "/",
         "expires": 4102444800, "httpOnly": 1, "secure": 1, "sameSite": "Lax"},
        {"name": "liepin_login_valid", "value": "v2", "domain": ".liepin.com", "path": "/",
         "expires": 4102444800, "httpOnly": 1, "secure": 1, "sameSite": "Lax"},
    ]

    crawler._self_heal_cookie_file(_FakePage(raw))

    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert {c["name"] for c in data} == {"lt_auth", "liepin_login_valid"}
    assert not list(tmp_path.glob("*.tmp"))  # 原子替换后不留临时文件


def test_self_heal_skips_guest_cookies_without_overwriting(monkeypatch, tmp_path):
    """访客态（缺少 lt_auth/liepin_login_valid）不得覆盖已有有效文件。"""
    target = tmp_path / "liepin_cookies.json"
    target.write_text('{"valid": true}', encoding="utf-8")
    monkeypatch.setattr(crawler, "COOKIE_FILE", str(target))

    crawler._self_heal_cookie_file(_FakePage([
        {"name": "user_name", "value": "guest", "domain": ".liepin.com", "path": "/"},
    ]))

    assert json.loads(target.read_text(encoding="utf-8")) == {"valid": True}


def test_self_heal_skips_empty_and_swallows_errors(monkeypatch, tmp_path):
    target = tmp_path / "liepin_cookies.json"
    monkeypatch.setattr(crawler, "COOKIE_FILE", str(target))

    # 空 cookie：不落盘
    crawler._self_heal_cookie_file(_FakePage([]))
    assert not target.exists()

    # page.cookies 抛异常：不冒泡、不落盘
    class _BoomPage:
        def cookies(self, all_info=False, all_domains=False):
            raise RuntimeError("browser gone")

    crawler._self_heal_cookie_file(_BoomPage())
    assert not target.exists()


def test_check_login_status_prefers_auth_cookies_without_navigation(monkeypatch):
    """已有 lt_auth/liepin_login_valid：直接判定已登录，不做任何导航。"""
    page = _FakePage([
        {"name": "lt_auth", "value": "v1", "expires": 4102444800},
        {"name": "liepin_login_valid", "value": "v2", "expires": 4102444800},
    ])
    page.get = lambda *a, **k: pytest.fail("有登录凭证时不得导航")
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)

    assert crawler._check_login_status(page) is True


def test_check_login_status_rejects_c_liepin_login_page(monkeypatch):
    """URL 前缀是 c.liepin.com 但停在登录页：不得误判已登录。"""
    class _LoginPage(_FakePage):
        url = "about:blank"

        def get(self, url, **kwargs):
            self.url = "https://c.liepin.com/login?backUrl=x"
            return True

    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    assert crawler._check_login_status(_LoginPage([])) is False


def test_check_login_status_requires_auth_cookie_even_on_home(monkeypatch):
    """落在 c.liepin.com 首页但没有登录键：仍判未登录（防访客态假阳性）。"""
    class _HomePage(_FakePage):
        url = "about:blank"

        def get(self, url, **kwargs):
            self.url = "https://c.liepin.com/"
            return True

    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    assert crawler._check_login_status(_HomePage([])) is False


def test_check_login_status_accepts_cookies_after_navigation(monkeypatch):
    class _LoginAfterGetPage:
        def __init__(self):
            self.url = "about:blank"
            self.logged_in = False

        def cookies(self, all_info=False, all_domains=False):
            if not self.logged_in:
                return []
            return [
                {"name": "lt_auth", "value": "v1", "expires": 4102444800},
                {"name": "liepin_login_valid", "value": "v2", "expires": 4102444800},
            ]

        def get(self, url, **kwargs):
            self.url = "https://c.liepin.com/"
            self.logged_in = True
            return True

    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
    assert crawler._check_login_status(_LoginAfterGetPage()) is True


# ==========================================
# 采集门（nl_controller 入口双判据接线）
# ==========================================

nlc = _load_nl_controller()


def test_gate_blocks_when_no_file_and_no_evidence(monkeypatch):
    monkeypatch.setattr(nlc, "liepin_collect_ready", lambda path: False)
    notified = []

    async def fake_notify(chat_id, message):
        notified.append(message)

    engine_calls = []

    def fake_engine(*a, **k):
        engine_calls.append(a)
        return 0

    monkeypatch.setattr(nlc, "_notify_feishu_liepin", fake_notify)
    monkeypatch.setattr(nlc, "run_scraping_task", fake_engine)

    _run(nlc.process_liepin_scraping_request(
        chat_id="agent_cli", city="上海", keyword="生物信息", salary="20-30K",
        start_page=1, target_jobs=10,
    ))

    assert not engine_calls  # 双判据皆否：引擎不得被调用
    assert any("唤起浏览器" in m for m in notified)
    assert any("liepin_cookie_harvester" in m for m in notified)


def test_gate_allows_on_evidence_and_reaches_engine(monkeypatch):
    monkeypatch.setattr(nlc, "liepin_collect_ready", lambda path: True)
    notified = []

    async def fake_notify(chat_id, message):
        notified.append(message)

    engine_calls = []

    def fake_engine(*a, **k):
        engine_calls.append(a)
        return 0

    monkeypatch.setattr(nlc, "_notify_feishu_liepin", fake_notify)
    monkeypatch.setattr(nlc, "run_scraping_task", fake_engine)

    _run(nlc.process_liepin_scraping_request(
        chat_id="agent_cli", city="上海", keyword="生物信息", salary="20-30K",
        start_page=1, target_jobs=10,
    ))

    assert len(engine_calls) == 1  # 实证有效：放行并触达引擎
    assert not any("缺少猎聘 Cookie" in m for m in notified)


def test_gate_reports_engine_crash_to_feishu(monkeypatch):
    """引擎崩溃快停后：异步入口发 ❌ 告警（真实原因），绝不发 🎉 庆功报文。"""
    monkeypatch.setattr(nlc, "liepin_collect_ready", lambda path: True)
    notified = []

    async def fake_notify(chat_id, message):
        notified.append(message)

    def fake_engine(*a, **k):
        nlc.LAST_ENGINE_CRASH = "猎聘爬虫子进程异常退出(code=1)，已中止翻页循环"
        return 0

    monkeypatch.setattr(nlc, "_notify_feishu_liepin", fake_notify)
    monkeypatch.setattr(nlc, "run_scraping_task", fake_engine)

    try:
        _run(nlc.process_liepin_scraping_request(
            chat_id="agent_cli", city="上海", keyword="生物信息", salary="20-30K",
            start_page=1, target_jobs=10,
        ))
    finally:
        nlc.LAST_ENGINE_CRASH = None

    assert any("❌ 猎聘抓取中止" in m for m in notified)
    assert any("edge_liepin.log" in m for m in notified)
    assert not any("🎉" in m for m in notified)


# ==========================================
# ② Edge 拉起加固（0928 事故：Edge 154 × macOS 12 dyld SIGABRT）
# ==========================================

class _FakeCO:
    """最小 ChromiumOptions 替身（承接 _setup_chromium_browser 的链式配置）。"""

    def set_argument(self, *a):
        pass

    def set_browser_path(self, p):
        self.path = p

    def set_local_port(self, p):
        pass

    def set_user_data_path(self, p):
        self.profile = p

    def headless(self, v):
        pass


class _FakeLivePage:
    """成功拉起后的假页面：c.liepin.com 判定通过（已登录），cookies 为空。"""

    def __init__(self):
        self.url = ""

    def get(self, url):
        self.url = url

    def cookies(self, all_info=False):
        return []


def _patch_edge_present(monkeypatch):
    """Edge 存在 / Cookie 文件不存在的确定性 os.path.exists（防真机依赖）。"""
    real_exists = crawler.os.path.exists

    def fake_exists(path):
        if "Microsoft Edge" in str(path):
            return True
        return real_exists(path) if "liepin_cookies" in str(path) else False

    monkeypatch.setattr(crawler.os.path, "exists", fake_exists)


def test_setup_raises_install_guide_when_edge_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(crawler.os.path, "exists", lambda p: False)
    monkeypatch.setattr(crawler, "ChromiumOptions", _FakeCO)

    with pytest.raises(RuntimeError, match="未找到 Microsoft Edge"):
        crawler._setup_chromium_browser()


def test_setup_diagnoses_dead_binary(monkeypatch, tmp_path):
    """拉起失败且二进制体检不过（dyld SIGABRT 场景）：报错带「版本不兼容」定性+加载器原文。"""
    _patch_edge_present(monkeypatch)
    monkeypatch.setattr(crawler, "ChromiumOptions", _FakeCO)
    # 2026-10-31：_setup_chromium_browser 先走统一生命周期（ensure_browser_ready_sync
    # + 身份守卫）；本用例只测 ChromiumPage 失败后的二进制体检，故打桩前两步。
    monkeypatch.setattr(crawler, "ensure_browser_ready_sync", lambda cfg, **k: (True, "alive"))
    monkeypatch.setattr(crawler, "verify_browser_identity", lambda *a, **k: (True, "profile_match"))

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--version" in cmd:
            import types
            return types.SimpleNamespace(returncode=-6, stderr="dyld: Symbol not found: (_kVT...)", stdout="")
        import types
        return types.SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(crawler.subprocess, "run", fake_run)
    monkeypatch.setattr(crawler, "_clear_stale_profile_locks", lambda p: False)

    def _boom(opts):
        raise RuntimeError("BrowserConnectError: 127.0.0.1:9226")

    monkeypatch.setattr(crawler, "ChromiumPage", _boom)

    with pytest.raises(RuntimeError) as ei:
        crawler._setup_chromium_browser()

    msg = str(ei.value)
    assert "疑似系统与浏览器版本不兼容" in msg
    assert "Symbol not found" in msg
    assert any("--version" in c for c in calls)  # 体检确实执行了


def test_setup_diagnoses_healthy_binary_connect_fail(monkeypatch, tmp_path):
    """二进制体检通过但 CDP 连不上：报错指向端口/档案锁而非冤枉版本。"""
    import types

    _patch_edge_present(monkeypatch)
    monkeypatch.setattr(crawler, "ChromiumOptions", _FakeCO)
    # 同上：统一生命周期/身份守卫打桩，专测 ChromiumPage 失败后的体检文案。
    monkeypatch.setattr(crawler, "ensure_browser_ready_sync", lambda cfg, **k: (True, "alive"))
    monkeypatch.setattr(crawler, "verify_browser_identity", lambda *a, **k: (True, "profile_match"))
    monkeypatch.setattr(crawler.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="154.0", stderr=""))
    monkeypatch.setattr(crawler, "_clear_stale_profile_locks", lambda p: False)

    def _boom(opts):
        raise RuntimeError("BrowserConnectError: 127.0.0.1:9226")

    monkeypatch.setattr(crawler, "ChromiumPage", _boom)

    with pytest.raises(RuntimeError) as ei:
        crawler._setup_chromium_browser()

    msg = str(ei.value)
    assert "二进制自检正常" in msg
    assert "9226" in msg
    assert "疑似系统与浏览器版本不兼容" not in msg


def test_setup_retries_once_after_clearing_stale_locks(monkeypatch, tmp_path):
    """首次失败+无主档案锁已清：重试成功即继续（登录守卫链路照常走通）。"""
    _patch_edge_present(monkeypatch)
    monkeypatch.setattr(crawler, "ChromiumOptions", _FakeCO)
    monkeypatch.setattr(crawler.time, "sleep", lambda s: None)  # _check_login_status 的 2s 等待
    monkeypatch.setattr(crawler, "_clear_stale_profile_locks", lambda p: True)
    # 统一生命周期/身份守卫打桩，专测 ChromiumPage 首次失败后的清锁重试。
    monkeypatch.setattr(crawler, "ensure_browser_ready_sync", lambda cfg, **k: (True, "alive"))
    monkeypatch.setattr(crawler, "verify_browser_identity", lambda *a, **k: (True, "profile_match"))

    attempts = []

    def fake_page_factory(opts):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("BrowserConnectError: profile locked")
        return _FakeLivePage()

    monkeypatch.setattr(crawler, "ChromiumPage", fake_page_factory)

    page = crawler._setup_chromium_browser()

    assert len(attempts) == 2  # 恰好重试一次
    assert isinstance(page, _FakeLivePage)


# ==========================================
# ③ 采集门拦截报错透传 + 会话状态收敛（2026-11-01）
# ==========================================

def test_gate_blocks_emits_error_sse_and_marks_result_meta(monkeypatch):
    """门禁拦截时：必须推送 type: error 的 SSE 消息并更新 result_meta 为失败，防前端误报已完成。"""
    monkeypatch.setattr(nlc, "liepin_collect_ready", lambda path: False)
    notified = []

    async def fake_notify(chat_id, message):
        notified.append(message)

    monkeypatch.setattr(nlc, "_notify_feishu_liepin", fake_notify)

    from app.tasks.state import task_queues
    task_id = "test_liepin_gate_task_123"
    q = asyncio.Queue()
    task_queues[task_id] = q

    result_meta = {}

    try:
        _run(nlc.process_liepin_scraping_request(
            chat_id="agent_cli", city="上海", keyword="生物信息", salary="20-30K",
            start_page=1, target_jobs=10,
            sse_task_id=task_id, result_meta=result_meta,
        ))

        # 验证 SSE 消息（先 start 后 error）
        messages = []
        while not q.empty():
            sse_raw = q.get_nowait()
            if sse_raw.startswith("data: "):
                messages.append(json.loads(sse_raw[6:].strip()))

        types = [m.get("type") for m in messages]
        assert "start" in types
        assert "error" in types
        error_msg = next(m for m in messages if m.get("type") == "error")
        assert "猎聘 Cookie 缺失/已失效" in error_msg.get("message", "")

        # 验证 result_meta 标记
        assert result_meta.get("success") is False
        assert "猎聘登录态失效" in result_meta.get("fail_reason", "")
    finally:
        task_queues.pop(task_id, None)


def test_platform_sessions_liepin_state_judgement(monkeypatch):
    """验证 browser.get_all_platform_sessions 对猎聘状态的本地双校验。"""
    from app.session.browser import get_all_platform_sessions
    import types

    fake_status = types.SimpleNamespace(
        state=types.SimpleNamespace(value="healthy"),
        message="已连接",
    )
    monkeypatch.setattr("app.session.health_checker.probe_port", lambda *a, **k: True)
    monkeypatch.setattr("app.session.cdp_probe.probe_cdp_channel", lambda *a, **k: "alive")
    monkeypatch.setattr("app.session.health_checker.check_session_via_cdp", lambda cfg: fake_status)

    # 1. 当 cookie 文件失效，且 profile 未登录时 -> expired
    monkeypatch.setattr("app.session.health_checker.is_liepin_cookie_file_valid", lambda p: False)
    monkeypatch.setattr("app.session.health_checker._read_login_keys_via_profile_db", lambda p: None)

    sessions = get_all_platform_sessions()
    lp = next(s for s in sessions if s["platform"] == "liepin")
    assert lp["state"] == "expired"
    assert "请点击唤起浏览器扫码登录" in lp["message"]

    # 2. 当 cookie 文件失效，但 profile 登录有效时 -> degraded
    monkeypatch.setattr("app.session.health_checker._read_login_keys_via_profile_db", lambda p: {"lt_auth": 1})
    monkeypatch.setattr("app.session.health_checker._judge_login_keys", lambda k: True)

    sessions = get_all_platform_sessions()
    lp = next(s for s in sessions if s["platform"] == "liepin")
    assert lp["state"] == "degraded"
    assert "待自愈" in lp["message"]
    assert "已连接" in lp["message"]  # 保留原有 cdp message 前缀

    # 3. 当 cookie 文件有效时 -> healthy
    monkeypatch.setattr("app.session.health_checker.is_liepin_cookie_file_valid", lambda p: True)

    sessions = get_all_platform_sessions()
    lp = next(s for s in sessions if s["platform"] == "liepin")
    assert lp["state"] == "healthy"
    assert "Cookie 凭证有效" in lp["message"]
    assert "已连接" in lp["message"]


@pytest.mark.parametrize("scenario,returncode,set_blocked,stop_flag,expected_success,expected_reason_substr", [
    ("访客墙拦截", 0, True, False, False, "访客态被登录墙拦截"),
    ("引擎崩溃", 1, False, False, False, "子进程异常退出(code=1)"),
    ("手动急刹", 0, False, True, False, None),
    ("正常完成", 0, False, False, True, None),
])
def test_run_task_fail_reason_branches(monkeypatch, scenario, returncode, set_blocked, stop_flag, expected_success, expected_reason_substr):
    """测试 run_task 收尾处对 fail_reason 的精确赋值契约。"""
    import types
    fake_process = types.SimpleNamespace(returncode=returncode)
    monkeypatch.setattr(nlc, "popen_hidden", lambda *a, **k: fake_process)

    def fake_process_output(*a, **k):
        if set_blocked:
            nlc.LAST_GUEST_BLOCKED = True
        return 1, True, 10

    monkeypatch.setattr(nlc, "_process_crawler_output", fake_process_output)
    monkeypatch.setattr("app.session.scrape_sessions.report_condition_round", lambda *a, **k: None)

    monkeypatch.setattr(nlc, "GLOBAL_STOP_FLAG", stop_flag)

    result_meta = {}
    try:
        nlc.run_task(
            keyword="测试岗位", city="上海", start_page=1, target_jobs=1, salary="20-30K",
            result_meta=result_meta
        )

        assert result_meta["success"] is expected_success
        if expected_reason_substr is None:
            assert result_meta["fail_reason"] is None
        else:
            assert expected_reason_substr in (result_meta["fail_reason"] or "")
    finally:
        nlc.LAST_GUEST_BLOCKED = False
        nlc.LAST_ENGINE_CRASH = None
        nlc.GLOBAL_STOP_FLAG = False

