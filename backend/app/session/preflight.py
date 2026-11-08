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
   豁免 DOM 登录判定（匿名首页不渲染登录元素，判定必然误报）；但 legacy cookie
   文件缺失时与登录失效同通道拦截——自动唤起专用浏览器（四平台行为统一）+
   飞书提醒 + 等待窗口内复检
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
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

# 终止检查点异常（2026-11-05 僵尸链路事故）：定义在 app.automation.abort（与终止
# 旗子同源），此处 re-export 供既有引用兼容。顶层导入无循环（abort 模块不反向
# 依赖 app.session）；_raise_if_aborted 内对 abort 函数仍惰性导入同模块。
from app.automation.abort import PipelineAbortedError  # noqa: F401
from app.core.utils import ensure_import_path

from .browser import ensure_browser_ready_sync
from .health_checker import (
    check_liepin_login_evidence,
    check_login_with_fallback,
    check_platform_login_cookie_evidence,
    is_liepin_cookie_file_valid,
    probe_port,
)
from .models import SessionState, SessionStatus
from .registry import resolve_platform

logger = logging.getLogger(__name__)


def _ensure_liepin_import_path() -> None:
    """把 backend/liepin_scraper 加入 sys.path，供预检惰性导入 liepin_session。

    与 app/automation/tools.py 的投递工具同一口径：该目录平时要到投递引擎执行时才入路径，
    预检跑得更早，裸 `import liepin_session` 在安装版必然 ModuleNotFoundError（用户数据目录
    也不含 site-packages 补丁），导致 Cookie 注入自愈分支永久失效、每次登录失效都吃满等待窗口。

    用 append 而非 insert(0)：这里只为兜底惰性导入，不应抢占最高优先级——目录内若出现
    与标准库/三方包同名的模块，insert(0) 会造成全进程 import 遮蔽。
    """
    ensure_import_path(str(Path(__file__).resolve().parents[2] / "liepin_scraper"))


# 视为可用的状态：HEALTHY=登录有效；DEGRADED=Edge 未运行但 cookie 文件可用（爬虫可跑）
_OK_STATES = (SessionState.HEALTHY, SessionState.DEGRADED)


def _raise_if_aborted(stage: str) -> None:
    """终止检查点：全链路被终止时立即中断 preflight 片段序列。

    stage 仅用于日志取证（卡点定位），无行为分支。
    """
    from app.automation import abort as abort_mod  # 惰性导入，避免循环依赖
    if abort_mod.is_aborted():
        raise PipelineAbortedError(f"全链路终止信号命中于预检阶段: {stage}")


# to_thread 同步段的看门狗上限（2026-11-05 事故：CDP 探测在 Edge 停留登录页时
# 无超时挂死 → 协程永不返回 → 终止收尾代码执行不到，automation_logs 永久 running、
# 占坑不释放）。线程内调用无法被旗子打断，只能到点放弃等待：代价是泄漏一个后台
# 线程直至调用自然返回，但主链解放、收尾保证执行。取值依据：正常浏览器拉起
# ≤15s、CDP 探活 <5s、DOM 判定 2~4s，120s 已覆盖 20 倍余量。
_SYNC_SEGMENT_TIMEOUT_S = 120.0


async def _to_thread_guarded(fn, /, *args, **kwargs):
    """asyncio.to_thread + 超时看门狗：同步段挂死时到点放弃，不拖死主链。"""
    return await asyncio.wait_for(
        asyncio.to_thread(fn, *args, **kwargs), timeout=_SYNC_SEGMENT_TIMEOUT_S
    )


async def _to_thread_degradable(fn, /, *args, fallback, **kwargs):
    """_to_thread_guarded 的降级包装：看门狗超时不击穿整轮预检（P1 修复），
    记错误后返回调用方指定的单平台降级值（False / UNKNOWN SessionStatus 等）。

    fallback 为关键字专属参数（R2-P0）：位置传参曾把 config 与 fallback 顺序
    写反（SessionStatus 被当 config 传入判定函数），签名上锁死杜绝复发。"""
    try:
        return await _to_thread_guarded(fn, *args, **kwargs)
    except asyncio.TimeoutError:
        logger.error(
            f"⏱️ [preflight] 同步段 {getattr(fn, '__name__', fn)} 超过 "
            f"{_SYNC_SEGMENT_TIMEOUT_S:.0f}s（疑似 CDP/浏览器挂死），按降级值处理"
        )
        return fallback


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


