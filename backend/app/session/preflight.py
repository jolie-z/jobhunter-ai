"""
全链路启动前置检查 — 平台登录态自动保障
======================================

全自动链路（run_full_auto_pipeline）抓取段开始前调用 ensure_platforms_ready：

1. 端口探测：平台浏览器未监听 → 自动 launch_edge 拉起（registry 唯一配置区），等待就绪
2. 登录态检查：health_checker.check_login_with_fallback —— DOM 级判定 + cookie 兜底收敛
   （附加平台浏览器 → 导航 login_check_url → 按 registry login_indicators 判定，
   与各平台 collector 的 _ensure_login 同一标准；不再用 Tab URL 启发式，
   避免「智联 auth_url 命中登录页特征」的假阳性与「BOSS/51job 掉线 URL 不变」的假阴性）
   收敛原则「确证失效才跳，存疑放行」：DOM 判 EXPIRED/UNKNOWN 但 legacy cookie 文件
   存在时按 DEGRADED 兜底放行（与旧 check_platform 的 cookie 兜底语义一致）
2.5 requires_login=False 的平台（如猎聘：搜索抓取无需登录，cookie 仅可选注入）
   直接豁免登录校验放行，不做 DOM 判定（匿名首页不渲染登录元素，判定必然误报）
3. 失效/判定失败 → 发飞书通知（接收目标与日报一致：job_goals.feishu_receive_id），
   并在等待窗口内按固定间隔复检，给用户手动扫码登录的时间
   （DOM 检查本身失败时按「无法判定」处理，同样走等待/提醒，不静默放行）
4. 窗口结束仍未恢复 → 该平台标记失效，本次任务的抓取跳过（无抓取自然也无投递）

环境变量：
- PIPELINE_LOGIN_WAIT_S：等待用户登录的窗口秒数，默认 300
- PIPELINE_LOGIN_POLL_S：复检间隔秒数，默认 10
"""
import asyncio
import logging
import os
import time

from .browser import close_edge, launch_edge
from .cdp_probe import probe_cdp_channel
from .health_checker import (
    check_liepin_login_evidence,
    check_login_with_fallback,
    probe_port,
)
from .models import SessionState, SessionStatus
from .registry import resolve_platform

logger = logging.getLogger(__name__)

# 视为可用的状态：HEALTHY=登录有效；DEGRADED=Edge 未运行但 cookie 文件可用（爬虫可跑）
_OK_STATES = (SessionState.HEALTHY, SessionState.DEGRADED)

# pending 平台的待办类型：
#   "login"       = 登录态失效，复检走 DOM 级 check_login_with_fallback
#   "cookie_file" = 免登录平台但本地 legacy cookie 文件缺失（如猎聘：抓取引擎缺文件直接 0 条
#                   收工，2026-09-26 新机排查）。复检双判据（2026-09-27）：文件落盘，或
#                   Edge profile 登录实证有效（会话条「唤起浏览器」登录与采集引擎共用同一
#                   profile，登录落账即解锁，CDP 直读内存 cookie 不受刷盘延迟影响）
_PENDING_KIND_LOGIN = "login"
_PENDING_KIND_COOKIE_FILE = "cookie_file"


def _wait_seconds() -> int:
    try:
        return max(0, int(os.environ.get("PIPELINE_LOGIN_WAIT_S", "300")))
    except ValueError:
        return 300


def _poll_seconds() -> int:
    try:
        return max(3, int(os.environ.get("PIPELINE_LOGIN_POLL_S", "10")))
    except ValueError:
        return 10


