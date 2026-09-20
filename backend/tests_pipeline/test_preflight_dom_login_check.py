"""
预检登录态 DOM 级判定测试（问题 B：飞书预检通知报假警）。

覆盖：
1. indicator 定位符归一化与匹配函数（纯逻辑，mock 元素查询）
2. check_login_via_dom 三态：命中→HEALTHY / 未命中→EXPIRED / 检查失败→UNKNOWN
3. 假阳性回归（智联）：Tab URL 停在 passport.zhaopin.com 但 DOM 有登录标识 → 必须判正常
4. 假阴性回归（BOSS/51job）：掉线时 Tab URL 不变但 DOM 无登录标识 → 必须判失效
5. cookie 兜底收敛（确证失效才跳，存疑放行）：
   EXPIRED/UNKNOWN + cookie 存在 → DEGRADED 放行；无 cookie → 维持原状态
6. requires_login=False 平台（猎聘）预检直接豁免
"""
import asyncio

import pytest

from app.session.health_checker import (
    to_dp_locator,
    is_logged_in_by_indicators,
    check_login_via_dom,
    check_login_with_fallback,
)
from app.session.models import PlatformConfig, SessionState
from app.session.registry import PLATFORM_CONFIGS


# ---------- 假 page：可注入 DOM 命中集合与异常 ----------

class FakePage:
    """模拟 DrissionPage page：记录导航目标，按注入集合返回元素命中。

    ele 签名与真实 DrissionPage 对齐：ele(locator, index=1, timeout=None)——
    第二个位置参数是 index（第几个匹配元素）而非 timeout。
    每个 locator 视为页面内仅匹配 1 个元素，index≠1 时返回 None（防回归关键）。
    """

    def __init__(self, present=(), raise_on_get=False, raise_on_ele=False):
        self.present = set(present)
        self.raise_on_get = raise_on_get
        self.raise_on_ele = raise_on_ele
        self.navigated_to = []

    def get(self, url, timeout=None):
        self.navigated_to.append(url)
        if self.raise_on_get:
            raise TimeoutError("导航超时")

    def ele(self, locator, index=1, timeout=None):
        if self.raise_on_ele:
            raise RuntimeError("元素查询异常")
        if index != 1:
            # 真实语义：页面只有 1 个匹配元素，取第 index 个必然落空。
            # 旧代码把 timeout 当位置参数传入 → index=2.0 → 恒判 MISS。
            return None
        return object() if locator in self.present else None


def _config(**overrides):
    base = dict(
        name="boss",
        display_name="BOSS直聘",
        port=19222,
        login_check_url="https://www.zhipin.com/",
        login_indicators=["css:.user-nav", "text:退出登录"],
    )
    base.update(overrides)
    return PlatformConfig(**base)


@pytest.fixture(autouse=True)
def _force_port_open(monkeypatch):
    """单测中端口一律视为已监听（端口不通分支单独测试）。"""
    import app.session.health_checker as hc
    monkeypatch.setattr(hc, "probe_port", lambda *a, **k: True)


# ---------- indicator 归一化与匹配 ----------

def test_to_dp_locator_keeps_prefix_and_defaults_css():
    assert to_dp_locator("css:.user-nav") == "css:.user-nav"
    assert to_dp_locator("text:退出登录") == "text:退出登录"
    assert to_dp_locator("xpath://div") == "xpath://div"
    assert to_dp_locator(".uname") == "css:.uname"


def test_is_logged_in_any_indicator_hits():
    seen = []

    def query(locator, timeout=None):
        seen.append(locator)
        return object() if locator == "text:退出登录" else None

    assert is_logged_in_by_indicators(query, ["css:.user-nav", "text:退出登录"]) is True
    # or 语义：命中即短路返回
    assert seen == ["css:.user-nav", "text:退出登录"]


def test_is_logged_in_none_hits_returns_false():
    assert is_logged_in_by_indicators(lambda loc, timeout=None: None, ["css:.user-nav", "text:退出登录"]) is False
    assert is_logged_in_by_indicators(lambda loc, timeout=None: None, []) is False


