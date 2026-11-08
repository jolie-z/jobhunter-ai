"""engine_guard Windows 专有路径单测（2026-10-29 误杀修复）。

承接平台无关矩阵用例（test_engine_guard.py）之外的部分：
- _win_commandline 分层：psutil 主路径 → CIM 兜底（重试/超时放宽）→ 进程已死短路；
- _psutil_commandline 异常分类（NoSuchProcess/AccessDenied/宽泛兜底）与 list2cmdline 引号还原。

全 mock（注入 psutil 桩 / 打桩 subprocess），绝不触碰真实进程与端口。
"""

import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import engine_guard as eg


class _FakePsutilError(Exception):
    pass


def _install_psutil(monkeypatch, *, argv=None, dead=False, denied=False, boom=False):
    """向 eg 注入 psutil 桩，隔离真实进程。dead/denied/boom 控制 Process.cmdline() 行为。"""
    fake_ns = type("FakeNoSuchProcess", (_FakePsutilError,), {})
    fake_ad = type("FakeAccessDenied", (_FakePsutilError,), {})

    class FakePsutil:
        Error = _FakePsutilError
        NoSuchProcess = fake_ns
        AccessDenied = fake_ad

        class Process:
            def __init__(self, pid):
                self.pid = pid

            def cmdline(self):
                if dead:
                    raise fake_ns()
                if denied:
                    raise fake_ad()
                if boom:
                    raise _FakePsutilError("底层 OSError 模拟")
                return list(argv or [])

    monkeypatch.setattr(eg, "psutil", FakePsutil)


# ============================================================
# _win_commandline 分层编排
# ============================================================

def test_win_commandline_psutil_primary_no_cim(monkeypatch):
    """psutil 主路径成功 → 直接返回 list2cmdline 结果，CIM 兜底不发生（正常路径零 PowerShell 开销）。"""
    argv = [r"C:\Program Files\Microsoft Edge\msedge.exe", r"--user-data-dir=C:\prof\boss", "--flag"]
    _install_psutil(monkeypatch, argv=argv)
    monkeypatch.setattr(
        eg, "_ps_commandline_cim",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("CIM 兜底不应发生")),
    )
    assert eg._win_commandline("123") == subprocess.list2cmdline(argv)


def test_win_commandline_dead_short_circuits(monkeypatch):
    """NoSuchProcess（进程已退出）→ 短路返回 None：不兜底 CIM、不重试等待，交由守卫重探归类。"""
    _install_psutil(monkeypatch, dead=True)
    monkeypatch.setattr(
        eg, "_ps_commandline_cim",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("死进程不应走 CIM 兜底")),
    )
    monkeypatch.setattr(
        eg.time, "sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("死进程不应重试等待")),
    )
    assert eg._win_commandline("123") is None


def test_win_commandline_empty_argv_treated_dead(monkeypatch):
    """psutil 返回空 argv（进程查询间隙退出）→ 与 NoSuchProcess 同等 dead 短路。"""
    _install_psutil(monkeypatch, argv=[])
    monkeypatch.setattr(
        eg, "_ps_commandline_cim",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("死进程不应走 CIM 兜底")),
    )
    assert eg._win_commandline("123") is None


def test_win_commandline_access_denied_falls_back_to_cim(monkeypatch):
    """AccessDenied（权限受限）→ 回落 CIM 兜底一次成功。"""
    _install_psutil(monkeypatch, denied=True)
    monkeypatch.setattr(eg, "_ps_commandline_cim", lambda pid, timeout: (False, "CIM 命令行"))
    assert eg._win_commandline("123") == "CIM 命令行"


def test_win_commandline_cim_transient_retries_wider_timeout(monkeypatch):
    """CIM 首试失败（高负载超时嫌疑）→ 等 1s 重试一次、超时 5s→10s（对齐矩阵③复探先例）。"""
    _install_psutil(monkeypatch, denied=True)  # 强制走 CIM 兜底
    seq = [(False, None), (False, "CIM 第二次成功")]
    timeouts: list[float] = []

    def fake_cim(pid, timeout):
        timeouts.append(timeout)
        return seq[len(timeouts) - 1]

    sleeps: list[float] = []
    monkeypatch.setattr(eg, "_ps_commandline_cim", fake_cim)
    monkeypatch.setattr(eg.time, "sleep", lambda s: sleeps.append(s))
    assert eg._win_commandline("123") == "CIM 第二次成功"
    assert timeouts == [eg._CMD_TIMEOUT_S, eg._PS_RETRY_TIMEOUT_S]
    assert sleeps == [eg._PS_RETRY_DELAY_S]


