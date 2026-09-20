import json
import os
import sys
import time
import random
import secrets
import sqlite3
import datetime
import argparse
from playwright.sync_api import sync_playwright


# ==========================================
# 核心路径与配置
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from engine_guard import verify_browser_identity

# 端口/profile 口径与 51job_auto_delivery 同源：registry 优先，独立脚本环境 fallback（同其 :50-57 先例）
try:
    from app.session.registry import get_platform_port, get_profile_path
    L51_PORT = get_platform_port("51job")
    L51_PROFILE_DIR = get_profile_path("51job")
except Exception:
    L51_PORT = 9227
    L51_PROFILE_DIR = os.path.join(PARENT_DIR, 'data', 'profiles', '51job')

DB_PATH = os.path.join(PARENT_DIR, 'data', 'job_hunter.db')
COOKIE_FILE = os.path.join(CURRENT_DIR, '51job_cookies.json')

# 51job 城市代码字典
CITY_CODE_MAP = {
    "广州": "030200",
    "深圳": "040000",
    "杭州": "080200",
    "北京": "010000",
    "上海": "020000",
    "成都": "090200",
    "南京": "070200",
    "武汉": "180200"
}

# 51job 薪资代码字典 (包含你找出的所有规律，并兼容 K 的写法)
SALARY_CODE_MAP = {
    "8千以下": "201",
    "0.8-1万": "06",
    "8-10K": "06",
    "1-1.5万": "07",
    "1万-1.5万": "07",
    "10-15K": "07",
    "1.5-2万": "08",
    "1.5万-2万": "08",
    "15-20K": "08",
    "2-3万": "09",
    "2万-3万": "09",
    "20-30K": "09",
    "3-4万": "10",
    "3万-4万": "10",
    "30-40K": "10",
    "4-5万": "11",
    "4万-5万": "11",
    "40-50K": "11",
    "不限": ""
}

def get_city_code(city_name):
    """根据飞书配置的城市名匹配代码，默认为全国(000000)"""
    for name, code in CITY_CODE_MAP.items():
        if name in city_name:
            return code
    return "000000"

def get_salary_code(salary_text):
    """提取薪资代码，支持多选（自动拼凑 %2C）"""
    if not salary_text or "不限" in salary_text:
        return ""
        
    codes = set()
    # 遍历字典，如果飞书填写的文本包含了字典里的词，就收集对应的代码
    for key, code in SALARY_CODE_MAP.items():
        if key in salary_text:
            codes.add(code)
            
    if codes:
        # 将收集到的所有代码去重、排序，然后用 %2C 拼接（例如：07%2C08）
        return "%2C".join(sorted(codes))
        
    return ""

def save_to_raw_db(job_data):
    """将数据安全写入 SQLite，并强制写入本地精确时间"""
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        
        # 🌟 获取本地的当前准确时间，避免数据库使用 UTC 默认时间
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
            job_data.get('publish_date'), '51job', current_time # 🌟 写入正确的爬取时间
        ))
        inserted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        print(f"      ❌ 数据库写入失败: {e}")
        return False