def test_is_logged_in_query_exception_propagates():
    """元素查询异常不能吞成「未登录」，必须抛给调用方区分判定失败。"""

    def boom(locator, timeout=None):
        raise RuntimeError("CDP disconnected")

    with pytest.raises(RuntimeError):
        is_logged_in_by_indicators(boom, ["css:.user-nav"])


def test_is_logged_in_timeout_passed_as_keyword():
    """ele_query 契约守卫：timeout 必须以关键字传参（防 DrissionPage index 误用，任务 #12 根因）。"""
    calls = []

    def query(locator, index=1, timeout=None):
        calls.append({"locator": locator, "index": index, "timeout": timeout})
        return None

    is_logged_in_by_indicators(query, ["css:.user-nav"], timeout=2.0)
    assert calls[0]["timeout"] == 2.0
    # index 必须保持默认 1；若 timeout 被当位置参数传入，index 会变成 2.0 → 真实页面恒 MISS
    assert calls[0]["index"] == 1


# ---------- check_login_via_dom 三态 ----------

def test_dom_check_healthy_when_indicator_present():
    page = FakePage(present={"css:.user-nav"})
    status = check_login_via_dom(_config(), page_factory=lambda port: page)
    assert status.state == SessionState.HEALTHY
    assert page.navigated_to == ["https://www.zhipin.com/"]
    assert status.last_healthy is not None


def test_dom_check_expired_when_no_indicator():
    page = FakePage(present=())
    status = check_login_via_dom(_config(), page_factory=lambda port: page)
    assert status.state == SessionState.EXPIRED
    assert "未命中" in status.message
    assert status.last_healthy is None


def test_dom_check_unknown_on_navigation_failure():
    """导航失败 = 判定失败 ≠ 未登录 → UNKNOWN，日志留痕、不静默放行。"""
    page = FakePage(raise_on_get=True)
    status = check_login_via_dom(_config(), page_factory=lambda port: page)
    assert status.state == SessionState.UNKNOWN
    assert "无法判定" in status.message


def test_dom_check_unknown_on_element_query_failure():
    page = FakePage(present={"css:.user-nav"}, raise_on_ele=True)
    status = check_login_via_dom(_config(), page_factory=lambda port: page)
    assert status.state == SessionState.UNKNOWN


def test_dom_check_unknown_on_attach_failure():
    """附加浏览器（DrissionPage 构造）抛异常 → UNKNOWN。"""

    def factory(port):
        raise ConnectionError("attach timeout")

    status = check_login_via_dom(_config(), page_factory=factory)
    assert status.state == SessionState.UNKNOWN


def test_dom_check_unknown_when_no_indicators_configured():
    status = check_login_via_dom(_config(login_indicators=[]), page_factory=lambda port: FakePage())
    assert status.state == SessionState.UNKNOWN


def test_dom_check_unknown_when_port_closed(monkeypatch):
    import app.session.health_checker as hc
    monkeypatch.setattr(hc, "probe_port", lambda *a, **k: False)
    status = check_login_via_dom(_config(), page_factory=lambda port: FakePage(present={"css:.user-nav"}))
    assert status.state == SessionState.UNKNOWN
    assert "端口" in status.message


def test_dom_check_single_match_element_hits_with_real_ele_signature():
    """
    防回归（任务 #12/#13）：DrissionPage 真实签名 ele(locator, index=1, timeout=None)。
    旧代码 `ele_query(locator, timeout)` 位置传参 → timeout 被当 index=2.0，
    而登录标识（如 .user-nav）页面仅匹配 1 个元素 → 已登录也恒判 EXPIRED，
    导致 BOSS/智联预检误报并跳过。本用例在旧代码上必失败、新代码上通过。
    """
    page = FakePage(present={"css:.user-nav"})  # 仅 1 个匹配元素
    status = check_login_via_dom(_config(), page_factory=lambda port: page)
    assert status.state == SessionState.HEALTHY


# ---------- 误判场景回归 ----------

