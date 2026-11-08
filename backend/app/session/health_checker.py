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
import os
import socket
import time
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
                站点内但未命中标识（可能只是不在登录页）——交由调用方按「需确认」处理
                （预检会发提醒/等待；legacy cookie 存在时走兜底放行）
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
            # 不导航、不误杀，但也不谎报「已登录」——由预检发提醒并等待用户确认。
            return _mk(SessionState.UNKNOWN, "已在平台站点内但未命中登录标识（可能停在登录页或非登录页），需要你确认登录状态")
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


# ==========================================
# 猎聘 profile 登录实证（2026-09-27 双判据批，plan-review R3 PASS）
# ==========================================
# 猎聘登录后才存在的鉴权 cookie 键（本机 liepin_cookies.json 实测键集合背书，
# 游客态无此二键）；与文件通道里的键同名，改名需同步 harvester/引擎注入侧。
LIEPIN_LOGIN_COOKIE_KEYS = ("lt_auth", "liepin_login_valid")

# Chrome/Edge Cookies 库时间基准：1601-01-01 与 unix epoch 的秒差
_CHROME_EPOCH_OFFSET_S = 11644473600.0


def _judge_login_keys(found: dict[str, float]) -> bool:
    """判据：两键同时存在且均未过期。expires<=0 视为会话 cookie，落账即有效。"""
    if not all(k in found for k in LIEPIN_LOGIN_COOKIE_KEYS):
        return False
    now = time.time()
    return all(exp <= 0 or exp > now for exp in found.values())


def _cookie_expiry_value(cookie: dict) -> float | None:
    """取 cookie 过期时间（Unix 秒）；None = 字段无法解析，按失效处理。"""
    exp = cookie.get("expires")
    if exp is None:
        exp = cookie.get("expiry", -1)
    if exp in (None, ""):
        return 0.0  # 会话 cookie：落账即有效
    try:
        return float(exp)
    except (TypeError, ValueError):
        return None


def has_valid_liepin_auth_cookies(cookies) -> bool:
    """从浏览器 cookie 列表判定猎聘登录态（lt_auth + liepin_login_valid 齐且未过期）。

    与 `_judge_login_keys` 同一判据，供 liepin_session / liepin_crawler 在浏览器内
    直接判定，避免 `check_login_status()` 仅凭 URL 前缀误把登录页当已登录。
    """
    found: dict[str, float | None] = {}
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if name in LIEPIN_LOGIN_COOKIE_KEYS and name not in found:
            found[name] = _cookie_expiry_value(c)
    if not all(k in found for k in LIEPIN_LOGIN_COOKIE_KEYS):
        return False
    now = time.time()
    return all(exp is not None and (exp <= 0 or exp > now) for exp in found.values())


def _collect_login_keys_from_cookies(cookies, keys=LIEPIN_LOGIN_COOKIE_KEYS) -> dict[str, float]:
    """cookie 列表 → 登录键字典（CDP/Playwright 两种返回形态共用）。"""
    found: dict[str, float] = {}
    for c in cookies or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if name in keys and name not in found:
            exp = c.get("expires", -1)
            found[name] = float(exp) if isinstance(exp, (int, float)) and exp > 0 else 0.0
    return found