def _login_guidance(status, kind: str, launched: bool) -> tuple[str, str]:
    """把内部判定收敛成 (原因, 动作) 一对，避免两处关键字匹配漂移。"""
    msg = (status.message or "").strip()
    if kind == _PENDING_KIND_COOKIE_FILE:
        if not launched:
            return (
                "缺少登录凭证（首次使用需要扫码登录一次）",
                "浏览器没能自动打开：请在指挥中心「平台会话」点「唤起浏览器」，再扫码登录。",
            )
        return (
            "缺少登录凭证（首次使用需要扫码登录一次）",
            "请切到刚打开的浏览器窗口扫码登录；看到头像/用户名即完成，登录凭证会自动生成。",
        )
    # 状态优先于文案关键字：EXPIRED 的 message 也可能含「未命中登录标识」，
    # 若先走关键字分支会被误译成「暂时没确认」，与已确证的失效结论矛盾。
    if status.state == SessionState.EXPIRED:
        return (
            "登录已失效",
            "请切到刚打开的浏览器窗口重新登录（扫码或账号密码均可）。",
        )
    if "存疑放行" in msg or "未命中登录标识" in msg:
        return (
            "暂时没确认到登录状态（页面可能停在登录页，也可能只是不在登录页）",
            "请切到刚打开的浏览器窗口看一眼：已显示头像/用户名就不用操作；如果是登录页，请完成扫码或账号登录。",
        )
    if "未打开平台页面" in msg:
        return (
            "浏览器已打开，但还没进入平台页面",
            "请切到浏览器窗口，打开该平台首页并完成登录。",
        )
    if "检查失败" in msg or "无法判定" in msg:
        return (
            "自动检查登录状态失败，需要你确认",
            "请切到刚打开的浏览器窗口确认登录状态；如果页面异常，重新登录一次即可。",
        )
    if "浏览器未运行" in msg or "端口未监听" in msg:
        return (
            "浏览器还没准备好",
            "请先在指挥中心「平台会话」点「唤起浏览器」，再完成登录。",
        )
    if "登录页" in msg or "失效" in msg or "过期" in msg:
        return (
            "登录已失效",
            "请切到刚打开的浏览器窗口重新登录（扫码或账号密码均可）。",
        )
    return (
        "需要确认登录状态",
        "请切到刚打开的浏览器窗口确认登录状态；如果是登录页，请完成登录。",
    )


async def _notify_login_needed(items: list, wait_s: int, launched: set[str] | None = None) -> None:
    """汇总一条飞书通知：哪些平台需要登录、具体怎么做、什么时候截止。

    items: [(config, status, kind)]，kind 见 _PENDING_KIND_* 常量。
    launched: 预检已成功拉起专用浏览器的平台 config.name 集合（cookie_file 类平台
    2026-10-28 起自动唤起，与 requires_login 平台行为统一），用于区分通知文案。

    文案原则（2026-10-30 工单）：面向用户、可执行，不出现端口号、内部脚本路径、
    「存疑放行」等诊断术语；明确告诉用户「登录完不用回复，系统会自动继续」。
    wait_s=0 时不承诺自动继续（预检不会轮询，未登录平台直接跳过）。
    """
    launched = launched or set()
    count = len(items)
    deadline = datetime.now() + timedelta(seconds=wait_s) if wait_s > 0 else None

    if wait_s > 0:
        # 与 deadline 同口径：不足 1 分钟按秒展示，避免“最多 1 分钟”却只等 30 秒
        wait_text = f"{wait_s} 秒" if wait_s < 60 else f"{(wait_s + 59) // 60} 分钟"
        title = f"🔔 JobHunter 需要你登录（任务已暂停，最多等待 {wait_text}）"
    else:
        title = "🔔 JobHunter 需要你登录（本轮不等待，未登录平台将跳过）"

    lines = [title, ""]
    lines.append(
        f"本轮自动化任务在启动前检查到 {count} 个平台的登录状态需要确认。"
    )
    all_browsers_up = all(
        kind == _PENDING_KIND_LOGIN or config.name in launched
        for config, _, kind in items
    )
    if all_browsers_up:
        lines.append("对应浏览器已经自动打开，请按下面提示操作。")
    else:
        lines.append("部分平台的浏览器没能自动打开，下面会单独说明；也可以按文末方式手动唤起。")
    if wait_s > 0:
        lines.append(
            f"登录完成后不用回复、也不用关窗口：系统每 {_poll_seconds()} 秒自动检查一次，检测到就会继续。"
        )
    else:
        lines.append("本轮不轮询登录状态，请直接按下面的动作处理；未登录平台会被跳过。")
    lines.append("")

    for idx, (config, status, kind) in enumerate(items, 1):
        reason, action = _login_guidance(status, kind, config.name in launched)
        lines.append(f"{idx}. {config.display_name}：{reason}")
        lines.append(f"   → {action}")

    lines.append("")
    if deadline is not None:
        lines.append(
            f"⏰ 请在 {deadline:%H:%M} 前完成。逾期仍未登录的平台，"
            "本轮会自动跳过它的抓取和投递；已登录的平台与后续 AI 评估不受影响。"
        )
    else:
        lines.append("本轮不等待：未登录的平台会直接跳过抓取和投递，已登录的平台继续执行。")
    lines.append("找不到浏览器窗口？在指挥中心「平台会话」里点「唤起浏览器」即可。")
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


