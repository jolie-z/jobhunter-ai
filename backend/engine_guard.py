"""引擎环境守卫（Q24 产品级加固，2026-09-19）

背景：DrissionPage ChromiumPage(co) 连接 CDP 端口时，端口被占用即直接附着，
set_user_data_path 配置被无视；playwright connect_over_cdp 同样会附着端口既有
占用者。若占用者是其他浏览器（如用户日常在线的已登录浏览器），引擎会以其身份
执行页面操作（Q24 事故：worktree 隔离实例投递时接管了生产 BOSS Edge，
QA matrix §5G）。

守卫在引擎建立浏览器连接前校验端口占用者身份，非预期 profile 一律 fail-closed
拒绝，把「附着陌生浏览器」从静默事故变成确定性失败。

判定矩阵（HTTP 探测三态 × lsof 监听，任意组合有唯一结论）：
  ① lsof 无监听 PID + HTTP 立即拒绝(RST) → 放行（端口空闲，将由本引擎以配置自起）
  ② lsof 无监听 PID + HTTP 2xx          → 拒绝（lsof 盲区：跨用户监听进程不可见，宁可错杀）
  ③ lsof 无监听 PID + HTTP 超时/非2xx/异常 → 拒绝（超时恰是「有监听者但未应答」的信号，
     盲区场景下绝不可当端口空闲；探测不可信即 fail-closed）
  ④ lsof 有监听 PID                     → 校验占用者 --user-data-dir 与预期 profile 相等，不等即拒绝
  ⑤ lsof/ps 探测本身失败                → 拒绝（探测手段不可用，fail-closed）

退出码语义：lsof 退出码 1 且空输出 = 正常「查无匹配」（非异常）；
退出码 ≥2 / FileNotFoundError / 超时 = 异常 → fail-closed。

HTTP 探测（GET /json/version）的唯一作用：捕获 lsof 的非特权盲区（跨用户监听
进程 lsof 不可见但 HTTP 可达，对应矩阵②③）。端口是否空闲的权威判定是 lsof，
勿因「GET 已覆盖端口探活」的错觉移除其一。

已知局限（登记）：
- TOCTOU：判定通过与实际连接之间存在极小竞态窗口（探测时端口空闲、连接瞬间被
  其他浏览器抢占），概率极低，不做连接后复核。
- --user-data-dir 值以 (\\S+) 提取到空白截止：占用者 profile 路径含空格时被截断
  → 与预期不等 → 假拒绝（fail-closed，方向安全；本仓库 profile 均无空格）；
  理论上「预期路径恰为含空格真实路径的前缀」可假放行——argv 序列化歧义的本质
  限制，触发面要求两路径构成前缀关系，现实不存在。
- 多监听 PID 时「任一匹配即放行」（弱于「全部匹配」）：同端口多 LISTEN 需
  SO_REUSEPORT，现实触发面极低；不收紧为全匹配以免一个已死 PID 卡住合法浏览器。

Runbook（守卫阻断生产投递时）：
  1. 识别占用者：lsof -ti tcp:<端口> -sTCP:LISTEN && ps -ww -p <pid> -o command=
  2. 残留 QA/异常浏览器 → 关闭后重跑
  3. 受控场景确认占用者身份可接受 → 设 ENGINE_GUARD_ALLOW_FOREIGN_BROWSER=1
     临时豁免，用后删除（豁免时本模块打 WARNING 留痕）

本模块零 app 内依赖（纯标准库），供 boss/liepin/51job 三个 scraper 子系统直接
import（各文件均已把 backend 根插入 sys.path）；方案审查记录：
docs/reports/agy-review/2026-09-19_115121_plan-review_round3.md（VERDICT: PASS）
"""

import logging
import os
import re
import subprocess
import urllib.request

logger = logging.getLogger(__name__)

EXEMPT_ENV = "ENGINE_GUARD_ALLOW_FOREIGN_BROWSER"
_PROBE_TIMEOUT_S = 1
_CMD_TIMEOUT_S = 5
_USER_DATA_DIR_RE = re.compile(r"--user-data-dir=(\S+)")


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
    except urllib.error.HTTPError:
        # 非 2xx：端口有 HTTP 服务在听（否则是 RST），但不是预期 CDP——lsof 盲区同型
        return "untrusted"
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ConnectionRefusedError):
            return "refused"
        return "untrusted"
    except ConnectionRefusedError:
        return "refused"
    except Exception:
        return "untrusted"


def _lsof_pids(port: int) -> list[str] | None:
    """返回监听该端口的 PID 列表；None = lsof 异常（fail-closed），[] = 正常查无匹配。"""
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


def _ps_command(pid: str) -> str | None:
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


def _canonical(path: str) -> str:
    """normcase(realpath())：处理符号链接（/tmp→/private/tmp）与 APFS 大小写不敏感。"""
    return os.path.normcase(os.path.realpath(path))


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
        logger.critical("[引擎守卫] 平台 %s 端口 %s lsof 探测异常，fail-closed 拒绝", platform, port)
        return False, "lsof 探测异常（fail-closed）"
    if not pids:
        # HTTP 探测延迟到此刻：pids 非空时走身份校验、probe 结果弃用，不必白等
        probe = _probe_http(port)
        if probe == "refused":
            # 连接被立即拒绝 = 无监听者的强信号，端口空闲，可放行自起
            return True, "port_free"
        if probe == "ok":
            logger.critical(
                "[引擎守卫] 平台 %s 端口 %s lsof 盲区：HTTP 可达但无可见监听进程（疑跨用户监听），宁可错杀",
                platform, port,
            )
            return False, "lsof 盲区：HTTP 可达但无可见监听进程（fail-closed）"
        # probe == "untrusted"（超时/非 2xx/其他异常）：超时恰是「有监听者但未应答」的信号，
        # 在 lsof 盲区场景下绝不可当端口空闲放行——探测不可信即拒绝
        logger.critical(
            "[引擎守卫] 平台 %s 端口 %s HTTP 探测不可信（超时/非2xx/异常）且 lsof 无监听，fail-closed 拒绝",
            platform, port,
        )
        return False, "HTTP 探测不可信且 lsof 无监听（fail-closed）"

    expected = _canonical(expected_profile)
    foreign: list[str] = []
    for pid in pids:
        cmdline = _ps_command(pid)
        if cmdline is None:
            logger.critical("[引擎守卫] 平台 %s 端口 %s ps 查询 PID %s 失败，fail-closed 拒绝", platform, port, pid)
            return False, f"ps 查询 PID {pid} 失败（fail-closed）"
        actual = _USER_DATA_DIR_RE.search(cmdline)
        if actual is None:
            foreign.append(f"PID {pid}: 命令行无 --user-data-dir")
            continue
        if _canonical(actual.group(1)) == expected:
            return True, "profile_match"
        foreign.append(f"PID {pid}: {actual.group(1)}")

    reason = "；".join(foreign)
    logger.critical(
        "[引擎守卫] 平台 %s 端口 %s 占用者与预期 profile 不符，拒绝附着（预期 %s）→ %s",
        platform, port, expected_profile, reason,
    )
    return False, f"端口 {port} 占用者非预期 profile（预期 {expected_profile}）：{reason}"
