"""
Edge 浏览器统一拉起逻辑 — 全项目唯一实现。

主系统 auth 路由（/api/v1/auth/{platform}/edge）与简历回写子系统
（resume_server.py /api/platforms/launch）都必须调用这里，禁止各自复制一份。

端口 / profile 目录 / 授权 URL 全部来自 registry（全项目唯一配置区）。
"""
import json
import logging
import os
import subprocess
import time
from pathlib import Path

from .models import PlatformConfig

logger = logging.getLogger(__name__)

# Edge 可执行文件候选路径（Windows + macOS）
_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

# 拉起后 CDP 端口就绪轮询上限：exec 成功 ≠ 浏览器可用（2026-09-26 排查：
# Edge 曾多次 exec 后数分钟内静默退出，fire-and-forget 让前端永远停留在"唤起中"）
_CDP_READY_TIMEOUT_SECS = 30

# 每平台 Edge 运行日志（临终遗言落盘，关闭 2026-09-25 排查确认的"日志黑洞"）：
# backend/logs/edge_<platform>.log
_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
_EDGE_LOG_MAX_BYTES = 5 * 1024 * 1024


def edge_log_path(platform_name: str) -> Path:
    return _LOGS_DIR / f"edge_{platform_name}.log"

# 本机未装 Edge 时给用户的官方下载页（各唤起入口统一引用这份）。
# 前端 lib/platform-auth.ts 的 FALLBACK_EDGE_DOWNLOAD_URL 是同一地址的兜底副本，
# 改址需两处同步（前端在预检不可达时拿不到后端地址）。
EDGE_DOWNLOAD_URL = "https://www.microsoft.com/zh-cn/edge/download"

# 统一用户文案：异常与结构化错误体共用，避免多处手抄漂移
_EDGE_MISSING_MESSAGE = "未在本机找到 Microsoft Edge 浏览器，请先下载安装后重试。"


class EdgeNotFoundError(RuntimeError):
    """本机默认安装路径未找到 Microsoft Edge —— 需要引导用户下载安装，而非笼统报错。"""


def edge_not_installed_detail() -> dict:
    """「Edge 未安装」结构化错误体唯一来源：前端据 code=edge_not_installed 弹下载引导。"""
    return {
        "code": "edge_not_installed",
        "message": _EDGE_MISSING_MESSAGE,
        "download_url": EDGE_DOWNLOAD_URL,
    }


def find_edge_path() -> str:
    """查找本机 Edge 可执行文件；找不到抛 EdgeNotFoundError。"""
    for path in _EDGE_CANDIDATES:
        if os.path.exists(path):
            return path
    raise EdgeNotFoundError(_EDGE_MISSING_MESSAGE)


def get_edge_install_status() -> dict:
    """Edge 安装探测（供前端唤起前预检 + 未安装时给出下载引导）。

    复用 find_edge_path 的同一条扫描口径，避免两处候选列表逻辑漂移。
    """
    try:
        find_edge_path()
        installed = True
    except EdgeNotFoundError:
        installed = False
    return {"installed": installed, "download_url": EDGE_DOWNLOAD_URL}


