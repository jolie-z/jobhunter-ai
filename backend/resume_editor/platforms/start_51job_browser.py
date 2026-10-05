"""
51job简历编辑器 - Edge 浏览器启动脚本（2026-09-24 收编到 patchright 新链路）

旧实现（DrissionPage + 9227 端口直拉）已废弃：与主链路 patchright 引擎抢同一
Profile 目录（Chromium SingletonLock 冲突），会话分裂/导航挂死（2026-09-24 事故）。

新实现：调 app.session.browser.launch_edge（51job 自动分流到 patchright 登录守护）：
- 互斥走 .engine_lock（单一持有者模型），与采集/投递引擎天然互斥；
- 登录态由持久化 Profile 原生承载，探测成功自动关窗，不再需要人工按 Enter。

用法：
    python start_51job_browser.py
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
sys.path.insert(0, _BACKEND_DIR)

from app.session.registry import resolve_platform
from app.session.browser import launch_edge


def start_browser():
    print("=" * 60)
    print("  51job简历编辑器 - 浏览器启动（patchright 新链路）")
    print("=" * 60)

    config = resolve_platform("51job")
    if config is None:
        raise SystemExit("registry 中无平台配置: 51job")

    print(f"\n  Profile 目录: {config.profile_dir}")
    print("  正在拉起浏览器（登录态有效时自动校验；未登录时弹出扫码窗口）...")

    try:
        result = launch_edge(config)
        print(f"\n  ✅ {result.get('message', '浏览器已就绪')}")
    except RuntimeError as e:
        print(f"\n  ❌ 拉起失败: {e}")
        raise SystemExit(1)

    print("\n  后续审计脚本（51job_resume_audit / 51job_deep_extract）将按需直启引擎，")
    print("  无需保持本窗口；登录态已持久化在 Profile 中。")


if __name__ == "__main__":
    start_browser()
