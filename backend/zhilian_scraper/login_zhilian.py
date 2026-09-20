import os
import sys
import time

sys.path.insert(0, os.path.abspath('backend'))
from DrissionPage import ChromiumPage, ChromiumOptions

def login():
    print("🚀 启动 DrissionPage (Edge)...")
    _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _backend_dir not in sys.path:
        sys.path.insert(0, _backend_dir)
    from app.session.registry import get_profile_path, get_platform_port

    port = get_platform_port("zhilian")
    co = ChromiumOptions().set_local_port(port)
    
    # 🌟 使用全系统唯一统一 Profile（与简历回写、会话大盘、投递引擎 100% 共享）
    profile_dir = get_profile_path("zhilian")
    os.makedirs(profile_dir, exist_ok=True)
    co.set_user_data_path(profile_dir)
    
    mac_edge_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)
    
    page = ChromiumPage(co)
    page.get('https://www.zhaopin.com/')
    
    print("================================================================")
    print("请在打开的浏览器窗口中，手动登录智联招聘。")
    print("登录成功后，请在此终端按回车键继续...")
    print("================================================================")
    
    input("👉 按回车键确认登录已完成: ")
    print("✅ 登录状态已保存到 Profile 中，现在可以运行自动投递脚本了！")

if __name__ == '__main__':
    login()
