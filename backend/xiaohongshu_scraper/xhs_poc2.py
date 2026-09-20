import time
import os
import urllib.parse
from DrissionPage import ChromiumPage, ChromiumOptions

def setup_browser():
    port = 9224
    co = ChromiumOptions()
    co.set_local_port(port)
    
    user_data_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "xhs_userdata"))
    os.makedirs(user_data_path, exist_ok=True)
    co.set_user_data_path(user_data_path)
    co.set_argument('--disable-blink-features=AutomationControlled')
    
    mac_edge_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)
        
    try:
        return ChromiumPage(co)
    except Exception as e:
        print(f"❌ 启动浏览器失败: {e}")
        return None

def run_poc():
    page = setup_browser()
    if not page:
        return
        
    try:
        # 直接跳转到搜索页
        keyword = "前端 招聘"
        encoded_kw = urllib.parse.quote(keyword)
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={encoded_kw}&source=web_search_result_notes"
        
        print(f"🌐 正在直接访问搜索页面: {search_url}")
        page.get(search_url)
        
        print("⏳ 等待 15 秒，如果有登录弹窗请扫码，如果遇到滑块请手动滑过...")
        time.sleep(15)
        
        print(f"📍 当前页面 URL: {page.url}")
        
        print("📜 尝试解析搜索结果瀑布流...")
        # 寻找小红书瀑布流的笔记 section
        # 小红书笔记项通常是 section 标签
        note_items = page.eles('tag:section', timeout=5)
        
        print(f"✅ 找到 {len(note_items)} 篇相关笔记！")
        
        if note_items:
            print("🖱️ 尝试随机点击第一篇笔记...")
            note_items[0].scroll.to_see()
            time.sleep(1)
            note_items[0].click()
            
            print("⏳ 等待弹窗加载...")
            time.sleep(4)
            
            # 小红书正文通常在 .note-content, .desc, h1, #detail-title 等类名中
            title = page.ele('#detail-title', timeout=3) or page.ele('tag:h1', timeout=3) or page.ele('.title', timeout=3)
            content = page.ele('#detail-desc', timeout=3) or page.ele('.note-text', timeout=3) or page.ele('.desc', timeout=3)
            
            print("\n===============================")
            print(f"📝 标题: {title.text if title else '未找到标题'}")
            print(f"📄 正文: {content.text if content else '未找到正文'}")
            print("===============================\n")
            
            close_btn = page.ele('.close-circle', timeout=2) or page.ele('.close', timeout=2) or page.ele('css:.close-box', timeout=2)
            if close_btn:
                print("🖱️ 关闭详情弹窗...")
                close_btn.click()
                time.sleep(2)
        else:
            print("❌ 未能找到笔记列表。请检查当前页面是否被重定向到首页或遭遇了人机验证。")
            
    except Exception as e:
        print(f"❌ 运行过程中出现异常错误: {e}")

if __name__ == "__main__":
    run_poc()