async def _notify_login_needed(items: list, wait_s: int) -> None:
    """汇总一条飞书通知：哪些平台登录态/Cookie 资产异常、等待窗口多长。

    items: [(config, status, kind)]，kind 见 _PENDING_KIND_* 常量。
    """
    has_login_pending = any(kind == _PENDING_KIND_LOGIN for _, _, kind in items)
    lines = ["🚨 全链路预检：以下平台登录态/Cookie 资产异常，需要手动处理"]
    for config, status, kind in items:
        if kind == _PENDING_KIND_COOKIE_FILE:
            lines.append(
                f"· {config.display_name}：缺少本地 Cookie 文件"
                f"（{config.legacy_cookie_file}）——可在指挥中心会话条「唤起浏览器」"
                f"登录 {config.display_name}，或在后端终端运行"
                f" `liepin_cookie_harvester.py` 扫码生成；任一完成后自动继续"
            )
        else:
            lines.append(f"· {config.display_name}（端口 {config.port}）：{status.message}")
    if wait_s > 0:
        lines.append(f"等待窗口 {max(1, wait_s // 60)} 分钟；")
        if has_login_pending:
            lines.append("已自动唤起对应浏览器，请在窗口内完成登录；")
        lines.append("逾期未处理的平台，本次任务的抓取与投递将被跳过。")
    else:
        lines.append("本次任务将跳过上述平台的抓取与投递。")
    text = "\n".join(lines)

    # 统一发送通道：校验接收ID格式、检查真实送达、失败降级打印（不再假记「已发送」）
    from app.automation.pipeline_report import send_pipeline_report
    ok = await send_pipeline_report(text)
    if ok:
        logger.info("[preflight] 登录失效通知已真实送达飞书")
    else:
        logger.warning("[preflight] 登录失效通知未能送达飞书（详见控制台降级输出）")


async def _log_preflight(msg: str, emit_log=None) -> None:
    logger.info(f"[preflight] {msg}")
    if emit_log:
        try:
            await emit_log(msg)
        except Exception:
            pass


async def _ensure_browser_ready(config, emit_log=None) -> bool:
    """端口探活 + CDP 命令通道探活 → 按需优雅重启僵尸 / 拉起新浏览器，等待就绪。

    Returns:
        True=浏览器可用（CDP 命令通道就绪）；False=按不可用处理。
    僵尸判定与自愈（2026-10-08 51job 事故）：端口通但 CDP 命令永不响应（HTTP 活着、
    websocket 死了）时，TCP/HTTP 探活全绿，引擎附着即挂满超时——唯一修复是重启浏览器。
    """
    port_ok = await asyncio.to_thread(probe_port, config.port)
    restarting_from_zombie = False
    if port_ok:
        channel = await asyncio.to_thread(probe_cdp_channel, config.port)
        if channel == "alive":
            return True
        if channel == "zombie":
            await _log_preflight(
                f"🧟 {config.display_name} 端口 {config.port} CDP 命令通道僵死（HTTP 通但命令不应答），优雅重启浏览器…",
                emit_log,
            )
            try:
                await asyncio.to_thread(close_edge, config)
            except Exception as e:
                await _log_preflight(f"⚠️ {config.display_name} 旧浏览器关闭失败（仍尝试重新拉起）: {e}", emit_log)
            # 端口释放窗口：close_edge 已等进程退出，这里再留缓冲防 SingletonLock 竞争
            await asyncio.sleep(2)
            restarting_from_zombie = True
        # channel == "down"：端口通 TCP 但 HTTP 层确定无服务，与未监听同走拉起路径

    if restarting_from_zombie:
        await _log_preflight(f"♻️ {config.display_name} 僵尸浏览器已关闭，重新拉起…", emit_log)
    else:
        await _log_preflight(f"🌐 {config.display_name} 端口 {config.port} 未监听，自动拉起浏览器…", emit_log)
    try:
        await asyncio.to_thread(launch_edge, config)
    except Exception as e:
        await _log_preflight(f"❌ {config.display_name} 浏览器拉起失败: {e}", emit_log)
        return False
    for _ in range(30):
        await asyncio.sleep(1)
        if await asyncio.to_thread(probe_port, config.port):
            await _log_preflight(f"✓ {config.display_name} 浏览器已就绪（端口 {config.port}）", emit_log)
            return True
    await _log_preflight(f"❌ {config.display_name} 浏览器 30 秒内未就绪，按不可用处理", emit_log)
    return False


