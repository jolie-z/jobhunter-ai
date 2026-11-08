"""引擎环境守卫（Q24 产品级加固，2026-09-19）

背景：DrissionPage ChromiumPage(co) 连接 CDP 端口时，端口被占用即直接附着，
set_user_data_path 配置被无视；playwright connect_over_cdp 同样会附着端口既有
占用者。若占用者是其他浏览器（如用户日常在线的已登录浏览器），引擎会以其身份
执行页面操作（Q24 事故：worktree 隔离实例投递时接管了生产 BOSS Edge，
QA matrix §5G）。

守卫在引擎建立浏览器连接前校验端口占用者身份，非预期 profile 一律 fail-closed
拒绝，把「附着陌生浏览器」从静默事故变成确定性失败。

判定矩阵（HTTP 探测三态 × 监听探测，任意组合有唯一结论）：
  ① 无监听 PID + HTTP 立即拒绝(RST) → 放行（端口空闲，将由本引擎以配置自起）
  ② 无监听 PID + HTTP 2xx          → 拒绝（探测盲区：跨用户监听进程不可见，宁可错杀）
  ③ 无监听 PID + HTTP 超时/非2xx/异常 → 1.5s 后复探一次：复探 refused 视为关停竞态
     （半开 socket 吞 RST）放行自起；仍不可信则拒绝（超时恰是「有监听者但未应答」的
     信号，盲区场景下绝不可当端口空闲；探测不可信即 fail-closed）
  ④ 有监听 PID                     → 校验占用者 --user-data-dir 与预期 profile 相等，不等即拒绝
  ⑤ 监听探测本身失败               → 拒绝（探测手段不可用，fail-closed）
  ⑥ 命令行查询失败（2026-10-29 修订）→ 不再一票否决：兜底重试后重跑监听探测再归类——
     端口已无监听（占用者退出）按①放行自起；仍有监听者/复探不可信 → 拒绝（身份不可确认，
     fail-closed 不弱化）。缘起：2026-10-28 真机事故，PowerShell CIM 在四引擎并发启动的
     高负载点超 5s 预算，51job/boss 双双 fail-closed 误杀自家浏览器——探测手段不可用
     ≠ 身份不可信。
  ⑦ 有监听 PID 且 profile 非预期，但占用者是同产品桌面版（Electron 安装包）以
     JOBHUNTER_DATA_DIR 拉起的浏览器 → 放行（2026-10-30 事故：dev 实例与已安装的
     JobHunter 桌面版同时运行，桌面版后端用 userData profiles 拉起 Edge 并占用固定
     CDP 端口，dev 实例期望 backend/data/profiles，BOSS/51job 被当成陌生浏览器
     fail-closed 误杀）。只认本产品桌面版 userData 下的 profiles 根（macOS
     ~/Library/Application Support/{jobhunter-desktop,JobHunter}/profiles、
     Windows %APPDATA%\\{...}\\profiles、Linux $XDG_CONFIG_HOME 或
     ~/.config/{...}/profiles 及显式 JOBHUNTER_DATA_DIR/profiles）。
     安全边界（必须如实理解）：本修复把「worktree/dev 实例 → 安装版桌面浏览器」
     从 fail-closed 改为放行，这是恢复 dev 链路可用性的接受代价；Q24 的原始事故
     配对（worktree → 主仓 dev 浏览器）仍然拒绝。为抑制两个实例同时驱动同一
     Edge，采集器/投递引擎入口已加端口级跨进程锁（acquire_port_lock /
     cross_process_port_lock，POSIX flock / Windows msvcrt），锁被占用时采集器
     以 75（EX_TEMPFAIL）退出、投递按暂时性失败延后重试；锁设施不可用时
     fail-open 并打 WARNING（业务可用性优先）。锁为两层：进程内每端口 RLock
     （防同进程双 fd 自锁/重入）+ 文件锁；默认等待 90s，可用
     JOBHUNTER_CDP_LOCK_TIMEOUT_S 覆盖。

平台实现（2026-10-06 Windows 真机适配——lsof/ps 是 macOS 命令，Windows 上
FileNotFoundError 必触发矩阵⑤，boss/51job 采集全被误杀）：
  - macOS: lsof -ti tcp:<port> -sTCP:LISTEN + ps -ww -o command=（原路径不变）
  - Windows: netstat -ano -p TCP 解析 LISTENING 行取 PID（系统自带，零依赖）
             + PowerShell Get-CimInstance Win32_Process 取 CommandLine
             （Win11 24H2+ 已移除 wmic，PowerShell CIM 是官方替代）
  - 2026-10-29 命令行查询改 psutil 主路径（Process.cmdline() 毫秒级、无 WMI/PowerShell，
    argv 经 subprocess.list2cmdline 还原为引号包裹形态、与 CIM 原生字符串对齐）；
    CIM 降为兜底且首次失败重试一次（超时 5s→10s）。psutil 缺失（ImportError）时
    纯标准库 CIM 路径仍完整可用。

退出码语义：macOS lsof 退出码 1 且空输出 = 正常「查无匹配」（非异常）；
退出码 ≥2 / FileNotFoundError / 超时 = 异常 → fail-closed。Windows netstat
恒为 0 退出码，以「LISTENING 行解析结果」为准。

HTTP 探测（GET /json/version）的唯一作用：捕获监听探测的非特权盲区（跨用户监听
进程不可见但 HTTP 可达，对应矩阵②③）。端口是否空闲的权威判定是监听探测，
勿因「GET 已覆盖端口探活」的错觉移除其一。

已知局限（登记）：
- TOCTOU：判定通过与实际连接之间存在极小竞态窗口（探测时端口空闲、连接瞬间被
  其他浏览器抢占），概率极低，不做连接后复核。
- --user-data-dir 提取：引号包裹形态（Windows list2cmdline / CIM）与裸路径均支持；
  裸路径以「下一个 --flag / 目标 URL」或行尾为界，路径本身含「 --」时仍可能截断
  （fail-closed 方向安全）。理论上若截断点恰好等于预期路径（两路径构成前缀关系），
  可构成假放行——触发面要求真实路径内部出现「 --flag」形态，现实不存在。
  macOS 打包态 profile 位于
  `~/Library/Application Support/jobhunter-desktop/profiles/...`，2026-10-30
  真机事故即由旧的 (\\S+) 在空格处截断，导致 boss/51job 自家浏览器被误杀。
- 多监听 PID 时「任一匹配即放行」（弱于「全部匹配」）：同端口多 LISTEN 需
  SO_REUSEPORT，现实触发面极低；不收紧为全匹配以免一个已死 PID 卡住合法浏览器。
- 矩阵⑦的 trusted root 用 realpath 双侧归一：用户若在
  `.../jobhunter-desktop/profiles/<平台>` 放一个指向 QA/沙箱目录的符号链接，
  占用者会被判定为可信兄弟（同用户威胁模型下的意外进程，非提权面）。不做
  `lstat` 反查——那会让 macOS 上正常的 profile 目录（可能经 /var 符号链接）
  也被误杀；登记为已知局限。
- `JobHunter` 是较通用的应用名：若同机存在同名第三方 Electron 应用，其
  `profiles/<平台>` 也会被矩阵⑦信任。`jobhunter-desktop` 是实际安装包的
  userData 名，无碰撞；保留 `JobHunter` 候选是为了兼容 productName 落点。
- 跨进程锁的锁目录默认 `~/.jobhunter-cdp-locks`（可用
  `JOBHUNTER_CDP_LOCK_DIR` 覆盖）。目录不可写时 fail-open 并打 WARNING——
  宁可回到修复前的竞态风险，也不让整个抓取/投递因锁设施故障而瘫痪。
- 跨进程锁覆盖采集器与投递引擎的实际浏览器操作；投递前的登录预检
  （ensure_delivery_platforms_ready）与手动会话探活不在锁内，仍可能与对端
  实例的页面导航短暂重叠（以只读探活为主，风险低于抓取/投递）。

Runbook（守卫阻断生产投递时）：
  1. 识别占用者：lsof -ti tcp:<端口> -sTCP:LISTEN && ps -ww -p <pid> -o command=
  2. 残留 QA/异常浏览器 → 关闭后重跑
  3. 受控场景确认占用者身份可接受 → 设 ENGINE_GUARD_ALLOW_FOREIGN_BROWSER=1
     临时豁免，用后删除（豁免时本模块打 WARNING 留痕）

本模块零 app 内依赖（标准库 + 可选 psutil 加速路径，缺失自动回落纯标准库），供
boss/liepin/51job 三个 scraper 子系统直接
import（各文件均已把 backend 根插入 sys.path）；方案审查记录：
docs/reports/agy-review/2026-09-19_115121_plan-review_round3.md（VERDICT: PASS）
"""

