#!/usr/bin/env python3
"""
前程无忧 Cookie 采集器

功能：
1. 通过 browser_cookie3 从用户日常浏览器（Chrome/Edge）中读取 51job Cookie
2. 转换为 Playwright 兼容格式并保存到 51job_cookies.json

用法：
  1. 先在自己的 Chrome 或 Edge 浏览器中登录 51job
  2. 运行本脚本: python 51job_cookie_harvester.py
  3. Cookie 会自动保存，后续爬虫和投递自动使用
"""

import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

COOKIE_FILE = os.path.join(_SCRIPT_DIR, '51job_cookies.json')


def harvest_51job_cookies():
    """从用户日常浏览器中采集前程无忧登录 Cookie"""
    print("🚀 启动前程无忧 Cookie 采集器...\n")

    try:
        import browser_cookie3
    except ImportError:
        print("❌ browser_cookie3 未安装，请运行: pip install browser_cookie3")
        return

    pw_cookies = []
    source_browser = ""

    # 依次尝试 Chrome 和 Edge
    for browser_name, loader in [("Chrome", browser_cookie3.chrome), ("Edge", browser_cookie3.edge)]:
        print(f"🔍 正在从 {browser_name} 读取 51job Cookie...")
        try:
            cj = loader(domain_name='.51job.com')
            raw_cookies = [c for c in cj]
            if not raw_cookies:
                print(f"   ⚠️ {browser_name} 中未找到 51job Cookie")
                continue
            print(f"   ✅ 找到 {len(raw_cookies)} 个 Cookie")
            for c in raw_cookies:
                cookie = {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "secure": bool(c.secure),
                    "httpOnly": bool(getattr(c, 'httpOnly', False)),
                    "expires": float(c.expires) if c.expires else -1,
                }
                pw_cookies.append(cookie)
            source_browser = browser_name
            break
        except Exception as e:
            print(f"   ⚠️ {browser_name} 读取失败: {e}")
            continue

    if not pw_cookies:
        print("\n❌ 未在任何浏览器中找到 51job Cookie")
        print("   请先在 Chrome 或 Edge 中登录 https://we.51job.com/，然后重新运行此脚本")
        return

    # 检查关键认证 cookie
    auth_cookie = next((c for c in pw_cookies if c["name"] == "51job"), None)
    if auth_cookie:
        print(f"\n✅ 找到关键认证 cookie: 51job = {auth_cookie['value'][:30]}...")
    else:
        print(f"\n⚠️ 未找到名为 '51job' 的认证 cookie，登录态可能不完整")

    # 保存
    with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
        json.dump(pw_cookies, f, ensure_ascii=False, indent=2)
    print(f"💾 Cookie 已保存到: {COOKIE_FILE}")

    # 打印预览
    print(f"\n📋 Cookie 预览（来源: {source_browser}，共 {len(pw_cookies)} 个）:")
    for i, cookie in enumerate(pw_cookies[:5]):
        name = cookie.get('name', 'N/A')
        value = cookie.get('value', '')[:30]
        domain = cookie.get('domain', 'N/A')
        print(f"   {i + 1}. [{domain}] {name} = {value}...")

    print("\n" + "=" * 70)
    print("🎉 登录态备份完成！后续爬虫和自动投递将自动使用此 Cookie。")
    print("   Cookie 有效期与你浏览器中的登录态一致（通常数月）。")
    print("   过期后只需在浏览器中重新登录 51job，再运行此脚本即可。")
    print("=" * 70)


if __name__ == "__main__":
    harvest_51job_cookies()
