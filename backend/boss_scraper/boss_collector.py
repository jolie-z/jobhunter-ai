#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import random
import sqlite3
import argparse
from datetime import datetime
import subprocess

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from DrissionPage import ChromiumPage, ChromiumOptions

from engine_guard import verify_browser_identity

BOSS_DEBUG_PORT = 19222
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'job_hunter.db')
PROFILE_DIR = os.path.join(PROJECT_ROOT, "data", "profiles", "boss")
os.makedirs(PROFILE_DIR, exist_ok=True)

# ==========================================
# 浏览器初始化（配置本地持久化环境）
# ==========================================
_co = ChromiumOptions()
_co.set_local_port(BOSS_DEBUG_PORT)

edge_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
if os.path.exists(edge_path):
    _co.set_browser_path(edge_path)

_co.set_user_data_path(PROFILE_DIR)
_co.set_argument('--disable-blink-features=AutomationControlled')
_co.set_argument('--disable-dev-shm-usage')
_co.set_argument('--disable-gpu')
_co.set_pref('credentials_enable_service', False)

_page = None

def get_browser_page():
    """安全地获取或重启浏览器实例，复用投递模块的浏览器"""
    global _page
    if _page is not None:
        try:
            if not _page.is_stopped:
                return _page
        except Exception:
            pass

    # 🛡️ 环境守卫（Q24）：端口占用者身份校验——守卫通过前连 /json/new 兜底都不许发
    ok, guard_reason = verify_browser_identity(BOSS_DEBUG_PORT, PROFILE_DIR, platform="boss")
    if not ok:
        print(f"   ⛔ [环境守卫] 拒绝连接浏览器：{guard_reason}")
        sys.exit(1)

    # 🌟 兜底保障：探测 19222 是否存在活跃标签页，若为 0 则通过 /json/new 建立默认页
    try:
        import requests
        r = requests.get(f"http://127.0.0.1:{BOSS_DEBUG_PORT}/json", proxies={"http": None, "https": None}, timeout=1).json()
        page_tabs = [t for t in r if t.get("type") == "page"]
        if not page_tabs:
            requests.put(f"http://127.0.0.1:{BOSS_DEBUG_PORT}/json/new?https://www.zhipin.com", proxies={"http": None, "https": None}, timeout=2)
    except Exception:
        pass

    lock_file = os.path.join(PROFILE_DIR, 'SingletonLock')
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
        except Exception:
            pass

    try:
        _page = ChromiumPage(_co)
        return _page
    except Exception as e:
        print(f"   ⚠️ 浏览器连接失败，请检查 Edge 浏览器是否已开启调试端口 19222！错误详情：{e}")
        sys.exit(1)