import errno
import functools
import inspect
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

try:
    # POSIX 跨进程锁；Windows 走 msvcrt（两者按平台二选一）
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

try:
    # 主路径依赖（requirements 已锁定 psutil==7.2.2）：毫秒级进程命令行查询，
    # 不依赖 WMI/PowerShell。缺失时回落纯标准库 CIM 路径——psutil 是可选依赖。
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

logger = logging.getLogger(__name__)

EXEMPT_ENV = "ENGINE_GUARD_ALLOW_FOREIGN_BROWSER"
# verify_browser_identity 的 reason 常量：调用方（如 app.session.browser）据此区分
# “本平台 profile / 可信桌面版 sibling / 陌生占用者”，避免跨模块硬编码字面量。
IDENTITY_REASON_SIBLING = "sibling_profile_match"
# 跨进程端口锁：同平台浏览器同一时刻只允许一个 JobHunter 实例（dev / 桌面版）驱动。
# 锁被占用时采集器以 75 退出（EX_TEMPFAIL），调度器据此中性跳过而非误报环境熔断。
PORT_LOCK_BUSY_EXIT_CODE = 75
_PORT_LOCK_DIR_ENV = "JOBHUNTER_CDP_LOCK_DIR"
_PORT_LOCK_TIMEOUT_ENV = "JOBHUNTER_CDP_LOCK_TIMEOUT_S"
_PORT_LOCK_TIMEOUT_S = 90.0
_DELIVERY_PAYLOAD_KEY = "job_data"
_PROBE_TIMEOUT_S = 1
_CMD_TIMEOUT_S = 5
# 2026-10-29 误杀修复：CIM 兜底首次失败后的重试参数（对齐矩阵③ _REPROBE_DELAY_S 复探先例）——
# PowerShell 冷启动 + WMI 预热在四引擎并发启动的高负载点可能超出 5s 首试预算
_PS_RETRY_DELAY_S = 1.0
_PS_RETRY_TIMEOUT_S = 10
# 矩阵③复探前的等待：给关停竞态期的半开 socket 留出收尾时间（见 verify_browser_identity）
_REPROBE_DELAY_S = 1.5
# POSIX（macOS / Linux）ps 输出不保证给含空格参数加引号：
#   a) 值被引号包裹：--user-data-dir="/Users/a b/profiles/boss"
#   b) 单引号形态（shlex.join / 部分启动器）
#   c) 裸路径：--user-data-dir=/Users/a b/profiles/boss --remote-allow-origins=*
# 裸路径以「下一个 --flag / 目标 URL」或行尾为界（不能用 (\S+)，空格是合法路径字符）。
_USER_DATA_DIR_RE = re.compile(
    r'--user-data-dir="([^"]+)"'
    r"|--user-data-dir='([^']+)'"
    r"|--user-data-dir=(.+?)(?=\s+(?:--[A-Za-z]|(?:https?|file|about):)|$)"
)
# Windows：CommandLine 中 --user-data-dir 的三种引号形态（含空格路径时）：
#   a) 值被引号包裹：--user-data-dir="C:\a b"（部分启动器 / Chromium 自拼命令行形态）
#   b) 整个参数被引号包裹："--user-data-dir=C:\a b"（subprocess.list2cmdline 的标准形态，
#      即 psutil 主路径还原出的字符串；CIM 查询真实进程时同样可能出现）
#   c) 无引号：--user-data-dir=C:\a_b（无空格路径，本仓库 profile 现状）
# 引号形态优先取引号内完整路径；裸 (\S+) 在含空格路径下截断致假拒绝（fail-closed 方向）。
_USER_DATA_DIR_RE_WIN = re.compile(
    r'--user-data-dir="([^"]+)"'      # a) 引号在值上
    r'|"--user-data-dir=([^"]+)"'     # b) 引号包住整个参数
    r'|--user-data-dir=(\S+)'         # c) 无引号
)