def test_win_commandline_cim_dead_no_retry(monkeypatch):
    """CIM 查询成功但无输出（进程已退出）→ dead 短路，不重试。"""
    _install_psutil(monkeypatch, denied=True)
    monkeypatch.setattr(eg, "_ps_commandline_cim", lambda *a, **k: (True, None))
    monkeypatch.setattr(
        eg.time, "sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("死进程不应重试等待")),
    )
    assert eg._win_commandline("123") is None


def test_win_commandline_cim_exhausted_returns_none(monkeypatch):
    """CIM 首试 + 重试都失败 → 返回 None（身份不可确认，交由守卫矩阵⑥重探归类）。"""
    _install_psutil(monkeypatch, boom=True)
    timeouts: list[float] = []

    def fake_cim(pid, timeout):
        timeouts.append(timeout)
        return (False, None)

    monkeypatch.setattr(eg, "_ps_commandline_cim", fake_cim)
    monkeypatch.setattr(eg.time, "sleep", lambda s: None)
    assert eg._win_commandline("123") is None
    assert timeouts == [eg._CMD_TIMEOUT_S, eg._PS_RETRY_TIMEOUT_S]


def test_win_commandline_psutil_missing_uses_cim(monkeypatch):
    """psutil 缺失（ImportError 场景）→ 纯标准库 CIM 路径仍完整可用。"""
    monkeypatch.setattr(eg, "psutil", None)
    monkeypatch.setattr(eg, "_ps_commandline_cim", lambda pid, timeout: (False, "CIM 路径"))
    assert eg._win_commandline("123") == "CIM 路径"


def test_win_commandline_non_numeric_pid(monkeypatch):
    """pid 非数字（防注入契约）→ 直接 None，任何探测都不发生。"""
    monkeypatch.setattr(
        eg, "_psutil_commandline",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("非数字 pid 不应进入 psutil 路径")),
    )
    assert eg._win_commandline("not-a-pid") is None


# ============================================================
# _psutil_commandline 异常分类与 list2cmdline 引号还原
# ============================================================

def test_psutil_commandline_exception_taxonomy(monkeypatch):
    """异常分类：NoSuchProcess→dead；AccessDenied/psutil.Error/广义异常→回落 CIM（不向上抛）。"""
    _install_psutil(monkeypatch, dead=True)
    assert eg._psutil_commandline(123) == (True, None)

    _install_psutil(monkeypatch, denied=True)
    assert eg._psutil_commandline(123) == (False, None)

    _install_psutil(monkeypatch, boom=True)
    assert eg._psutil_commandline(123) == (False, None)


def test_list2cmdline_quoting_matches_win_regex(monkeypatch):
    """argv 含空格路径 → list2cmdline 把整个参数包进引号，三形态正则仍完整提取
    （agy-review 2026-10-29 P2：提取偏差会让矩阵④比对假拒绝）。"""
    monkeypatch.setattr(eg.sys, "platform", "win32")
    spaced = r"C:\Users\Jo hn\profiles\boss"
    argv = [r"C:\Program Files\Microsoft Edge\msedge.exe", f"--user-data-dir={spaced}", "--flag"]
    raw = subprocess.list2cmdline(argv)
    # b) 整个参数被引号包裹："--user-data-dir=C:\Users\Jo hn\profiles\boss"
    assert eg._extract_user_data_dir(raw) == spaced

    # a) 值被引号包裹：--user-data-dir="C:\Users\Jo hn\profiles\boss"
    assert eg._extract_user_data_dir(f'msedge.exe --user-data-dir="{spaced}" --flag') == spaced

    # c) 无空格路径（本仓库 profile 现状）→ 裸形态
    assert eg._extract_user_data_dir(r"msedge.exe --user-data-dir=C:\prof\boss --flag") == r"C:\prof\boss"
    assert eg._extract_user_data_dir("msedge.exe --other=1") is None


def test_psutil_missing_returns_not_dead(monkeypatch):
    """psutil 为 None → (False, None)（非 dead），调用方继续走 CIM 兜底而非误判进程已死。"""
    monkeypatch.setattr(eg, "psutil", None)
    assert eg._psutil_commandline(123) == (False, None)