async def ensure_platforms_ready(platforms: list, emit_log=None) -> dict:
    """
    逐平台保障登录态，返回 {平台key: 是否可用}。

    platforms : registry 规范平台 key 列表（boss/liepin/51job/zhilian/xiaohongshu）
    emit_log  : 可选 async callable(message)，把过程日志推进全链路 SSE
    """
    async def _log(msg: str):
        logger.info(f"[preflight] {msg}")
        if emit_log:
            try:
                await emit_log(msg)
            except Exception:
                pass

    results: dict = {}
    pending: dict = {}  # 平台key -> (config, status)，等待用户登录

    for key in platforms:
        config = resolve_platform(key)
        if config is None:
            await _log(f"⚠️ 平台 {key} 无 registry 配置，按不可用处理")
            results[key] = False
            continue

        # 0. 登录豁免：抓取不强制登录的平台（如猎聘，cookie 仅可选注入）直接放行，
        #    匿名首页不渲染登录元素，DOM 校验只会误报。
        #    但豁免 ≠ 资产齐全：猎聘抓取引擎硬依赖本地 legacy cookie 文件（缺失时
        #    直接 0 条收工、整轮空转），故文件缺失时按「登录态异常」同通道拦截——
        #    发飞书通知指引扫码 + 等待窗口内轮询放行。复检双判据（2026-09-27）：
        #    文件落盘，或 Edge profile 登录实证有效（专用浏览器与采集引擎同
        #    profile，用户在会话条登录即解锁，无需命令行 harvester）。
        #    文件存在 ≠ 凭证有效（有效期由平台服务端说了算），有效性由投递门
        #    ensure_login DOM 实测兜底，预检不重复做。
        if not config.requires_login:
            if config.legacy_cookie_file:
                try:
                    cookie_ok = os.path.exists(config.legacy_cookie_file)
                except OSError:
                    cookie_ok = False
                if not cookie_ok:
                    # 双判据之实证侧：目前仅猎聘（键集合为猎聘特有，别平台误用会恒 False）
                    if config.name == "liepin":
                        evidence_ok = await asyncio.to_thread(check_liepin_login_evidence)
                        if evidence_ok:
                            results[key] = True
                            await _log(
                                f"✅ {config.display_name} 无 Cookie 文件，"
                                f"但专用浏览器登录实证有效，放行（采集启动后将自动回写文件）"
                            )
                            continue
                    pending[key] = (
                        config,
                        SessionStatus(
                            platform=config.name,
                            state=SessionState.EXPIRED,
                            message=f"缺少本地 Cookie 文件: {config.legacy_cookie_file}",
                        ),
                        _PENDING_KIND_COOKIE_FILE,
                    )
                    await _log(
                        f"⚠️ {config.display_name} 缺少 Cookie 文件且未检出浏览器登录态，"
                        f"等待处理（会话条唤起浏览器登录，或运行 liepin_cookie_harvester.py）…"
                    )
                    continue
            results[key] = True
            await _log(f"✅ {config.display_name} 无需登录，豁免预检登录校验")
            continue

        # 1. 浏览器探活/拉起/僵尸自愈（共用 _ensure_browser_ready）
        if not await _ensure_browser_ready(config, emit_log):
            results[key] = False
            continue

        # 1.5 确保至少存在 1 个活跃标签页，防止 CDP 连接因 0 标签页失败
        try:
            import requests as _rq
            _r = await asyncio.to_thread(_rq.get, f"http://127.0.0.1:{config.port}/json", proxies={"http": None, "https": None}, timeout=1)  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
            _tabs = [t for t in (_r.json() or []) if t.get("type") == "page"]
            if not _tabs:
                _target_url = config.login_check_url or config.auth_url or "about:blank"
                await asyncio.to_thread(_rq.put, f"http://127.0.0.1:{config.port}/json/new?{_target_url}", proxies={"http": None, "https": None}, timeout=2)  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        except Exception:
            pass

        # 2. 登录态检查（DOM 级判定 + cookie 兜底收敛：确证失效才跳，存疑放行）
        status = await asyncio.to_thread(check_login_with_fallback, config)
        if status.state in _OK_STATES:
            results[key] = True
            if status.state == SessionState.DEGRADED:
                await _log(f"✅ {config.display_name} cookie 兜底放行（{status.message}）")
            else:
                await _log(f"✅ {config.display_name} 登录态正常（{status.message}）")
        else:
            pending[key] = (config, status, _PENDING_KIND_LOGIN)

    # 3. 失效平台：发飞书通知 + 等待窗口内轮询复检
    aborted_early = False
    if pending:
        wait_s = _wait_seconds()
        await _notify_login_needed(list(pending.values()), wait_s)
        names = "、".join(c.display_name for c, _, _ in pending.values())
        await _log(f"⚠️ 登录态/资产异常: {names}；已发飞书通知，等待 {wait_s} 秒内手动处理…")

        # 0928 事故修复：等待循环接入终止信号——用户点「终止任务」不应干等满窗口
        from app.automation import abort as abort_mod  # 惰性导入，避免模块级循环依赖

        deadline = time.monotonic() + wait_s
        while pending and time.monotonic() < deadline:
            if abort_mod.is_aborted():
                aborted_early = True
                await _log("🛑 检测到全链路终止信号，预检等待提前结束，未恢复平台按跳过处理")
                break
            await asyncio.sleep(_poll_seconds())
            for key in list(pending):
                config, _, kind = pending[key]
                if kind == _PENDING_KIND_COOKIE_FILE:
                    # 复检双判据（2026-09-27）：①文件落盘即放行（hot-polling 原判据）；
                    # ②猎聘增补——Edge profile 登录实证有效也放行（CDP 直读内存 cookie，
                    # 用户在会话条扫码登录落账的瞬间即被感知，不受磁盘刷盘延迟影响）
                    try:
                        recovered = os.path.exists(config.legacy_cookie_file)
                    except OSError:
                        recovered = False
                    message = "Cookie 文件已生成" if recovered else ""
                    if not recovered and config.name == "liepin":
                        recovered = await asyncio.to_thread(check_liepin_login_evidence)
                        if recovered:
                            message = "专用浏览器登录实证有效（Cookie 文件将在采集启动时自动回写）"
                    if recovered:
                        status = SessionStatus(
                            platform=config.name,
                            state=SessionState.HEALTHY,
                            message=message,
                        )
                    else:
                        continue
                else:
                    status = await asyncio.to_thread(check_login_with_fallback, config)
                if status.state in _OK_STATES:
                    results[key] = True
                    del pending[key]
                    await _log(f"🎉 {config.display_name} 登录已恢复，纳入本轮任务")

    # 4. 窗口结束仍未登录 → 本次任务跳过
    for key, (config, status, kind) in pending.items():
        results[key] = False
        if aborted_early:
            await _log(f"🛑 {config.display_name} 因任务终止被跳过（预检未完成）")
        elif kind == _PENDING_KIND_COOKIE_FILE:
            await _log(f"⛔ {config.display_name} 等待超时仍未生成 Cookie 文件，本次任务跳过该平台")
        else:
            await _log(f"⛔ {config.display_name} 等待超时仍未登录，本次任务跳过该平台（{status.message}）")

    return results


