#!/usr/bin/env python3
"""
猎聘网全自动极速爬虫（纯净收割版）

功能：
1. 自动薪资映射：将飞书的月薪格式自动转换为猎聘的年薪代码。
2. 自动 URL 拼接：告别手动挂起，程序启动直接拿到目标数据包。
3. DOM 视觉交叉验证：识破猎聘“数据投毒”，过滤未在页面渲染的过期/钓鱼岗位。
4. 机械臂防风控：在每个岗位详情页下钻时，模拟真实人类的鼠标轨迹和滚轮阅读。
5. 纯净入库：不进行任何业务规则清洗，无脑入库，彻底贯彻 解耦架构。
"""

import json
import os
import time
import random
import sqlite3
import datetime
import argparse
import re
from DrissionPage import ChromiumPage, ChromiumOptions



# ==========================================
# 核心路径与配置
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
DB_PATH = os.path.join(PARENT_DIR, 'data', 'job_hunter.db')
COOKIE_FILE = os.path.join(CURRENT_DIR, 'liepin_cookies.json')

# 🌟 更新后的猎聘城市代码映射表 (结合了链接提取规律与原有数据)
LIEPIN_CITY_MAP = {
    "全国": "410", 
    "北京": "010", 
    "上海": "020", 
    "天津": "030", 
    "重庆": "040", 
    "广州": "050020", 
    "深圳": "050090",
    "杭州": "070020", 
    "成都": "280020", 
    "武汉": "170020", 
    "南京": "060020",
    "苏州": "060080"  # 根据你提供的链接补充
}

# ================= 新增：猎聘薪资换算字典 =================
# 猎聘是年薪制，这里帮你把常见的月薪配置，智能映射到对应的年薪代码
LIEPIN_SALARY_MAP = {
    "10万以下": "1", "8千以下": "1", "8-10K": "1", "3K以下": "1", "3-5K": "1", "5-10K": "1", "8K以下": "1",
    "10-15万": "2", "10-15K": "2", "1万-1.5万": "2",
    "16-20万": "3", "15-20K": "3", "1.5万-2万": "3", "10-20K": "3",
    "21-30万": "4", "20-30K": "4", "2万-3万": "4", "20-50K": "4",
    "30-50万": "5", "30-50K": "5", "3万-5万": "5",
    "50万以上": "6", "50K以上": "6", "5万以上": "6",
    "不限": "0"
}
# ==========================================================

def get_city_code(city_name):
    for name, code in LIEPIN_CITY_MAP.items():
        if name in city_name: return code
    return ""

def get_liepin_salary_code(salary_text):
    """提取猎聘年薪代码"""
    if not salary_text or "不限" in salary_text:
        return ""
    # 遍历字典寻找匹配项
    for key, code in LIEPIN_SALARY_MAP.items():
        if key.upper() in salary_text.upper():
            return code
    return ""

def determine_role(company_name, recruiter_title):
    """智能判断 HR 还是 猎头"""
    comp = str(company_name)
    title = str(recruiter_title)
    if comp.startswith("某") or "保密" in comp: return "猎头"
    if any(k in comp for k in ["人力", "猎头", "咨询", "人才", "外包", "德科"]): return "猎头"
    if "猎头" in title or "顾问" in title: return "猎头"
    return "HR"

def save_to_raw_db(job_data):
    """将数据安全写入 SQLite，并强制写入本地时间"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        
        # 🌟 获取 Python 本地的当前准确时间
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
            INSERT OR IGNORE INTO raw_jobs (
                job_link, job_title, company_name, city, jd_text, 
                salary, work_address, hr_activity, industry, welfare_tags, 
                company_size, education_req, experience_req, hr_skill_tags, 
                company_intro, role, publish_date, platform, crawl_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job_data.get('job_link'), job_data.get('job_title'),
            job_data.get('company_name'), job_data.get('city'),
            job_data.get('jd_text'), job_data.get('salary'),
            job_data.get('work_address'), job_data.get('hr_activity'),
            job_data.get('industry'), job_data.get('welfare_tags'),
            job_data.get('company_size'), job_data.get('education_req'),
            job_data.get('experience_req'), job_data.get('hr_skill_tags'),
            job_data.get('company_intro'), job_data.get('role'),
            job_data.get('publish_date'), '猎聘', current_time # 🌟 把当前时间传给 crawl_time
        ))
        inserted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        print(f"      ❌ 数据库写入失败: {e}")
        return False

def check_exists(company, title, city):
    """前置查重"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM raw_jobs WHERE company_name=? AND job_title=? AND city=?', (company, title, city))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    except Exception:
        return False

