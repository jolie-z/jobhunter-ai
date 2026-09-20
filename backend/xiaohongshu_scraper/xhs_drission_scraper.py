import os
import time
import json
import sqlite3
import random
import urllib.parse
import re
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions

# 项目根目录
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")

# 全局停止标志
_stop_flag = False

def set_stop_flag(flag: bool):
    global _stop_flag
    _stop_flag = flag

def push_sse_message(task_id: str, message: str, status: str = "running", loop=None):
    from app.tasks.state import task_queues
    if task_id in task_queues:
        data = {
            "type": "log",
            "platform": "xiaohongshu",
            "message": message,
            "status": status,
            "timestamp": datetime.now().isoformat()
        }
        msg = f'data: {json.dumps(data)}\n\n'
        if loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(task_queues[task_id].put(msg), loop)
        print(f"[{status.upper()}] 小红书爬虫: {message}")

def push_sse_progress(task_id: str, total_inserted: int, target_jobs: int, loop=None):
    from app.tasks.state import task_queues
    if task_id in task_queues:
        data = {
            "type": "progress",
            "platform": "xiaohongshu",
            "total_inserted": total_inserted,
            "target_jobs": target_jobs,
            "current_page": 1,
            "timestamp": datetime.now().isoformat()
        }
        msg = f'data: {json.dumps(data)}\n\n'
        if loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(task_queues[task_id].put(msg), loop)

def get_processed_note_ids():
    """从数据库读取已抓取的 note_id 列表，用于跨任务去重"""
    note_ids = set()
    try:
        if not os.path.exists(DB_PATH):
            return note_ids
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='xhs_raw_posts'")
        if not cursor.fetchone():
            return note_ids
            
        cursor.execute("SELECT post_link FROM xhs_raw_posts")
        rows = cursor.fetchall()
        for row in rows:
            link = row[0]
            if link:
                match = re.search(r'/(?:explore|search_result)/([a-zA-Z0-9]{24})', link)
                if match:
                    note_ids.add(match.group(1))
        conn.close()
    except Exception as e:
        print(f"❌ 获取已处理笔记 ID 失败: {e}")
    return note_ids

def setup_browser():
    port = 9224
    co = ChromiumOptions()
    co.set_local_port(port)
    
    user_data_path = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "profiles", "xiaohongshu"))
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