# ==========================================
# 批次级投递预检（定时发射 / 手动批量 / delivery_node 逐岗共用，2026-10-08/09）
# ==========================================

# 预检成功 TTL 缓存：delivery_node 逐岗调用时避免每岗全量探活/登录判定。
# 只缓存成功——失败/超时不进缓存，下次调用照常全检。
# 失效机制（CR R1 P1）：命中时保留 probe_port 最小探活兜底（浏览器被关/僵尸可当场识破）；
# close-all 等主动关闭路径须调 clear_platform_ready_cache 清缓存。
# 失败冷却（CR R1 P2）：未就绪平台 30s 内直接判失败，不重进等待窗口，防逐岗串行阻塞。
_READY_TTL_S = 300
_NOT_READY_COOLDOWN_S = 30
_ready_cache: dict[str, float] = {}
_notready_until: dict[str, float] = {}


def clear_platform_ready_cache(platform: str | None = None) -> None:
    """主动关闭浏览器/登出/手动唤起等场景调用：清投递预检状态（成功缓存 + 失败冷却）。

    只清成功缓存不清冷却 → 手动唤起扫码后仍会被残余冷却拦 ≤30s（CR R2 P2），两者同步清。"""
    if platform is None:
        _ready_cache.clear()
        _notready_until.clear()
    else:
        _ready_cache.pop(platform, None)
        _notready_until.pop(platform, None)