def test_regression_zhilian_false_positive_eliminated():
    """
    旧逻辑假阳性：智联 auth_url=passport.zhaopin.com 本身命中 login_page_indicators，
    浏览器自动拉起即被误判「会话过期」。
    新逻辑不看 Tab URL，只看 DOM：已登录时即便刚从 passport 域回来也判 HEALTHY。
    """
    cfg = PLATFORM_CONFIGS["zhilian"]
    assert "passport.zhaopin.com" in cfg.login_page_indicators  # 旧启发式会因此误判
    page = FakePage(present={"css:.c-login__top__name"})
    status = check_login_via_dom(cfg, page_factory=lambda port: page)
    assert status.state == SessionState.HEALTHY


def test_regression_boss_false_negative_eliminated():
    """
    旧逻辑假阴性：BOSS 掉线时 Tab URL 不变（同域弹登录框），旧逻辑误判 HEALTHY。
    新逻辑按 DOM 判定：无 .user-nav / 无「退出登录」→ 必须 EXPIRED。
    """
    cfg = PLATFORM_CONFIGS["boss"]
    page = FakePage(present=())  # 页面仍停在 zhipin.com 域名，但没有任何登录标识
    status = check_login_via_dom(cfg, page_factory=lambda port: page)
    assert status.state == SessionState.EXPIRED


def test_regression_51job_false_negative_eliminated():
    """51job 掉线同样 URL 不变（同域弹登录表单）→ DOM 无标识必须 EXPIRED。"""
    cfg = PLATFORM_CONFIGS["51job"]
    page = FakePage(present=())
    status = check_login_via_dom(cfg, page_factory=lambda port: page)
    assert status.state == SessionState.EXPIRED


def test_registry_all_platforms_have_dom_check_fields():
    """四个招聘平台必须齐备 DOM 级判定所需字段。"""
    for key in ("boss", "51job", "zhilian", "liepin"):
        cfg = PLATFORM_CONFIGS[key]
        assert cfg.login_check_url, f"{key} 缺少 login_check_url"
        assert cfg.login_indicators, f"{key} 缺少 login_indicators"


def test_registry_login_exempt_and_strict_platforms():
    """猎聘抓取无需登录 → requires_login=False 豁免；BOSS/智联保持严格 DOM 把关。"""
    assert PLATFORM_CONFIGS["liepin"].requires_login is False
    for key in ("boss", "zhilian"):
        assert PLATFORM_CONFIGS[key].requires_login is True, f"{key} 不得豁免登录校验"


def test_registry_51job_check_url_on_we_domain():
    """51job 登录态体现在 we.51job.com（www 首页无登录元素），indicators 为实测值。"""
    cfg = PLATFORM_CONFIGS["51job"]
    assert cfg.login_check_url.startswith("https://we.51job.com")
    assert "css:.user-info" in cfg.login_indicators
    assert "text:退出登录" in cfg.login_indicators
    # 旧猜测值不得回流
    assert "css:.uname" not in cfg.login_indicators


def test_registry_zhilian_indicators_are_calibrated():
    """智联 indicators 必须为 2026-08 实测值（calibrate_boss_zhilian_login_dom.py），旧猜测值不得回流。"""
    cfg = PLATFORM_CONFIGS["zhilian"]
    assert "css:.c-login__top__name" in cfg.login_indicators
    assert "css:.c-login__top__img" in cfg.login_indicators
    assert "text:退出" in cfg.login_indicators
    # 旧猜测值在智联首页不存在，不得回流
    assert "css:.user-nav" not in cfg.login_indicators
    assert "css:.header-user-info" not in cfg.login_indicators


def test_preflight_uses_dom_check_with_cookie_fallback():
    """
    防回退守卫（新语义）：
    - preflight 登录检查必须走 check_login_with_fallback（DOM 判定 + cookie 兜底收敛），
      不得直接使用 check_platform / URL 启发式；
    - 收敛层内部仍以 check_login_via_dom 为判定主体，不退回 URL 启发式。
    """
    import app.session.preflight as pf
    import app.session.health_checker as hc
    from app.session.health_checker import check_login_with_fallback

    assert pf.check_login_with_fallback is check_login_with_fallback
    assert not hasattr(pf, "check_platform")
    assert not hasattr(pf, "check_session_via_cdp")
    # 收敛函数必须以 DOM 判定为主体
    import inspect
    src = inspect.getsource(hc.check_login_with_fallback)
    assert "check_login_via_dom" in src