def normalize_publish_date(date_str: str) -> str:
    """归一化发布日期，将 1天前, 05-11 转换为 YYYY-MM-DD"""
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")
        
    date_str = date_str.strip()
    now = datetime.now()
    
    if "今天" in date_str or "小时" in date_str or "分钟" in date_str or "秒" in date_str or "刚刚" in date_str:
        return now.strftime("%Y-%m-%d")
        
    if "昨天" in date_str:
        from datetime import timedelta
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
        
    # 匹配 "X天前"
    match = re.search(r'(\d+)天前', date_str)
    if match:
        days = int(match.group(1))
        from datetime import timedelta
        return (now - timedelta(days=days)).strftime("%Y-%m-%d")
        
    # 匹配 "MM-DD"
    match = re.search(r'^(\d{1,2})-(\d{1,2})$', date_str)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        # 简单处理跨年问题：如果月份大于当前月份，可能是去年
        year = now.year if month <= now.month else now.year - 1
        return f"{year}-{month:02d}-{day:02d}"
        
    # 匹配 "YYYY-MM-DD"
    match = re.search(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', date_str)
    if match:
        return date_str
        
    return now.strftime("%Y-%m-%d")

def save_raw_post(note_id, post_link, account_name, raw_text, image_urls, publish_date=""):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO xhs_raw_posts 
            (post_link, account_name, raw_text, image_urls, video_urls, crawl_time, clean_status, publish_date, note_id)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
        ''', (
            post_link,
            account_name,
            raw_text,
            json.dumps(image_urls, ensure_ascii=False),
            "[]",  # video_urls 暂缓
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            publish_date,
            note_id
        ))
        conn.commit()
    except Exception as e:
        print(f"写入数据库失败: {e}")
    finally:
        conn.close()

def _get_sort_btn_text(actual_sort: str) -> str:
    if actual_sort == "time_descending":
        return "最新"
    if actual_sort == "popularity_descending":
        return "最热"
    return "综合"

def _switch_sort_mode(page, actual_sort, sse_task_id, loop):
    try:
        sort_btn_text = _get_sort_btn_text(actual_sort)
        if sort_btn_text != "综合":
            filter_btn = page.ele('text:筛选', timeout=5)
            if filter_btn:
                filter_btn.hover()
                time.sleep(1)
                btn = page.ele(f'text:{sort_btn_text}', timeout=3)
                if btn:
                    btn.click()
                    push_sse_message(sse_task_id, f"✨ 已成功切换至【{sort_btn_text}】排序模式", loop=loop)
                    time.sleep(4)
                else:
                    push_sse_message(sse_task_id, f"⚠️ 展开筛选菜单后未找到【{sort_btn_text}】选项", loop=loop)
            else:
                push_sse_message(sse_task_id, "⚠️ 未能在页面上找到【筛选】悬浮菜单，采用默认排序", loop=loop)
    except Exception as e:
        push_sse_message(sse_task_id, f"⚠️ 切换【{sort_btn_text}】排序时发生异常: {e}", loop=loop)

def _extract_images_from_note(page):
    images = page.eles('css:.media-container img') or page.eles('css:.swiper-slide img') or page.eles('tag:img')
    image_urls = []
    for img in images:
        src = img.attr('src')
        if src and ('sns-webpic' in src or 'ci.xiaohongshu.com' in src or 'spectrum' in src):
            if src not in image_urls:
                image_urls.append(src)
    return image_urls

def _parse_and_save_note(item, page, sse_task_id, loop, post_link, note_id, account_name, publish_date, crawled_count, target_jobs) -> int:
    """进入详情页，解析数据，关闭弹窗，返回新增的爬取数量(1或0)"""
    try:
        item.scroll.to_see()
        time.sleep(0.5)
        item.click()
        
        time.sleep(3) # 等待弹窗和图片加载
        
        title_ele = page.ele('#detail-title', timeout=2) or page.ele('tag:h1', timeout=2) or page.ele('.title', timeout=2)
        content_ele = page.ele('#detail-desc', timeout=2) or page.ele('.note-text', timeout=2) or page.ele('.desc', timeout=2)
        
        title_text = title_ele.text if title_ele else ""
        content_text = content_ele.text if content_ele else ""
        raw_text = f"【标题】{title_text}\n【正文】{content_text}"
        
        image_urls = _extract_images_from_note(page)
                    
        if title_text or content_text or image_urls:
            normalized_date = normalize_publish_date(publish_date)
            save_raw_post(note_id, post_link, account_name, raw_text, image_urls, normalized_date)
            new_count = crawled_count + 1
            push_sse_progress(sse_task_id, new_count, target_jobs, loop=loop)
            push_sse_message(sse_task_id, f"✅ 成功提取 ({len(image_urls)}张图片)，当前进度 {new_count}/{target_jobs}", loop=loop)
            return 1
            
        push_sse_message(sse_task_id, "⚠️ 数据提取为空，跳过此笔记", loop=loop)
        return 0
    except Exception as e:
        print(f"❌ 解析笔记详情失败: {e}")
        push_sse_message(sse_task_id, f"❌ 解析报错: {str(e)[:50]}", "error", loop=loop)
        return 0
    finally:
        close_btn = page.ele('.close-circle', timeout=2) or page.ele('.close', timeout=2) or page.ele('css:.close-box', timeout=2)
        if close_btn:
            close_btn.click()
            time.sleep(1)

def _extract_note_info(item):
    """提取单条笔记的基础信息，返回 (href, account_name, publish_date)"""
    link_ele = item.ele('css:a.title', timeout=1) or item.ele('css:a.cover', timeout=1) or item.ele('tag:a', timeout=1)
    if not link_ele:
        return None, None, None
    
    href = link_ele.attr('href')
    if not href:
        return None, None, None
        
    author_ele = item.ele('.author', timeout=1) or item.ele('.name', timeout=1)
    account_name = author_ele.text if author_ele else "未知作者"
    
    time_ele = item.ele('.time', timeout=1)
    publish_date = time_ele.text if time_ele else ""
    
    return href, account_name, publish_date

def _check_and_handle_duplicate(href, processed_links, session_skipped_ids, sse_task_id, loop):
    """检查是否是重复笔记，返回 (is_duplicate, note_id, post_link)"""
    match = re.search(r'/(?:explore|search_result)/([a-zA-Z0-9]{24})', href)
    if not match:
        return True, None, None
    
    note_id = match.group(1)
    post_link = f"https://www.xiaohongshu.com{href}" if href.startswith('/') else href
        
    if note_id in processed_links:
        if note_id not in session_skipped_ids:
            push_sse_message(sse_task_id, f"⏭️ 发现重复笔记 (ID:{note_id[:6]})... 直接跳过拦截", loop=loop)
            session_skipped_ids.add(note_id)
        return True, note_id, post_link
        
    return False, note_id, post_link

def _process_note_items(note_items, page, sse_task_id, loop, processed_links, session_skipped_ids, crawled_count, target_jobs):
    processed_any = False
    for item in note_items:
        if _stop_flag or crawled_count >= target_jobs:
            break
            
        href, account_name, publish_date = _extract_note_info(item)
        if not href:
            continue
            
        is_duplicate, note_id, post_link = _check_and_handle_duplicate(href, processed_links, session_skipped_ids, sse_task_id, loop)
        if is_duplicate:
            continue
            
        processed_links.add(note_id)
        processed_any = True
        
        push_sse_message(sse_task_id, f"🖱️ 正在抓取第 {crawled_count + 1} 篇笔记: {account_name} ({publish_date})", loop=loop)
        
        added = _parse_and_save_note(item, page, sse_task_id, loop, post_link, note_id, account_name, publish_date, crawled_count, target_jobs)
        crawled_count += added
        
        break
    
    return processed_any, crawled_count

def process_xhs_scraping_request(keyword: str, target_jobs: int = 10, sse_task_id: str = None, loop=None, sort_by: str = "general"):
    set_stop_flag(False)
    
    print(f"\n{'='*50}")
    print(f"🕵️ [DEBUG] 小红书请求已进入执行中枢！参数: 关键词={keyword}, 目标数量={target_jobs}, 排序={sort_by}")
    
    push_sse_message(sse_task_id, "🚀 开始启动小红书真机爬虫...", loop=loop)
    
    sort_labels = {
        "general": "综合",
        "time_descending": "最新",
        "popularity_descending": "最热(最多点赞/收藏/评论)",
        "collects_descending": "最多收藏(内部映射为最热)",
        "comments_descending": "最多评论(内部映射为最热)"
    }
    label = sort_labels.get(sort_by, "综合")
    push_sse_message(sse_task_id, f"📋 搜索关键词: {keyword}, 目标数量: {target_jobs}, 排序方式: {label}", loop=loop)
    
    actual_sort = "popularity_descending" if sort_by in ["collects_descending", "comments_descending"] else sort_by

    processed_links = get_processed_note_ids()
    push_sse_message(sse_task_id, f"🛡️ 去重机制: 已从数据库加载 {len(processed_links)} 条历史记录，遇到将自动跳过", loop=loop)
    
    page = setup_browser()
    if not page:
        push_sse_message(sse_task_id, "❌ 浏览器连接失败，请确保端口 9224 处于调试模式", "error", loop=loop)
        return

    try:
        encoded_kw = urllib.parse.quote(keyword)
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={encoded_kw}&source=web_search_result_notes&sort={actual_sort}"
        
        push_sse_message(sse_task_id, f"🌐 正在跳转到搜索页面 (按{label}排序)...", loop=loop)
        page.get(search_url)
        time.sleep(3)
        
        _switch_sort_mode(page, actual_sort, sse_task_id, loop)
            
        crawled_count = 0
        session_skipped_ids = set()
        
        while crawled_count < target_jobs and not _stop_flag:
            note_items = page.eles('tag:section')
            
            if not note_items:
                push_sse_message(sse_task_id, "⚠️ 未检测到笔记列表，可能遇到了风控或网络延迟，尝试向下滚动...", loop=loop)
                page.scroll.down(500)
                time.sleep(3)
                continue
                
            processed_any, crawled_count = _process_note_items(
                note_items, page, sse_task_id, loop, processed_links, session_skipped_ids, crawled_count, target_jobs
            )
            
            if not processed_any and not _stop_flag and crawled_count < target_jobs:
                push_sse_message(sse_task_id, "📜 正在向下滚动加载更多笔记...", loop=loop)
                page.scroll.down(800)
                time.sleep(3)
                
    except Exception as e:
        push_sse_message(sse_task_id, f"❌ 严重错误: {str(e)}", "error", loop=loop)
    finally:
        if _stop_flag:
            push_sse_message(sse_task_id, "🛑 抓取任务已手动终止", loop=loop)
        else:
            push_sse_message(sse_task_id, f"🎉 小红书抓取完成！共入库 {crawled_count} 篇原始笔记。等待多模态大模型进行异步清洗...", loop=loop)