def _read_login_keys_via_cdp(port: int, keys=LIEPIN_LOGIN_COOKIE_KEYS) -> dict[str, float] | None:
    """端口 UP 模：playwright connect_over_cdp 被动附着读内存 cookie。

    零页面导航、零 cookie 写入，实时感知扫码落账（不受磁盘 WAL 刷盘延迟影响）。
    sync API 只能在无事件循环的线程中运行（异步调用方须 asyncio.to_thread 包装）。
    连接失败/异常返回 None，由调用方回退 profile Cookies 库。

    2026-10-30 真机修复：旧实现遍历 `browser.contexts[*].cookies()`，附着 DrissionPage
    拉起的 Edge 时会触发 `Browser.setDownloadBehavior: Browser context management is
    not supported`，导致登录实证恒 False（预检误判失效、投递前反复要求扫码）。
    改为 browser 级 CDP session 的 `Storage.getCookies`，不触碰 Playwright 的 context
    管理；旧路径保留为兜底。
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=3000)
            try:
                try:
                    session = browser.new_browser_cdp_session()
                    try:
                        result = session.send("Storage.getCookies")
                    finally:
                        try:
                            session.detach()
                        except Exception:
                            pass
                    return _collect_login_keys_from_cookies(result.get("cookies") or [], keys)
                except Exception as cdp_e:
                    logger.info(f"[health] browser CDP session 读 cookie 失败（port={port}），回退 context.cookies: {cdp_e}")
                    found: dict[str, float] = {}
                    for ctx in browser.contexts:
                        for c in ctx.cookies():
                            if c.get("name") in keys and c.get("name") not in found:
                                exp = c.get("expires", -1)
                                found[c["name"]] = float(exp) if isinstance(exp, (int, float)) and exp > 0 else 0.0
                    return found
            finally:
                # CDP 附着模式下 close() 仅断开连接，不杀远端浏览器进程
                browser.close()
    except Exception as e:
        logger.info(f"[health] CDP 读 cookie 失败（port={port}）: {e}")
        return None


def _read_login_keys_via_profile_db(profile_dir: str, keys=LIEPIN_LOGIN_COOKIE_KEYS) -> dict[str, float] | None:
    """端口 DOWN 模：拷贝 profile Cookies 库（连同 -wal/-shm）到临时目录后只读查键，用完即删。"""
    import shutil
    import sqlite3
    import tempfile

    if not profile_dir:
        return None
    try:
        src = os.path.join(profile_dir, "Default", "Cookies")
        if not os.path.exists(src):
            return None
        with tempfile.TemporaryDirectory(prefix="liepin_cookie_probe_") as tmp:
            dst = os.path.join(tmp, "Cookies")
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(src + suffix):
                    shutil.copy2(src + suffix, dst + suffix)
            conn = sqlite3.connect(dst)
            try:
                rows = conn.execute(
                    f"SELECT name, expires_utc FROM cookies WHERE name IN ({', '.join('?' * len(keys))})",
                    tuple(keys),
                ).fetchall()
            finally:
                conn.close()
    except Exception as e:
        logger.info(f"[health] profile Cookies 库读取失败（{profile_dir}）: {e}")
        return None

    found: dict[str, float] = {}
    for name, exp_utc in rows:
        # Chrome epoch（1601-01-01 起微秒）→ unix 秒；0/空=会话 cookie，落盘可恢复，计有效
        found[name] = 0.0 if not exp_utc else max(0.0, exp_utc / 1_000_000 - _CHROME_EPOCH_OFFSET_S)
    return found


def is_liepin_cookie_file_valid(path: str) -> bool:
    """猎聘 legacy cookie 文件级有效性：文件存在且解析后含未过期的登录键。

    2026-10-31 事故根治：文件「存在」≠「有效」——猎聘 Cookie 有效期由平台
    服务端控制，过期文件曾让预检放行、引擎降级访客态深页抓取，被登录墙
    整轮拦截后还静默 0 条收场。判据与浏览器内 `has_valid_liepin_auth_cookies`
    完全同源（lt_auth + liepin_login_valid 双键未过期）；文件缺失/损坏/
    解析异常一律 fail-closed 判 False。
    """
    try:
        if not path or not os.path.exists(path):
            return False
        with open(path, encoding="utf-8") as f:
            cookies = json.load(f)
        if not isinstance(cookies, list):
            return False
        return has_valid_liepin_auth_cookies(cookies)
    except Exception as e:
        logger.info(f"[health] 猎聘 Cookie 文件有效性判定异常，fail-closed: {e}")
        return False


def _judge_login_keys_for(found: dict[str, float], keys) -> bool:
    """凭证键集合判定：全部在列且未过期（expires<=0 视为会话 cookie，落账即有效）。"""
    if not keys:
        return False
    if not all(k in found for k in keys):
        return False
    now = time.time()
    return all(exp <= 0 or exp > now for exp in (found[k] for k in keys))


def check_platform_login_cookie_evidence(
    platform: str, port: int | None = None, profile_dir: str | None = None
) -> bool:
    """平台通用登录实证（纯同步）：registry.auth_cookie_keys 全键齐且未过期。

    check_liepin_login_evidence 的多平台泛化（2026-11-03 冷启动误判根治）：
    预检拉起浏览器后先做本实证（零导航、零 DOM、不惊动风控），实证通过即无需
    DOM 判定——冷启动场景 DOM 判定会跑在 Edge 会话恢复之前造成全员误判。
    双模取数与 fail-closed 语义与猎聘版完全一致。
    """
    try:
        from .registry import get_platform_port, get_profile_path, resolve_platform
        cfg = resolve_platform(platform)
        if not cfg or not cfg.auth_cookie_keys:
            return False
        _port = port if port is not None else get_platform_port(platform)
        _profile = profile_dir if profile_dir is not None else (cfg.profile_dir or get_profile_path(platform))
        keys = tuple(cfg.auth_cookie_keys)

        if probe_port(_port, timeout=0.3):
            found = _read_login_keys_via_cdp(_port, keys)
            if not found:
                # None=通道异常；{}=内存里暂无凭证键。都回退磁盘库兜底
                # （2026-11-03：session 键不落盘会假阴性，磁盘兜底是最后防线）
                logger.info(
                    "[health] %s CDP 读 cookie 不可用/无凭证（port=%s，found=%r），回退 profile Cookies 库：%s",
                    platform, _port, found, _profile,
                )
                found = _read_login_keys_via_profile_db(_profile, keys)
        else:
            found = _read_login_keys_via_profile_db(_profile, keys)
        if not found:
            return False
        return _judge_login_keys_for(found, keys)
    except Exception as e:
        logger.info(f"[health] {platform} 登录实证异常，fail-closed: {e}")
        return False


def check_liepin_login_evidence(port: int | None = None, profile_dir: str | None = None) -> bool:
    """猎聘登录实证（纯同步）：Edge 专用 profile 是否携带真实登录态。

    双模取数：端口 UP → CDP 直读内存 cookie；端口 DOWN → 离线拷贝 profile Cookies 库
    （连同 -wal/-shm，规避只拷主文件漏读 WAL 的假阴性）。端口 UP 但 CDP 读失败时
    （2026-10-30：DrissionPage 拉起的 Edge 与 Playwright context 不兼容），同样回退
    离线 profile Cookies 库，避免把「读不到」误判成「未登录」。判据=LIEPIN_LOGIN_COOKIE_KEYS
    两键齐且未过期。全流程兜底 try/except，任一环节失败一律 fail-closed 判 False
    （回到「缺 Cookie 文件」原路径），绝不因探测异常误放行或向调用方抛错。
    """
    try:
        from .registry import get_platform_port, get_profile_path
        _port = port if port is not None else get_platform_port("liepin")
        _profile = profile_dir if profile_dir is not None else get_profile_path("liepin")

        if probe_port(_port, timeout=0.3):
            found = _read_login_keys_via_cdp(_port)
            if found is None:
                logger.info(
                    "[health] CDP 读 cookie 不可用（port=%s），回退 profile Cookies 库：%s",
                    _port, _profile,
                )
                found = _read_login_keys_via_profile_db(_profile)
        else:
            found = _read_login_keys_via_profile_db(_profile)
        if not found:
            return False
        return _judge_login_keys(found)
    except Exception as e:
        logger.info(f"[health] 猎聘登录实证异常，fail-closed: {e}")
        return False


# 猎聘实证复检重试参数：DrissionPage 拉起的 Edge 上 CDP 读 cookie 不稳定
# （2026-10-30 已记录的 Playwright context 兼容性问题），单次复检会在「可用/
# 不可用」间翻转，曾把预检刚实证放行的轮次在采集门误拦（2026-10-31 晚间事故：
# 19:59:01 预检通过、19:59:07 采集门拦截，间隔 6 秒结论相反）。
_LIEPIN_EVIDENCE_ATTEMPTS = 3
_LIEPIN_EVIDENCE_RETRY_INTERVAL_S = 2.0


def liepin_collect_ready(cookie_file: str) -> bool:
    """采集入口放行双判据：Cookie 文件有效（存在且凭证未过期），或 Edge profile 登录实证有效。

    nl_controller 的文件硬门改判据后的统一入口（主进程不持浏览器会话，
    实证由本函数在调用线程内完成）。
    2026-10-31 事故根治：文件短路从「存在」升级为「有效」——过期文件曾让
    本门放行、引擎以访客态跑完全程静默 0 条；失效文件与缺失文件同走实证
    复检（profile 可能仍带活登录态，引擎启动后会自愈回写新文件）。
    实证复检带界重试：单次 CDP 读在 DrissionPage Edge 上会闪断，任一次成功即放行，
    全部失败才 fail-closed。"""
    if is_liepin_cookie_file_valid(cookie_file):
        return True
    for attempt in range(_LIEPIN_EVIDENCE_ATTEMPTS):
        if check_liepin_login_evidence():
            return True
        if attempt < _LIEPIN_EVIDENCE_ATTEMPTS - 1:
            time.sleep(_LIEPIN_EVIDENCE_RETRY_INTERVAL_S)
    return False
