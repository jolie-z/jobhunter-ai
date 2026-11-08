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

from app.session.registry import get_liepin_cookie_file, get_profile_path, get_platform_port
from app.session.health_checker import has_valid_liepin_auth_cookies
from engine_guard import EngineGuardError, verify_browser_identity

COOKIE_FILE = get_liepin_cookie_file()
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


def _browser_auth_ok(p) -> bool:
    """浏览器当前 cookie 是否含有效猎聘登录凭证（不导航、不看 URL）。"""
    try:
        return has_valid_liepin_auth_cookies(p.cookies(all_info=True, all_domains=True))
    except Exception:
        return False


def check_login_status() -> bool:
    """校验猎聘登录态：优先看 lt_auth/liepin_login_valid 两键，URL 仅作兜底。

    2026-10-30 修复：旧实现只看 `p.url.startswith("https://c.liepin.com")`。
    猎聘登录页也可能挂在 c.liepin.com 下，URL 前缀会把登录页误判成已登录，
    进而跳过 Cookie 注入、甚至把访客态 cookie 覆盖回有效文件。
    """
    try:
        p = get_browser_page()
        if _browser_auth_ok(p):
            return True
        p.get(LIEPIN_HOME_URL)
        time.sleep(2)
        url = getattr(p, "url", "") or ""
        if not url.startswith("https://c.liepin.com"):
            return False
        if any(ind in url for ind in ("/login", "loginBackUrl", "passport")):
            return False
        return _browser_auth_ok(p)
    except Exception as e:
        print(f"   ⚠️ 校验猎聘登录态异常: {e}")
        return False


def _clean_cookie_payload(cookies) -> list[dict]:
    """过滤成 DrissionPage 可安全注入的字段，避免脏字段导致整批注入静默失败。"""
    valid_keys = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
    out = []
    for c in cookies or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        clean = {k: v for k, v in c.items() if k in valid_keys and v is not None}
        if "expires" not in clean and c.get("expiry") is not None:
            clean["expires"] = c.get("expiry")  # 兼容旧文件/旧 DrissionPage 的 expiry 键名
        if "value" not in clean:
            clean["value"] = ""
        out.append(clean)
    return out


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
            clean = _clean_cookie_payload(cookies)
            if not clean:
                print("   ⚠️ Cookie 文件为空或格式异常，跳过注入")
                return

            p.get("https://www.liepin.com/")
            time.sleep(1)
            p.set.cookies(clean)
            p.refresh()
            time.sleep(2)
            if check_login_status():
                print(f"   ✅ 本地 Cookie 注入成功（{len(clean)} 条），登录态已恢复！")
                save_current_cookies()
            else:
                print("   ⚠️ 本地 Cookie 文件已失效，需要扫码登录")
        except Exception as e:
            print(f"   ⚠️ 注入 Cookie 异常: {e}")
    else:
        print("   ⚠️ 未找到本地 Cookie 备份文件，请在浏览器中扫码登录")


def save_current_cookies():
    """把浏览器最新 cookies 回写 COOKIE_FILE（playwright 格式），供后续注入复用。

    2026-10-30 修复：仅在当前会话确实含有效猎聘登录凭证时才回写。
    旧实现无条件覆盖，访客态/登录页误判都会把仅存的有效文件冲掉，导致下次
    拉起时「文件不新鲜 → 注入失败 → 又要扫码」。
    """
    try:
        p = get_browser_page()
        raw = p.cookies(all_info=True, all_domains=True)
        if not has_valid_liepin_auth_cookies(raw):
            print("   ⚠️ 跳过 Cookie 回写：当前会话缺少猎聘登录凭证（避免访客 cookie 覆盖有效文件）")
            return
        out = []
        for c in raw:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            exp = c.get("expires")
            if exp is None:
                exp = c.get("expiry", -1)
            try:
                exp = float(exp) if exp is not None else -1.0
            except (TypeError, ValueError):
                exp = -1.0
            same_site = str(c.get("sameSite") or "Lax").strip()
            if same_site.lower() == "none":
                same_site = "None"
            elif same_site.lower() == "strict":
                same_site = "Strict"
            else:
                same_site = "Lax"
            out.append({
                "name": c.get("name"), "value": c.get("value"), "domain": c.get("domain"),
                "path": c.get("path", "/"), "expires": exp,
                "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
                "sameSite": same_site,
            })
        tmp_path = COOKIE_FILE + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, COOKIE_FILE)
        print(f"   💾 已回写 Cookie 文件（{len(out)} 条）")
    except Exception as e:
        print(f"   ⚠️ Cookie 回写失败（不影响流程）: {e}")


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
        try:
            _ = p.url  # 浏览器被关闭/重启时重新取句柄，避免在死对象上空转
        except Exception:
            p = get_browser_page()
        if _browser_auth_ok(p):
            print("   ✅ 登录成功，登录态已恢复！")
            time.sleep(2)
            save_current_cookies()
            return True
    return False


def inject_cookies_if_needed() -> bool:
    """外部入口（投递预检/唤起路径用，2026-10-09）：确保专用浏览器处于登录态。

    前置：浏览器已在目标调试端口运行（调用方负责，如预检的 _ensure_browser_ready）。
    流程 = _inject_cookies_if_needed（profile 优先 → cookie 文件注入兜底，成功即回写）。
    返回最终是否登录（lt_auth/liepin_login_valid 凭证判定）。可能抛 EngineGuardError
    （端口被陌生浏览器占用），调用方自行兜底。
    """
    _inject_cookies_if_needed()
    return check_login_status()
