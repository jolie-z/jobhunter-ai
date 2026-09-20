#!/usr/bin/env python3
"""猎聘浏览器会话与登录守卫模块。

核心职责：
- 管理 Edge 9226 端口 profile 与 options 配置；
- get_browser_page() 动态探活与自愈单例；
- Cookie 读取、注入与持久化回写；
- check_login_status / ensure_login 登录态检测与守卫。
"""

import os
import sys
import time
import json
from DrissionPage import ChromiumPage, ChromiumOptions

# 双身份导入引导
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.session.registry import get_profile_path, get_platform_port
from engine_guard import EngineGuardError, verify_browser_identity

COOKIE_FILE = os.path.join(_SCRIPT_DIR, 'liepin_cookies.json')
LIEPIN_HOME_URL = "https://c.liepin.com/"

_port = get_platform_port("liepin")
_LIEPIN_PROFILE = get_profile_path("liepin")
os.makedirs(_LIEPIN_PROFILE, exist_ok=True)

_co = ChromiumOptions()
_co.set_local_port(_port)
_co.set_user_data_path(_LIEPIN_PROFILE)

mac_edge_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
if os.path.exists(mac_edge_path):
    _co.set_browser_path(mac_edge_path)

# 懒加载句柄：模块级默认为 None，严禁外部模块直接 from-import page
page = None


def get_browser_page():
    """探活获取猎聘常驻浏览器句柄：被外力杀掉/端口失联时自动清锁重拉"""
    global page
    if page is not None:
        try:
            _ = page.url  # 探活：进程被杀或断联时抛异常
            return page
        except Exception:
            print("   ⚠️ 猎聘常驻浏览器已失联，自动重拉...")
            try:
                page.quit()
            except Exception:
                pass
            page = None

    # 🛡️ 环境守卫（Q24）：端口占用者身份校验——非本引擎 profile 拉起的浏览器绝不附着
    ok, guard_reason = verify_browser_identity(_port, _LIEPIN_PROFILE, platform="liepin")
    if not ok:
        raise EngineGuardError(f"猎聘引擎环境守卫拒绝连接浏览器：{guard_reason}")

    lock_file = os.path.join(_LIEPIN_PROFILE, 'SingletonLock')
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            print("   🧹 已清理猎聘残留的浏览器锁定文件...")
        except Exception:
            pass

    try:
        page = ChromiumPage(_co)
        return page
    except Exception as e:
        print(f"   ⚠️ 猎聘浏览器连接重试（{e}）...")
        time.sleep(1)
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception:
                pass
        page = ChromiumPage(_co)
        return page


def check_login_status() -> bool:
    """校验猎聘登录态：访问 c.liepin.com，若保持在 c.liepin.com 则登录态有效"""
    try:
        p = get_browser_page()
        p.get(LIEPIN_HOME_URL)
        time.sleep(2)
        return p.url.startswith("https://c.liepin.com")
    except Exception as e:
        print(f"   ⚠️ 校验猎聘登录态异常: {e}")
        return False


def _inject_cookies_if_needed():
    """仅在 Edge Profile 未登录时，尝试注入本地 cookie 文件作为备用兜底，严禁无脑覆盖活跃 Session"""
    if check_login_status():
        print("   ✅ Edge Profile 自带活跃登录态，直接复用")
        save_current_cookies()
        return

    p = get_browser_page()
    if os.path.exists(COOKIE_FILE):
        print("   🍪 Edge Profile 未登录，正在尝试从本地 Cookie 文件注入登录态...")
        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookies = json.load(f)

            p.get("https://www.liepin.com/")
            time.sleep(1)
            p.set.cookies(cookies)
            p.refresh()
            time.sleep(2)
            if check_login_status():
                print("   ✅ 本地 Cookie 注入成功，登录态已恢复！")
                save_current_cookies()
            else:
                print("   ⚠️ 本地 Cookie 文件已失效，需要扫码登录")
        except Exception as e:
            print(f"   ⚠️ 注入 Cookie 异常: {e}")
    else:
        print("   ⚠️ 未找到本地 Cookie 备份文件，请在浏览器中扫码登录")


def save_current_cookies():
    """把浏览器最新 cookies 回写 COOKIE_FILE（playwright 格式），供后续注入复用"""
    try:
        p = get_browser_page()
        raw = p.cookies(all_info=True)
        out = [{
            "name": c.get("name"), "value": c.get("value"), "domain": c.get("domain"),
            "path": c.get("path", "/"), "expires": c.get("expires", -1) or -1,
            "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
            "sameSite": c.get("sameSite", "Lax") or "Lax",
        } for c in raw]
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def ensure_login(wait_s: int = 0) -> bool:
    """登录守卫：Profile 优先 → 备用 Cookie 注入 → 可选阻塞等扫码"""
    _inject_cookies_if_needed()
    if check_login_status():
        print("   ✅ 猎聘登录态有效")
        return True
    if wait_s <= 0:
        print("   ❌ 猎聘未登录（不等待扫码）")
        return False
    print("=" * 64)
    print("   ⚠️  猎聘未登录！请在 9226 Edge 浏览器中扫码/短信登录")
    print(f"   ⏳ 登录成功后脚本自动继续，最长等待 {wait_s // 60} 分钟")
    print("=" * 64)
    t0 = time.time()
    p = get_browser_page()
    while time.time() - t0 < wait_s:
        time.sleep(5)
        if p.url.startswith("https://c.liepin.com"):
            print("   ✅ 登录成功，登录态已恢复！")
            time.sleep(2)
            save_current_cookies()
            return True
    return False