def simulate_human_reading(page):
    """机械臂：模拟人类阅读和鼠标轨迹"""
    try:
        for _ in range(random.randint(2, 4)):
            page.scroll.down(random.randint(300, 800))
            time.sleep(random.uniform(1.0, 3.0))
        page.scroll.up(random.randint(100, 400))
        time.sleep(random.uniform(1.0, 2.0))
    except Exception: pass

def clean_job_description(raw_desc):
    """清理 JD 首尾无用文本"""
    if not raw_desc: return ""
    start_markers = ["职位介绍", "岗位职责", "工作内容", "任职要求"]
    for marker in start_markers:
        if marker in raw_desc:
            parts = raw_desc.split(marker, 1)
            if len(parts) > 1:
                raw_desc = parts[1]
                break
    end_markers = ["猎聘温馨提示", "其他信息", "猜你喜欢", "相关推荐", "联系方式", "举报"]
    for marker in end_markers:
        if marker in raw_desc:
            raw_desc = raw_desc.split(marker)[0]
    return ' '.join(raw_desc.split()).strip()

def _extract_address_from_tab(tab, is_headhunter):
    """辅助函数：精准提取职位地址"""
    if is_headhunter:
        return "猎头保密地址"
        
    exact_address = ""
    # 🌟 核心升级：XPath 精准定位包含"职位地址"的 label-box
    addr_ele = tab.ele('xpath://div[contains(@class,"label-box")][.//span[contains(text(),"职位地址")]]//span[contains(@class,"text")]')
    if addr_ele:
        exact_address = addr_ele.text.strip()
    
    # 🛡️ 备用方案：如果上面的结构失效，依然保留底层的正则抓取逻辑作为兜底
    if not exact_address:
        html_content = tab.html
        addr_matches = re.findall(r'"address"\s*:\s*"([^"]+)"', html_content)
        for addr in addr_matches:
            if len(addr) > 3 and "http" not in addr:
                exact_address = addr
                break
        if not exact_address:
            text_match = re.search(r'(?:工作|职位)地址[：:]?\s*<[^>]+>\s*([^<]+)<', html_content)
            if text_match: 
                exact_address = text_match.group(1)
    
    return exact_address.replace('查看地图', '').strip() if exact_address else exact_address

def fetch_liepin_detail(main_page, job_link, is_headhunter):
    """下钻详情：精准提取详细 JD 与 职位地址"""
    tab = None
    exact_address = ""
    jd_text = ""
    try:
        tab = main_page.new_tab(job_link)
        simulate_human_reading(tab)
        
        # 1. 抓取正文
        jd_ele = tab.ele('tag:main') or tab.ele('.job-intro') or tab.ele('[data-selector="job-intro-content"]')
        if jd_ele:
            jd_text = clean_job_description(jd_ele.text.strip())
            
        # 2. 抓取地址
        exact_address = _extract_address_from_tab(tab, is_headhunter)
        
        return jd_text, exact_address
    except Exception:
        return jd_text, exact_address
    finally:
        if tab: tab.close()

