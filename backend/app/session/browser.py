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

# M2 收口：JOBHUNTER_DATA_DIR 注入时落用户数据目录
from app.core.db_paths import writable_path

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
# M2 收口：JOBHUNTER_DATA_DIR 注入时落 <DATA_DIR>/logs/
_LOGS_DIR = writable_path(Path(__file__).resolve().parents[2] / "logs", "logs")
# 打包只读形态下 logs 目录不存在：监护进程打开日志文件前必须确保目录在
try:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
_EDGE_LOG_MAX_BYTES = 5 * 1024 * 1024


def edge_log_path(platform_name: str) -> Path:
    return _LOGS_DIR / f"edge_{platform_name}.log"


def find_edge_path() -> str:
    """查找本机 Edge 可执行文件；找不到抛 RuntimeError。"""
    for path in _EDGE_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError("未在默认路径找到 Microsoft Edge 浏览器，请确认已安装。")


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


def _testing_fuse_active() -> bool:
    """launch_edge 测试熔断判定（单测定点 monkeypatch 本函数即可解禁，
    不必污染全局 RUN_LIVE_E2E 开关——agy round1 P2）。默认与飞书外发守卫同语义。"""
    from app.core.testing_guard import is_testing_env

    return is_testing_env()


# 真实判定函数的稳定引用：单测 monkeypatch _testing_fuse_active 解禁后，
# 熔断回归用例经此引用恢复默认判定（不被打桩连坐——agy round2 P1）
_REAL_FUSE_ACTIVE = _testing_fuse_active


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

    2026-11-06 测试熔断（智联 Edge 自动拉起事故根治）：launch_edge 是双重 fork
    守护进程（孤儿链 launchd→监护→Edge），pytest 进程退出后浏览器仍常驻，用户侧
    表现为「莫名其妙被拉起智联登录页」。熔断位于复用检查之前（agy round1 P1 定稿）：
    测试进程内即使端口已有真实浏览器（宿主机常驻实例）也不得复用/接管——逃逸链路
    借宿主机浏览器走通复用同样是越权行为，且复用判定依赖宿主机端口状态会让单测
    非确定。测试进程内一律拒绝；真机验证显式 RUN_LIVE_E2E=1 解禁（经
    _testing_fuse_active 统一收口，单测可定点打桩）。
    """
    from .health_checker import probe_port

    # 测试熔断（先于复用检查与真实拉起）：测试进程内绝不 exec 新 Edge、
    # 也绝不静默复用宿主机常驻浏览器（见 docstring 2026-11-06 段）
    if _testing_fuse_active():
        raise RuntimeError(
            f"[测试熔断] 测试进程内禁止拉起/接管真实浏览器（{config.display_name} 端口 "
            f"{config.port}）。单测请 monkeypatch _testing_fuse_active 或 mock "
            f"_launch_edge_daemon / ensure_browser_ready_sync；真机验证请 RUN_LIVE_E2E=1 显式解禁。"
        )

    # 防双实例竞态：端口已有浏览器在听 → 复用前先过身份守卫。
    # 2026-10-31 复审 P2：probe_port 与复用之间可能被陌生浏览器抢注端口；
    # 复用路径同样必须确认占用者是本平台 profile（或可信桌面版 profile）。
    if probe_port(config.port, timeout=0.4):
        try:
            from engine_guard import verify_browser_identity
            ok, reason = verify_browser_identity(config.port, config.profile_dir, platform=config.name)
        except Exception as e:
            ok, reason = False, f"identity_guard_unavailable: {e}"
        if not ok:
            raise RuntimeError(
                f"{config.display_name} 端口 {config.port} 已被其他实例占用，拒绝复用：{reason}"
            )
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


# /json 探测有界重试（2026-10-31 事故根治）：刚拉起的 Edge TCP 已监听但 DevTools
# HTTP 首响应可远超 2s——四平台冷启动实测 10s+ 仍未应答（profile 700MB-1GB、
# 系统盘余量 <6Gi 的 I/O 争抢下），单次或短窗探测即判死会把可自愈的平台整轮
# 跳过。GET 按截止时间预算重试（默认 24s 窗）；PUT 补建只做一次，避免重试
# 放大成 tab 风暴。
_PAGE_TAB_PROBE_DEADLINE_S = 24.0
_PAGE_TAB_PROBE_INTERVAL_S = 1.0


def _get_page_tabs(requests, url: str, proxies: dict) -> list:
    """GET /json → page/webview tab 列表；网络异常向上抛，由调用方决定重试。"""
    resp = requests.get(url, proxies=proxies, timeout=2)
    return [t for t in (resp.json() or []) if t.get("type") in ("page", "webview")]


def _ensure_page_tab_sync(config: PlatformConfig) -> str | None:
    """确保端口上至少有一个 page/webview 目标。

    DrissionPage 的 connect_browser 要求 /json 返回至少一个 page tab；CDP 活着
    但窗口全关（0 tab）的浏览器会让它等满 30s 后抛 BrowserConnectError。
    返回 "alive"（已有 tab）/ "page_tab_created"（补建成功）/ None（失败）。
    """
    import requests

    url = f"http://127.0.0.1:{config.port}/json"
    proxies = {"http": None, "https": None}
    deadline = time.monotonic() + _PAGE_TAB_PROBE_DEADLINE_S

    tabs: list | None = None
    last_error: Exception | None = None
    while True:
        try:
            tabs = _get_page_tabs(requests, url, proxies)
            if tabs:
                return "alive"
            break  # 0 tab：交给下方补建（补建只做一次，不再重试 GET）
        except Exception as e:
            tabs, last_error = None, e
            if time.monotonic() >= deadline:
                break
            time.sleep(_PAGE_TAB_PROBE_INTERVAL_S)
    if tabs is None:
        logger.warning(
            "[browser] %s 端口 %s 检查 page tab 失败（%.0fs 探测预算耗尽）: %s",
            config.name, config.port, _PAGE_TAB_PROBE_DEADLINE_S, last_error,
        )
        return None

    target_url = config.login_check_url or config.auth_url or "about:blank"
    try:
        requests.put(f"{url}/new?{target_url}", proxies=proxies, timeout=2)
    except Exception as e:
        logger.warning(
            "[browser] %s 端口 %s 补建 page tab 失败: %s", config.name, config.port, e,
        )
        return None
    while True:
        try:
            if _get_page_tabs(requests, url, proxies):
                return "page_tab_created"
        except Exception as e:
            last_error = e
        if time.monotonic() >= deadline:
            break
        time.sleep(_PAGE_TAB_PROBE_INTERVAL_S)
    logger.warning(
        "[browser] %s 端口 %s 补建后 page tab 仍不可见: %s", config.name, config.port, last_error,
    )
    return None


def _wait_for_port(port: int, timeout_s: float) -> bool:
    from .health_checker import probe_port

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if probe_port(port, timeout=0.4):
            return True
        time.sleep(0.5)
    return False


def _wait_for_port_release(port: int, timeout_s: float = 8.0) -> bool:
    from .health_checker import probe_port

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not probe_port(port, timeout=0.2):
            return True
        time.sleep(0.5)
    return False


def ensure_browser_ready_sync(
    config: PlatformConfig,
    *,
    allow_restart: bool = True,
    launch_timeout_s: float = 30.0,
) -> tuple[bool, str]:
    """同步版「浏览器就绪」单一实现（预检 + 采集子进程共用）。

    契约：
    - 只有「CDP 可达 **且** 至少一个 page tab」才返回 True；
    - 端口被占用时先过 ``verify_browser_identity``：陌生 profile 一律 fail-closed；
      可信桌面版 profile 仅在 CDP 健康时允许复用，CDP 不可用时拒绝按端口重启
      （不误杀用户正在用的桌面版浏览器）；
    - ``allow_restart=False``（抓取/投递在飞）时只做只读探活，不关闭、不重启。

    返回 (ok, reason)。reason 供调用方做日志/分诊，不要用于业务分支以外的判断：
    alive / page_tab_created / launched / zombie_restarted / in_flight_alive /
    in_flight_unavailable / port_busy_foreign / sibling_browser_unhealthy_refused /
    launch_failed / launch_timeout / no_page_tab / port_release_timeout /
    identity_guard_unavailable。
    """
    from .cdp_probe import probe_cdp_channel
    from .health_checker import probe_port

    port = config.port
    port_up = probe_port(port, timeout=0.4)

    if not port_up:
        if not allow_restart:
            return False, "in_flight_unavailable"
        try:
            launch_edge(config)
        except Exception as e:
            logger.warning("[browser] %s 端口 %s 拉起失败: %s", config.name, port, e)
            return False, f"launch_failed: {e}"
        if not _wait_for_port(port, launch_timeout_s):
            return False, "launch_timeout"
        tab_state = _ensure_page_tab_sync(config)
        if tab_state is None:
            return False, "no_page_tab"
        return True, "launched"

    # 在飞保护：抓取/投递正在进行时只做只读探活，不校验身份、不补 tab、不重启。
    # 正在导航的浏览器 CDP 命令可能暂时不应答，任何写操作都可能误伤。
    if not allow_restart:
        if probe_cdp_channel(port) == "alive":
            return True, "in_flight_alive"
        return False, "in_flight_unavailable"

    # 端口被占用：先确认占用者身份，绝不附着/杀掉陌生浏览器（Q24）。
    try:
        from engine_guard import IDENTITY_REASON_SIBLING, verify_browser_identity
    except Exception as e:  # 打包态/独立进程缺模块时 fail-closed
        logger.critical("[browser] %s 端口 %s 身份守卫不可用，拒绝操作: %s", config.name, port, e)
        return False, f"identity_guard_unavailable: {e}"

    ok, guard_reason = verify_browser_identity(port, config.profile_dir, platform=config.name)
    if not ok:
        logger.critical(
            "[browser] %s 端口 %s 占用者身份校验失败，拒绝附着/重启: %s",
            config.name, port, guard_reason,
        )
        return False, f"port_busy_foreign: {guard_reason}"

    channel = probe_cdp_channel(port)
    if channel == "alive":
        tab_state = _ensure_page_tab_sync(config)
        if tab_state is None:
            return False, "no_page_tab"
        return True, tab_state

    # 同产品桌面版浏览器（sibling_profile_match）不是本实例的资产：CDP 已坏时
    # 只允许复用其登录态，绝不允许按端口 close_edge——否则会杀掉用户正在用的
    # 桌面版 JobHunter 浏览器。要求用户关闭/重启桌面版后重试。
    if guard_reason == IDENTITY_REASON_SIBLING:
        logger.critical(
            "[browser] %s 端口 %s 被同产品桌面版浏览器占用但 CDP 不可用（%s），"
            "拒绝按端口重启；请关闭/重启桌面版 JobHunter 后重试",
            config.name, port, channel,
        )
        return False, "sibling_browser_unhealthy_refused"

    # zombie / down：端口有人监听但 CDP 不可用。身份已确认为本平台 profile，可以优雅重启。
    logger.warning(
        "[browser] %s 端口 %s CDP 通道不可用（%s），优雅重启浏览器",
        config.name, port, channel,
    )
    try:
        close_edge(config)
    except Exception as e:
        logger.warning("[browser] %s 旧浏览器关闭失败（仍尝试重新拉起）: %s", config.name, e)
    if not _wait_for_port_release(port, timeout_s=8.0):
        return False, "port_release_timeout"
    try:
        launch_edge(config)
    except Exception as e:
        logger.warning("[browser] %s 端口 %s 重启失败: %s", config.name, port, e)
        return False, f"launch_failed: {e}"
    if not _wait_for_port(port, launch_timeout_s):
        return False, "launch_timeout"
    tab_state = _ensure_page_tab_sync(config)
    if tab_state is None:
        return False, "no_page_tab"
    return True, "zombie_restarted"


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
            # CDP 命令通道探活（2026-10-08 51job 事故）：HTTP /json 活着但命令永不响应的
            # 僵尸 Edge 曾全程显示 healthy——先探通道再判登录，僵死直接亮红而非误报绿
            from .cdp_probe import probe_cdp_channel
            if probe_cdp_channel(cfg.port) == "zombie":
                results.append({
                    "platform": key,
                    "display_name": cfg.display_name,
                    "port": cfg.port,
                    "state": "zombie",
                    "message": "CDP 命令通道僵死（HTTP 通但命令不应答），下次任务预检将自动重启",
                    "is_alive": False,
                })
                continue
            cdp_status = check_session_via_cdp(cfg)
            state_val = cdp_status.state.value if hasattr(cdp_status.state, "value") else str(cdp_status.state)
            message = cdp_status.message or "已连接"
            if key == "liepin":
                # 猎聘加固（2026-11-01）：猎聘匿名首页亦不在 /login 上，不能仅凭 Tab URL 判定 healthy。
                # 经本地凭证双校验收敛真实状态（Cookie 文件有效性 + profile 登录键实证，耗时 < 5ms）：
                from .health_checker import (
                    _judge_login_keys,
                    _read_login_keys_via_profile_db,
                    is_liepin_cookie_file_valid,
                )
                cookie_file_valid = False
                try:
                    cookie_file_valid = is_liepin_cookie_file_valid(cfg.legacy_cookie_file) if cfg.legacy_cookie_file else False
                except Exception as e:
                    logger.warning(f"[Session] 猎聘 Cookie 文件有效性检查异常: {e}")
                if cookie_file_valid:
                    message = f"{message}；Cookie 凭证有效"
                    state_val = "healthy"
                else:
                    profile_logged_in = False
                    try:
                        profile_keys = _read_login_keys_via_profile_db(cfg.profile_dir)
                        profile_logged_in = _judge_login_keys(profile_keys) if profile_keys else False
                    except Exception as e:
                        logger.warning(f"[Session] 猎聘 profile 登录态检查异常: {e}")
                    if profile_logged_in:
                        message = f"{message}；浏览器登录态有效；Cookie 文件待自愈"
                        state_val = "degraded"
                    else:
                        file_desc = "Cookie 文件已失效" if (cfg.legacy_cookie_file and os.path.exists(cfg.legacy_cookie_file)) else "缺少 Cookie 文件"
                        message = f"{file_desc}且浏览器未登录（请点击唤起浏览器扫码登录）"
                        state_val = "expired"
            results.append({
                "platform": key,
                "display_name": cfg.display_name,
                "port": cfg.port,
                "state": state_val,
                "message": message,
                "is_alive": True,
            })
    return results