# ---------- cookie 兜底收敛：确证失效才跳，存疑放行 ----------

def _config_with_cookie(cookie_path: str, **overrides):
    return _config(legacy_cookie_file=cookie_path, **overrides)


def test_fallback_expired_with_cookie_passes_degraded(tmp_path):
    """DOM 判 EXPIRED 但 legacy cookie 文件存在 → 兜底 DEGRADED 放行（属可用态）。"""
    cookie = tmp_path / "51job_cookies.json"
    cookie.write_text("[]")
    page = FakePage(present=())  # 未命中任何登录标识 → EXPIRED
    status = check_login_with_fallback(
        _config_with_cookie(str(cookie)), page_factory=lambda port: page
    )
    assert status.state == SessionState.DEGRADED
    assert "兜底放行" in status.message


def test_fallback_expired_without_cookie_confirms_expired(tmp_path):
    """DOM 判 EXPIRED 且无 cookie 兜底 → 确证失效，维持 EXPIRED。"""
    missing = tmp_path / "not_exist.json"
    page = FakePage(present=())
    status = check_login_with_fallback(
        _config_with_cookie(str(missing)), page_factory=lambda port: page
    )
    assert status.state == SessionState.EXPIRED


def test_fallback_unknown_with_cookie_passes_degraded(tmp_path):
    """DOM 判定失败（UNKNOWN）+ cookie 存在 → 兜底 DEGRADED 放行，不静默也不误杀。"""
    cookie = tmp_path / "cookies.json"
    cookie.write_text("[]")
    page = FakePage(raise_on_get=True)  # 导航异常 → UNKNOWN
    status = check_login_with_fallback(
        _config_with_cookie(str(cookie)), page_factory=lambda port: page
    )
    assert status.state == SessionState.DEGRADED


def test_fallback_unknown_without_cookie_stays_unknown(tmp_path):
    """UNKNOWN 且无 cookie → 维持 UNKNOWN（走等待/提醒，不静默放行）。"""
    page = FakePage(raise_on_get=True)
    status = check_login_with_fallback(
        _config_with_cookie(""), page_factory=lambda port: page
    )
    assert status.state == SessionState.UNKNOWN


def test_fallback_healthy_passthrough(tmp_path):
    """DOM 判 HEALTHY → 原样放行，不触发 cookie 兜底。"""
    cookie = tmp_path / "cookies.json"
    cookie.write_text("[]")
    page = FakePage(present={"css:.user-nav"})
    status = check_login_with_fallback(
        _config_with_cookie(str(cookie)), page_factory=lambda port: page
    )
    assert status.state == SessionState.HEALTHY


# ---------- requires_login=False 平台预检豁免 ----------

def test_preflight_exempt_platform_skips_dom_check(monkeypatch):
    """requires_login=False（猎聘）→ 直接放行：不探测端口、不拉起浏览器、不做 DOM 判定。"""
    import app.session.preflight as pf

    def _forbidden(*a, **k):
        raise AssertionError("豁免平台不应触发端口探测/浏览器拉起/DOM 校验")

    monkeypatch.setattr(pf, "probe_port", _forbidden)
    monkeypatch.setattr(pf, "launch_edge", _forbidden)
    monkeypatch.setattr(pf, "check_login_with_fallback", _forbidden)

    results = asyncio.run(pf.ensure_platforms_ready(["liepin"]))
    assert results == {"liepin": True}


def test_preflight_exempt_platform_logged(monkeypatch):
    """豁免平台需记录「无需登录，豁免预检」日志。"""
    import app.session.preflight as pf

    logged = []

    async def emit(msg):
        logged.append(msg)

    results = asyncio.run(pf.ensure_platforms_ready(["liepin"], emit_log=emit))
    assert results == {"liepin": True}
    assert any("豁免" in m and "无需登录" in m for m in logged)
