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
from .models import SessionState
from .registry import resolve_platform

logger = logging.getLogger(__name__)

# 视为可用的状态：HEALTHY=登录有效；DEGRADED=Edge 未运行但 cookie 文件可用（爬虫可跑）
_OK_STATES = (SessionState.HEALTHY, SessionState.DEGRADED)


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
    """汇总一条飞书通知：哪些平台登录态异常（DOM 级校验结论逐条列出）、等待窗口多长。"""
    lines = ["🚨 全链路预检（DOM 级校验）：以下平台登录态异常，需要手动登录"]
    for config, status in items:
        lines.append(f"· {config.display_name}（端口 {config.port}）：{status.message}")
    if wait_s > 0:
        lines.append(f"已自动唤起对应浏览器，请在 {max(1, wait_s // 60)} 分钟内完成登录；")
        lines.append("逾期未登录的平台，本次任务的抓取与投递将被跳过。")
    else:
        lines.append("已自动唤起对应浏览器；本次任务将跳过上述平台的抓取与投递。")
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
        #    匿名首页不渲染登录元素，DOM 校验只会误报
        if not config.requires_login:
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
            pending[key] = (config, status)

    # 3. 失效平台：发飞书通知 + 等待窗口内轮询复检
    if pending:
        wait_s = _wait_seconds()
        await _notify_login_needed(list(pending.values()), wait_s)
        names = "、".join(c.display_name for c, _ in pending.values())
        await _log(f"⚠️ 登录态失效: {names}；已发飞书通知，等待 {wait_s} 秒内手动登录…")

        deadline = time.monotonic() + wait_s
        while pending and time.monotonic() < deadline:
            await asyncio.sleep(_poll_seconds())
            for key in list(pending):
                config, _ = pending[key]
                status = await asyncio.to_thread(check_login_with_fallback, config)
                if status.state in _OK_STATES:
                    results[key] = True
                    del pending[key]
                    await _log(f"🎉 {config.display_name} 登录已恢复，纳入本轮任务")

    # 4. 窗口结束仍未登录 → 本次任务跳过
    for key, (config, status) in pending.items():
        results[key] = False
        await _log(f"⛔ {config.display_name} 等待超时仍未登录，本次任务跳过该平台（{status.message}）")

    return results