class EngineGuardError(RuntimeError):
    """环境守卫拒绝：端口占用者身份与预期 profile 不符（或无法确认）。"""


def _probe_http(port: int) -> str:
    """GET /json/version 探测（绕代理直连 127.0.0.1）。三态，勿坍缩：

    - "refused"  : 连接被立即拒绝（RST）——无监听者的强信号，唯一可判端口空闲的结局
    - "ok"       : 2xx 响应——端口确有 CDP 服务
    - "untrusted": 超时/其他异常/非 2xx——有监听者但未应答（或不可判），探测不可信
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=_PROBE_TIMEOUT_S) as resp:
            return "ok" if 200 <= resp.status < 300 else "untrusted"
    except urllib.error.HTTPError as e:
        # 非 2xx：端口有 HTTP 服务在听（否则是 RST），但不是预期 CDP——lsof 盲区同型
        logger.info("[engine_guard._probe_http] 端口 %s HTTP %s（有 HTTP 服务但非预期 CDP）", port, e.code)
        return "untrusted"
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ConnectionRefusedError):
            return "refused"
        # 异常留痕（2026-10-08）：「浏览器确已退出却报 untrusted」的事故无法定案，
        # 正是因为这里吞掉了异常细节——留下 repr 供下次直接定位根因
        logger.info("[engine_guard._probe_http] 端口 %s URLError: %r", port, e)
        return "untrusted"
    except ConnectionRefusedError:
        return "refused"
    except Exception as e:
        logger.info("[engine_guard._probe_http] 端口 %s 探测异常: %r", port, e)
        return "untrusted"


def _lsof_pids(port: int) -> list[str] | None:
    """返回监听该端口的 PID 列表；None = 探测异常（fail-closed），[] = 正常查无匹配。

    macOS 走 lsof；Windows 走 netstat -ano（lsof 不存在，FileNotFoundError 必炸 fail-closed）。
    """
    if sys.platform == "win32":
        return _netstat_pids(port)
    try:
        proc = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=_CMD_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    out = (proc.stdout or "").split()
    if proc.returncode == 0:
        return out
    if proc.returncode == 1 and not out:
        return []
    return None


# Windows GUI/打包态防控制台窗口闪烁（子进程隐藏窗口；非 Windows 平台属性不存在取 0）
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _netstat_pids(port: int) -> list[str] | None:
    """Windows：netstat -ano -p TCP 解析 LISTENING 行取 PID。语义与 _lsof_pids 对齐。"""
    try:
        # 2026-10-07 编码修复：应用以 -X utf8/PYTHONUTF8=1 跑后端（防 GBK 管道 emoji 崩溃），
        # 子进程继承 UTF-8 模式——text=True 未指定 encoding 时按 UTF-8 解 netstat 的 GBK
        # 表头（"活动连接"），读取线程 UnicodeDecodeError 崩溃且 stdout 静默变空 →
        # 误判"查无监听" → 矩阵② 把自家 Edge 当跨用户监听 fail-closed（boss/51job 全灭）。
        # 显式 errors="replace"：数据行纯 ASCII 完整可解析，仅 GBK 表头乱码（无害）。
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_CMD_TIMEOUT_S, creationflags=_CREATE_NO_WINDOW,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    # R1 P2：returncode 校验前置——非 0 一律 fail-closed，即便解析出结果也不信任
    if proc.returncode != 0:
        return None
    pids: list[str] = []
    for line in (proc.stdout or "").splitlines():
        cols = line.split()
        # 形如: TCP  127.0.0.1:9227  0.0.0.0:0  LISTENING  <pid>（IPv6 local 为 [::]:9227 同型）
        if len(cols) >= 5 and cols[0].upper() == "TCP" and cols[3].upper() == "LISTENING" \
                and cols[1].lower().endswith(f":{port}"):
            if cols[4] not in pids:
                pids.append(cols[4])
    return pids


def _ps_command(pid: str) -> str | None:
    if sys.platform == "win32":
        return _win_commandline(pid)
    try:
        proc = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=_CMD_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def _psutil_commandline(pid_int: int) -> tuple[bool, str | None]:
    """psutil 主路径查进程命令行：毫秒级、不依赖 WMI/PowerShell。返回 (dead, cmdline)。

    dead=True 仅在「进程确认已退出」时成立（NoSuchProcess——含子类 ZombieProcess——或
    空 argv），调用方应跳过兜底与重试，直接交由 verify_browser_identity 重跑监听探测
    按端口状态归类（端口已空闲 → 按矩阵①放行自起）。AccessDenied/其他 psutil.Error/
    OSError/广义异常 → (False, None)，由调用方回落 PowerShell CIM 兜底（agy-review
    2026-10-29 P2：宽泛兜底，探测异常绝不向上抛破坏守卫）。
    """
    if psutil is None:
        return False, None
    try:
        argv = psutil.Process(pid_int).cmdline()
    except psutil.NoSuchProcess:
        logger.info("[engine_guard._psutil_commandline] PID %s 已不存在（NoSuchProcess）", pid_int)
        return True, None
    except psutil.AccessDenied:
        logger.warning("[engine_guard._psutil_commandline] PID %s AccessDenied（权限受限），回落 PowerShell CIM", pid_int)
        return False, None
    except (psutil.Error, OSError) as e:
        logger.warning("[engine_guard._psutil_commandline] PID %s psutil 查询异常: %r，回落 PowerShell CIM", pid_int, e)
        return False, None
    except Exception as e:  # 兜底：探测异常不允许破坏守卫逻辑
        logger.warning("[engine_guard._psutil_commandline] PID %s psutil 未预期异常: %r，回落 PowerShell CIM", pid_int, e)
        return False, None
    if not argv:
        logger.info("[engine_guard._psutil_commandline] PID %s 空命令行（进程已退出）", pid_int)
        return True, None
    # list2cmdline 还原 Windows 引号包裹形态，与 CIM 原生 CommandLine 字符串一致——
    # naive " ".join 在含空格路径下丢引号，--user-data-dir 提取会偏差（agy-review P2）
    return False, subprocess.list2cmdline(argv)


def _ps_commandline_cim(pid_int: int, timeout: float) -> tuple[bool, str | None]:
    """PowerShell CIM 查进程命令行（wmic 在 Win11 24H2+ 已移除）。返回 (dead, cmdline)。

    dead=True 仅在「查询成功但查无此进程」（returncode 0 + 空输出）时成立；查询失败
    （超时/非零退出/异常）返回 (False, None) 并在日志留痕具体原因——2026-10-28 事故
    因吞掉失败类型无法定案根因，此处是第 0 层可观测性落点。
    """
    try:
        # [Console]::OutputEncoding=UTF8：让 PowerShell 以 UTF-8 写 stdout（默认 OEM/GBK），
        # 配合 encoding="utf-8" 精确解码——路径含中文（中文用户名）时 user-data-dir 比对不失真
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid_int}').CommandLine"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        logger.error("[engine_guard._ps_commandline_cim] PID %s powershell 不可用（FileNotFoundError）", pid_int)
        return False, None
    except subprocess.TimeoutExpired:
        logger.error(
            "[engine_guard._ps_commandline_cim] PID %s CIM 查询超时（>%ss）：高负载点 PowerShell 冷启动/WMI 预热可能超预算",
            pid_int, timeout,
        )
        return False, None
    except OSError as e:
        logger.error("[engine_guard._ps_commandline_cim] PID %s CIM 查询进程创建失败: %r", pid_int, e)
        return False, None
    if proc.returncode != 0:
        stderr_tail = ((proc.stderr or "").strip().splitlines() or ["(无 stderr)"])[-1]
        logger.error(
            "[engine_guard._ps_commandline_cim] PID %s CIM 查询失败（returncode=%s）stderr 尾行: %s",
            pid_int, proc.returncode, stderr_tail,
        )
        return False, None
    out = (proc.stdout or "").strip()
    if not out:
        logger.warning("[engine_guard._ps_commandline_cim] PID %s CIM 查询成功但无输出（进程已退出）", pid_int)
        return True, None
    return False, out


def _win_commandline(pid: str) -> str | None:
    """Windows 查进程命令行：psutil 主路径（毫秒级）→ PowerShell CIM 兜底（重试一次）。

    2026-10-28 真机事故：此前仅 CIM 一条路、超时预算 5s，四引擎并发启动的高负载点超时
    → 「进程命令行查询失败」一票否决 fail-closed 误杀自家浏览器。修复后：
    - psutil 主路径正常场景毫秒级返回，不再触碰 PowerShell/WMI；
    - CIM 兜底首次失败等 _PS_RETRY_DELAY_S 重试一次，超时放宽到 _PS_RETRY_TIMEOUT_S；
    - 进程确认已退出（dead）不重试不兜底——立即返回 None，由 verify_browser_identity
      重跑监听探测按端口状态归类。
    """
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return None
    dead, cmdline = _psutil_commandline(pid_int)
    if cmdline is not None:
        return cmdline
    if dead:
        return None
    dead2, cmdline2 = _ps_commandline_cim(pid_int, _CMD_TIMEOUT_S)
    if cmdline2 is not None:
        return cmdline2
    if dead2:
        return None
    logger.warning(
        "[engine_guard._win_commandline] PID %s 命令行查询首次失败，%ss 后重试（超时放宽至 %ss）",
        pid_int, _PS_RETRY_DELAY_S, _PS_RETRY_TIMEOUT_S,
    )
    time.sleep(_PS_RETRY_DELAY_S)
    _, cmdline3 = _ps_commandline_cim(pid_int, _PS_RETRY_TIMEOUT_S)
    return cmdline3


def _extract_user_data_dir(cmdline: str) -> str | None:
    """按平台提取 --user-data-dir 值；Windows / POSIX 均支持引号与含空格路径。"""
    if sys.platform == "win32":
        m = _USER_DATA_DIR_RE_WIN.search(cmdline)
        if m is None:
            return None
        return m.group(1) or m.group(2) or m.group(3)
    m = _USER_DATA_DIR_RE.search(cmdline)
    if m is None:
        return None
    return m.group(1) or m.group(2) or m.group(3)


def _canonical(path: str) -> str:
    """normcase(realpath())：处理符号链接（/tmp→/private/tmp）与 APFS 大小写不敏感。"""
    return os.path.normcase(os.path.realpath(path))


# 桌面版 Electron 壳的应用名候选：app.getPath("userData") 由 package.json 的 name
# （jobhunter-desktop）或 productName（JobHunter）决定，两者都可能是实际落点。
_DESKTOP_APP_NAMES = ("jobhunter-desktop", "JobHunter")


def _desktop_profile_roots() -> list[str]:
    """同产品桌面版（Electron 安装包）的 profiles 根目录候选。

    2026-10-30 真机事故：dev 实例与已安装的 JobHunter 桌面版同时运行，桌面版后端
    以 JOBHUNTER_DATA_DIR（Electron userData）拉起 Edge 并占用固定 CDP 端口；
    dev 实例期望 backend/data/profiles，守卫按「非预期 profile」拒绝，BOSS/51job
    抓取启动即退出码 1。桌面版 profile 与 dev profile 同属本产品（不是陌生浏览器），
    故作为可信兄弟根放行；worktree / 沙箱 / 日常浏览器不在候选内，仍 fail-closed。
    """
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base_root = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    elif sys.platform == "darwin":
        base_root = os.path.join(home, "Library", "Application Support")
    else:
        base_root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    roots = [os.path.join(base_root, name, "profiles") for name in _DESKTOP_APP_NAMES]
    data_dir = os.environ.get("JOBHUNTER_DATA_DIR", "").strip()
    if data_dir:
        # 与 expected_profile 的 isabs 规则对齐：相对路径按当前工作目录归一，
        # `~` 显式展开；否则 join 出的相对路径在 realpath 后可能意外命中 cwd 下的目录。
        roots.append(os.path.join(os.path.abspath(os.path.expanduser(data_dir)), "profiles"))
    return roots


def _port_lock_dir() -> str:
    override = os.environ.get(_PORT_LOCK_DIR_ENV, "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(os.path.expanduser("~"), ".jobhunter-cdp-locks")


def _port_lock_path(port: int) -> str:
    return os.path.join(_port_lock_dir(), f"port-{int(port)}.lock")


def _resolve_lock_timeout(timeout_s: float | None) -> float:
    def _coerce(value) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return max(0.0, parsed)

    if timeout_s is not None:
        parsed = _coerce(timeout_s)
        if parsed is None:
            # 显式参数是调用方 bug，直接抛错；只有 env 才警告后回落默认
            raise ValueError(f"timeout_s 必须是有限数字，收到 {timeout_s!r}")
        return parsed
    raw = os.environ.get(_PORT_LOCK_TIMEOUT_ENV, "").strip()
    if raw:
        parsed = _coerce(raw)
        if parsed is None:
            logger.warning(
                "[跨进程锁] %s=%r 非有限数字，回落默认 %.0fs",
                _PORT_LOCK_TIMEOUT_ENV, raw, _PORT_LOCK_TIMEOUT_S,
            )
            return _PORT_LOCK_TIMEOUT_S
        return parsed
    return _PORT_LOCK_TIMEOUT_S


def _try_flock(fd: int) -> bool:
    """非阻塞加锁；返回 False=被占用，True=已持有。"""
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
    if msvcrt is not None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as e:
            # Windows: EACCES / EDEADLOCK 才是「被占用」；EBADF/EIO 等是锁设施
            # 故障，必须上抛走 fail-open，不能空转一个超时后误判为对端实例。
            busy_errnos = {
                errno.EACCES,
                getattr(errno, "EDEADLOCK", 36),
                getattr(errno, "EDEADLK", 35),
            }
            if getattr(e, "errno", None) in busy_errnos:
                return False
            raise
    return True  # acquire_port_lock 已在前置检查拦截「无锁原语」平台


def _unlock_fd(fd: int) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


# 进程内每端口 RLock 注册表：flock/msvcrt 按「打开文件描述」互斥，同进程第二次
# os.open 后再加锁会失败。若两个线程并发进入同端口入口，没有这层本地串行就会
# 把「自己人」误判成对端实例并白等一个超时。RLock + depth 同时支持同线程重入。
_local_guard = threading.Lock()
_local_locks: dict[int, threading.RLock] = {}
_local_owner: dict[int, int] = {}
_local_depth: dict[int, int] = {}
_fd_ports: dict[int, int] = {}


def _local_lock_for(port: int) -> threading.RLock:
    with _local_guard:
        lock = _local_locks.get(port)
        if lock is None:
            lock = threading.RLock()
            _local_locks[port] = lock
        return lock


def _drop_local_state(port: int, local: threading.RLock) -> None:
    with _local_guard:
        _local_owner.pop(port, None)
        _local_depth.pop(port, None)
        # 注册 fd 后、handed_off 置位前被打断的窄窗口：fd 已映射但未交接，
        # 必须同步清掉，否则后续重入 next() 会命中已关闭的悬挂 fd。
        for mapped_fd, mapped_port in list(_fd_ports.items()):
            if mapped_port == port:
                _fd_ports.pop(mapped_fd, None)
    local.release()


def _write_lock_metadata(fd: int, platform: str) -> None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        payload = f"pid={os.getpid()} platform={platform} ts={time.time():.0f}\n".encode()
        data = payload[:256].ljust(256, b" ")
        while data:
            written = os.write(fd, data)
            if written <= 0:
                break
            data = data[written:]
    except OSError:
        pass


def acquire_port_lock(
    port: int,
    platform: str = "",
    timeout_s: float | None = None,
    poll_s: float = 0.5,
) -> int | None:
    """跨进程独占平台 CDP 端口，返回锁 fd。

    返回值：>=0 持有锁（调用方必须在 finally 里 release_port_lock）；None=等待超时
    （本进程或对端实例正在抓取/投递）；-1=锁设施不可用（fail-open，仅打 WARNING，
    不阻断业务）。

    两层锁：进程内每端口 RLock（防同进程双 fd 自锁/重入）+ 跨进程文件锁
    （flock / msvcrt）。同线程重入返回同一 fd，按 depth 计数，最后一次 release
    才真正释放文件锁。
    """
    timeout_s = _resolve_lock_timeout(timeout_s)
    poll_s = max(0.05, float(poll_s))
    if fcntl is None and msvcrt is None:
        logger.warning("[跨进程锁] 当前平台无文件锁原语，跳过互斥（fail-open）")
        return -1

    deadline = time.monotonic() + timeout_s
    local = _local_lock_for(port)
    if not local.acquire(timeout=timeout_s):
        logger.warning("[跨进程锁] 本进程内同端口 %s 被其他线程占用，等待 %.0fs 超时", port, timeout_s)
        return None

    fd = None
    handed_off = False
    is_reentry = False
    reentry_depth_before: int | None = None
    try:
        tid = threading.get_ident()
        with _local_guard:
            if _local_owner.get(port) == tid and _local_depth.get(port, 0) > 0:
                existing_fd = next((f for f, p in _fd_ports.items() if p == port), None)
                if existing_fd is not None:
                    is_reentry = True
                    reentry_depth_before = _local_depth.get(port, 1)
                    _local_depth[port] = reentry_depth_before + 1
                    logger.info(
                        "[跨进程锁] 平台 %s 端口 %s 同线程重入（depth=%s）",
                        platform, port, _local_depth[port],
                    )
                    # 置位放在 logging 之后：logging 抛异常时由 finally 回滚 depth 并退一层 RLock
                    handed_off = True
                    return existing_fd
            _local_owner[port] = tid
            _local_depth[port] = 1

        path = _port_lock_path(port)
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            # Windows 需显式 O_BINARY，避免文本模式把元数据换行翻译成 CRLF
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
            fd = os.open(path, flags, 0o600)
        except OSError as e:
            logger.warning("[跨进程锁] 锁目录不可用，跳过互斥（fail-open）: %r", e)
            return -1
        try:
            # Windows msvcrt.locking 需要至少 1 字节可锁区域；POSIX 空文件可 flock
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
        except OSError:
            pass
        while True:
            try:
                if _try_flock(fd):
                    _write_lock_metadata(fd, platform)
                    with _local_guard:
                        _fd_ports[fd] = port
                    logger.info("[跨进程锁] 平台 %s 端口 %s 已获取（pid=%s）", platform, port, os.getpid())
                    # 置位放在 logging 之后：logging 抛异常时由 finally close fd 并清映射
                    handed_off = True
                    return fd
            except OSError as e:
                logger.warning("[跨进程锁] 平台 %s 端口 %s 加锁异常（fail-open）: %r", platform, port, e)
                return -1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning("[跨进程锁] 平台 %s 端口 %s 等待 %.0fs 仍被对端进程占用", platform, port, timeout_s)
                return None
            time.sleep(min(poll_s, remaining))
    finally:
        # BaseException（KeyboardInterrupt/SystemExit/CancelledError）也必须归还
        # 本地 RLock，否则该端口在本进程内会永久中毒（每次白等满超时）。
        if not handed_off:
            if is_reentry:
                # 重入层被打断：depth 可能已 +1（赋值后、置位前），按快照回滚；
                # 只退一层 RLock，保留外层 owner/depth 与文件锁。
                if reentry_depth_before is not None:
                    with _local_guard:
                        current = _local_depth.get(port)
                        if current is not None and current > reentry_depth_before:
                            _local_depth[port] = current - 1
                local.release()
            else:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                _drop_local_state(port, local)


def release_port_lock(fd: int | None) -> None:
    """释放端口锁；必须由 acquire_port_lock 的同一线程调用。

    跨线程/未注册 fd 一律拒绝并留日志：错误线程释放会先放掉文件锁、再在
    local.release() 抛错，持有者临界区仍在跑时对端就能抢锁；重复释放则可能
    close 一个已被 OS 复用的无关 fd。
    """
    if fd is None or fd < 0:
        return
    with _local_guard:
        port = _fd_ports.get(fd)
        if port is None:
            logger.warning(
                "[跨进程锁] release_port_lock 收到未注册 fd=%s（重复释放或非本模块获取），已忽略",
                fd,
            )
            return
        owner = _local_owner.get(port)
        if owner is not None and owner != threading.get_ident():
            logger.error(
                "[跨进程锁] release_port_lock 跨线程释放被拒绝（owner=%s, caller=%s, port=%s）",
                owner, threading.get_ident(), port,
            )
            return
        depth = _local_depth.get(port, 1) - 1
        if depth > 0:
            _local_depth[port] = depth
            local = _local_locks.get(port)
        else:
            _local_depth.pop(port, None)
            _local_owner.pop(port, None)
            _fd_ports.pop(fd, None)
            local = _local_locks.get(port)
    if depth > 0:
        # 同线程重入：只退一层 RLock，文件锁继续持有
        if local is not None:
            local.release()
        return
    _unlock_fd(fd)
    try:
        os.close(fd)
    except OSError:
        pass
    if local is not None:
        local.release()


def cross_process_port_lock(
    port: int,
    platform: str = "",
    timeout_s: float | None = None,
    on_busy: str = "raise",
):
    """装饰同步入口：函数执行全程独占平台 CDP 端口（跨进程）。

    on_busy:
      - "raise"（默认）：抛 EngineGuardError，调用方按异常处理；
      - "exit"：打印中性原因并以 75（EX_TEMPFAIL）退出——**仅用于独立进程入口
        （采集器脚本）**。常驻后端进程/线程内使用会 sys.exit 整个进程，必须改用
        "raise" 或 "false"；
      - "false"：给首个 dict 参数（或 kwargs["job_data"]）写 delivery_error 并返回
        False（投递引擎语义，失败分诊会按「浏览器」暂时性故障保留待投递自愈重试）。

    仅支持同步函数：async/生成器会在 await/yield 期间释放锁，装饰即报错。
    acquire/release 在同一同步调用线程内完成，不可跨线程释放。
    timeout_s=None 时按 JOBHUNTER_CDP_LOCK_TIMEOUT_S / 默认 90s 解析。
    """
    if on_busy not in ("raise", "exit", "false"):
        raise ValueError(f"on_busy 必须是 raise/exit/false，收到 {on_busy!r}")

    def decorator(func):
        if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func) or inspect.isgeneratorfunction(func):
            raise TypeError(
                "cross_process_port_lock 仅支持同步函数：async/生成器会在 await/yield 期间释放锁"
            )

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            fd = acquire_port_lock(port, platform, timeout_s)
            if fd is None:
                msg = (
                    f"{platform or '该平台'} 浏览器端口 {port} 正被占用"
                    f"（本进程或另一个 JobHunter 实例），本次操作已跳过"
                )
                logger.warning("[跨进程锁] %s", msg)
                if on_busy == "exit":
                    sys.exit(PORT_LOCK_BUSY_EXIT_CODE)
                if on_busy == "false":
                    payload = args[0] if args and isinstance(args[0], dict) else kwargs.get(_DELIVERY_PAYLOAD_KEY)
                    if isinstance(payload, dict):
                        payload["delivery_error"] = msg
                    else:
                        logger.warning(
                            "[跨进程锁] on_busy=false 未找到 %s dict，无法写入 delivery_error",
                            _DELIVERY_PAYLOAD_KEY,
                        )
                    return False
                raise EngineGuardError(msg)
            try:
                return func(*args, **kwargs)
            finally:
                release_port_lock(fd)
        return wrapper
    return decorator


def verify_browser_identity(port: int, expected_profile: str, platform: str = "") -> tuple[bool, str]:
    """
    校验 CDP 端口占用者身份。返回 (ok, reason)；ok=False 时调用方必须拒绝连接。

    expected_profile 必须是绝对路径（各引擎现有 PROFILE 常量均基于 __file__ 推导；
    非绝对路径说明配置错误，直接拒绝——realpath 的 cwd 语义不可靠）。
    """
    if os.environ.get(EXEMPT_ENV) == "1":
        logger.warning(
            "[引擎守卫] %s=1 显式豁免：跳过平台 %s 端口 %s 身份校验（受控场景，用后删除）",
            EXEMPT_ENV, platform, port,
        )
        return True, "exempted_by_env"

    if not os.path.isabs(expected_profile):
        logger.critical("[引擎守卫] 平台 %s 的 expected_profile 非绝对路径：%r", platform, expected_profile)
        return False, f"expected_profile 非绝对路径: {expected_profile!r}"

    pids = _lsof_pids(port)

    if pids is None:
        logger.critical("[引擎守卫] 平台 %s 端口 %s 监听探测异常，fail-closed 拒绝", platform, port)
        return False, "端口监听探测异常（fail-closed）"
    if not pids:
        # HTTP 探测延迟到此刻：pids 非空时走身份校验、probe 结果弃用，不必白等
        probe = _probe_http(port)
        if probe == "refused":
            # 连接被立即拒绝 = 无监听者的强信号，端口空闲，可放行自起
            return True, "port_free"
        if probe == "ok":
            logger.critical(
                "[引擎守卫] 平台 %s 端口 %s 探测盲区：HTTP 可达但无可见监听进程（疑跨用户监听），宁可错杀",
                platform, port,
            )
            return False, "探测盲区：HTTP 可达但无可见监听进程（fail-closed）"
        # probe == "untrusted"（超时/非 2xx/其他异常）：超时恰是「有监听者但未应答」的信号，
        # 在探测盲区场景下绝不可当端口空闲放行——探测不可信即拒绝。
        # 2026-10-08 复探：15:30 猎聘事故实测「浏览器确已退出却报 untrusted」（进程关停
        # 竞态期的半开 socket 可吞 RST 致 1s 探测超时）。1.5s 后复探一次，仅「复探=refused
        # （确定性 RST）」才放行自起；仍不可信维持 fail-closed——盲区语义不弱化（51job
        # 僵尸场景监听 PID 非空，根本不走此分支）。
        time.sleep(_REPROBE_DELAY_S)
        probe2 = _probe_http(port)
        if probe2 == "refused":
            logger.warning(
                "[引擎守卫] 平台 %s 端口 %s 首探 untrusted 但复探 refused（关停竞态），放行自起",
                platform, port,
            )
            return True, "port_free"
        logger.critical(
            "[引擎守卫] 平台 %s 端口 %s HTTP 探测不可信（超时/非2xx/异常；复探=%s）且无监听进程，fail-closed 拒绝",
            platform, port, probe2,
        )
        return False, "HTTP 探测不可信且无监听进程（fail-closed）"

    expected = _canonical(expected_profile)
    # 矩阵⑦：同产品桌面版 profile 根（仅安装版 userData，不含 worktree/沙箱）。
    # 平台键以 expected_profile 的末段为准（调用方传 "BOSS直聘" 之类展示名也不会失配）；
    # 末段为空才回退 platform 参数。
    platform_key = os.path.basename(os.path.normpath(expected_profile)) or platform
    if platform_key:
        trusted_siblings = {
            _canonical(os.path.join(root, platform_key))
            for root in _desktop_profile_roots()
        }
    else:
        # 末段与 platform 皆空时 join(root, "") 会把整个 profiles 根当可信兄弟，
        # 等于放行该根下任意平台目录——宁可少放行，不扩大信任面。
        logger.warning("[引擎守卫] 平台键为空，跳过矩阵⑦兄弟 profile 放行（fail-closed）")
        trusted_siblings = set()
    foreign: list[str] = []
    query_failed_pids: list[str] = []
    for pid in pids:
        cmdline = _ps_command(pid)
        if cmdline is None:
            # 查询失败不立即否决：先给其他 PID 匹配机会（任一匹配即放行的既有语义，
            # 也让「netstat 残留死 PID + 合法浏览器」场景不再被遮蔽），统一收集后走矩阵⑥
            query_failed_pids.append(pid)
            continue
        actual = _extract_user_data_dir(cmdline)
        if actual is None:
            foreign.append(f"PID {pid}: 命令行无 --user-data-dir")
            continue
        actual_canon = _canonical(actual)
        if actual_canon == expected:
            return True, "profile_match"
        if actual_canon in trusted_siblings:
            logger.warning(
                "[引擎守卫] 平台 %s 端口 %s 占用者为同产品桌面版浏览器（%s），"
                "放行复用其登录态；请勿让 dev 实例与桌面版同时发起抓取/投递",
                platform, port, actual,
            )
            return True, IDENTITY_REASON_SIBLING
        foreign.append(f"PID {pid}: {actual}")

    if query_failed_pids:
        # 矩阵⑥（2026-10-29 修订，真机误杀事故）：查询失败 ≠ 身份不可信，重跑监听探测再归类：
        # 端口已无监听 → 占用者在探测间隙退出（TOCTOU/进程已死），按矩阵①语义放行自起；
        # 仍有监听者或复探不可信 → 身份无法确认，维持 fail-closed（防护不弱化），文案给 runbook。
        reprobe_pids = _lsof_pids(port)
        if reprobe_pids == []:
            probe = _probe_http(port)
            if probe == "refused":
                logger.warning(
                    "[引擎守卫] 平台 %s 端口 %s 命令行查询失败（PID %s）但复探已无监听（占用者退出），按端口空闲放行自起",
                    platform, port, "、".join(query_failed_pids),
                )
                return True, "port_free"
            if probe == "ok":
                logger.critical(
                    "[引擎守卫] 平台 %s 端口 %s 命令行查询失败且复探无监听但 HTTP 可达（疑跨用户监听盲区），宁可错杀",
                    platform, port,
                )
                return False, (
                    "命令行查询失败且复探无监听但 HTTP 可达（疑跨用户监听盲区，宁可错杀，fail-closed）；"
                    f"受控场景可临时设 {EXEMPT_ENV}=1 豁免（用后删除）"
                )
        failed = "、".join(query_failed_pids)
        logger.critical(
            "[引擎守卫] 平台 %s 端口 %s 进程命令行查询 PID %s 失败且端口仍有监听者/复探不可信，fail-closed 拒绝。"
            "处理：①在会话条「唤起浏览器」重启该平台浏览器后重跑；②受控场景可临时设 %s=1 豁免（用后删除）",
            platform, port, failed, EXEMPT_ENV,
        )
        return False, (
            f"进程命令行查询 PID {failed} 失败且端口仍有监听者/复探不可信（fail-closed）；"
            f"可重启该平台浏览器后重跑，或临时设 {EXEMPT_ENV}=1 豁免（用后删除）"
        )

    reason = "；".join(foreign)
    logger.critical(
        "[引擎守卫] 平台 %s 端口 %s 占用者与预期 profile 不符，拒绝附着（预期 %s）→ %s",
        platform, port, expected_profile, reason,
    )
    return False, f"端口 {port} 占用者非预期 profile（预期 {expected_profile}）：{reason}"
