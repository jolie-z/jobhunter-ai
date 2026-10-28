"""Windows 控制台子进程防闪窗统一助手（2026-10-11）

背景：桌面壳以 detached:true（DETACHED_PROCESS）拉起 Python 后端，后端自身无控制台；
后端再 spawn 任何控制台子系统程序（python.exe / pip.exe / boss CLI 等）时，Windows 会
为子进程新分配控制台 → 黑窗闪现。stdout=PIPE 重定向不能阻止窗口分配，只有
CREATE_NO_WINDOW 能——它只跳过窗口创建，不影响进程组/管道/terminate() 急刹车语义，
与 DETACHED_PROCESS 的「脱离进程组」有本质区别（后者会破坏爬虫 process.terminate()
与 chatops active_processes 终止逻辑，禁止替代）。

用法：生产路径所有 subprocess.Popen / subprocess.run / asyncio.create_subprocess_exec
一律改走本助手；调用点平台分支零感知（POSIX 上不注入任何参数、纯透传零行为变化；
Windows 上 Popen 仅在 creationflags 非 0 时才 raise ValueError，注入值合法）。

参照实现：engine_guard._CREATE_NO_WINDOW（netstat / PowerShell CIM 已用）。
本模块零 app 内依赖（纯标准库），供 scraper 子系统与 app/ 两侧直接 import
（backend 根在两侧 sys.path 上；与 engine_guard 同款布局）。
"""

import asyncio
import subprocess
import sys

# 仅 win32 存在该属性；非 Windows 平台取 0（本助手在该平台根本不注入，纯透传）
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _win_hidden(kwargs: dict) -> dict:
    """平台分支唯一收口点：Windows 分支补 CREATE_NO_WINDOW，其余平台原样透传。"""
    if sys.platform == "win32":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
    return kwargs


def popen_hidden(*args, **kwargs):
    """subprocess.Popen 的防闪窗包装。"""
    return subprocess.Popen(*args, **_win_hidden(kwargs))


def run_hidden(*args, **kwargs):
    """subprocess.run 的防闪窗包装。"""
    return subprocess.run(*args, **_win_hidden(kwargs))


def create_subprocess_exec_hidden(*args, **kwargs):
    """asyncio.create_subprocess_exec 的防闪窗包装（同步工厂，返回协程，await 语义不变）。

    asyncio 传输层把 **kwargs 透传给底层 subprocess.Popen（unix_events /
    windows_events 实测），故注入的 creationflags 双平台均生效。
    """
    return asyncio.create_subprocess_exec(*args, **_win_hidden(kwargs))