def _setup_chromium_browser():
    """辅助函数：初始化并配置 DrissionPage 浏览器环境"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    co = ChromiumOptions()
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-blink-features=AutomationControlled')
    
    # 🌟 统一架构：强制指定 Microsoft Edge 的绝对路径
    mac_edge_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)

    # 🌟 1. 随机分配一个不冲突的调试端口 (避开默认的 9222，防止与日常浏览器/僵尸进程抢占)
    co.set_local_port(9226)
    print(f"🛡️  [固定端口] DrissionPage 调试端口: 9226")

    # 🌟 2. 设置物理隔离的用户数据目录 (防止与日常 Chrome / Edge 进程抢 Profile 锁)
    profile_path = os.path.join(project_root, 'data', 'profiles', 'liepin')
    os.makedirs(profile_path, exist_ok=True)
    co.set_user_data_path(profile_path)
    print(f"🛡️  [Profile 物理隔离] 用户数据目录: {profile_path}")

    co.headless(False)
    page = ChromiumPage(co)

    # 🌟 登录态守卫（与投递侧 liepin_auto_delivery 一致）：profile 自带活跃 session 时
    #    严禁注入本地 cookie 文件，防止过期 cookie 覆盖/污染有效登录态。
    if _check_login_status(page):
        print("   ✅ Edge Profile 自带活跃登录态，跳过 Cookie 注入")
        return page

    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            page.get('https://www.liepin.com')
            valid_keys = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
            for c in cookies:
                if isinstance(c, dict) and "name" in c and "value" in c:
                    clean_c = {k: v for k, v in c.items() if k in valid_keys and v is not None}
                    try:
                        page.set.cookies(clean_c)
                    except Exception:
                        pass
            if _check_login_status(page):
                print(f"🍪 本地 Cookie 注入成功，猎聘登录态已恢复")
            else:
                print(f"⚠️ 本地 Cookie 文件已失效，需要扫码登录（本次爬取将以未登录态进行）")
        except Exception as e:
            print(f"⚠️ 读取/注入猎聘 Cookie 异常: {e}")

    return page

def _check_login_status(page) -> bool:
    """校验猎聘登录态：访问 c.liepin.com，若保持在 c.liepin.com 则登录态有效"""
    try:
        page.get('https://c.liepin.com/')
        time.sleep(2)
        return page.url.startswith("https://c.liepin.com")
    except Exception as e:
        print(f"   ⚠️ 校验猎聘登录态异常: {e}")
        return False

def _intercept_job_packet(page, url):
    """辅助函数：请求页面并拦截 pc-search-job 数据包"""
    print("🔄 正在自动请求并拦截底层数据包...")
    page.listen.start('pc-search-job')
    try:
        page.get(url)
    except Exception:
        print("      💡 提示：页面加载超时，但可能岗位数据已渲染，尝试强制解析...")

    target_packet = None
    raw_body = {}

    for packet in page.listen.steps(timeout=30):
        if packet.request.method == 'OPTIONS':
            continue

        temp_body = packet.response.body
        if isinstance(temp_body, str):
            try:
                temp_body = json.loads(temp_body)
            except Exception:
                temp_body = {}
        elif not isinstance(temp_body, dict):
            temp_body = {}

        if 'data' in temp_body and isinstance(temp_body['data'], dict) and 'jobCardList' in temp_body['data'].get('data', {}):
            target_packet = packet
            raw_body = temp_body
            break
        else:
            print("      👀 忽略了一个无关的数据包...")

    page.listen.stop()
    time.sleep(3)
    
    return target_packet, raw_body

def _process_single_job(item, page, idx, total_jobs):
    """辅助函数：处理单个岗位解析、查重、抓详情、入库"""
    job_info = item.get('job', {})
    comp_info = item.get('comp', {})
    recruiter = item.get('recruiter', {})

    title = job_info.get('title', '未知')
    company = comp_info.get('compName', '未知')
    city = job_info.get('dq', '')
    link = job_info.get('link', '')

    raw_time = str(job_info.get('refreshTime', ''))
    if raw_time and len(raw_time) >= 8:
        try:
            job_date = datetime.datetime.strptime(raw_time[:8], "%Y%m%d")
            days_ago = (datetime.datetime.now() - job_date).days
            if days_ago > 180:
                print(f"   ⏳ [过期拦截] 岗位已 {days_ago} 天未刷新 (超过180天阈值)，跳过: {company} - {title}")
                return False, True 
        except Exception:
            pass

    if check_exists(company, title, city):
        print(f"   ⏩ [{idx+1}/{total_jobs}] 跳过已收录: {company} - {title}")
        return False, True

    recruiter_title = recruiter.get('title', '未知')
    role = determine_role(company, recruiter_title)
    is_headhunter = (role == "猎头")

    print(f"   🔍 [{idx+1}/{total_jobs}] 提取详情: {company} - {title} ({role})")
    
    jd_text, exact_addr = fetch_liepin_detail(page, link, is_headhunter)
    
    pub_date = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]}" if len(raw_time)>=8 else datetime.datetime.now().strftime("%Y-%m-%d")

    job_data = {
        'job_link': link,
        'job_title': title,
        'company_name': company,
        'city': city,
        'jd_text': jd_text,
        'salary': job_info.get('salary', '面议'),
        'work_address': exact_addr if exact_addr else city,
        'hr_activity': recruiter_title,
        'industry': comp_info.get('compIndustry', '其他'),
        'welfare_tags': ', '.join(job_info.get('labels', [])),
        'company_size': comp_info.get('compScale', '未知'),
        'education_req': job_info.get('requireEduLevel', '不限'),
        'experience_req': job_info.get('requireWorkYears', '不限'),
        'hr_skill_tags': ', '.join(job_info.get('labels', [])),
        'company_intro': '',
        'role': role,
        'publish_date': pub_date,
    }

    if save_to_raw_db(job_data):
        print(f"   🕷️ [抓取成功] 🏢 {job_data.get('company_name', '未知公司')} | 💼 {job_data.get('job_title', '未知岗位')} | 💰 {job_data.get('salary', '未知薪资')}")
        return True, False
    
    return False, False

def _process_job_items(job_items, page, target, target_page):
    """辅助函数：遍历处理页面抓取到的岗位条目"""
    print(f"✅ 成功截获 {len(job_items)} 个符合薪资区间的岗位，开启蜜罐防御扫描...")
    success_count = skip_count = 0
    total_jobs = len(job_items)
    
    for idx, item in enumerate(job_items):
        is_success, is_skipped = _process_single_job(item, page, idx, total_jobs)
        
        if is_skipped:
            skip_count += 1
            continue
            
        if is_success:
            success_count += 1
            
        if target > 0 and success_count >= target:
            print(f"   🎯 [单页目标拦截] 本页已成功抓取 {success_count} 个岗位，满足所需数量，提前结束本页。")
            break
        
        sleep_time = random.randint(30, 60)
        print(f"   💤 深度潜行，随机休眠 {sleep_time} 秒...")
        time.sleep(sleep_time)

    print(f"🎯 第 {target_page} 页处理完毕！新增入库 {success_count} 个，拦截/跳过 {skip_count} 个。")

def _extract_search_total(raw_body):
    """从搜索拦截包体里提取「搜索结果总数」（分母）。字段名以真机为准，候选键兜底。"""
    try:
        nodes = []
        data = raw_body.get('data') if isinstance(raw_body, dict) else None
        if isinstance(data, dict):
            nodes.append(data)
            if isinstance(data.get('data'), dict):
                nodes.append(data['data'])
        for key in ('totalCount', 'total', 'totalSize', 'totalNum', 'count', 'pageTotal'):
            for node in nodes:
                val = node.get(key)
                if isinstance(val, int) and val > 0:
                    return val
                if isinstance(val, str) and val.isdigit() and int(val) > 0:
                    return int(val)
        return 0
    except Exception:
        return 0


def _execute_single_task(task, i, total_tasks, page, target_page, target, real_page_index):
    """辅助函数：处理单个抓取任务"""
    keyword_t = task.get('keyword', '')
    city_name = task.get('city', '')
    task_salary = task.get('salary', '不限')
    
    city_code = get_city_code(city_name)
    salary_code = get_liepin_salary_code(task_salary)
    
    print(f"\n{'='*50}")
    print(f"▶️ 执行指令 [{i+1}/{total_tasks}]: 【{keyword_t} | {city_name} | 薪资: {task_salary} (代码: {salary_code})】 第 {target_page} 页")
    
    url = f"https://www.liepin.com/zhaopin/?key={keyword_t}&dq={city_code}&currentPage={real_page_index}"
    if salary_code:
        url += f"&salaryCode={salary_code}"

    target_packet, raw_body = _intercept_job_packet(page, url)

    if target_packet is None:
        print("❌ 在 30 秒内未截获到包含 'jobCardList' 的核心数据包。")
        print("   可能原因：1. 遇到了滑块验证码 2. 该搜索条件下确实没有岗位 3. 网络极度卡顿。")
        return

    job_items = raw_body.get('data', {}).get('data', {}).get('jobCardList', [])

    # 解析搜索总数（分母）：接口字段名以真机为准，候选键兜底；拿不到不打印（上层走兜底规则）
    _total = _extract_search_total(raw_body)
    if _total and _total > 0:
        print(f"搜索总数 {_total} 个")

    _process_job_items(job_items, page, target, target_page)

def start_auto_collector(target_page, keyword=None, city=None, salary=None, target=0):
    print(f"🚀 启动猎聘【全自动纯净版】采集器 | 锁定抓取页码: P{target_page}")
    
    if keyword:
        print(f"🎯 使用传入的搜索条件：keyword={keyword}, city={city}, salary={salary}")
        tasks = [{'keyword': keyword, 'city': city or '', 'salary': salary or ''}]
    else:
        print("❌ 错误：未提供搜索关键词 (--keyword)！")
        return

    real_page_index = target_page - 1 if target_page > 0 else 0
    page = _setup_chromium_browser()

    try:
        total_tasks = len(tasks)
        for i, task in enumerate(tasks):
            _execute_single_task(task, i, total_tasks, page, target_page, target, real_page_index)

            if i < total_tasks - 1:
                print("💤 任务切换，休眠 60 秒...")
                time.sleep(60)
    finally:
        page.quit()
        print("\n🏁 本次全自动页面抓取指令已全部执行完毕！程序退出。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="猎聘全自动单页采集器")
    parser.add_argument('-p', '--page', type=int, default=1, help="指定要抓取的页码，默认是 1")
    parser.add_argument('--platform', type=str, default=None, help="指定平台名称（兼容调度器）")
    parser.add_argument('--keyword', type=str, default=None, help="搜索关键词")
    parser.add_argument('--city', type=str, default=None, help="搜索城市")
    parser.add_argument('--salary', type=str, default=None, help="薪资范围")
    parser.add_argument('--target', type=int, default=0, help="本页需要抓取的目标数量，达到后自动停止本页抓取")
    args = parser.parse_args()
    
    start_auto_collector(args.page, args.keyword, args.city, args.salary, args.target)