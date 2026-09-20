import time
import os
import random
from DrissionPage import ChromiumPage, ChromiumOptions

def setup_browser():
    print("⚙️ 初始化浏览器配置...")
    # 使用 9224 端口，避免和 Boss 直聘的 9223 冲突
    port = 9224
    
    co = ChromiumOptions()
    co.set_local_port(port)
    
    # 设置一个独立的用户数据目录，确保每次登录态独立，防止污染日常数据
    user_data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "xhs_userdata"))
    os.makedirs(user_data_path, exist_ok=True)
    co.set_user_data_path(user_data_path)
    
    # 规避一部分无头特征
    co.set_argument('--disable-blink-features=AutomationControlled')
    
    # Mac 上 Edge 的默认路径
    mac_edge_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)
    else:
        print("⚠️ 未找到 Edge 默认路径，将尝试使用系统默认的 Chromium 内核浏览器。")
        
    try:
        page = ChromiumPage(co)
        return page
    except Exception as e:
        print(f"❌ 启动浏览器失败: {e}")
        return None

def _wait_for_login():
    print("⏳ 等待 20 秒，请在弹出的浏览器中确认是否需要扫码登录...")
    print("⏳ (如果已经处于登录状态，请耐心等待)")
    for i in range(20, 0, -1):
        print(f"   倒计时: {i} 秒...", end="\r")
        time.sleep(1)
    print("\n")


def _perform_search(page, keyword):
    print(f"🔍 尝试在首页搜索关键词: '{keyword}'...")
    
    # 寻找搜索框
    search_box = page.ele('@placeholder=搜索小红书', timeout=5)
    if not search_box:
        search_box = page.ele('.search-input', timeout=5)
        
    if not search_box:
        print("❌ 未能找到搜索框。可能是由于未登录被强行拦截在登录页，或者是页面DOM结构与预期不同。")
        return False
        
    search_box.clear()
    search_box.input(keyword)
    # 点击搜索按钮或回车
    search_btn = page.ele('.search-icon', timeout=2)
    if search_btn:
        search_btn.click()
    else:
        search_box.input('\n')
        
    print("⏳ 等待搜索结果加载 (5秒)...")
    time.sleep(5)
    return True


def _parse_and_click_first_note(page):
    print("📜 尝试解析搜索结果瀑布流...")
    # 找到笔记列表
    note_items = page.eles('.note-item')
    if not note_items:
        note_items = page.eles('tag:section')
        
    print(f"✅ 找到 {len(note_items)} 篇相关笔记！")
    
    if not note_items:
        return
        
    print("🖱️ 尝试随机点击第一篇笔记...")
    # 滑动到元素可见
    note_items[0].scroll.to_see()
    time.sleep(1)
    note_items[0].click()
    
    print("⏳ 等待弹窗加载...")
    time.sleep(4)
    
    # 尝试提取正文
    title = page.ele('.title', timeout=3) or page.ele('tag:h1', timeout=3)
    content = page.ele('.note-text', timeout=3) or page.ele('.desc', timeout=3)
    
    print("\n===============================")
    print(f"📝 标题: {title.text if title else '未找到标题'}")
    print(f"📄 正文: {content.text if content else '未找到正文'}")
    print("===============================\n")
    
    # 尝试关闭弹窗
    close_btn = page.ele('.close-circle', timeout=2) or page.ele('.close', timeout=2)
    if close_btn:
        print("🖱️ 关闭详情弹窗...")
        close_btn.click()
        time.sleep(2)


def run_poc():
    print("🚀 正在启动小红书实验性爬虫 (端口 9224)...")
    page = setup_browser()
    if not page:
        return
        
    try:
        print("🌐 正在访问小红书主页 (https://www.xiaohongshu.com/)...")
        page.get("https://www.xiaohongshu.com/")
        
        # 小红书可能会弹登录框，留出 20 秒给人工扫码登录
        _wait_for_login()
        
        if _perform_search(page, "前端 招聘"):
            _parse_and_click_first_note(page)
            
    except Exception as e:
        print(f"❌ 运行过程中出现异常错误: {e}")

if __name__ == "__main__":
    run_poc()