def _launch_edge_daemon(command: list[str], log_path: str | None = None) -> None:
    """以双重 fork 守护进程模式拉起 Edge（孤儿链：launchd → 监护 python → Edge）。

    业务价值：
    彻底切断 Edge 进程与 Python/FastAPI/PM2 父进程的任何血缘联系
    （孙进程经双重 fork 被 launchd 接管），当 PM2 重启（pm2 restart）使用
    tree-kill 扫描父子进程树时，Edge 绝不会被视作 Python 的子进程，
    实现服务热重启与全流程迭代期间 100% 常驻存活。

    2026-09-26 变更：孙进程不再直接 execv Edge，而是作为一个常驻监护 python
    ——它把 Edge 的 stdout/stderr 接入 log_path（临终遗言留痕，此前进 /dev/null
    导致退出原因永远成谜），并在 Edge 退出后追加 `[edge exit] code=N` 标记行。
    监护进程同样在孤儿链上，PM2 tree-kill 依然扫不到 Edge。
    """
    import sys
    if hasattr(os, "fork"):
        launcher_code = """
import os, subprocess, sys, time
log_path, cmd = sys.argv[1], sys.argv[2:]
pid = os.fork()
if pid == 0:
    os.setsid()
    pid2 = os.fork()
    if pid2 == 0:
        try:
            fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(fd, 1)
            os.dup2(fd, 2)
            fd0 = os.open(os.devnull, os.O_RDONLY)
            os.dup2(fd0, 0)
            for f in (fd, fd0):
                if f > 2:
                    os.close(f)
        except Exception:
            pass
        code = -1
        try:
            code = subprocess.run(cmd).returncode
        except Exception as sup_e:
            try:
                print(f"[edge supervisor] 启动失败: {sup_e}", flush=True)
            except Exception:
                pass
        try:
            with open(log_path, "a", encoding="utf-8", errors="replace") as f:
                f.write(f"\\n[edge exit] code={code} at {time.strftime('%Y-%m-%d %H:%M:%S')}\\n")
        except Exception:
            pass
        os._exit(0)
    else:
        os._exit(0)
else:
    os.waitpid(pid, 0)
"""
        subprocess.run(
            [sys.executable, "-c", launcher_code, log_path or os.devnull, *command],
            check=True,
            timeout=5,
        )
    else:
        # Windows 兼容模式（无 fork，无监护进程，输出接入同一日志文件）
        log_fh = open(log_path, "ab") if log_path else subprocess.DEVNULL
        try:
            subprocess.Popen(
                command,
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        finally:
            if log_fh is not subprocess.DEVNULL:
                log_fh.close()


def _rotate_edge_log_if_oversized(log_path: Path) -> None:
    """超限即整个重建（调试留痕日志，不值得做轮转保存）。"""
    try:
        if log_path.exists() and log_path.stat().st_size > _EDGE_LOG_MAX_BYTES:
            log_path.unlink()
    except Exception:
        pass


def _read_log_tail(log_path: Path, limit: int = 600) -> str:
    try:
        size = log_path.stat().st_size
        with open(log_path, "rb") as f:
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return "(日志文件不可读)"


def launch_edge(config: PlatformConfig, url: str | None = None) -> dict:
    """
    拉起指定平台的专用 Edge：固定调试端口 + 独立 profile + 自动打开授权页。

    :param url: 打开后自动访问的地址；缺省用 config.auth_url（可传 login_check_url 做静默续期）。
    成功返回 {"status": "success", "message": ...}；失败抛 RuntimeError。

    2026-09-26 加固（唤起卡死排查）：
    1. 端口已有监听者时直接复用返回，绝不二次拉起——Chromium 单例锁竞争会让
       同 profile 双实例互相伤害（轻则一方被顶掉，重则 cookie 库损坏）；
    2. 拉起后轮询 CDP 端口至多 30s，exec 成功但浏览器秒退时如实抛错并附日志尾部，
       不再对前端谎报成功。
    """
    from .health_checker import probe_port

    # 防双实例竞态：端口已有浏览器在听 → 直接复用
    if probe_port(config.port, timeout=0.4):
        # 注意：复用路径不会导航到 url 参数指定的页面（续期/重新登录类调用方需自行补发 CDP 导航）
        logger.info(
            f"[launch_edge] {config.name} 端口 {config.port} 已有浏览器监听，跳过重复拉起"
            + ("（本次未导航到调用方指定页面）" if url else "")
        )
        return {
            "status": "success",
            "message": (
                f"{config.display_name} 浏览器已在端口 {config.port} 运行，已直接复用。"
                + ("（复用模式：未跳转到本次传入的页面）" if url else "")
            ),
            "reused": True,
        }

    edge_path = find_edge_path()

    profile_dir = config.profile_dir
    os.makedirs(profile_dir, exist_ok=True)

    command = [
        edge_path,
        f"--remote-debugging-port={config.port}",
        f"--user-data-dir={profile_dir}",
        "--remote-allow-origins=*",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-features=Translate",
    ]
    target_url = url or config.auth_url
    if target_url:
        command.append(target_url)

    log_path = edge_log_path(config.name)
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_edge_log_if_oversized(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[launch {time.strftime('%Y-%m-%d %H:%M:%S')}] platform={config.name} port={config.port}\n")
    except Exception as log_e:
        logger.warning(f"[launch_edge] Edge 日志文件初始化失败（不阻断拉起）: {log_e}")
        log_path = None

    try:
        _launch_edge_daemon(command, str(log_path) if log_path else None)
    except Exception as e:
        logger.exception("启动 Edge 浏览器失败")
        raise RuntimeError(f"启动浏览器失败: {e}") from e

    deadline = time.time() + _CDP_READY_TIMEOUT_SECS
    while time.time() < deadline:
        if probe_port(config.port, timeout=0.4):
            logger.info(
                f"成功启动 Edge 浏览器（Double-Fork 守护模式，孤儿链 launchd→监护→Edge），"
                f"平台: {config.name}, 端口: {config.port}，CDP 已就绪"
            )
            return {"status": "success", "message": f"Edge 浏览器已成功在端口 {config.port} 唤起。"}
        time.sleep(0.5)

    tail = _read_log_tail(log_path) if log_path else "(日志不可用)"
    logger.error(f"[launch_edge] {config.name} CDP 端口 {config.port} {_CDP_READY_TIMEOUT_SECS}s 未就绪；日志尾部: {tail}")
    raise RuntimeError(
        f"浏览器进程已拉起，但 CDP 端口 {config.port} 在 {_CDP_READY_TIMEOUT_SECS}s 内未就绪"
        f"（进程可能已异常退出）。临终日志: {log_path}；日志尾部: {tail}"
    )


def _find_port_processes(port: int) -> list:
    """找出所有带指定调试端口参数的 Edge 进程。"""
    import psutil
    procs = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if f"--remote-debugging-port={port}" in " ".join(cmdline):
                procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return procs


def _close_via_cdp(port: int) -> bool:
    """通过 CDP Browser.close 优雅关闭：让 Edge 走正常退出流程，登录 cookie 落盘。"""
    try:
        import requests
        info = requests.get(
            f"http://127.0.0.1:{port}/json/version",
            proxies={"http": None, "https": None}, timeout=2,  # type: ignore[dict-item]  # requests stub 过严：None 值运行时合法
        ).json()
        ws_url = info.get("webSocketDebuggerUrl")
        if not ws_url:
            return False
        import websocket
        ws = websocket.create_connection(ws_url, timeout=5)
        try:
            ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            try:
                ws.recv()
            except Exception:
                pass  # 浏览器关闭会直接断开连接，recv 抛错属正常
        finally:
            ws.close()
        return True
    except Exception as e:
        # websocket-client 缺失 / CDP 连接失败都会走到这里：必须留痕，
        # 否则优雅关闭静默退化为 terminate 强杀，可能丢刚扫码的登录态
        logger.warning(f"CDP Browser.close 优雅关闭失败（端口 {port}），将退化为 terminate 强杀: {e}")
        return False


def _close_port_gracefully(port: int, wait_secs: float = 8.0) -> bool:
    """
    优雅关闭占用指定调试端口的 Edge：先 CDP Browser.close（cookie 正常落盘），
    等待进程退出，超时才 terminate() 强杀兜底。禁止直接 terminate —— 会丢刚扫码的登录态。
    """
    import traceback
    caller_stack = "".join(traceback.format_stack()[:-1])
    logger.warning(f"🚨 [BROWSER_CLOSE] 端口 {port} 收到关闭指令！触发调用栈如下:\n{caller_stack}")

    procs = _find_port_processes(port)
    if not procs:
        return False

    cdp_ok = _close_via_cdp(port)
    if cdp_ok:
        deadline = time.time() + wait_secs
        while time.time() < deadline and _find_port_processes(port):
            time.sleep(0.5)

    for proc in _find_port_processes(port):
        try:
            proc.terminate()
        except Exception:
            pass
    return True


def close_edge(config: PlatformConfig) -> bool:
    """关闭指定平台的专用 Edge 浏览器进程（优雅关闭，落盘登录态）"""
    try:
        import traceback
        caller_stack = "".join(traceback.format_stack()[:-1])
        logger.warning(f"🚨 [CLOSE_EDGE] 单平台 {config.name} (端口 {config.port}) 被调用 close_edge！调用栈:\n{caller_stack}")
        return _close_port_gracefully(config.port)
    except Exception as e:
        logger.warning(f"关闭 Edge 浏览器异常 (端口 {config.port}): {e}")
        return False


def close_all_edges() -> int:
    """优雅关闭所有已配置平台的 Edge 浏览器进程，确保登录 cookie 落盘"""
    try:
        import traceback
        caller_stack = "".join(traceback.format_stack()[:-1])
        logger.warning(f"🚨 [CLOSE_ALL_EDGES] 全部平台浏览器被调用 close_all_edges！调用栈:\n{caller_stack}")
        from .registry import PLATFORM_CONFIGS
        ports = {cfg.port for cfg in PLATFORM_CONFIGS.values()}
        closed_count = 0
        for port in ports:
            if _close_port_gracefully(port):
                closed_count += 1
        return closed_count
    except Exception as e:
        logger.warning(f"关闭所有 Edge 浏览器异常: {e}")
        return 0


def _domain_of(url: str) -> str:
    """取 URL 的根域（末两段），用于 cookie 域匹配：we.51job.com → 51job.com。"""
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
        parts = [p for p in host.split(".") if p]
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return ""


def inspect_profile_cookie_freshness(config: PlatformConfig) -> dict:
    """
    只读探测平台 profile 的 Cookies 库，返回登录 cookie 的存活概况。

    用途：浏览器未运行（offline）时给状态面板补充「离线 ≠ 登录丢失」的信息——
    profile 落盘的 cookie 仍可能有效，下次拉起即可直接用。
    只读连接（mode=ro），绝不写库；Cookies 文件缺失/被浏览器锁住时按 unknown 收场。

    返回 {"state": "valid"|"expired"|"unknown", "expires_at": "YYYY-MM-DD"|None,
          "valid_count": int}
    state=valid：仍存在未过期的平台域 cookie（Chrome epoch 换算本地时间）。
    """
    from datetime import datetime, timedelta
    result = {"state": "unknown", "expires_at": None, "valid_count": 0}
    domain = _domain_of(config.login_check_url or config.auth_url or "")
    if not domain:
        return result
    cookies_path = os.path.join(config.profile_dir, "Default", "Cookies")
    if not os.path.exists(cookies_path):
        return result
    epoch_now = (datetime.now() - datetime(1601, 1, 1)).total_seconds() * 1_000_000
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{cookies_path}?mode=ro&immutable=1", uri=True)
        try:
            rows = conn.execute(
                "SELECT host_key, expires_utc FROM cookies WHERE host_key LIKE ?",
                (f"%{domain}%",),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        # 浏览器持锁/文件损坏都按无法判定处理，绝不报错阻断状态接口
        return result

    valid_expiries = [
        exp for _host, exp in rows
        if exp and exp > epoch_now
    ]
    if not valid_expiries:
        result["state"] = "expired" if rows else "unknown"
        return result
    # 最早过期的有效 cookie 决定「能撑到哪天」；展示天数比精确时刻更有用
    soonest = min(valid_expiries)
    soonest_dt = datetime(1601, 1, 1) + timedelta(microseconds=soonest)
    result.update({
        "state": "valid",
        "expires_at": soonest_dt.strftime("%Y-%m-%d"),
        "valid_count": len(valid_expiries),
    })
    return result


def get_all_platform_sessions() -> list:
    """
    获取 5 大平台（Boss, 智联, 51job, 猎聘, 小红书）的实时会话健康状态。

    端口不通（offline）时补读 profile Cookies 库的存活概况：
    offline 但 cookie 有效 → state 保持 offline，message 标注「登录 cookie 有效至 X」，
    前端可据此显示「离线但可拉起即用」，不再误导用户以为登录丢失。
    """
    from .health_checker import check_session_via_cdp, probe_port
    from .registry import PLATFORM_CONFIGS
    results = []
    for key in ["boss", "zhilian", "51job", "liepin", "xiaohongshu"]:
        cfg = PLATFORM_CONFIGS.get(key)
        if not cfg:
            continue
        is_port_open = probe_port(cfg.port, timeout=0.4)
        if not is_port_open:
            freshness = inspect_profile_cookie_freshness(cfg)
            message = f"未运行 (端口 {cfg.port} 未开放)"
            if freshness["state"] == "valid":
                message = (
                    f"未运行，但登录 cookie 有效至 {freshness['expires_at']}"
                    f"（拉起即用）"
                )
            elif freshness["state"] == "expired":
                message = "未运行，且登录 cookie 已过期（需重新扫码）"
            results.append({
                "platform": key,
                "display_name": cfg.display_name,
                "port": cfg.port,
                "state": "offline",
                "message": message,
                "is_alive": False,
            })
        else:
            cdp_status = check_session_via_cdp(cfg)
            state_val = cdp_status.state.value if hasattr(cdp_status.state, "value") else str(cdp_status.state)
            message = cdp_status.message or "已连接"
            if key == "liepin":
                # 猎聘的 healthy 只代表浏览器在跑（匿名首页不渲染登录元素），补注资产实况，
                # 消除「会话条已连接、预检却报缺 Cookie 文件」的矛盾观感（2026-09-27）。
                # freshness 走只读快照，浏览器运行中可能滞后数秒——此处仅提示，不做门禁判定。
                if cfg.legacy_cookie_file and os.path.exists(cfg.legacy_cookie_file):
                    message += "；Cookie 文件存在"
                else:
                    freshness = inspect_profile_cookie_freshness(cfg)
                    if freshness["state"] == "valid":
                        message += (
                            f"；profile 登录有效至 {freshness['expires_at']}"
                            f"（采集启动时将自动自愈回写 Cookie 文件）"
                        )
                    else:
                        message += "；Cookie 文件未生成"
            results.append({
                "platform": key,
                "display_name": cfg.display_name,
                "port": cfg.port,
                "state": state_val,
                "message": message,
                "is_alive": True,
            })
    return results
