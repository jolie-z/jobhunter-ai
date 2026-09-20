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

def _extract_images(page):
    images = page.eles('css:.media-container img') or page.eles('css:.swiper-slide img') or page.eles('tag:img')
    image_urls = []
    for img in images:
        src = img.attr('src')
        if src and ('sns-webpic' in src or 'ci.xiaohongshu.com' in src or 'spectrum' in src or not src.startswith('data:')):
            if src not in image_urls:
                image_urls.append(src)
    return image_urls

def _process_first_note(page, note_items):
    print("🖱️ 尝试点击第一篇笔记...")
    note_items[0].scroll.to_see()
    time.sleep(1)
    note_items[0].click()
    
    print("⏳ 等待弹窗和图片加载...")
    time.sleep(4)
    
    title = page.ele('#detail-title', timeout=3) or page.ele('tag:h1', timeout=3) or page.ele('.title', timeout=3)
    content = page.ele('#detail-desc', timeout=3) or page.ele('.note-text', timeout=3) or page.ele('.desc', timeout=3)
    
    image_urls = _extract_images(page)
    
    print("\n===============================")
    print(f"📝 标题: {title.text if title else '未找到标题'}")
    print(f"📄 正文: {content.text if content else '未找到正文'}")
    print(f"🖼️ 提取到的相关图片 URL (共 {len(image_urls)} 张):")
    for idx, url in enumerate(image_urls, 1):
        print(f"  [{idx}] {url}")
    print("===============================\n")
    
    close_btn = page.ele('.close-circle', timeout=2) or page.ele('.close', timeout=2) or page.ele('css:.close-box', timeout=2)
    if close_btn:
        close_btn.click()
        time.sleep(1)


def run_poc():
    page = setup_browser()
    if not page:
        return
        
    try:
        keyword = "前端 招聘"
        encoded_kw = urllib.parse.quote(keyword)
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={encoded_kw}&source=web_search_result_notes"
        
        print(f"🌐 正在访问搜索页面: {search_url}")
        page.get(search_url)
        
        time.sleep(5) # 给点时间加载
        
        note_items = page.eles('tag:section', timeout=5)
        
        if note_items:
            _process_first_note(page, note_items)
        else:
            print("❌ 未能找到笔记列表。")
            
    except Exception as e:
        print(f"❌ 运行过程中出现异常错误: {e}")

if __name__ == "__main__":
    run_poc()