def check_job_exists(company_name, job_title, city, job_link=None):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        
        if job_link:
            cursor.execute('''
                SELECT 1 FROM raw_jobs 
                WHERE job_link = ? OR (company_name = ? AND job_title = ? AND city = ?)
            ''', (job_link, company_name, job_title, city))
        else:
            cursor.execute('''
                SELECT 1 FROM raw_jobs 
                WHERE company_name = ? AND job_title = ? AND city = ?
            ''', (company_name, job_title, city))
            
        res = cursor.fetchone()
        conn.close()
        return res is not None
    except Exception as e:
        print(f"Check DB Error: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def save_single_job_to_db(job_data):
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT OR IGNORE INTO raw_jobs (
                job_link, job_title, company_name, city, jd_text, 
                salary, work_address, hr_activity, industry, welfare_tags, 
                company_size, education_req, experience_req, hr_skill_tags, 
                company_intro, role, publish_date, platform, crawl_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_data.get('job_link', ''), job_data.get('job_title', ''),
            job_data.get('company_name', ''), job_data.get('city', ''),
            job_data.get('jd_text', ''), job_data.get('salary', ''),
            job_data.get('work_address', ''), job_data.get('hr_activity', ''),
            job_data.get('industry', ''), job_data.get('welfare_tags', ''),
            job_data.get('company_size', ''), job_data.get('education_req', ''),
            job_data.get('experience_req', ''), job_data.get('hr_skill_tags', ''),
            job_data.get('company_intro', ''), job_data.get('role', ''),          
            job_data.get('publish_date', ''), 'BOSS直聘', current_time                           
        ))
        inserted = cursor.rowcount > 0 
        conn.commit()
        return inserted
    except Exception as e:
        print(f"      ❌ 数据库写入出错: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def _handle_security_captcha(page):
    """处理 BOSS 安全滑块"""
    captcha_ele = page.ele('css:#nc_1_n1z', timeout=2)
    if not captcha_ele:
        captcha_ele = page.ele('text:安全验证', timeout=1)

    if captcha_ele:
        print("\n⚠️ 触发了 BOSS 安全验证！")
        print("⏳ 脚本已暂停，请在浏览器中【手动拖动滑块】...")
        page.wait.ele_deleted('css:#nc_1_n1z', timeout=60)

def _ensure_logged_in(page, url):
    """检查登录状态，如未登录则推送飞书通知并等待扫码；超时优雅终止，不再无限挂起"""
    import time
    is_logged_in = page.ele('css:.user-nav', timeout=2) or page.ele('text:退出登录', timeout=2)
    if not is_logged_in:
        wait_s = int(os.environ.get("BOSS_LOGIN_WAIT_S", "300"))
        alert_msg = f"🚨【BOSS直聘】登录态已失效或未登录！已自动唤起浏览器（端口 19222），请在 {max(1, wait_s // 60)} 分钟内完成扫码登录！"
        print(f"\n⚠️ {alert_msg}")
        
        # 尝试推送飞书告警
        try:
            from app.automation.pipeline_report import send_pipeline_report
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(send_pipeline_report(alert_msg))
                else:
                    loop.run_until_complete(send_pipeline_report(alert_msg))
            except RuntimeError:
                asyncio.run(send_pipeline_report(alert_msg))
        except Exception as fe:
            print(f"   ⚠️ 飞书告警推送异常（降级打印）: {fe}")

        deadline = time.monotonic() + wait_s
        logged_in = False
        while time.monotonic() < deadline:
            time.sleep(3)
            if page.ele('css:.user-nav', timeout=1) or page.ele('text:退出登录', timeout=1):
                print("🎉 扫码成功，登录态已恢复！")
                try:
                    from app.automation.pipeline_report import send_pipeline_report
                    import asyncio
                    asyncio.run(send_pipeline_report("🎉【BOSS直聘】扫码登录成功，已自动恢复抓取流程！"))
                except Exception:
                    pass
                logged_in = True
                break
        if not logged_in:
            raise RuntimeError(f"BOSS 登录等待超时（{wait_s} 秒），本次任务跳过 BOSS直聘")
        page.get(url)
        time.sleep(3)
        _handle_security_captcha(page)

def _extract_search_total(zp_data):
    """从 BOSS joblist.json 的 zpData 节点提取搜索总数（分母），候选键兜底。"""
    try:
        for key in ('totalCount', 'total', 'totalNum', 'count', 'jobCount'):
            val = zp_data.get(key)
            if isinstance(val, int) and val > 0:
                return val
            if isinstance(val, str) and val.isdigit() and int(val) > 0:
                return int(val)
        return 0
    except Exception:
        return 0

def _extract_json_job_map(page):
    """解析截获的所有 API 响应，提取额外数据（行业、规模、福利、技能等）；顺带捕获搜索总数（分母）"""
    json_job_map = {}
    search_total = 0
    import json
    for packet in page.listen.steps(timeout=0.5):
        try:
            body = packet.response.body
            if isinstance(body, dict) and 'zpData' in body:
                zp = body['zpData']
                job_list = zp.get('jobList', [])
                for job in job_list:
                    jid = job.get('encryptJobId')
                    if jid:
                        json_job_map[jid] = job
                _total = _extract_search_total(zp)
                if _total > search_total:
                    search_total = _total
        except Exception:
            pass
    return json_job_map, search_total

def _parse_job_salary(raw_salary, default_salary, json_job):
    """解析并返回真实的薪资，处理加密和 JSON 备用逻辑"""
    if json_job and json_job.get('salaryDesc'):
        return json_job.get('salaryDesc')
    is_encrypted = any(0xE000 <= ord(c) <= 0xF8FF for c in raw_salary)
    if is_encrypted:
        return default_salary if default_salary and default_salary != "不限" else "[加密薪资]"
    return raw_salary

def _extract_clean_jd(detail_box):
    """从详情容器中提取并清洗职位描述(JD)的水印"""
    jd_ele = detail_box.ele('css:.job-detail-body .desc', timeout=2)
    if jd_ele and jd_ele.text:
        return jd_ele.text.replace('kanzhun', '').replace('BOSS直聘', '').replace('BOSS', '').replace('boss', '').replace('来自', '').replace('直聘', '')
    return ""

def _get_fallback_address(detail_box, job_city, json_job):
    """提取兜底的地区信息"""
    district = json_job.get('areaDistrict', '')
    business = json_job.get('businessDistrict', '')
    if district or business:
        return f"{job_city} {district} {business}".strip()
    address_ele = detail_box.ele('css:.job-detail-header .tag-list li:first-child', timeout=1)
    return address_ele.text if address_ele else job_city

def _try_fetch_loc_address(detail_box):
    """单次尝试提取具体门牌号"""
    loc_address_ele = detail_box.ele('css:.location-address', timeout=0.5)
    if not loc_address_ele:
        loc_address_ele = detail_box.ele('css:.job-address', timeout=0.5)
    if loc_address_ele and loc_address_ele.text and loc_address_ele.text.strip():
        addr = loc_address_ele.text.strip()
        addr = addr.replace('工作地址', '').replace('点击查看地图', '')
        return ' '.join(addr.split())
    return ""

def _extract_work_address(detail_box, job_city, json_job):
    """尝试获取具体工作地址，自带重试机制"""
    import time
    for _ in range(8):
        addr = _try_fetch_loc_address(detail_box)
        if addr:
            return addr
        time.sleep(0.5)
    return _get_fallback_address(detail_box, job_city, json_job)

def _extract_basic_card_info(card, city):
    """提取卡片外层的基本信息字段"""
    job_name_ele = card.ele('css:.job-name', timeout=1)
    company_name_ele = card.ele('css:.boss-name', timeout=1)
    salary_ele = card.ele('css:.job-salary', timeout=1)
    city_ele = card.ele('css:.company-location', timeout=1)
    
    job_link = job_name_ele.attr('href') if job_name_ele else ""
    if job_link and job_link.startswith("/"):
        job_link = "https://www.zhipin.com" + job_link
    if "?" in job_link:
        job_link = job_link.split("?")[0]
        
    tag_eles = card.eles('css:.tag-list li')
    tags = [t.text for t in tag_eles]
    
    return {
        'job_title': job_name_ele.text if job_name_ele else '未知岗位',
        'company_name': company_name_ele.text if company_name_ele else '未知公司',
        'raw_salary': salary_ele.text if salary_ele else '未知薪资',
        'job_city': city_ele.text if city_ele else city,
        'job_link': job_link,
        'exp_req': tags[0] if len(tags) > 0 else "",
        'edu_req': tags[1] if len(tags) > 1 else ""
    }

def _process_job_card(page, card, json_job_map, city, salary, index, total_cards):
    """处理单个岗位卡片，并保存到数据库"""
    import re
    import time
    import random
    
    info = _extract_basic_card_info(card, city)
    job_id_match = ""
    m = re.search(r'/job_detail/([^.]+)\.html', info['job_link'])
    if m:
        job_id_match = m.group(1)
        
    json_job = json_job_map.get(job_id_match, {})
    job_salary = _parse_job_salary(info['raw_salary'], salary, json_job)
    
    if check_job_exists(info['company_name'], info['job_title'], info['job_city'], info['job_link']):
        print(f"   ⏩ [拦截] [{index}/{total_cards}] {info['company_name']} - {info['job_title']} | 数据库已存在，跳过！")
        return "skipped"
    
    print(f"   🔍 [{index}/{total_cards}] 正在抓取详情: {info['company_name']} - {info['job_title']}")
    
    card.click()
    time.sleep(random.uniform(2, 4))
    _handle_security_captcha(page)
    
    detail_box = page.ele('css:.job-detail-box', timeout=5)
    if not detail_box:
        print("      ⚠️ 详情页加载失败，跳过。")
        return "error"

    jd_text = _extract_clean_jd(detail_box)
    work_address = _extract_work_address(detail_box, info['job_city'], json_job)
    
    active_ele = detail_box.ele('css:.boss-active-time', timeout=1)
    
    job_data = {
        'job_link': info['job_link'],
        'job_title': info['job_title'], 
        'company_name': info['company_name'], 
        'city': info['job_city'],
        'jd_text': jd_text, 
        'salary': job_salary, 
        'work_address': work_address,
        'hr_activity': active_ele.text if active_ele else "", 
        'industry': json_job.get('brandIndustry', ''),
        'welfare_tags': ','.join(json_job.get('welfareList', [])), 
        'company_size': json_job.get('brandScaleName', ''),
        'education_req': info['edu_req'],
        'experience_req': info['exp_req'],
        'hr_skill_tags': ','.join(json_job.get('skills', [])), 
        'company_intro': '', 
        'role': '', 
        'publish_date': '',
    }
    
    if save_single_job_to_db(job_data):
        print(f"   🕷️ [抓取成功] 🏢 {info['company_name']} | 💼 {info['job_title']} | 💰 {job_salary}")
        res = "success"
    else:
        print(f"   ⚠️ [数据已存在] 🏢 {info['company_name']} | {info['job_title']} (链接已存在，跳过)")
        res = "exist"

    time.sleep(random.uniform(3, 8))
    return res

def _build_search_url(keyword, city, salary):
    """构建 Boss 直聘搜索 URL"""
    import urllib.parse
    from boss_scraper.boss_cli.constants import CITY_CODES, SALARY_CODES
    
    base_url = "https://www.zhipin.com/web/geek/jobs"
    query_params = {"query": keyword}
    
    if city and city != "全国":
        query_params["city"] = CITY_CODES.get(city, city)
            
    if salary:
        salary_code = SALARY_CODES.get(salary)
        if salary_code:
            query_params["salary"] = salary_code
        
    return f"{base_url}?{urllib.parse.urlencode(query_params)}"

def _scroll_and_get_cards(page, target_page):
    """执行瀑布流滚动并截取目标页的卡片数据（带断连与加载重试保护）"""
    import time
    import random
    
    if target_page > 1:
        print(f"🔄 检测到 Boss 瀑布流机制，正在向下滚动 {target_page - 1} 次以加载数据...")
        for _ in range(target_page - 1):
            try:
                page.scroll.to_bottom()
                time.sleep(random.uniform(2, 3))
            except Exception as e:
                print(f"   ⚠️ 滚动页面遇到瞬时抖动: {e}，等待重试...")
                time.sleep(1.5)

    job_cards = None
    for attempt in range(1, 4):
        try:
            # 确保 DOM 稳定加载
            try:
                page.wait.doc_loaded(timeout=3)
            except Exception:
                pass
            job_cards = page.eles('css:.job-card-wrap')
            if job_cards:
                break
            time.sleep(1.5)
        except Exception as e:
            print(f"   ⚠️ [第 {attempt}/3 次] 获取卡片遇到页面连接断开或抖动: {e}，稍候重试...")
            time.sleep(2)
            try:
                page = get_browser_page()
            except Exception:
                pass

    if not job_cards:
        return []
        
    start_index = (target_page - 1) * 30
    current_page_cards = job_cards[start_index:]
    if not current_page_cards:
        current_page_cards = job_cards[-30:] if len(job_cards) > 30 else job_cards
        
    return current_page_cards

def collect_single_page(keyword, city, salary, target_page, target_count=0):
    """
    🌟 DrissionPage 版本的抓取引擎
    """
    import time
    import random
    
    print(f"\n{'='*50}")
    
    search_terms = [t for t in [city, keyword, salary] if t]
    full_query_str = "-".join(search_terms)
    
    print(f"📍 正在基于 DrissionPage 抓取【{full_query_str}】的第 {target_page} 页数据...")
    
    page = get_browser_page()
    url = _build_search_url(keyword, city, salary)
    
    try:
        page.listen.start('wapi/zpgeek/search/joblist.json')
    except Exception:
        pass

    page.get(url)
    try:
        page.wait.doc_loaded(timeout=5)
    except Exception:
        pass
    time.sleep(random.uniform(3, 5))
    
    _handle_security_captcha(page)
    _ensure_logged_in(page, url)

    current_page_cards = _scroll_and_get_cards(page, target_page)
    if not current_page_cards:
        print(f"⚠️ 第 {target_page} 页无数据返回，可能已到底部。")
        return

    print(f"✅ 成功锁定本页的 {len(current_page_cards)} 个岗位。")
    
    json_job_map, search_total = _extract_json_job_map(page)
    print(f"📡 成功解析 {len(json_job_map)} 个底层 JSON 岗位数据用于字段扩充。")

    # 解析搜索总数（分母）：拿不到不打印（上层走兜底规则）
    if search_total and search_total > 0:
        print(f"搜索总数 {search_total} 个")
    
    success_count = 0
    skip_count = 0
    total_cards = len(current_page_cards)
    
    for i, card in enumerate(current_page_cards):
        if target_count > 0 and success_count >= target_count:
            print(f"\n🎯 已达到本页的目标入库数量限制 ({target_count} 个)，提前结束本页抓取。")
            break
            
        try:
            status = _process_job_card(page, card, json_job_map, city, salary, i+1, total_cards)
            if status == "success":
                success_count += 1
            elif status == "skipped":
                skip_count += 1
        except Exception as e:
            print(f"      ❌ 解析卡片出错: {e}")
            continue
            
    print(f"🎯 第 {target_page} 页处理完毕。新增入库 {success_count} 个，跳过 {skip_count} 个。")
    print(f"新增入库 {success_count} 个")

def start_auto_patrol(target_page, platform="boss", keyword=None, city=None, salary=None, target_count=0):
    print(f"🚀 启动 [{platform}] 精准采集矩阵 | 当前锁定页码: P{target_page}")
    
    if platform != "boss" and platform != "boss直聘":
        print(f"⚠️ 注意：[{platform}] 平台暂不支持。")
        return

    if not keyword:
        print("❌ 错误：缺少搜索关键词。请在调度器或命令行中传入 keyword 参数。")
        return

    print(f"🎯 使用调度器传入的搜索条件：keyword={keyword}, city={city}, salary={salary}, target_count={target_count}")
    collect_single_page(keyword, city or '', salary or '', target_page, target_count)
    print("\n🏁 本次手动页面抓取指令已全部执行完毕！程序退出。")
    print("\n🏁 本次自动巡逻抓取指令已全部执行完毕！程序退出。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多平台半自动单页采集器")
    parser.add_argument('--platform', type=str, default='boss', help="指定目标平台")
    parser.add_argument('-p', '--page', type=int, default=1, help="指定要抓取的页码，默认是 1")
    parser.add_argument('--keyword', type=str, default=None, help="搜索关键词")
    parser.add_argument('--city', type=str, default=None, help="搜索城市")
    parser.add_argument('--salary', type=str, default=None, help="薪资范围")
    parser.add_argument('--target', type=int, default=0, help="本页期望最大入库数量 (0代表不限制)")
    args = parser.parse_args()
    
    start_auto_patrol(args.page, args.platform, args.keyword, args.city, args.salary, args.target)
