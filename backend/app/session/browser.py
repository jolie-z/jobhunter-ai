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

from .models import PlatformConfig

logger = logging.getLogger(__name__)

# Edge 可执行文件候选路径（Windows + macOS）
_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_edge_path() -> str:
    """查找本机 Edge 可执行文件；找不到抛 RuntimeError。"""
    for path in _EDGE_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError("未在默认路径找到 Microsoft Edge 浏览器，请确认已安装。")


def _launch_edge_daemon(command: list[str]) -> None:
    """以双重 fork 守护进程模式拉起 Edge（PPID=1 launchd 接管）。

    业务价值：
    彻底切断 Edge 进程与 Python/FastAPI/PM2 父进程的任何血缘联系（PPID 恒为 1）。
    当 PM2 重启（pm2 restart）使用 tree-kill 扫描父子进程树时，
    Edge 绝不会被视作 Python 的子进程，从而实现服务热重启与全流程迭代期间 100% 常驻存活。
    """
    import sys
    if hasattr(os, "fork"):
        launcher_code = """
import os, sys
cmd = sys.argv[1:]
pid = os.fork()
if pid == 0:
    os.setsid()
    pid2 = os.fork()
    if pid2 == 0:
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)
        os.execv(cmd[0], cmd)
    else:
        os._exit(0)
else:
    os.waitpid(pid, 0)
"""
        subprocess.run(
            [sys.executable, "-c", launcher_code, *command],
            check=True,
            timeout=5,
        )
    else:
        # Windows 兼容模式
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
        )


def launch_edge(config: PlatformConfig, url: str | None = None) -> dict:
    """
    拉起指定平台的专用 Edge：固定调试端口 + 独立 profile + 自动打开授权页。

    :param url: 打开后自动访问的地址；缺省用 config.auth_url（可传 login_check_url 做静默续期）。
    成功返回 {"status": "success", "message": ...}；失败抛 RuntimeError。
    """
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

    try:
        _launch_edge_daemon(command)
    except Exception as e:
        logger.exception("启动 Edge 浏览器失败")
        raise RuntimeError(f"启动浏览器失败: {e}") from e

    logger.info(f"成功启动 Edge 浏览器（Double-Fork 守护模式，PPID=1），平台: {config.name}, 端口: {config.port}")
    return {"status": "success", "message": f"Edge 浏览器已成功在端口 {config.port} 唤起。"}


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
            results.append({
                "platform": key,
                "display_name": cfg.display_name,
                "port": cfg.port,
                "state": state_val,
                "message": cdp_status.message or "已连接",
                "is_alive": True,
            })
    return results
