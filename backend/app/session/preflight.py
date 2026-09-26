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

from .browser import launch_edge
from .health_checker import check_login_with_fallback, probe_port
from .models import SessionState, SessionStatus
from .registry import resolve_platform

logger = logging.getLogger(__name__)

# 视为可用的状态：HEALTHY=登录有效；DEGRADED=Edge 未运行但 cookie 文件可用（爬虫可跑）
_OK_STATES = (SessionState.HEALTHY, SessionState.DEGRADED)

# pending 平台的待办类型：
#   "login"       = 登录态失效，复检走 DOM 级 check_login_with_fallback
#   "cookie_file" = 免登录平台但本地 legacy cookie 文件缺失（如猎聘：抓取引擎缺文件直接 0 条
#                   收工，2026-09-26 新机排查），复检只看文件是否落盘（hot-polling）
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
                f"（{config.legacy_cookie_file}）——请在后端终端运行"
                f" `liepin_cookie_harvester.py` 扫码登录生成后自动继续"
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
        #    发飞书通知指引扫码 + 等待窗口内轮询文件落盘即放行（hot-polling）。
        #    文件存在 ≠ 凭证有效（有效期由平台服务端说了算），有效性由投递门
        #    ensure_login DOM 实测兜底，预检不重复做。
        if not config.requires_login:
            if config.legacy_cookie_file:
                try:
                    cookie_ok = os.path.exists(config.legacy_cookie_file)
                except OSError:
                    cookie_ok = False
                if not cookie_ok:
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
                        f"⚠️ {config.display_name} 免登录平台但缺少 Cookie 文件，"
                        f"等待扫码生成（运行 liepin_cookie_harvester.py）…"
                    )
                    continue
            results[key] = True
            await _log(f"✅ {config.display_name} 无需登录，豁免预检登录校验")
            continue

        # 1. 端口探测 → 不通则自动拉起并等待就绪
        port_ok = await asyncio.to_thread(probe_port, config.port)
        if not port_ok:
            await _log(f"🌐 {config.display_name} 端口 {config.port} 未监听，自动拉起浏览器…")
            try:
                await asyncio.to_thread(launch_edge, config)
            except Exception as e:
                await _log(f"❌ {config.display_name} 浏览器拉起失败: {e}")
                results[key] = False
                continue
            ready = False
            for _ in range(30):
                await asyncio.sleep(1)
                if await asyncio.to_thread(probe_port, config.port):
                    ready = True
                    break
            if not ready:
                await _log(f"❌ {config.display_name} 浏览器 30 秒内未就绪，按不可用处理")
                results[key] = False
                continue
            await _log(f"✓ {config.display_name} 浏览器已就绪（端口 {config.port}）")

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
    if pending:
        wait_s = _wait_seconds()
        await _notify_login_needed(list(pending.values()), wait_s)
        names = "、".join(c.display_name for c, _, _ in pending.values())
        await _log(f"⚠️ 登录态/资产异常: {names}；已发飞书通知，等待 {wait_s} 秒内手动处理…")

        deadline = time.monotonic() + wait_s
        while pending and time.monotonic() < deadline:
            await asyncio.sleep(_poll_seconds())
            for key in list(pending):
                config, _, kind = pending[key]
                if kind == _PENDING_KIND_COOKIE_FILE:
                    # hot-polling：扫码脚本把 cookie 文件落盘的瞬间即放行，
                    # 不做 DOM 判定（免登录平台首页本就不渲染登录元素）
                    try:
                        recovered = os.path.exists(config.legacy_cookie_file)
                    except OSError:
                        recovered = False
                    if recovered:
                        status = SessionStatus(
                            platform=config.name,
                            state=SessionState.HEALTHY,
                            message="Cookie 文件已生成",
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
        if kind == _PENDING_KIND_COOKIE_FILE:
            await _log(f"⛔ {config.display_name} 等待超时仍未生成 Cookie 文件，本次任务跳过该平台")
        else:
            await _log(f"⛔ {config.display_name} 等待超时仍未登录，本次任务跳过该平台（{status.message}）")

    return results