def check_exists(company, title, city):
    """前置去重检查"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM raw_jobs WHERE company_name=? AND job_title=? AND city=?', (company, title, city))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists
    except Exception:
        return False

def fetch_exact_address(context, job_link):
    """详情页下钻：提取精确地址"""
    page = None
    try:
        page = context.new_page()
        page.goto(job_link, wait_until="domcontentloaded", timeout=20000)
        
        # 1. 优先尝试获取地图完整地址 (如截图所示的新版UI)
        map_address_loc = page.locator("*:has-text('地图完整地址：')").last
        if map_address_loc.count() > 0:
            text = map_address_loc.inner_text()
            return text.replace('地图完整地址：', '').strip()
            
        map_address_loc_en = page.locator("*:has-text('地图完整地址:')").last
        if map_address_loc_en.count() > 0:
            text = map_address_loc_en.inner_text()
            return text.replace('地图完整地址:', '').strip()

        # 2. 回退到传统的 上班地址
        address_loc = page.locator("p.fp:has-text('上班地址')")
        if address_loc.count() > 0:
            return address_loc.first.inner_text().replace('上班地址：', '').replace('查看地图', '').strip()
            
        return ""
    except Exception:
        return ""
    finally:
        if page: page.close()

def navigate_to_target_page(search_page, target_page, captured_data):
    """处理防遮挡连点模式，向目标页码推进，返回是否成功"""
    print(f"      🦘 开启【防遮挡连点模式】，向第 {target_page} 页推进...")
    try:
        for step in range(1, target_page):
            # 每次点击前清空旧数据
            captured_data.clear() 
            
            # 🌟 核心修复 2：降维打击，直接向浏览器注入 JS 代码执行底层的点击
            click_success = search_page.evaluate('''() => {
                let nextBtn = document.querySelector('button.btn-next, li.next, .el-pagination button:last-child');
                // 确保按钮存在，且没有被设置为 disabled
                if (nextBtn && !nextBtn.disabled && !nextBtn.className.includes('disabled')) {
                    nextBtn.click();
                    return true;
                }
                return false;
            }''')

            if click_success:
                # 模拟真人翻页速度，极大地降低被风控概率
                search_page.wait_for_timeout(secrets.SystemRandom().randint(1500, 2500))
                # 再次死等新的一页列表加载出来，确保 API 已经返回
                search_page.wait_for_selector(".joblist-item", timeout=10000)
            else:
                print(f"      ⚠️ 无法继续翻页，在第 {step} 页卡住：已到达最后一页（没有更多数据了）。")
                return False
        
        # 到达目标页后，稍微缓冲一下
        search_page.wait_for_timeout(2000)
        return True
    except Exception as e:
        print(f"      ❌ 翻页操作出现异常: {e}")
        return False

def extract_job_items(captured_data):
    """从 API 捕获的数据中安全提取岗位列表"""
    if not captured_data:
        print("      ⚠️ 未捕获到 API 数据。请检查页面是否弹出了滑动验证码或网络超时。")
        return [], 0
    try:
        # 🌟 修复：增加容错，防止 API 响应极慢导致的 IndexError
        job_node = captured_data[-1].get('resultbody', {}).get('job', {})
        return job_node.get('items', []), _extract_search_total(job_node)
    except IndexError:
        print("      ⚠️ API 数据解析异常，跳过本页处理。")
        return [], 0


def _extract_search_total(job_node):
    """从 51job 搜索 API 的 resultbody.job 节点提取搜索总数（分母），候选键兜底。"""
    try:
        for key in ('totalCount', 'total', 'totalNum', 'engineSearchTotal', 'count'):
            val = job_node.get(key)
            if isinstance(val, int) and val > 0:
                return val
            if isinstance(val, str) and val.isdigit() and int(val) > 0:
                return int(val)
        return 0
    except Exception:
        return 0

def process_job_items(context, job_items, target=0):
    """处理单页提取到的所有岗位记录并入库，返回成功条数。

    target>0 时按剩余配额截断：凑满即停，最后一页不会整页超收。
    """
    success_count = 0
    for item in job_items:
        if target > 0 and success_count >= target:
            print(f"\n🎯 [51job 配额拦截] 本页已入库 {success_count} 个，达到剩余配额 {target}，提前结束本页。")
            break
        title = item.get('jobName', '未知')
        company = item.get('companyName', '未知')
        city = item.get('jobAreaString', '')
        link = item.get('jobHref')

        if check_exists(company, title, city):
            print(f"      ⏩ [跳过] {company} - {title} (已在库)")
            continue

        print(f"      🔍 [下钻] 获取详情页精确地址: {company} - {title}")
        
        exact_addr = fetch_exact_address(context, link)
        
        job_data = {
            'job_link': link,
            'job_title': title,
            'company_name': company,
            'city': city,
            'jd_text': item.get('jobDescribe', '无详情'),
            'salary': item.get('provideSalaryString', '面议'),
            'work_address': exact_addr if exact_addr else city,
            'hr_activity': ', '.join(item.get('hrLabels', [])),
            'industry': item.get('companyIndustryType1Str', '其他'),
            'welfare_tags': ', '.join(item.get('jobTags', [])),
            'company_size': item.get('companySizeString', '未知规模'),
            'education_req': item.get('degreeString', '不限'),
            'experience_req': item.get('workYearString', '不限'),
            'hr_skill_tags': ', '.join(item.get('jobTags', [])),
            'company_intro': item.get('companyInfo', ''),
            'role': 'HR',
            'publish_date': item.get('issueDateString', '').split(' ')[0] if item.get('issueDateString') else datetime.datetime.now().strftime("%Y-%m-%d"),
        }

        if save_to_raw_db(job_data):
            success_count += 1
            print(f"   🕷️ [抓取成功] 🏢 {job_data.get('company_name', '未知公司')} | 💼 {job_data.get('job_title', '未知岗位')} | 💰 {job_data.get('salary', '未知薪资')}")
        
        sleep_time = secrets.SystemRandom().randint(15, 35) # 原来是 5-15，现在改为 15-35
        print(f"   💤 深度潜行，随机休眠 {sleep_time} 秒...")
        time.sleep(sleep_time)
        
    return success_count

def collect_51job_task(context, keyword, city_name, target_page, target_salary, target=0):
    """执行单一搜索任务，智能等待 DOM 渲染，利用 JS 原生事件连点下一页"""
    city_code = get_city_code(city_name)
    salary_code = get_salary_code(target_salary) 
    
    print(f"🚀 启动采集任务 | 关键词: {keyword} | 城市: {city_name} (代码: {city_code}) | 薪资: {target_salary} | 目标页码: {target_page}")
    print(f"\n{'='*40}")
    print(f"📍 [51job] 正在准备抓取第 {target_page} 页...")
    
    captured_data = []
    def on_response(response):
        if "api/job/search" in response.url and response.status == 200:
            try: 
                captured_data.append(response.json())
            except Exception: 
                pass

    search_page = context.new_page()
    search_page.on("response", on_response)

    url = f"https://we.51job.com/pc/search?keyword={keyword}&jobArea={city_code}&salary={salary_code}"
    try:
        # 放宽判定条件：只要 DOM 加载完就算成功，不等待无关紧要的图片和广告
        search_page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        print("      💡 提示：页面加载超时，但核心数据可能已渲染，强制放行...")

    # 🌟 核心修复 1：死等！必须确认页面上的职位列表或者分页条已经加载完毕，最多等 15 秒
    try:
        search_page.wait_for_selector(".joblist-item, .btn-next", timeout=15000)
    except Exception:
        print("      ⚠️ 页面加载超时，可能网络卡顿或该关键词无任何岗位数据。")
        search_page.close()
        return

    if target_page > 1:
        if not navigate_to_target_page(search_page, target_page, captured_data):
            search_page.close()
            return

    job_items, search_total = extract_job_items(captured_data)
    if not job_items:
        search_page.close()
        return

    if search_total and search_total > 0:
        print(f"搜索总数 {search_total} 个")

    print(f"      ✅ 成功到达目标第 {target_page} 页！本页捕获到 {len(job_items)} 个岗位，开始深度处理...")

    success_count = process_job_items(context, job_items, target=target)

    print(f"      🎯 本页成功采集并入库 {success_count} 条数据。")
    search_page.close()


def _inject_cookies_if_available(context):
    """从本地 cookie 文件注入登录态到 Playwright context"""
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        if not cookies:
            return False
        context.add_cookies(cookies)
        print(f"🍪 已从 51job_cookies.json 注入 {len(cookies)} 个 Cookie，恢复登录态。")
        return True
    except Exception as e:
        print(f"⚠️ Cookie 注入失败: {e}")
        return False


def _inject_cookies_if_available(context):
    """从本地 cookie 文件注入登录态到 Playwright context"""
    if not os.path.exists(COOKIE_FILE):
        print("⚠️ 未找到 51job_cookies.json，请先在前端备份登录态或运行 51job_cookie_harvester.py")
        return False
    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        if not cookies:
            return False
        context.add_cookies(cookies)
        print(f"🍪 已注入 {len(cookies)} 个 Cookie，恢复登录态。")
        return True
    except Exception as e:
        print(f"⚠️ Cookie 注入失败: {e}")
        return False


def start_collector(target_page, keyword=None, city=None, salary=None, target=0):
    print(f"🚀 启动 51job 精准代码采集矩阵 (目标提取页码: {target_page}, 剩余配额: {target or '不限'})...")

    if not keyword:
        print("❌ 错误：缺少搜索关键词。请在调度器或命令行中传入 keyword 参数。")
        return

    print(f"🎯 使用调度器传入的搜索条件：keyword={keyword}, city={city}, salary={salary}")
    tasks = [{'keyword': keyword, 'city': city or '', 'salary': salary or ''}]

    # 🛡️ 环境守卫（Q24）：占用者必须是由 profiles/51job 拉起的实例，绝不附着陌生浏览器。
    # 放在 with 之外——拒绝时连 playwright driver 都不拉起
    ok, guard_reason = verify_browser_identity(L51_PORT, L51_PROFILE_DIR, platform="51job")
    if not ok:
        print(f"⛔ [环境守卫] 拒绝连接 Edge (端口 {L51_PORT})：{guard_reason}")
        return

    with sync_playwright() as p:
        # 连接已运行的持久化 Edge 浏览器（端口 9227），共享登录态
        print(f"🌐 正在连接 Edge 浏览器 (端口 {L51_PORT})...")
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{L51_PORT}")
            context = browser.contexts[0]
        except Exception as e:
            print(f"❌ 无法连接 Edge (端口 {L51_PORT})。请先通过前端「唤起51job浏览器」按钮启动 Edge。错误: {e}")
            return
        
        for i, task in enumerate(tasks):
            kw = task.get('keyword', '')
            city_name = task.get('city', '')
            target_salary = task.get('salary', '')
            
            print(f"\n▶️ 执行任务 [{i+1}/{len(tasks)}]: 【{kw} | {city_name} | 薪资: {target_salary}】")
            collect_51job_task(context, kw, city_name, target_page, target_salary, target=target)
            
            if i < len(tasks) - 1:
                print("💤 任务切换，休眠 60 秒...")
                time.sleep(60)
                
        # 注意：不关闭 browser，因为是 CDP 连接共享的 Edge 实例

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="51job 指定页码单页抓取工具")
    parser.add_argument('-p', '--page', type=int, required=True, help="需要抓取的页码，例如: -p 3")
    parser.add_argument('--platform', type=str, default=None, help="指定平台名称（兼容调度器）")
    parser.add_argument('--keyword', type=str, default=None, help="搜索关键词")
    parser.add_argument('--city', type=str, default=None, help="搜索城市")
    parser.add_argument('--salary', type=str, default=None, help="薪资范围")
    parser.add_argument('--target', type=int, default=0, help="剩余入库配额（0=不限制），凑满即停防超收")

    args = parser.parse_args()
    start_collector(args.page, args.keyword, args.city, args.salary, target=args.target)