async def _wait_login_cookie_evidence(config, timeout_s: float = 24.0, poll_s: float = 4.0) -> bool:
    """冷启动稳定期：轮询凭证 cookie 内存实证，等待 Edge 配置文件会话恢复完成。

    背景（2026-11-03 事故）：拉起浏览器后 0.5~7 秒即做 DOM 登录判定，Edge 配置文件
    会话尚在恢复中，四平台被全员误判「登录态异常」并误发飞书告警。凭证 cookie 由
    CDP 直读（零导航、零 DOM、不惊动风控），会话恢复完成的瞬间即可实证成功。
    auth_cookie_keys 为空（未摸底平台）直接返回 False 走原 DOM 路径。
    在线程内阻塞轮询，调用方须 asyncio.to_thread 包装。
    """
    if not config.auth_cookie_keys:
        return False
    from .health_checker import check_platform_login_cookie_evidence
    deadline = time.monotonic() + timeout_s
    while True:
        # 轮询间隙接终止信号（2026-11-05）：24s 窗口内用户按终止不必白等满窗
        _raise_if_aborted(f"cookie_evidence_poll:{config.name}")
        if await _to_thread_degradable(check_platform_login_cookie_evidence, config.name, fallback=False):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(poll_s)


async def _ensure_browser_ready(config, emit_log=None, out_reason: dict | None = None) -> bool:
    """端口探活 + CDP 命令通道探活 + page tab 保障 → 按需重启僵尸 / 拉起浏览器。

    2026-10-31：核心逻辑下沉到 ``app.session.browser.ensure_browser_ready_sync``，
    预检与采集子进程共用同一份实现（猎聘爬虫也调用它，避免两份探活语义漂移）。
    在飞保护：同平台抓取/投递进行中时只做只读探活，绝不 close_edge（防误杀正在
    导航的浏览器）。

    Returns:
        True=浏览器可用（CDP 命令通道就绪且至少 1 个 page tab）；False=不可用。
    """
    from app.automation import platform_mutex  # 惰性导入，避免循环依赖

    busy = (
        platform_mutex.is_scrape_busy(config.name)
        or platform_mutex.is_delivery_busy(config.name)
    )
    # 看门狗（2026-11-05 僵尸链路事故）：ensure_browser_ready_sync 内部含 Edge 拉起
    # + CDP 探活 + page tab 补建，其中 CDP socket 读无超时，Edge 停留登录页/弹窗
    # 时曾挂死 10 分钟+。线程内无法被终止旗子打断，这里到点放弃等待（泄漏一个
    # 后台线程直至调用自然返回），主链按「浏览器不可用」处理并保留收尾能力。
    try:
        ok, reason = await _to_thread_guarded(
            ensure_browser_ready_sync, config, allow_restart=not busy
        )
    except asyncio.TimeoutError:
        logger.error(
            f"⏱️ [preflight] {config.name} 浏览器就绪探查超过 {_SYNC_SEGMENT_TIMEOUT_S:.0f}s，"
            f"按不可用处理（同步段看门狗；疑似 CDP 挂死）"
        )
        if out_reason is not None:
            out_reason.clear()
            out_reason["reason"] = "probe_timeout"
        return False
    if out_reason is not None:
        out_reason.clear()
        out_reason["reason"] = reason
    if ok:
        if reason == "launched":
            await _log_preflight(
                f"🌐 {config.display_name} 端口 {config.port} 未监听，已自动拉起浏览器",
                emit_log,
            )
        elif reason == "zombie_restarted":
            await _log_preflight(
                f"♻️ {config.display_name} 僵尸浏览器已重启（端口 {config.port}）",
                emit_log,
            )
        elif reason == "page_tab_created":
            await _log_preflight(
                f"🧭 {config.display_name} 已补建空白标签页（端口 {config.port}）",
                emit_log,
            )
        elif reason == "in_flight_alive":
            await _log_preflight(
                f"⏭️ {config.display_name} 抓取/投递在飞，浏览器只做只读探活（不重启）",
                emit_log,
            )
        return True

    if reason.startswith("port_busy_foreign"):
        await _log_preflight(
            f"⛔ {config.display_name} 端口 {config.port} 被其他实例占用，拒绝附着/重启：{reason}",
            emit_log,
        )
    elif reason == "sibling_browser_unhealthy_refused":
        await _log_preflight(
            f"⛔ {config.display_name} 端口 {config.port} 被桌面版 JobHunter 浏览器占用但 CDP 不可用；"
            f"为避免误杀，请关闭/重启桌面版后重试",
            emit_log,
        )
    elif reason == "in_flight_unavailable":
        await _log_preflight(
            f"❌ {config.display_name} 抓取/投递在飞但浏览器不可用（端口 {config.port}），按不可用处理",
            emit_log,
        )
    else:
        await _log_preflight(
            f"❌ {config.display_name} 浏览器不可用（端口 {config.port}）：{reason}",
            emit_log,
        )
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
    browser_launched: set[str] = set()  # cookie_file 类平台已成功唤起浏览器的 config.name 集合

    for key in platforms:
        # 终止检查点（2026-11-05 僵尸链路事故）：逐平台边界快速失败——用户终止后
        # 不再为剩余平台继续拉浏览器/做登录判定，直接抛异常向上走终止收尾
        _raise_if_aborted(f"platform_loop:{key}")
        config = resolve_platform(key)
        if config is None:
            await _log(f"⚠️ 平台 {key} 无 registry 配置，按不可用处理")
            results[key] = False
            continue

        # 0. 登录豁免：抓取不强制登录的平台（如猎聘，cookie 仅可选注入）免 DOM 判定，
        #    匿名首页不渲染登录元素，DOM 校验只会误报。
        #    但豁免 ≠ 资产齐全：猎聘抓取引擎硬依赖本地 legacy cookie 文件（缺失或
        #    失效时深页抓取被登录墙整轮拦截、0 条收工），故文件缺失或凭证过期时
        #    按「登录态异常」同通道拦截——自动唤起专用浏览器（与 requires_login
        #    平台行为统一，2026-10-28）+ 飞书通知指引扫码 + 等待窗口内轮询放行。
        #    复检双判据（2026-09-27）：文件凭证有效，或 Edge profile 登录实证有效
        #    （专用浏览器与采集引擎同 profile，用户扫码登录即解锁，无需命令行
        #    harvester）。
        #    2026-10-31 事故根治：文件「存在」升级为「凭证有效」（键级过期判定，
        #    详见 is_liepin_cookie_file_valid）——此前只查存在性，过期文件放行后
        #    引擎静默降级访客态，整轮 0 条还报成功。
        if not config.requires_login:
            if config.legacy_cookie_file:
                file_exists = False
                try:
                    file_exists = os.path.exists(config.legacy_cookie_file)
                except OSError:
                    file_exists = False
                # 2026-10-31 事故根治：文件「存在」≠「有效」。猎聘 Cookie 有效期由平台
                # 服务端控制，过期文件曾让这里放行、引擎降级访客态深页抓取，被登录墙
                # 整轮拦截后还静默 0 条收场。猎聘按「存在且凭证未过期」判定，失效文件
                # 与缺失文件同走下方实证复检 + 自动唤起 + 等待窗通道（判据键集合为
                # 猎聘特有，其余平台保持存在性语义不变）。
                if config.name == "liepin":
                    cookie_ok = file_exists and is_liepin_cookie_file_valid(config.legacy_cookie_file)
                else:
                    cookie_ok = file_exists
                if not cookie_ok:
                    cookie_problem = "Cookie 文件已失效" if file_exists else "缺少 Cookie 文件"
                    # 双判据之实证侧：目前仅猎聘（键集合为猎聘特有，别平台误用会恒 False）
                    evidence_ok = False
                    if config.name == "liepin":
                        evidence_ok = await asyncio.to_thread(check_liepin_login_evidence)
                        if evidence_ok:
                            results[key] = True
                            await _log(
                                f"✅ {config.display_name} 无有效 Cookie 文件，"
                                f"但专用浏览器登录实证有效，放行（采集启动后将自动回写文件）"
                            )
                            continue
                    # 四平台行为统一（2026-10-28）：文件缺失且无登录实证时不再干等用户去
                    # 会话条手动唤起——与 requires_login 平台同通道自动拉起专用浏览器，
                    # 用户在等待窗口内直接扫码登录。拉起后端口转 UP，补一次实证复检：
                    # 此前离线读库漏判的既有登录态当场放行（CDP 直读内存 cookie）。
                    browser_ready = await _ensure_browser_ready(config, emit_log)
                    if browser_ready and config.name == "liepin":
                        evidence_ok = await asyncio.to_thread(check_liepin_login_evidence)
                        if evidence_ok:
                            results[key] = True
                            await _log(
                                f"✅ {config.display_name} 无有效 Cookie 文件，"
                                f"但专用浏览器登录实证有效，放行（采集启动后将自动回写文件）"
                            )
                            continue
                    if browser_ready:
                        browser_launched.add(config.name)
                        await _log(
                            f"⚠️ {config.display_name} {cookie_problem}且未检出浏览器登录态，"
                            f"已自动唤起专用浏览器，请在等待窗口内扫码登录"
                            f"（或运行 liepin_cookie_harvester.py 生成 Cookie 文件）…"
                        )
                    else:
                        await _log(
                            f"⚠️ {config.display_name} {cookie_problem}且未检出浏览器登录态，"
                            f"浏览器自动唤起失败，请在指挥中心会话条手动唤起浏览器登录"
                            f"（或运行 liepin_cookie_harvester.py 生成 Cookie 文件）…"
                        )
                    pending[key] = (
                        config,
                        SessionStatus(
                            platform=config.name,
                            state=SessionState.EXPIRED,
                            message=f"{cookie_problem}: {config.legacy_cookie_file}",
                        ),
                        _PENDING_KIND_COOKIE_FILE,
                    )
                    continue
            # 2026-10-31：Cookie 文件存在只豁免「登录判定」，不豁免「浏览器生命周期」。
            # 猎聘爬虫（DrissionPage）硬依赖 9226 上可用 CDP + page tab；此前这里直接
            # 放行，导致僵尸/异种监听占着 9226 时预检不自愈，爬虫裸抛 BrowserConnectError。
            if not await _ensure_browser_ready(config, emit_log):
                results[key] = False
                continue
            browser_launched.add(config.name)
            results[key] = True
            await _log(f"✅ {config.display_name} 无需登录，豁免预检登录校验（浏览器已就绪）")
            continue

        # 1. 浏览器探活/拉起/僵尸自愈（共用 _ensure_browser_ready）
        fresh_reason: dict = {}
        if not await _ensure_browser_ready(config, emit_log, out_reason=fresh_reason):
            results[key] = False
            continue
        # 冷启动标记（拉起/僵尸重启）：本轮登录判定须过「稳定期」，防 Edge 会话恢复前误判
        freshly_launched = fresh_reason.get("reason") in ("launched", "zombie_restarted")

        # 终止检查点：浏览器拉起/重启是分钟级片段，用户常在此窗口按终止——
        # 后续 24s 实证轮询 + DOM 判定 + 8s 复核全无意义，直接放弃
        _raise_if_aborted(f"after_browser_ready:{key}")

        # 1.2 冷启动稳定期（2026-11-03 误判根治）：凭证 cookie 内存实证优先——
        # 拉起后 Edge 配置文件会话恢复需数十秒，立即做 DOM 判定会把已登录平台
        # 全员误判失效并误发飞书告警。实证零导航零 DOM，会话恢复完成瞬间即通过。
        if freshly_launched and config.auth_cookie_keys:
            if await _wait_login_cookie_evidence(config):
                results[key] = True
                await _log(f"✅ {config.display_name} 冷启动凭证实证有效（cookie: {'、'.join(config.auth_cookie_keys)}），跳过 DOM 判定")
                continue
            await _log(f"⏳ {config.display_name} 冷启动实证窗口内未见登录凭证，转入 DOM 判定（可能确已掉登录）")

        # 1.5 登录校验在飞守卫（2026-10-29 沙箱事故根治）：同平台抓取或投递任一在飞时
        # 跳过 DOM 登录校验直接放行。校验的"免导航"仅限当前 Tab 已在平台根域，投递/抓取页
        # 常在子域/深链，跨域即 page.get 导航——会把在飞操作正在使用的页面带跑（与抓取器
        # 撞浏览器同源风险，外审 round1 P1 指出抓取在飞时本预检同样是干扰源）。在飞本身即
        # 证明会话存活；投递引擎自身的 ensure_login 仍逐岗兜底。
        from app.automation import (
            platform_mutex,  # 惰性导入，避免 app.automation ↔ app.session 循环依赖
        )
        if platform_mutex.is_delivery_busy(config.name) or platform_mutex.is_scrape_busy(config.name):
            results[key] = True
            await _log(f"✅ {config.display_name} 抓取/投递进行中，跳过 DOM 登录校验直接放行（防预检导航干扰在飞操作）")
            continue

        # 2. 登录态检查（DOM 级判定 + cookie 兜底收敛：确证失效才跳，存疑放行）
        #    外审 round3-P1/round4-P1：判定段套预检短租约——租约等待期间不持登记，
        #    获得后短暂持有独立 preflight 槽（时长=判定的 2-4s）；对侧引擎在飞使租约
        #    超时 → False，必须跳过导航（存疑放行），绝不带 False 硬闯把在飞标签页带跑。
        from app.automation import (
            platform_mutex as _pm,  # 惰性导入，避免 app.automation ↔ app.session 循环依赖
        )
        async with _pm.preflight_lease(config.name, owner=f"preflight:{key}") as leased:
            if not leased:
                await _log(f"⏭️ {config.display_name} 抓取/投递在飞，预检跳过 DOM 登录导航（存疑放行，防导航干扰在飞操作）")
                results[key] = True
                continue
            # 看门狗超时降级：按 UNKNOWN（非 OK 态）处理 → 走 pending 等待窗复检，
            # 其余健康平台不受影响（P1 修复：超时不得击穿整轮预检）
            status = await _to_thread_degradable(
                check_login_with_fallback, config,
                fallback=SessionStatus(platform=config.name, state=SessionState.UNKNOWN,
                                       message=f"登录判定超时（>{_SYNC_SEGMENT_TIMEOUT_S:.0f}s，疑似 CDP 挂死）"),
            )
        if status.state in _OK_STATES:
            results[key] = True
            if status.state == SessionState.DEGRADED:
                await _log(f"✅ {config.display_name} cookie 兜底放行（{status.message}）")
            else:
                await _log(f"✅ {config.display_name} 登录态正常（{status.message}）")
        elif freshly_launched and config.auth_cookie_keys:
            # 双重判定（冷启动防误报第二道闸）：DOM 判死但本平台是本轮刚拉起的，
            # 再做一次凭证实证复核——会话恰好在此刻恢复完成则改判放行，仍无凭证才挂起。
            # 实证读 cookie 不导航，无需租约；失败/异常 fail-closed 走挂起。
            await _log(f"🔎 {config.display_name} DOM 判定 {status.state.value}（冷启动），8s 后凭证复核…")
            # 8s 切片成 8×1s：终止信号到达时最多 1s 内退出，不再白等满 8s
            for _ in range(8):
                _raise_if_aborted(f"cold_start_recheck:{key}")
                await asyncio.sleep(1)
            if await _to_thread_degradable(check_platform_login_cookie_evidence, config.name, fallback=False):
                results[key] = True
                await _log(f"✅ {config.display_name} 复核实证有效（会话恢复晚于 DOM 判定），改判登录正常")
            else:
                pending[key] = (config, status, _PENDING_KIND_LOGIN)
        else:
            pending[key] = (config, status, _PENDING_KIND_LOGIN)

    # 3. 失效平台：发飞书通知 + 等待窗口内轮询复检
    aborted_early = False
    if pending:
        wait_s = _wait_seconds()
        await _notify_login_needed(list(pending.values()), wait_s, launched=browser_launched)
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
                    from app.automation import (
                        platform_mutex as _pm,  # 惰性导入（同上，复检同口径）
                    )
                    async with _pm.preflight_lease(config.name, owner=f"preflight-recheck:{key}") as leased:
                        if not leased:
                            # 对侧在飞：本轮复检放弃导航，等下个轮询周期再试（不误判失效）
                            continue
                        # 看门狗超时降级：UNKNOWN 非 OK 态 → 留在 pending 下轮再试（P1 修复）
                        status = await _to_thread_degradable(
                            check_login_with_fallback, config,
                            fallback=SessionStatus(platform=config.name, state=SessionState.UNKNOWN,
                                                   message="复检登录判定超时（疑似 CDP 挂死）"),
                        )
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


