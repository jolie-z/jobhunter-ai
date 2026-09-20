import os
import re
import sqlite3
import json
import time
import random
import platform
import argparse
from datetime import datetime
from DrissionPage import ChromiumPage, ChromiumOptions

# ==========================================
# 核心路径配置
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
DB_PATH = os.path.join(PARENT_DIR, 'data', 'job_hunter.db')

# ==========================================
# 城市映射表
# ==========================================
CITY_MAP = {
    "全国": "489",
    "北京": "530",
    "上海": "538",
    "广州": "763",
    "深圳": "765",
    "杭州": "653",
    "成都": "801",
    "重庆": "551",
    "武汉": "736",
    "西安": "854",
    "苏州": "639",
    "南京": "635",
    "天津": "531",
    "郑州": "719",
}

def get_city_code(city_name):
    if not city_name:
        return "489"
    for name, code in CITY_MAP.items():
        if name in city_name or city_name in name:
            return code
    return "489"

# ==========================================
# 内存秒级指纹库（0ms 秒级判重引擎）
# ==========================================
_KNOWN_JOB_LINKS = set()
_KNOWN_JOB_ENTITIES = set()
_FINGERPRINTS_LOADED = False

def _init_memory_fingerprints():
    """启动时一次性载入智联招聘历史已存岗位指纹，避免对数千卡片逐个建立磁盘 SQLite 连接"""
    global _KNOWN_JOB_LINKS, _KNOWN_JOB_ENTITIES, _FINGERPRINTS_LOADED
    if _FINGERPRINTS_LOADED:
        return
    try:
        if os.path.exists(DB_PATH):
            with sqlite3.connect(DB_PATH, timeout=10) as conn:
                cursor = conn.cursor()
                rows = cursor.execute(
                    "SELECT job_link, company_name, job_title, city FROM raw_jobs WHERE platform = '智联招聘' OR platform = 'zhilian'"
                ).fetchall()
                for link, comp, title, city in rows:
                    if link:
                        _KNOWN_JOB_LINKS.add(link.strip().split('?')[0])
                    if comp and title:
                        _KNOWN_JOB_ENTITIES.add((comp.strip(), title.strip(), (city or '').strip()))
                print(f"⚡ [指纹引擎] 智联招聘已预加载 {len(_KNOWN_JOB_LINKS)} 条历史链接、{len(_KNOWN_JOB_ENTITIES)} 组实体指纹（开启 0ms 内存秒级判重）")
    except Exception as e:
        print(f"⚠️ [指纹引擎] 预加载历史指纹异常: {e}")
    finally:
        _FINGERPRINTS_LOADED = True

def check_job_exists(company_name, job_title, city, job_link):
    _init_memory_fingerprints()
    if job_link:
        clean_link = job_link.strip().split('?')[0]
        if clean_link in _KNOWN_JOB_LINKS:
            return True
    if company_name and job_title:
        entity_key = (company_name.strip(), job_title.strip(), (city or '').strip())
        if entity_key in _KNOWN_JOB_ENTITIES:
            return True
    return False

