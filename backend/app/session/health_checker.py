"""
健康检查器 — 多层检测：
  Tier 1: TCP 端口探测（瞬间）
  Tier 2: CDP /json 接口读取 Tab URL（轻量，仅供前端状态展示等低频轻量场景）
  DOM 级: 附加到平台浏览器端口 → 导航 login_check_url → 按 registry login_indicators
          判定登录态（与各平台 collector 的 _ensure_login 同一标准，供预检使用）

历史教训：仅凭 Tab URL 判登录双向都不可靠——
  假阳性：智联 auth_url=passport.zhaopin.com 本身命中 login_page_indicators，浏览器拉起即误判失效；
  假阴性：BOSS/51job 掉线时 URL 不变（同域弹登录框），被误判正常。
因此预检登录校验一律走 DOM 级判定，URL 启发式不再参与登录判定。
"""
import json
import logging
import socket
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

from .models import PlatformConfig, SessionState, SessionStatus

logger = logging.getLogger(__name__)

# DOM 级检查超时（附加浏览器/导航）与单个 indicator 等待秒数
DOM_CHECK_TIMEOUT_S = 15.0
INDICATOR_WAIT_S = 2.0


def probe_port(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    """TCP 连接探测端口是否开放"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


_no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check_session_via_cdp(config: PlatformConfig) -> SessionStatus:
    """
    通过 CDP /json 接口获取所有 Tab 的 URL，判断登录状态。
    - 如果有 Tab 在 login_page_indicators 域上 → EXPIRED
    - 如果有 Tab 在目标平台域上且不在登录页 → HEALTHY
    - 端口通但无相关 Tab → UNKNOWN（浏览器开着但没打开对应网站）
    """
    now = datetime.now()
    try:
        url = f"http://127.0.0.1:{config.port}/json"
        req = urllib.request.Request(url, method="GET")
        with _no_proxy_opener.open(req, timeout=0.8) as response:
            if response.status != 200:
                return SessionStatus(
                    platform=config.name,
                    state=SessionState.UNKNOWN,
                    last_checked=now,
                    message=f"CDP 响应异常: HTTP {response.status}",
                    port=config.port,
                    profile_path=config.profile_dir,
                    browser_type=config.browser_type,
                )
            tabs = json.loads(response.read().decode())
    except Exception as e:
        return SessionStatus(
            platform=config.name,
            state=SessionState.UNKNOWN,
            last_checked=now,
            message=f"无法连接 CDP: {e}",
            port=config.port,
            profile_path=config.profile_dir,
            browser_type=config.browser_type,
        )

    # 平台注册域（主机名最后两段）：c.liepin.com→liepin.com、we.51job.com→51job.com，
    # 使 www.liepin.com / www.51job.com 的 Tab 也能命中平台域
    # （旧实现用 login_check_url 子串匹配，只认单个子域，用户停在 www 子域即误报「未登录」）
    def _host_of(url: str) -> str:
        try:
            return (urlparse(url).hostname or "").lower()
        except Exception:
            return ""

    platform_domain = ""
    for base_url in (config.login_check_url, config.auth_url):
        host = _host_of(base_url or "")
        if host:
            platform_domain = ".".join(host.split(".")[-2:])
            break

    platform_tabs = []  # 平台域内各 Tab 是否命中登录页特征
    for tab in tabs:
        tab_url = tab.get("url", "")
        host = _host_of(tab_url)
        in_platform = bool(platform_domain) and (
            host == platform_domain or host.endswith("." + platform_domain)
        )
        if not in_platform:
            continue
        # 登录页特征只在平台域 Tab 上判定：任意网站 URL 恰好含 "/login"（如 github.com/login）
        # 不再误伤本平台判定（liepin 的 "/login" 指标曾对全网 Tab 生效）
        on_login = any(indicator in tab_url for indicator in config.login_page_indicators)
        platform_tabs.append(on_login)

    # 判定优先级：只要有一个平台域 Tab 不在登录页 → 已登录；
    # 平台域 Tab 存在但全在登录页 → 过期（旧实现任一历史登录页 Tab 残留即压过已登录 Tab）；
    # 无平台域 Tab → 未知
    if any(not on_login for on_login in platform_tabs):
        return SessionStatus(
            platform=config.name,
            state=SessionState.HEALTHY,
            last_checked=now,
            last_healthy=now,
            message="会话正常",
            port=config.port,
            profile_path=config.profile_dir,
            browser_type=config.browser_type,
        )

    if platform_tabs:
        return SessionStatus(
            platform=config.name,
            state=SessionState.EXPIRED,
            last_checked=now,
            message="检测到登录页，会话已过期",
            port=config.port,
            profile_path=config.profile_dir,
            browser_type=config.browser_type,
        )

    # 端口通但没有平台相关 Tab
    return SessionStatus(
        platform=config.name,
        state=SessionState.UNKNOWN,
        last_checked=now,
        message="浏览器运行中，但未打开平台页面",
        port=config.port,
        profile_path=config.profile_dir,
        browser_type=config.browser_type,
    )


def check_platform(config: PlatformConfig) -> SessionStatus:
    """完整的单平台健康检查流程"""
    now = datetime.now()

    # Tier 1: 端口探测
    if not probe_port(config.port):
        # 特殊处理：猎聘目前搜索不需要登录，端口不通也算可用
        # 51job 如果有 cookie 文件也算可用（兼容旧逻辑）
        fallback_msg = "浏览器未运行"
        state = SessionState.UNKNOWN

        if config.name == "liepin":
            # 猎聘爬虫搜索不强制登录，端口不通时检查 cookie 文件
            import os
            if config.legacy_cookie_file and os.path.exists(config.legacy_cookie_file):
                return SessionStatus(
                    platform=config.name,
                    state=SessionState.HEALTHY,
                    last_checked=now,
                    last_healthy=now,
                    message="Cookie 文件存在（搜索可用）",
                    port=config.port,
                    profile_path=config.profile_dir,
                    browser_type=config.browser_type,
                )

        if config.name == "51job":
            import os
            if config.legacy_cookie_file and os.path.exists(config.legacy_cookie_file):
                return SessionStatus(
                    platform=config.name,
                    state=SessionState.DEGRADED,
                    last_checked=now,
                    message="Edge 未运行，但 Cookie 文件存在（爬虫可用，投递不可用）",
                    port=config.port,
                    profile_path=config.profile_dir,
                    browser_type=config.browser_type,
                )

        return SessionStatus(
            platform=config.name,
            state=state,
            last_checked=now,
            message=fallback_msg,
            port=config.port,
            profile_path=config.profile_dir,
            browser_type=config.browser_type,
        )

    # Tier 2: CDP Tab 检测
    return check_session_via_cdp(config)


# ============================================================
# DOM 级登录态判定（预检专用，替代 URL 启发式）
# ============================================================

def to_dp_locator(indicator: str) -> str:
    """registry indicator → DrissionPage ele 定位符；无前缀的裸选择器按 CSS 处理。"""
    for prefix in ("css:", "text:", "xpath:", "tag:"):
        if indicator.startswith(prefix):
            return indicator
    return f"css:{indicator}"


def is_logged_in_by_indicators(ele_query, indicators, timeout: float = INDICATOR_WAIT_S) -> bool:
    """
    纯逻辑判定：任一 indicator 命中即视为已登录（与 collector `_ensure_login` 的 or 语义一致）。

    ele_query  : callable(locator, timeout=...) -> element | None（如 DrissionPage page.ele）。
                 契约：timeout 必须以关键字传参——DrissionPage 真实签名是
                 ele(locator, index=1, timeout=None)，第二个位置参数是 index 而非 timeout，
                 位置传参会把 timeout 误当 index（任务 #12 实测根因：已登录却恒判 MISS）。
    indicators : registry 的 login_indicators 列表
    注意：ele_query 抛出的异常不在这里吞掉——由调用方区分「判定失败」与「未登录」。
    """
    for indicator in indicators or []:
        if ele_query(to_dp_locator(indicator), timeout=timeout):
            return True
    return False


def _default_page_factory(port: int):
    """默认工厂：DrissionPage 附加到已监听的平台调试端口（不拉起新浏览器）。"""
    from DrissionPage import ChromiumOptions, ChromiumPage
    co = ChromiumOptions()
    co.set_address(f"127.0.0.1:{port}")
    co.set_timeouts(DOM_CHECK_TIMEOUT_S)
    return ChromiumPage(co)


def _root_domain(url: str) -> str:
    """取 URL 的根域（末两段）。子域视作同站：i.zhaopin.com 与 www.zhaopin.com 同域。"""
    try:
        host = (urlparse(url).netloc or "").split(":")[0].lower()
        parts = [p for p in host.split(".") if p]
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host
    except Exception:
        return ""


def check_login_via_dom(config: PlatformConfig, page_factory=None) -> SessionStatus:
    """
    DOM 级登录态判定：附加平台浏览器 → 按需导航 login_check_url → 按 login_indicators 判定。

    返回三态，绝不假判：
      HEALTHY : 命中任一登录标识
      EXPIRED : 页面正常加载但未命中任何登录标识（登录态确实失效）
      UNKNOWN : 检查本身失败（附加超时/导航异常/元素查询异常），或当前页已在平台
                站点内但未命中标识（可能只是不在登录页）——存疑放行，脚本层二次兜底
    page_factory 可注入以便单测（签名：port -> page-like，具备 .get/.ele/.url 可选）。

    免导航规则（2026-08-31 智联白纸事故）：当前 Tab 已在平台根域内时不再导航——
    预检翻页会把业务页拉走，诱发回写脚本冷加载读到未填充数据。
    """
    now = datetime.now()

    def _mk(state: SessionState, message: str) -> SessionStatus:
        return SessionStatus(
            platform=config.name,
            state=state,
            last_checked=now,
            last_healthy=now if state == SessionState.HEALTHY else None,
            message=message,
            port=config.port,
            profile_path=config.profile_dir,
            browser_type=config.browser_type,
        )

    if not config.login_indicators:
        msg = "registry 未配置 login_indicators，无法做 DOM 级登录判定"
        logger.warning(f"[health] {config.name} {msg}")
        return _mk(SessionState.UNKNOWN, msg)

    if not probe_port(config.port):
        msg = "浏览器端口未监听，无法做 DOM 级登录检查"
        logger.warning(f"[health] {config.name} {msg}（端口 {config.port}）")
        return _mk(SessionState.UNKNOWN, msg)

    factory = page_factory or _default_page_factory
    try:
        page = factory(config.port)
        current_url = ""
        try:
            current_url = getattr(page, "url", "") or ""
        except Exception:
            current_url = ""
        same_site = bool(current_url) and bool(config.login_check_url) and \
            _root_domain(current_url) == _root_domain(config.login_check_url)
        if config.login_check_url and not same_site:
            page.get(config.login_check_url, timeout=DOM_CHECK_TIMEOUT_S)
        if is_logged_in_by_indicators(page.ele, config.login_indicators):
            suffix = "（免导航）" if same_site else ""
            return _mk(SessionState.HEALTHY, f"DOM 级校验通过：命中登录标识{suffix}")
        if same_site:
            # 当前页就在平台站点内（可能停在业务页而非登录页），未命中标识≠未登录：
            # 按存疑放行，回写脚本层还有登录二次校验兜底
            return _mk(SessionState.UNKNOWN, "已在平台站点内但未命中登录标识（免导航预检，可能只是不在登录页），存疑放行")
        return _mk(SessionState.EXPIRED, "DOM 级校验未命中任何登录标识，登录态已失效")
    except Exception as e:
        # 判定失败 ≠ 未登录：留痕并交由调用方走等待/提醒流程
        msg = f"DOM 级检查失败，无法判定登录态: {e}"
        logger.warning(f"[health] {config.name} {msg}", exc_info=True)
        return _mk(SessionState.UNKNOWN, msg)


def _legacy_cookie_usable(config: PlatformConfig) -> bool:
    """该平台是否配置了 legacy cookie 文件且文件真实存在。"""
    import os
    return bool(config.legacy_cookie_file) and os.path.exists(config.legacy_cookie_file)


def check_login_with_fallback(config: PlatformConfig, page_factory=None) -> SessionStatus:
    """
    DOM 判定 + cookie 兜底收敛（预检实际入口）。原则：确证失效才跳，存疑放行。

    - DOM HEALTHY                          → 直接放行
    - DOM EXPIRED 且 legacy cookie 文件存在 → 退回旧 check_platform 的 cookie 兜底，DEGRADED 放行
    - DOM UNKNOWN（附加/导航/查询异常）且 cookie 存在 → 同上 DEGRADED 放行
    - DOM EXPIRED / UNKNOWN 且无 cookie     → 维持原状态（确证失效 / 走等待提醒），不误杀不静默放行

    check_login_via_dom 的三态返回结构不变，收敛只发生在结果层。
    """
    status = check_login_via_dom(config, page_factory=page_factory)
    if status.state == SessionState.HEALTHY:
        return status
    if status.state in (SessionState.EXPIRED, SessionState.UNKNOWN) and _legacy_cookie_usable(config):
        logger.info(
            f"[health] {config.name} DOM 判定 {status.state.value}，"
            f"但 legacy cookie 文件存在（{config.legacy_cookie_file}），按 DEGRADED 兜底放行"
        )
        return SessionStatus(
            platform=config.name,
            state=SessionState.DEGRADED,
            last_checked=status.last_checked,
            last_healthy=None,
            message=f"{status.message}；Cookie 文件存在，兜底放行（爬虫可用）",
            port=config.port,
            profile_path=config.profile_dir,
            browser_type=config.browser_type,
        )
    return status
