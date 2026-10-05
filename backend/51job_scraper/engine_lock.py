"""51job 引擎互斥锁 — 单一持有者模型（唯一实现）。

背景：Chromium 对 user_data_dir 是进程独占（SingletonLock），任何时刻只允许
一个进程持有 51job 的 Profile。统一互斥凭证 = profiles/51job/.engine_lock
（JSON：pid + started_at + heartbeat），由本模块全权管理读写与判定。

判定阈值统一为单一常量 _LOCK_STALE_SECS（10 分钟）：心跳超时或 pid 已死，
任一命中即判定 stale 并安全覆写接管（孤儿锁自愈，防 PID 复用误判）；
心跳存活且 pid 活着 → 拒绝拉起（防止双实例写坏 Profile）。

51job 专用；其他平台继续走 engine_guard 的 CDP 端口守卫，不受影响。
"""
import json
import os
import time
from typing import Literal

LOCK_STALE_SECS = 600  # 心跳超时阈值（秒）：唯一判定常量，超时即 stale 接管

# 登录守护结局口径（write_guard_state/write 唯一合法取值，browser.py exitcode 映射同源）
GuardOutcome = Literal["login_ok", "timeout", "window_closed", "error"]


def lock_path(profile_dir: str) -> str:
    return os.path.join(profile_dir, ".engine_lock")


def _read_lock(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("pid") else None
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 进程存在但属他人：按存活处理，拒绝接管
    except OSError:
        return False


def _write_lock(path: str, purpose: str, pid: int | None = None) -> None:
    # 注：不复用 app/api/resume_editor/common.py 的 atomic_write_json——本模块被 app 层
    # （browser.py）与独立脚本（engine/collector/delivery）双向使用，反向 import app 层
    # 会引入循环依赖；os.replace 原子替换语义与其一致（R2 P2 反驳记录）。
    now = time.time()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"  # tmp 混入 pid，防多进程并发写同一临时文件
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "pid": pid if pid is not None else os.getpid(),
            "purpose": purpose,
            "started_at": now,
            "heartbeat": now,
        }, f)
    os.replace(tmp, path)  # 原子替换，避免读到半截 JSON


def acquire_lock(profile_dir: str, purpose: str = "script", pid: int | None = None) -> tuple[bool, str]:
    """抢锁：成功返回 (True, "")；被拒返回 (False, 原因)。

    pid 参数：为「本进程代表但锁由另一进程持有」的场景预留（登录守护中
    Web 服务抢锁、worker 子进程持浏览器，锁必须记 worker 的 pid，
    否则 close_edge 会误杀 Web 服务——P0 修复）。
    拒绝仅发生在「锁心跳新鲜且 pid 存活」时——真有别的进程在持有 Profile。
    stale（心跳超时 / pid 已死 / 文件损坏）一律覆写接管，保证孤儿锁自愈。
    """
    path = lock_path(profile_dir)
    data = _read_lock(path)
    if data:
        heartbeat_age = time.time() - float(data.get("heartbeat") or 0)
        alive = _pid_alive(int(data["pid"]))
        if alive and heartbeat_age <= LOCK_STALE_SECS:
            held_purpose = data.get("purpose", "unknown")
            return False, (
                f"Profile 已被其他进程持有（pid={data['pid']}, purpose={held_purpose}, "
                f"心跳 {int(heartbeat_age)}s 前更新）。51job Profile 同一时刻只能由一个进程持有，"
                f"请等待其退出或在前端重新发起。"
            )
    _write_lock(path, purpose, pid=pid)
    return True, ""


def heartbeat(profile_dir: str, pid: int | None = None) -> None:
    """刷新心跳。持有者应在长任务循环中周期调用（如每页采集后）。

    pid 参数：锁记的是另一进程 pid 时（登录守护 worker），由该进程自身调用刷新。
    """
    path = lock_path(profile_dir)
    data = _read_lock(path)
    holder = int(data.get("pid") or 0) if data else 0
    if holder != (pid if pid is not None else os.getpid()):
        return  # 锁已被他人接管或损坏：不覆写，由调用方的下次操作感知
    data["heartbeat"] = time.time()
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def release_lock(profile_dir: str, pid: int | None = None) -> None:
    """释放锁：仅当锁确实是目标进程持有时才删除，防止误删他人锁。"""
    path = lock_path(profile_dir)
    data = _read_lock(path)
    holder = int(data.get("pid") or 0) if data else 0
    if data and holder == (pid if pid is not None else os.getpid()):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


LOGIN_STATE_FILE = ".login_state.json"


def write_login_state(profile_dir: str) -> None:
    """登录守护进程探测到登录态后落标记（时间戳 + 检测方式），供脚本快速判断。"""
    path = os.path.join(profile_dir, LOGIN_STATE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "logged_in_at": time.time(),
            "detected_by": "login_guard_dom_poll",
        }, f)
    os.replace(tmp, path)


def read_login_state(profile_dir: str, max_age_secs: int = 7 * 86400) -> bool:
    """读登录标记：存在且未过期（默认 7 天）才可信；过期/缺失返回 False（脚本再做 DOM 确认）。"""
    path = os.path.join(profile_dir, LOGIN_STATE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (time.time() - float(data.get("logged_in_at") or 0)) < max_age_secs
    except Exception:
        return False


def invalidate_login_state(profile_dir: str) -> None:
    """清除登录标记：服务端会话实测已死时调用，防止 7 天快速标记带病上岗。

    2026-09-25 真机教训：客户端 cookie 存活期 ≠ 服务端会话有效性；标记被
    DOM 实测证伪后必须删除，否则后续启动（含采集）继续误信快速通道。
    """
    path = os.path.join(profile_dir, LOGIN_STATE_FILE)
    try:
        os.remove(path)
    except OSError:
        pass


GUARD_STATE_FILE = ".login_guard_state.json"


def write_guard_state(profile_dir: str, outcome: GuardOutcome) -> None:
    """登录守护 worker 退出前落盘本次结局（login_ok/timeout/window_closed/error）。

    2026-09-25 用户反馈：窗口超时自动关闭是静默的，前端永远停留在「已弹出」，
    用户不知道窗口为何消失。状态轮询侧读本文件把结局透出到会话状态文案。
    与 write_login_state 同款原子写；写失败由调用方吞掉（绝不阻塞退出）。
    """
    path = os.path.join(profile_dir, GUARD_STATE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"finished_at": time.time(), "outcome": outcome}, f)
    os.replace(tmp, path)


def read_last_guard_state(profile_dir: str, max_age_secs: int = 1800) -> dict | None:
    """读最近一次登录守护结局；缺失/损坏/超过 max_age_secs（默认 30 分钟）返回 None。"""
    path = os.path.join(profile_dir, GUARD_STATE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = time.time() - float(data.get("finished_at") or 0)
        return data if 0 <= age < max_age_secs else None
    except Exception:
        return None


def invalidate_guard_state(profile_dir: str) -> None:
    """清除守护结局文件：新登录守护会话启动时调用。

    2026-09-25 R1 P1：否则窗口运行期间状态轮询仍透出上一次「已关窗/超时」文案，
    用户误以为窗口没了而重复点击唤起，撞上引擎锁报错。
    """
    path = os.path.join(profile_dir, GUARD_STATE_FILE)
    try:
        os.remove(path)
    except OSError:
        pass