def _register_job_to_memory(job_data):
    """新岗位入库后实时注册到内存指纹库"""
    link = (job_data.get('job_link') or '').strip().split('?')[0]
    if link:
        _KNOWN_JOB_LINKS.add(link)
    comp = (job_data.get('company_name') or '').strip()
    title = (job_data.get('job_title') or '').strip()
    city = (job_data.get('city') or '').strip()
    if comp and title:
        _KNOWN_JOB_ENTITIES.add((comp, title, city))

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
            job_data.get('publish_date', ''), '智联招聘', current_time                           
        ))
        inserted = cursor.rowcount > 0 
        conn.commit()
        if inserted:
            _register_job_to_memory(job_data)
        return inserted
    except Exception as e:
        print(f"      ❌ 数据库写入出错: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def _setup_browser():
    co = ChromiumOptions()
    edge_path = None
    if platform.system() == "Darwin":
        mac_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
        if os.path.exists(mac_path):
            edge_path = mac_path
    elif platform.system() == "Windows":
        for base in [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("LOCALAPPDATA", "")]:
            candidate = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(candidate):
                edge_path = candidate
                break
    if edge_path:
        co.set_browser_path(edge_path)
    co.set_local_port(9250)

    # 🛡️ [Profile 物理隔离] 必须绑定持久化 profile（与 registry / 投递侧 zhilian_auto_delivery 一致）：
    #    若 9250 端口无活跃 Edge，DrissionPage 会以默认用户目录拉起一份"无登录态"的浏览器，
    #    导致反复要求扫码登录，且该浏览器会占住 9250 端口，令后续预检/投递连锁误判掉线。
    profile_path = os.path.join(PARENT_DIR, 'data', 'profiles', 'zhilian')
    os.makedirs(profile_path, exist_ok=True)
    co.set_user_data_path(profile_path)
    print(f"🛡️  [Profile 物理隔离] 用户数据目录: {profile_path}")
    
    # 🌟 确保至少存在 1 个活跃标签页
    try:
        import requests
        r = requests.get("http://127.0.0.1:9250/json", proxies={"http": None, "https": None}, timeout=1).json()
        page_tabs = [t for t in r if t.get("type") == "page"]
        if not page_tabs:
            requests.put("http://127.0.0.1:9250/json/new?https://www.zhaopin.com", proxies={"http": None, "https": None}, timeout=2)
    except Exception:
        pass

    try:
        return ChromiumPage(co)
    except Exception as e:
        print(f"❌ 启动浏览器失败，请确保没有其他程序占用 9250 端口，或彻底关闭 Edge 重试: {e}")
        import sys
        sys.exit(1)

def _build_zhilian_jobs_url(city: str, keyword: str, page_num: int = 1) -> str:
    """构造智联招聘规范直达 URL，原生携带城市代码、关键词及分页参数"""
    city_code = get_city_code(city)
    import urllib.parse
    kw_encoded = urllib.parse.quote(keyword)
    if page_num > 1:
        return f"https://www.zhaopin.com/jobs?jl={city_code}&kw={kw_encoded}&p={page_num}"
    return f"https://www.zhaopin.com/jobs?jl={city_code}&kw={kw_encoded}"

def _apply_salary_filter(page, salary):
    if not salary or salary == "不限":
        return
    print(f"🎯 正在尝试通过模拟点击进行薪资筛选: {salary}")
    try:
        filter_label = (
            page.ele('text:薪资待遇', timeout=2)
            or page.ele('text:薪资要求', timeout=2)
            or page.ele('text:薪资', timeout=2)
            or page.ele('.joblist-box__filter-title', timeout=2)
        )
        if filter_label:
            try: page.scroll.to_see(filter_label)
            except Exception: pass
            filter_label.click(by_js=True)
            time.sleep(1)
            
            salary_ele = page.ele(f'text:{salary}', timeout=3)
            if salary_ele:
                salary_ele.click(by_js=True)
                print(f"      ✅ 成功点击薪资过滤: {salary}")
                time.sleep(3)
            else:
                print(f"      ⚠️ 未能在下拉框中找到薪资选项: {salary}")
    except Exception as e:
        print(f"      ⚠️ 薪资筛选模拟点击出错: {e}")

def _jump_to_page(page, city, keyword, target_page, salary):
    if target_page <= 1:
        return
    url = _build_zhilian_jobs_url(city, keyword, target_page)
    print(f"🎯 正在通过 URL 直达跳转到指定的起始页: 第 {target_page} 页 ({url})...")
    try:
        page.get(url)
        time.sleep(3)
        _apply_salary_filter(page, salary)
    except Exception as e:
        print(f"      ⚠️ 跳转起始页出现异常: {e}")

def _handle_page_freeze(page, city, keyword, salary, current_page):
    print(f"🔄 页面疑似卡死 (目标第 {current_page} 页无反应)，执行【URL直达刷新】重试机制...")
    url = _build_zhilian_jobs_url(city, keyword, current_page)
    try:
        page.get(url)
        time.sleep(4)
        _apply_salary_filter(page, salary)
    except Exception as e:
        print(f"      ⚠️ 页面卡死自愈恢复异常: {e}")

def _extract_job_basic_info(job_ele, city):
    cls = job_ele.attr('class') or ''
    if 'job-card' in cls:
        title_ele = job_ele.ele('.job-card__title-main', timeout=0) or job_ele.ele('.vue-clamp__text', timeout=0)
        job_title = title_ele.text if title_ele else ""

        salary_ele = job_ele.ele('.job-card__salary', timeout=0)
        salary = salary_ele.text if salary_ele else ""

        company_ele = job_ele.ele('.job-card__company-name', timeout=0) or job_ele.ele('.job-card__company', timeout=0)
        company_name = company_ele.text if company_ele else ""
        company_link = company_ele.attr('href') if company_ele else ""

        loc_ele = job_ele.ele('.job-card__location', timeout=0)
        work_address = loc_ele.text if loc_ele else city

        tag_eles = job_ele.eles('.job-card__skill-tag', timeout=0)
        tag_texts = [t.text.strip() for t in tag_eles if t.text.strip()]

        education_req = ""
        experience_req = ""
        skill_tags = []
        for t in tag_texts:
            if any(ed in t for ed in ["大专", "本科", "硕士", "博士", "中专", "高中", "学历不限"]):
                education_req = t
            elif re.fullmatch(r'(\d+[-~]\d+年|\d+年以上|经验不限|经验不限内|应届生?|在校生?|1年以内|无需经验)', t.strip()):
                # 严格匹配经验话术，避免「五险一年缴」之类的福利标签误入经验字段
                experience_req = t
            else:
                skill_tags.append(t)

        # 杜绝把公司主页 companydetail 当做岗位链接；优先尝试寻找卡片内的职位链接，未就绪则使用指纹链接等待右侧分栏 enrich
        job_a = job_ele.ele('css:a[href*="jobdetail"]', timeout=0) or job_ele.ele('css:a[href*="/job/"]', timeout=0)
        job_link = (job_a.attr('href') or "").split('?')[0] if job_a else f"https://www.zhaopin.com/job_{abs(hash((company_name, job_title, work_address)))}"

        return {
            'job_link': job_link,
            'job_title': job_title,
            'company_name': company_name,
            'city': city or work_address,
            'salary': salary,
            'work_address': work_address,
            'industry': "",
            'company_size': "",
            'welfare_tags': ', '.join(skill_tags[:5]),
            'education_req': education_req,
            'experience_req': experience_req,
            'hr_skill_tags': ', '.join(skill_tags),
            'publish_date': '未知',
            'jd_text': '',
            'role': 'HR',
            'hr_activity': ''
        }

    jobinfo = job_ele.ele('.jobinfo', timeout=0)
    companyinfo = job_ele.ele('.companyinfo', timeout=0)
    if not jobinfo or not companyinfo:
        return None
        
    job_link_ele = jobinfo.ele('.jobinfo__name', timeout=0)
    if not job_link_ele:
        return None
        
    job_title = job_link_ele.text
    job_link = job_link_ele.attr('href')
    
    company_name_ele = companyinfo.ele('.companyinfo__name', timeout=0)
    if not company_name_ele:
        return None
    company_name = company_name_ele.text
    
    other_info_items = [t.text.strip() for t in jobinfo.eles('.jobinfo__other-info-item', timeout=0) if t.text.strip()]
    current_city = city
    experience_req = ""
    education_req = ""
    
    for item_text in other_info_items:
        if any(ed in item_text for ed in ["大专", "本科", "硕士", "博士", "中专", "高中", "学历不限", "统招"]):
            if not education_req:
                education_req = item_text
        elif any(exp in item_text for exp in ["年", "经验", "应届", "在读", "不限"]):
            if not experience_req:
                experience_req = item_text
        else:
            if not current_city or current_city == city:
                current_city = item_text
    
    salary_ele = jobinfo.ele('.jobinfo__salary', timeout=0)
    salary = salary_ele.text.strip() if salary_ele else ''
    
    company_tags = [t.text.strip() for t in companyinfo.eles('.joblist-box__item-tag', timeout=0) if t.text.strip()]
    company_size = ""
    industry = ""
    for c_tag in company_tags:
        if any(sz in c_tag for sz in ["人", "规模", "微型", "小型", "中型", "大型", "少于", "以上"]):
            if not company_size:
                company_size = c_tag
        else:
            if not industry:
                industry = c_tag
    
    welfare_tags = ', '.join([t.text.strip() for t in jobinfo.eles('.joblist-box__item-tag', timeout=0) if t.text.strip()])
    
    return {
        'job_link': job_link, 'job_title': job_title, 'company_name': company_name,
        'city': current_city, 'salary': salary, 'work_address': current_city,
        'industry': industry, 'company_size': company_size, 'welfare_tags': welfare_tags,
        'education_req': education_req, 'experience_req': experience_req,
        'hr_skill_tags': '', 'publish_date': '未知',
        'jd_text': '', 'role': 'HR', 'hr_activity': ''
    }

def _simulate_human_click(page_or_frame, target_ele):
    import random
    offset_x = random.randint(-5, 5)
    offset_y = random.randint(-5, 5)
    page_or_frame.actions.move_to(target_ele, offset_x=offset_x, offset_y=offset_y).wait(random.uniform(0.1, 0.4))
    page_or_frame.actions.move(random.randint(-2, 2), random.randint(-2, 2)).wait(random.uniform(0.05, 0.1)).click()

def _try_click_verify_box(tab):
    verify_box = tab.ele('xpath://*[contains(text(), "确认您是真人")]', timeout=1)
    if verify_box:
        _simulate_human_click(tab, verify_box)
        return True
    
    iframe = tab.get_frame('tag:iframe')
    if iframe:
        verify_box_frame = iframe.ele('xpath://*[contains(text(), "确认您是真人")]', timeout=3)
        if verify_box_frame:
            _simulate_human_click(iframe, verify_box_frame)
            print("      ✅ 成功通过拟真物理轨迹点击了 iframe 内的验证复选框！")
            return True
    return False

def _handle_edgeone_captcha(tab):
    if tab.ele('text:请勾选下方复选框', timeout=3) or tab.ele('text:验证连接安全性', timeout=0):
        print("      🛡️ 触发了腾讯云 EdgeOne 安全验证，尝试自动通过...")
        try:
            if _try_click_verify_box(tab):
                time.sleep(4)
            if tab.ele('text:请勾选下方复选框', timeout=2):
                print("      🚨 自动点击未能通过验证，请立即在弹出的浏览器页面中【手动勾选】！为您倒计时等待 20 秒...")
                time.sleep(20)
        except Exception as e:
            print(f"      ⚠️ 自动点击复选框异常: {e}")

def _parse_publish_date_text(time_text):
    if not time_text:
        return ""
    import re
    match = re.search(r'(\d+)月(\d+)日', time_text)
    if match:
        year = datetime.now().year
        month = int(match.group(1))
        day = int(match.group(2))
        return f"{year}-{month:02d}-{day:02d}"
    if any(kw in time_text for kw in ['今天', '刚刚', '小时', '分钟']):
        return datetime.now().strftime("%Y-%m-%d")
    if '昨天' in time_text:
        from datetime import timedelta
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return time_text

def _extract_job_publish_date(tab, job_data):
    try:
        update_time_ele = tab.ele('text:更新时间', timeout=1) or tab.ele('text:发布时间', timeout=0.5)
        if not update_time_ele:
            job_data['publish_date'] = job_data.get('publish_date') or '未知'
            return
        time_text = update_time_ele.text.replace('更新时间', '').replace('发布时间', '').replace('：', '').replace(':', '').strip()
        parsed_date = _parse_publish_date_text(time_text)
        job_data['publish_date'] = parsed_date if parsed_date else '未知'
    except Exception as e:
        print(f"      ⚠️ 提取更新时间异常: {e}")
        job_data['publish_date'] = '未知'

def _get_jd_text_from_card(jd_title):
    card = jd_title.parent('.seo-card') or jd_title.parent('.describtion-card')
    if card:
        content = card.ele('.seo-card__content') or card.ele('.describtion-card__content')
        if content:
            return content.text
    return ""

def _get_jd_text_fallback(jd_title):
    curr = jd_title
    for _ in range(5):
        if curr.next() and len(curr.next().text) > 20:
            return curr.next().text
        curr = curr.parent()
        if curr and len(curr.text) > 50:
            return curr.text.replace("职位描述", "", 1).replace("职位详情", "", 1).strip()
    return ""

def _extract_job_detail_text(tab, job_data):
    jd_text = ""
    try:
        detail_ele = tab.ele('.describtion-card__detail-content', timeout=2)
        if detail_ele:
            jd_text = detail_ele.text
        else:
            jd_title = tab.ele('text:职位描述', timeout=2) or tab.ele('text:职位详情', timeout=2)
            if jd_title:
                jd_text = _get_jd_text_from_card(jd_title)
                if not jd_text:
                    jd_text = _get_jd_text_fallback(jd_title)
    except Exception as e:
        print(f"      ⚠️ 职位描述定位异常: {e}")
    if jd_text:
        job_data['jd_text'] = jd_text
        print("      ✅ 详情抓取成功。")
    else:
        print("      ⚠️ 详情定位失败，可能页面结构改变或未能通过安全验证。")

def _get_addr_text_from_dialog(addr_ele):
    dialog = addr_ele.ele('.address-info__dialog')
    if dialog:
        return addr_ele.text.replace(dialog.text, '').strip()
    return addr_ele.text

def _get_addr_text_from_card(addr_title):
    card = addr_title.parent('.seo-card')
    if card:
        content = card.ele('.seo-card__content')
        if content:
            return content.text
    return ""

def _get_addr_text_fallback(addr_title):
    curr = addr_title
    for _ in range(4):
        if curr.next() and len(curr.next().text) > 5:
            return curr.next().text
        curr = curr.parent()
        if curr and len(curr.text) > 10:
            return curr.text.replace("工作地点", "", 1)
    return ""

def _extract_job_work_address(tab_or_pane, job_data):
    """提取门牌级详细工作地址（优先提取气泡与地图正文，剔除弹窗文本）"""
    try:
        addr_text = ""
        # 1. 优先提取气泡/地图文本中的真实门牌级地址
        bubble = (
            tab_or_pane.ele('css:.address-info__bubble', timeout=0.5)
            or tab_or_pane.ele('css:.job-detail-address__content', timeout=0.5)
            or tab_or_pane.ele('css:.job-address__content-text', timeout=0.5)
        )
        if bubble and bubble.text.strip():
            addr_text = bubble.text.strip()
        else:
            addr_ele = tab_or_pane.ele('css:.address-info__content', timeout=0.5)
            if addr_ele:
                dialog = addr_ele.ele('css:.address-info__dialog', timeout=0.2)
                if dialog:
                    addr_text = addr_ele.text.replace(dialog.text, '').strip()
                else:
                    addr_text = addr_ele.text.strip()
            else:
                addr_title = tab_or_pane.ele('text:工作地点', timeout=0.5)
                if addr_title:
                    addr_text = _get_addr_text_from_card(addr_title)
                    if not addr_text:
                        addr_text = _get_addr_text_fallback(addr_title)

        if addr_text:
            addr_text = addr_text.replace('点击查看地图', '').replace('查看地图', '').replace('工作地点', '').strip()
            addr_text = ' '.join(addr_text.split())
            if addr_text:
                job_data['work_address'] = addr_text
                print(f"      📍 获取到详细地址: {addr_text}")
    except Exception as e:
        print(f"      ⚠️ 详细地址定位异常: {e}")


def _parse_zhilian_company_desc(raw_text: str) -> tuple[str, str]:
    """
    解析智联招聘组合型公司描述字符串（如：'已上市 · 1000-9999人 · 软件/IT服务、软件/IT服务 已审核'）
    返回: (company_size, industry)
    """
    if not raw_text:
        return "", ""
    
    # 剔除前置斜杠/空白与「已审核」字眼
    cleaned = re.sub(r'^[\s/]+', '', raw_text).replace('已审核', '').strip()
    # 按照中圆点、特殊分隔符或连续空格分割各段
    parts = [p.strip() for p in re.split(r'[·•\n\t|]+|\s{2,}', cleaned) if p.strip()]
    
    size = ""
    industry = ""
    financing_keywords = {
        '未融资', '天使轮', 'a轮', 'b轮', 'c轮', 'd轮', 'd轮及以上', 
        '已上市', '不需要融资', '战略融资', '上市', '已审核', '非营利组织', '国有企业'
    }
    
    for p in parts:
        p_clean = p.strip()
        # 匹配规模：含「人」或数字区间如 1000-9999人、20人以下、10000人以上、微型企业等
        if re.search(r'(\d+[-~至]\d+人|\d+人以[上下]|\d+人|少于\d+人|\d+以上|\b(微型|小型|中型|大型)企业)', p_clean):
            if not size:
                size = p_clean
        elif any(fk in p_clean.lower() for fk in financing_keywords) or re.match(r'入驻\d+年', p_clean):
            continue
        else:
            # 行业特征：长度>=2且非纯特殊符号
            if not industry and len(p_clean) >= 2:
                industry = p_clean
                
    return size, industry


def _extract_job_company_info(tab_or_pane, job_data):
    """从公司基本信息容器提取公司规模与所属行业（支持 2026 新版右侧分栏与独立详情页）"""
    try:
        size = ""
        industry = ""
        
        # 1. 优先定位 2026 结构化组合描述容器 (.job-company-info__desc / .job-detail-summary__company-meta / .company-info__desc)
        desc_ele = (
            tab_or_pane.ele('css:.job-company-info__desc', timeout=0.5)
            or tab_or_pane.ele('css:.job-detail-summary__company-meta', timeout=0.5)
            or tab_or_pane.ele('css:.company-info__desc', timeout=0.5)
            or tab_or_pane.ele('css:.company-card__desc', timeout=0.5)
        )
        if desc_ele and desc_ele.text.strip():
            s, ind = _parse_zhilian_company_desc(desc_ele.text)
            if s:
                size = s
            if ind:
                industry = ind

        # 2. 尝试从独立页/特定 DOM 的结构化 tag 容器提取
        if not size:
            scale_ele = (
                tab_or_pane.ele('css:.company-summary__icon--scale + .company-summary__text', timeout=0.3)
                or tab_or_pane.ele('css:.company-summary__text', timeout=0.3)
                or tab_or_pane.ele('css:.company-summary__item:has(.company-summary__icon--scale) .company-summary__text', timeout=0.2)
            )
            if scale_ele and scale_ele.text.strip():
                size = scale_ele.text.strip()

        if not industry:
            industry_ele = (
                tab_or_pane.ele('css:.company-summary__icon--industry + .company-summary__text', timeout=0.3)
                or tab_or_pane.ele('css:.company-summary__item:has(.company-summary__icon--industry) .company-summary__text', timeout=0.2)
            )
            if industry_ele and industry_ele.text.strip():
                industry = industry_ele.text.strip()

        # 3. 泛化遍历兜底：扫描所有可能的元数据子项
        if not size or not industry:
            candidates = tab_or_pane.eles('css:.company-summary__item, .company-info__item, .job-company-info p, .job-detail-summary span, .company-card__desc', timeout=0.5)
            for cand in (candidates or []):
                txt = cand.text.strip()
                if not txt:
                    continue
                s, ind = _parse_zhilian_company_desc(txt)
                if s and not size:
                    size = s
                if ind and not industry:
                    industry = ind

        if size:
            job_data['company_size'] = size
            print(f"      🏢 公司规模: {size}")
        if industry:
            job_data['industry'] = industry
            print(f"      🏭 所属行业: {industry}")
            
    except Exception as e:
        print(f"      ⚠️ 公司信息定位异常: {e}")


def _enrich_from_split_pane(page, right_pane, job_data):
    """点击卡片后从右侧分栏补抓字段（选择器已对 2026-08 真实 DOM 实证）：

    - 真实岗位链接：SPA 点击后地址栏路由 → zhaopin.com/job_XXXXX
    - 门牌级工作地址：.address-info__bubble / .job-detail-address__content
    - 公司规模/所属行业：.job-company-info__desc / .job-detail-summary__company-meta / .company-summary
    """
    if not right_pane:
        return

    # 1. 真实岗位链接（可独立打开的 jobdetail 格式）
    try:
        view_all = right_pane.ele('css:a[href*="jobdetail"]', timeout=1) or right_pane.ele('css:.job-company-info__view-all', timeout=0.5)
        href = (view_all.attr('href') or '') if view_all else ''
        if 'jobdetail' in href:
            clean = href.split('?')[0]
            if clean != job_data.get('job_link'):
                job_data['job_link'] = clean
                print(f"      🔗 真实岗位链接(jobdetail): {clean}")
    except Exception:
        pass
    try:
        if 'jobdetail' not in (job_data.get('job_link') or ''):
            cur_url = page.url or ""
            if '/job_' in cur_url or 'jobDetail' in cur_url or 'jobdetail' in cur_url:
                job_data['job_link'] = cur_url.split('?')[0]
    except Exception:
        pass

    # 2. 补抓公司规模与所属行业
    _extract_job_company_info(right_pane, job_data)

    # 3. 补抓门牌级详细工作地址
    _extract_job_work_address(right_pane, job_data)


def _process_single_fresh_card(page, job_ele, job_data, city, idx, total_count):
    """对未入库的新鲜岗位进行深度详情挖掘与入库"""
    print(f"   🔍 [{idx}/{total_count}] 正在下钻详情: {job_data['company_name']} - {job_data['job_title']}")
    
    cls = job_ele.attr('class') or ''
    try:
        if 'job-card' in cls:
            # 2026 新版分栏模式：点击卡片直接从右侧容器提取 JD + 补抓缺失字段
            job_ele.click(by_js=True)
            
            # 等待右侧分栏更新（校验公司名/岗位名匹配，避免读取到上一个卡片的残留渲染）
            c_name = (job_data.get('company_name') or '').strip()
            j_title = (job_data.get('job_title') or '').strip()
            right_pane = None
            for _ in range(8):
                right_pane = page.ele('.job-split-layout__right', timeout=0.3) or page.ele('.job-detail', timeout=0.3)
                if right_pane:
                    pane_txt = right_pane.text or ''
                    if (c_name and c_name in pane_txt) or (j_title and j_title in pane_txt):
                        break
                time.sleep(0.2)
                
            right_pane = page.ele('.job-split-layout__right', timeout=1) or page.ele('.job-detail', timeout=1)
            if right_pane:
                # JD 正文容器（2026-08 实证：job-detail-card__body 下的 .job-description）
                jd_ele = (right_pane.ele('.job-description', timeout=3)
                          or right_pane.ele('.job-detail-content', timeout=1)
                          or right_pane.ele('.job-detail-box', timeout=1))
                if jd_ele:
                    job_data['jd_text'] = jd_ele.text
                else:
                    # 兜底：整栏文本裁剪出「职位描述」到「工作地址」之间的正文，避免混入公司/HR 等噪音
                    pane_text = right_pane.text or ""
                    m_jd = re.search(r'职位描述[:：]?\s*(.*?)(?:工作地址|查看地图|职位类别|$)', pane_text, re.S)
                    job_data['jd_text'] = m_jd.group(1).strip() if m_jd else pane_text[:3000]
                print("      ✅ 右侧分栏详情抓取成功。")
            # 补抓真实岗位链接、公司规模、所属行业与门牌级工作地址
            _enrich_from_split_pane(page, right_pane, job_data)
        else:
            # 旧版新标签页模式
            sleep_duration = round(random.uniform(3, 8), 2)
            print(f"      ⏳ 防风控深度潜行: 等待 {sleep_duration} 秒...")
            time.sleep(sleep_duration)
            tab = page.new_tab(job_data['job_link'])
            _handle_edgeone_captcha(tab)
            _extract_job_publish_date(tab, job_data)
            _extract_job_detail_text(tab, job_data)
            _extract_job_company_info(tab, job_data)
            _extract_job_work_address(tab, job_data)
            tab.close()
    except Exception as e:
        print(f"      ⚠️ 详情获取异常: {e}")
        
    print(f"   📊 最终提取数据: \n"
          f"      - 职位: {job_data['job_title']}\n"
          f"      - 公司: {job_data['company_name']}\n"
          f"      - 城市: {job_data['city']}\n"
          f"      - 地址: {job_data['work_address']}\n"
          f"      - 薪资: {job_data['salary']}\n"
          f"      - 经验: {job_data['experience_req']}\n"
          f"      - 学历: {job_data['education_req']}\n"
          f"      - 行业: {job_data['industry']}\n"
          f"      - 规模: {job_data['company_size']}\n"
          f"      - 发布: {job_data['publish_date']}\n"
          f"      - 福利: {job_data['welfare_tags']}\n"
          f"      - 链接: {job_data['job_link']}\n"
          f"      - 详情长度: {len(job_data['jd_text'])} 字符")
          
    if save_single_job_to_db(job_data):
        print(f"   🕷️ [入库成功] 💰 {job_data['salary']}")
        return job_data, False
    return None, False

def _navigate_to_next_page(page, city, keyword, salary, current_page, is_sprint=False):
    current_page += 1
    # 极速跃迁时使用 0.7 秒轻量滑动，深度模式使用 2.0 秒防风控滑动
    wait_time = 0.7 if is_sprint else 2.0
    if not is_sprint:
        print(f"🔄 [瀑布流滚动] 正在向下滑动加载新岗位 (第 {current_page} 批)...")
    try:
        # 1. 优先向下滚动到底部触发瀑布流异步加载
        page.scroll.to_bottom()
        time.sleep(wait_time)
        
        # 2. 如果存在底部分页组件，辅助点击下一页
        next_btn = (
            page.ele('text:下一页', timeout=0.5)
            or page.ele('.soupager__btn--next', timeout=0.5)
            or page.ele('.el-pagination .btn-next', timeout=0.5)
        )
        if next_btn:
            btn_class = next_btn.attr('class') or ''
            if next_btn.attr('disabled') or 'disabled' in btn_class or 'is-disabled' in btn_class:
                print("到达最后一页/底部，抓取结束。")
                return False, current_page
            try:
                next_btn.click(by_js=True)
                time.sleep(wait_time)
            except Exception:
                pass

        return True, current_page
    except Exception as e:
        print(f"⚠️ 瀑布流滚动加载异常: {e}")
        return False, current_page

def _handle_empty_jobs(page, city, keyword, salary, consecutive_empty_scrolls, current_page):
    print("⚠️ 未截获到新数据，可能遇到了扫码风控拦截、页面假死或所有职位已抓取完毕。")
    if page.ele('.login-window', timeout=1) or page.ele('.geetest_window', timeout=1) or page.ele('.passport-login-container', timeout=1):
        print("🚨 发现智联招聘安全验证或强制登录弹窗！请立即在浏览器中手动完成验证...")
        time.sleep(30)
        return True, consecutive_empty_scrolls
    
    consecutive_empty_scrolls += 1
    if consecutive_empty_scrolls == 1:
        _handle_page_freeze(page, city, keyword, salary, current_page)
        return True, consecutive_empty_scrolls
    print("连续多次强制刷新自愈后仍未获取新数据，任务彻底停止。")
    return False, consecutive_empty_scrolls

def _get_job_elements(page):
    try:
        if page.wait.eles_loaded('.job-card', timeout=4):
            cards = page.eles('.job-card')
            if cards:
                return cards
    except Exception:
        pass
    try:
        if page.wait.eles_loaded('.joblist-box__iteminfo', timeout=3):
            return page.eles('.joblist-box__iteminfo')
    except Exception as e:
        print(f"⚠️ DOM 元素加载超时: {e}")
    return []

def _process_job_batch(page, job_elements, city, target, success_count, skip_count, current_page):
    """
    智能批次处理：
    - 快速探针：先用 0ms 内存指纹库扫描本批全部卡片的基本信息；
    - 极速跃迁态：如果本批 100% 均为已抓取的历史旧岗位，开启「极速跃迁模式」，折叠日志为 1 行并以 0.7s 快速推进；
    - 新鲜数据态：若发现新岗位，退出跃迁态，逐个卡片深度点击右侧分栏提取完整 JD、公司规模与工作地址入库。
    """
    total_in_batch = len(job_elements)
    if total_in_batch == 0:
        return success_count, skip_count, False

    # 1. 快速探针扫描
    card_probes = []
    for job_ele in job_elements:
        try:
            b_info = _extract_job_basic_info(job_ele, city)
            if b_info and b_info.get('job_title'):
                is_exist = check_job_exists(b_info['company_name'], b_info['job_title'], b_info['city'], b_info['job_link'])
                card_probes.append((job_ele, b_info, is_exist))
            else:
                card_probes.append((job_ele, None, True))
        except Exception:
            card_probes.append((job_ele, None, True))

    all_duplicate = all(is_exist for _, _, is_exist in card_probes)

    # 2. 极速跃迁分支：整批 100% 均为历史数据
    if all_duplicate:
        skip_count += total_in_batch
        print(f"⏩ [极速跃迁] 第 {current_page} 批 ({total_in_batch}/{total_in_batch} 岗位均已在库，跳过详情解析)，加速滑动下一批...")
        return success_count, skip_count, True

    # 3. 新鲜数据分支：逐个卡片深度提取
    print(f"🎯 [新鲜数据] 第 {current_page} 批截获 {total_in_batch} 个岗位（包含新岗位），进入深度解析模式...")
    for idx, (job_ele, b_info, is_exist) in enumerate(card_probes, 1):
        if not b_info or not b_info.get('job_title'):
            print("   ⏩ [跳过] 无法获取职位信息。")
            continue

        if is_exist:
            skip_count += 1
            print(f"   ⏩ [拦截] [{idx}/{total_in_batch}] {b_info['company_name']} - {b_info['job_title']} | 数据库已存在，跳过！")
            continue

        # 深度提取详情与入库
        res, is_skipped = _process_single_fresh_card(page, job_ele, b_info, city, idx, total_in_batch)
        if is_skipped:
            skip_count += 1
        elif res:
            success_count += 1

        if target > 0 and success_count >= target:
            print(f"   🎯 [目标拦截] 已成功抓取 {success_count} 个，满足目标要求，提前结束。")
            break

    return success_count, skip_count, False

def _drain_search_total(page, prev_total=0):
    """消费拦截队列，从包体（JSON 或 SSR HTML）提取搜索总数（分母）；拿不到保持原值。"""
    import re as _re
    total = prev_total or 0
    try:
        for packet in page.listen.steps(timeout=0.5):
            body = packet.response.body
            if isinstance(body, dict):
                nodes = [body]
                for _ in range(3):  # 嵌套 dict 展开三层，兼容 data.data 等结构
                    nodes += [v for n in nodes for v in n.values() if isinstance(v, dict)]
                for node in nodes:
                    for key in ('numFound', 'totalCount', 'total', 'totalNum', 'count'):
                        val = node.get(key)
                        if isinstance(val, int) and val > 0:
                            total = max(total, val)
                            break
                        if isinstance(val, str) and val.isdigit() and int(val) > 0:
                            total = max(total, int(val))
                            break
            elif isinstance(body, str):
                m = _re.search(r'"(?:numFound|totalCount|totalNum)"\s*:\s*(\d+)', body)
                if m and int(m.group(1)) > 0:
                    total = max(total, int(m.group(1)))
    except Exception:
        pass
    return total

def collect_waterfall(keyword, city, salary, start_page, target=0):
    """
    🌟 DrissionPage 核心：一次性完成列表解析与详情提取，支持瀑布流自适应极速跃迁与深度模式动态切换
    """
    search_terms = [t for t in [city, keyword, salary] if t]
    full_query_str = "-".join(search_terms)
    
    print(f"\n{'='*50}")
    print(f"📍 正在抓取智联招聘【{full_query_str}】的数据 (瀑布流极速跃迁模式)，目标数量: {target}")
    
    _init_memory_fingerprints()
    
    page = _setup_browser()
    listen_target = 'c/i/sou'
    print(f"📡 开启数据包拦截，监听特征: {listen_target} (同时支持 SSR 降维解析)")
    page.listen.start(listen_target)
    
    url = _build_zhilian_jobs_url(city, keyword, start_page)
    print(f"🌐 访问初始目标页: {url}")
    page.get(url)
    
    _apply_salary_filter(page, salary)

    # 解析搜索总数（分母）：首屏拦截包先消一次，循环结束后再补消兜底
    search_total = _drain_search_total(page)
    
    success_count = 0
    skip_count = 0
    consecutive_empty_scrolls = 0
    consecutive_sprint_batches = 0
    current_page = start_page
    
    while True:
        job_elements = _get_job_elements(page)
        
        if not job_elements:
            should_continue, consecutive_empty_scrolls = _handle_empty_jobs(page, city, keyword, salary, consecutive_empty_scrolls, current_page)
            if not should_continue:
                break
            continue

        consecutive_empty_scrolls = 0
        
        try:
            success_count, skip_count, is_sprint = _process_job_batch(page, job_elements, city, target, success_count, skip_count, current_page)
            
            if is_sprint:
                consecutive_sprint_batches += 1
                if consecutive_sprint_batches >= 20 and success_count == 0:
                    print(f"🏁 [抓尽收工] 连续 {consecutive_sprint_batches} 批均无新增岗位（已越过全部历史数据到达末尾），条件已抓尽，安全退出。")
                    break
            else:
                consecutive_sprint_batches = 0
                    
            if target > 0 and success_count >= target:
                break
                
            if not is_sprint:
                print("🎯 本批次处理完毕。准备进入下一页...")
            has_next, current_page = _navigate_to_next_page(page, city, keyword, salary, current_page, is_sprint=is_sprint)
            if not has_next:
                break
        except Exception as e:
            print(f"❌ 瀑布流处理出错: {e}")
            break
            
    # 解析搜索总数（分母）：拿不到不打印（上层走兜底规则）
    search_total = _drain_search_total(page, search_total)
    if search_total and search_total > 0:
        print(f"搜索总数 {search_total} 个")

    print(f"🎯 瀑布流抓取结束。总计新增入库 {success_count} 个，跳过 {skip_count} 个。")

def start_auto_patrol(start_page, keyword=None, city=None, salary=None, target=0):
    """主控引擎：按平台执行抓取"""
    print("🚀 启动 [智联招聘] 精准采集矩阵 (DrissionPage瀑布流引擎)")
    
    if keyword:
        print(f"🎯 使用调度器传入的搜索条件：keyword={keyword}, city={city}, target={target}")
        collect_waterfall(keyword, city or '', salary or '', start_page, target)
        print("\n🏁 本次抓取指令已全部执行完毕！程序退出。")
    else:
        print("❌ 错误：未提供搜索关键词 (--keyword)！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="智联招聘 多平台单页采集器 (DrissionPage)")
    parser.add_argument('-p', '--page', type=int, default=1, help="指定要抓取的页码，默认是 1")
    parser.add_argument('--platform', type=str, default=None, help="指定平台名称（兼容调度器）")
    parser.add_argument('--keyword', type=str, default=None, help="搜索关键词")
    parser.add_argument('--city', type=str, default=None, help="搜索城市")
    parser.add_argument('--salary', type=str, default=None, help="薪资范围")
    parser.add_argument('--target', type=int, default=0, help="本页需要抓取的目标数量")
    args = parser.parse_args()
    
    start_auto_patrol(args.page, args.keyword, args.city, args.salary, args.target)