async def ensure_delivery_platforms_ready(platforms: list, emit_log=None) -> dict:
    """投递发射前的平台就绪预检：浏览器探活/自愈 + 登录态判定 + 失效等待窗口。

    与抓取预检 ensure_platforms_ready 的差异：
    - 无登录豁免：投递需要登录态。猎聘（抓取侧 requires_login=False）在此改用
      check_liepin_login_evidence 做 cookie 键实证——浏览器 UP 时 CDP 直读内存
      cookie，等待窗口内用户扫码落账即时感知；浏览器 DOWN 时离线读 profile 库。
      实证失效时先尝试本地 Cookie 文件注入一次（浏览器已就绪），仍失效才进等待窗口。
    - 抓取豁免平台（小红书等）不在投递平台集合内，天然不经过本函数。
    - 成功结果 TTL 缓存（_READY_TTL_S）：delivery_node 逐岗接线后同平台短时间重复
      调用免重探。

    Returns:
        {平台key: 是否可用}。不可用平台调用方应跳过其岗位：保留飞书「待投递」门牌，
        在「自动投递失败日志」记 [环境] 跳过原因，下轮波次自然重试。
    """
    async def _log(msg: str):
        await _log_preflight(msg, emit_log)

    results: dict = {}
    pending: dict = {}  # 平台key -> (config, status)
    injection_attempted: set[str] = set()  # 猎聘 JSON 注入每轮预检至多尝试一次

    async def _judge(config) -> SessionStatus:
        """单平台登录判定：猎聘走 cookie 键实证，其余平台走 DOM+cookie 兜底。"""
        if config.name == "liepin":
            ok = await asyncio.to_thread(check_liepin_login_evidence)
            return SessionStatus(
                platform=config.name,
                state=SessionState.HEALTHY if ok else SessionState.EXPIRED,
                message="猎聘登录实证通过" if ok else "猎聘登录实证失效（登录 cookie 键缺失/过期），需扫码登录",
            )
        return await asyncio.to_thread(check_login_with_fallback, config)

    async def _judge_with_injection(config, key: str) -> SessionStatus:
        """猎聘专用：实证失效先尝试 JSON 注入一次再复测（浏览器已就绪），仍失效才进等待窗口。

        2026-10-09 猎聘 22:30 事故补环：引擎内 ensure_login 的注入逻辑流程上死在更早的
        无浏览器/守卫环节——预检把浏览器拉起后主动补一针注入，JSON 新鲜时直接恢复登录，
        不用等用户扫码。每轮预检至多注入一次（等待窗口轮询复检不再重复注入）。
        """
        status = await _judge(config)
        if status.state in _OK_STATES or config.name != "liepin" or key in injection_attempted:
            return status
        injection_attempted.add(key)
        await _log(f"🍪 [投递预检] {config.display_name} 登录实证失效，尝试本地 Cookie 文件注入…")
        try:
            import liepin_session  # DrissionPage 重导入，惰性加载
            ok = await asyncio.to_thread(liepin_session.inject_cookies_if_needed)
        except Exception as inj_e:
            await _log(f"⚠️ {config.display_name} Cookie 注入异常（继续走等待窗口）: {inj_e}")
            return status
        if ok:
            await _log(f"🍪 [投递预检] {config.display_name} Cookie 注入成功，登录态已恢复")
        return await _judge(config)

    for key in platforms:
        config = resolve_platform(key)
        if config is None:
            await _log(f"⚠️ 平台 {key} 无 registry 配置，按不可用处理")
            results[key] = False
            continue

        # 0a. 失败冷却：短期内刚判过未就绪 → 直接失败，不重进等待窗口（防逐岗串行阻塞）
        cool_until = _notready_until.get(key)
        if cool_until is not None and time.monotonic() < cool_until:
            results[key] = False
            await _log(f"⛔ [投递预检] {config.display_name} 处于未就绪冷却期（{_NOT_READY_COOLDOWN_S}s），本轮直接跳过")
            continue

        # 0b. 成功 TTL 缓存命中 → 免全量重探，但保留 probe_port 最小兜底（防缓存期浏览器被关/僵死穿透）
        last_ok = _ready_cache.get(key)
        if last_ok is not None and (time.monotonic() - last_ok) < _READY_TTL_S:
            if await asyncio.to_thread(probe_port, config.port):
                results[key] = True
                await _log(f"⚡ [投递预检] {config.display_name} {_READY_TTL_S}s 内已验证就绪（缓存命中且端口存活），跳过重探")
                continue
            _ready_cache.pop(key, None)
            await _log(f"⚠️ [投递预检] {config.display_name} 缓存期内端口已失活，缓存作废走全检")

        # 1. 浏览器探活/僵尸自愈/拉起
        if not await _ensure_browser_ready(config, emit_log):
            results[key] = False
            _notready_until[key] = time.monotonic() + _NOT_READY_COOLDOWN_S
            continue

        # 2. 登录判定（猎聘实证失效先注入一次再复测）
        status = await _judge_with_injection(config, key)
        if status.state in _OK_STATES:
            results[key] = True
            _ready_cache[key] = time.monotonic()
            await _log(f"✅ [投递预检] {config.display_name} 就绪（{status.message}）")
        else:
            pending[key] = (config, status)

    # 3. 失效平台：发一条飞书汇总 + 一个等待窗口（窗口内轮询复检，浏览器 UP 走 CDP 实时判定）
    if pending:
        wait_s = _wait_seconds()
        await _notify_login_needed(
            [(c, s, _PENDING_KIND_LOGIN) for c, s in pending.values()], wait_s,
        )
        names = "、".join(c.display_name for c, _ in pending.values())
        await _log(f"⚠️ [投递预检] 登录态异常: {names}；已发飞书通知，等待 {wait_s} 秒内手动登录…")

        from app.automation import abort as abort_mod  # 惰性导入，避免模块级循环依赖

        deadline = time.monotonic() + wait_s
        while pending and time.monotonic() < deadline:
            if abort_mod.is_aborted():
                await _log("🛑 检测到全链路终止信号，投递预检等待提前结束，未恢复平台按跳过处理")
                break
            await asyncio.sleep(_poll_seconds())
            for key in list(pending):
                config, _ = pending[key]
                status = await _judge(config)
                if status.state in _OK_STATES:
                    results[key] = True
                    _ready_cache[key] = time.monotonic()
                    del pending[key]
                    await _log(f"🎉 [投递预检] {config.display_name} 登录已恢复，纳入本轮发射")

    # 4. 窗口结束仍未恢复 → 本轮跳过（岗位保留「待投递」，下轮波次自然重试）
    for key, (config, status) in pending.items():
        results[key] = False
        _notready_until[key] = time.monotonic() + _NOT_READY_COOLDOWN_S
        await _log(f"⛔ [投递预检] {config.display_name} 等待超时仍未登录，本轮发射跳过该平台（{status.message}）")

    return results