async def ensure_delivery_platforms_ready(
    platforms: list,
    emit_log=None,
    cancel_check: Callable[[], bool] | None = None,
    wait_s: int | None = None,
) -> dict:
    """投递发射前的平台就绪预检：浏览器探活/自愈 + 登录态判定 + 失效等待窗口。

    与抓取预检 ensure_platforms_ready 的差异：
    - 无登录豁免：投递需要登录态。猎聘（抓取侧 requires_login=False）在此改用
      check_liepin_login_evidence 做 cookie 键实证——浏览器 UP 时 CDP 直读内存
      cookie，等待窗口内用户扫码落账即时感知；浏览器 DOWN 时离线读 profile 库。
      实证失效时先尝试本地 Cookie 文件注入一次（浏览器已就绪），仍失效才进等待窗口。
    - 抓取豁免平台（小红书等）不在投递平台集合内，天然不经过本函数。
    - 成功结果 TTL 缓存（_READY_TTL_S）：delivery_node 逐岗接线后同平台短时间重复
      调用免重探。

    Args:
        cancel_check: 单岗终止判定回调（通常为 `lambda: is_job_delivery_cancelled(rid)`）。
            等待窗口内每秒检查一次，命中立即结束等待——用户点「终止投递」不必干等满
            PIPELINE_LOGIN_WAIT_S。批量/定时波次调用不传，行为与旧版一致。
        wait_s: 覆盖本轮等待窗口秒数（None 取环境变量默认值）。手动单岗重试可传更短的值。

    Returns:
        {平台key: 是否可用}。不可用平台调用方应跳过其岗位：保留飞书「待投递」门牌，
        在「自动投递失败日志」记 [环境] 跳过原因，下轮波次自然重试。
    """
    async def _log(msg: str):
        await _log_preflight(msg, emit_log)

    results: dict = {}
    pending: dict = {}  # 平台key -> (config, status)
    injection_attempted: set[str] = set()  # 猎聘 JSON 注入每轮预检至多尝试一次
    cancelled_early = False  # 等待窗口是否被单岗终止打断（决定跳过归因与冷却登记）

    def _cancel_requested() -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception as e:
            logger.warning(f"⚠️ [投递预检] 单岗终止判定异常（按未终止继续）: {e}")
            return False

    async def _judge(config) -> SessionStatus:
        """单平台登录判定：猎聘走 cookie 键实证，其余平台走 DOM+cookie 兜底。

        外审 round3-P1/round4-P1：DOM 判定段套预检短租约（独立 preflight 槽，秒级持有）。
        抓取/投递引擎在飞 → 租约超时 False → 跳过导航按存疑放行（HEALTHY 假判 +
        日志明示），绝不带 False 硬闯把在飞抓取的标签页导航走；登录若实际已失效，
        引擎侧失败按 [登录]/[环境] 暂时性出列自愈。猎聘实证分支不导航，无需租约。
        """
        from app.automation import platform_mutex as _pm  # 惰性导入，避免循环依赖
        if config.name == "liepin":
            ok = await asyncio.to_thread(check_liepin_login_evidence)
            return SessionStatus(
                platform=config.name,
                state=SessionState.HEALTHY if ok else SessionState.EXPIRED,
                message="猎聘登录实证通过" if ok else "猎聘登录实证失效（登录 cookie 键缺失/过期），需扫码登录",
            )
        async with _pm.preflight_lease(config.name, owner=f"delivery-preflight:{config.name}") as leased:
            if not leased:
                # 存疑放行假判（round5-P2-2）：HEALTHY 仅供本轮放行，message 打标
                # 「存疑放行」，调用方据此不写入就绪 TTL 缓存——缓存窗口内真实 DOM
                # 校验仍照常进行；登录若实际已失效，引擎逐岗 ensure_login 兜底。
                return SessionStatus(
                    platform=config.name,
                    state=SessionState.HEALTHY,
                    message="存疑放行：抓取/投递在飞，跳过 DOM 判定（防预检导航干扰在飞操作）",
                )
            # 看门狗超时降级：UNKNOWN 非 OK 态 → 调用方按未就绪处理进等待窗（P1 修复）
            return await _to_thread_degradable(
                check_login_with_fallback, config,
                fallback=SessionStatus(platform=config.name, state=SessionState.UNKNOWN,
                                       message="投递预检登录判定超时（疑似 CDP 挂死）"),
            )

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
            _ensure_liepin_import_path()
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

        # 1.5 登录校验在飞守卫（外审 round1 P1）：同平台抓取/投递任一在飞时跳过 DOM 判定
        # 直接放行——_judge 的 check_login_with_fallback 跨域时会 page.get 导航，会把在飞
        # 操作（抓取器正翻页/投递引擎正上传）正在使用的标签页带跑。在飞本身即证明会话存活；
        # 若登录实际已失效，引擎侧失败按 [登录]/[环境] 暂时性出列自愈，不会永久卡死。
        from app.automation import (
            platform_mutex,  # 惰性导入，避免 app.automation ↔ app.session 循环依赖
        )
        if platform_mutex.is_delivery_busy(config.name) or platform_mutex.is_scrape_busy(config.name):
            results[key] = True
            _ready_cache[key] = time.monotonic()
            await _log(f"✅ [投递预检] {config.display_name} 抓取/投递进行中，跳过 DOM 判定直接放行（防预检导航干扰在飞操作）")
            continue

        # 2. 登录判定（猎聘实证失效先注入一次再复测）
        status = await _judge_with_injection(config, key)
        if status.state in _OK_STATES:
            results[key] = True
            # 存疑放行假判（租约超时）不进就绪 TTL 缓存：缓存窗口内的下轮预检仍走真实判定
            if "存疑放行" not in status.message:
                _ready_cache[key] = time.monotonic()
            await _log(f"✅ [投递预检] {config.display_name} 就绪（{status.message}）")
        else:
            pending[key] = (config, status)

    # 3. 失效平台：发一条飞书汇总 + 一个等待窗口（窗口内轮询复检，浏览器 UP 走 CDP 实时判定）
    if pending:
        try:
            effective_wait_s = _wait_seconds() if wait_s is None else max(0, int(wait_s))
        except (TypeError, ValueError):
            effective_wait_s = _wait_seconds()
        await _notify_login_needed(
            [(c, s, _PENDING_KIND_LOGIN) for c, s in pending.values()], effective_wait_s,
        )
        names = "、".join(c.display_name for c, _ in pending.values())
        await _log(f"⚠️ [投递预检] 登录态异常: {names}；已发飞书通知，等待 {effective_wait_s} 秒内手动登录…")

        from app.automation import abort as abort_mod  # 惰性导入，避免模块级循环依赖

        # 2026-10-30 工单：等待循环此前只认全局终止，单岗「终止投递」要在窗口自然到期后
        # 才生效（实测 3 分 52 秒）。改为 1 秒切片：每秒检查终止信号，登录复检仍按
        # _poll_seconds() 节奏执行，不给 CDP 判定增加额外压力。
        deadline = time.monotonic() + effective_wait_s
        next_probe = time.monotonic() + _poll_seconds()
        while pending and time.monotonic() < deadline:
            if abort_mod.is_aborted():
                await _log("🛑 检测到全链路终止信号，投递预检等待提前结束，未恢复平台按跳过处理")
                break
            if _cancel_requested():
                cancelled_early = True
                await _log("🛑 检测到单岗终止指令，投递预检等待提前结束，本轮发射取消")
                break
            await asyncio.sleep(min(1.0, max(0.0, next_probe - time.monotonic())))
            if time.monotonic() < next_probe:
                continue
            next_probe = time.monotonic() + _poll_seconds()
            for key in list(pending):
                config, _ = pending[key]
                status = await _judge(config)
                if status.state in _OK_STATES:
                    results[key] = True
                    _ready_cache[key] = time.monotonic()
                    del pending[key]
                    await _log(f"🎉 [投递预检] {config.display_name} 登录已恢复，纳入本轮发射")

    # 4. 窗口结束仍未恢复 → 本轮跳过（岗位保留「待投递」，下轮波次自然重试）
    #    取消可能落在最后一轮 _judge 批次执行期间或 deadline 交界处：登记冷却前轻量复判一次，
    #    避免用户已点终止却被 30s 冷却拦在重试之外。
    if not cancelled_early and _cancel_requested():
        cancelled_early = True
        await _log("🛑 检测到单岗终止指令，投递预检按取消收尾")
    for key, (config, status) in pending.items():
        results[key] = False
        if cancelled_early:
            # 单岗终止打断的等待不登记冷却：用户随时可能重试，不能被 30s 冷却误拦
            await _log(f"🛑 [投递预检] {config.display_name} 因岗位终止被跳过（预检未完成）")
            continue
        _notready_until[key] = time.monotonic() + _NOT_READY_COOLDOWN_S
        await _log(f"⛔ [投递预检] {config.display_name} 等待超时仍未登录，本轮发射跳过该平台（{status.message}）")

    return results
