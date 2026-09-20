"""
猎聘简历编辑器 - Edge 浏览器启动脚本

功能：
1. 在猎聘统一端口启动 Edge（持久化 profile，端口由全项目统一配置区 registry 提供）
2. 导航到猎聘简历页面
3. 等待用户手动登录
4. 登录完成后保持浏览器打开，供后续审计脚本连接

用法：
    python start_liepin_browser.py
"""

import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))

from DrissionPage import ChromiumPage, ChromiumOptions

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port, get_platform_profile

# 配置
PORT = get_platform_port("liepin")
# 🛡️ profile 统一走 registry（与主链路同一份登录态）；私有 profile 会与主链路抢端口、互不见登录
PROFILE_DIR = get_platform_profile("liepin")
LIEPIN_RESUME_URL = "https://c.liepin.com/resume/preview"
LIEPIN_LOGIN_URL = "https://www.liepin.com/"


def start_browser():
    """启动 Edge 浏览器并导航到猎聘"""
    print("=" * 60)
    print("  猎聘简历编辑器 - 浏览器启动")
    print("=" * 60)

    # 确保 profile 目录存在
    os.makedirs(PROFILE_DIR, exist_ok=True)
    print(f"\n  Profile 目录: {PROFILE_DIR}")
    print(f"  端口: {PORT}")

    # 配置浏览器
    co = ChromiumOptions()
    co.set_local_port(PORT)
    co.set_user_data_path(PROFILE_DIR)

    # macOS Edge 路径
    mac_edge_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)
        print(f"  浏览器: Microsoft Edge")
    else:
        print("  浏览器: 默认 Chrome/Chromium")

    # 启动浏览器
    print("\n  正在启动浏览器...")
    page = ChromiumPage(co)
    print("  浏览器已启动")

    # 先导航到猎聘首页（方便登录）
    print(f"\n  正在导航到猎聘首页...")
    page.get(LIEPIN_LOGIN_URL)
    time.sleep(2)

    print("\n" + "=" * 60)
    print("  请在浏览器中手动登录猎聘账号")
    print("  登录完成后，回到这里按 Enter 继续")
    print("=" * 60)

    # 等待用户登录
    input("\n  按 Enter 确认已登录...")

    # 检查登录状态
    print("\n  正在检查登录状态...")
    page.get(LIEPIN_RESUME_URL)
    time.sleep(3)

    # 简单检查是否登录成功
    current_url = page.url
    title = page.title
    print(f"  当前 URL: {current_url}")
    print(f"  页面标题: {title}")

    if "login" in current_url.lower() or "passport" in current_url.lower():
        print("\n  似乎还未登录成功，请在浏览器中完成登录后重试")
        print("  浏览器保持打开状态，你可以重新运行此脚本")
    else:
        print("\n  登录状态正常！")
        print(f"  浏览器保持打开，后续审计脚本将连接端口 {PORT}")

    print("\n  提示: 不要关闭浏览器窗口")
    print("  按 Ctrl+C 退出此脚本（浏览器会保持打开）")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n  脚本已退出，浏览器保持打开")


if __name__ == "__main__":
    start_browser()
