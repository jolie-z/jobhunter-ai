import json
import os
import sys
import time
import random
import secrets
import sqlite3
import datetime
import argparse

# 2026-09-24 反爬改造（plan-review R2 PASS）：patchright 替换官方 playwright。
# patchright 修补 CDP Runtime.enable 泄漏与自动化启动参数；API 同构。
# 浏览器启动统一走 engine.launch_or_fail（本文件不再直接使用 sync_playwright）。


# ==========================================
# 核心路径与配置
# ==========================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

# 端口/profile 口径与 51job_auto_delivery 同源：registry 优先，独立脚本环境 fallback（同其 :50-57 先例）
try:
    from app.session.registry import get_profile_path
    L51_PROFILE_DIR = get_profile_path("51job")
except Exception:
    L51_PROFILE_DIR = os.path.join(PARENT_DIR, 'data', 'profiles', '51job')

# patchright 直启引擎（唯一实现）：互斥锁 + 持久化上下文 + 登录态双确认
from engine import launch_or_fail, touch_heartbeat, migrate_legacy_cookies_if_needed

DB_PATH = os.path.join(PARENT_DIR, 'data', 'job_hunter.db')
# legacy cookie 路径保留：engine.migrate_legacy_cookies_if_needed 一次性迁移用
COOKIE_FILE = os.path.join(CURRENT_DIR, '51job_cookies.json')

# 51job 城市代码字典
# 城市薪资字典 + raw_jobs 入库/去重 → storage.py（2026-09-24 拆分，防单文件超 500 行）
from storage import (DB_PATH, get_city_code, get_salary_code, save_to_raw_db, check_exists)

# 详情页懒加载区块提取 JS：福利标签/关键字/公司信息/行业/规模。
# 2026-09-25 真机实证：div.job-corp 与 div.corp-card 不滚动就不渲染（Vue 懒加载），
# 调用方必须先逐步滚动再 evaluate。关键字 innerText 是粘连串，必须逐 <a> 取。
_DETAIL_EXTRA_JS = r"""() => {
    const out = {welfare_tags: "", hr_skill_tags: "", company_intro: "", industry: "", company_size: ""};
    const tags = document.querySelector('.job-detail div.tags');
    if (tags) out.welfare_tags = tags.innerText.split('\n').map(s => s.trim()).filter(Boolean).join('、');
    const kwParagraph = [...document.querySelectorAll('p.fp')].find(e => (e.innerText || '').trim().startsWith('关键字'));
    if (kwParagraph) {
        const kws = [...kwParagraph.querySelectorAll('a')].map(a => a.innerText.trim()).filter(Boolean);
        if (kws.length) out.hr_skill_tags = [...new Set(kws)].join('、');
    }
    const jobCorpEl = document.querySelector('div.job-corp');
    if (jobCorpEl) {
        const lines = (jobCorpEl.innerText || '').split('\n').map(s => s.trim());
        while (lines.length && !lines[0]) lines.shift();
        if (lines[0] === '公司信息') lines.shift();
        out.company_intro = lines.join('\n').trim();
    }
    const card = document.querySelector('div.corp-card');
    if (card) {
        const lines = (card.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
        // 规模枚举全档：少于50人 / 50-150人 / … / 5000-10000人 / 10000人以上
        const sizeLine = lines.find(l => /^(少于)?\d+([-~]\d+)?人(以上)?$/.test(l));
        if (sizeLine) out.company_size = sizeLine;
        const viewIdx = lines.findIndex(l => l.includes('查看所有职位'));
        const industryLine = viewIdx > 0 ? lines[viewIdx - 1]
            : lines.find(l => /计算机|互联网|软件|服务|科技|电子|通信|金融|教育|医疗|制造|房产|贸易|物流|餐饮|快消|能源|化工|汽车|医药/.test(l));
        if (industryLine) {
            const links = [...card.querySelectorAll('a')].map(a => a.innerText.trim()).filter(Boolean);
            const parts = [...new Set(links.filter(t => industryLine.includes(t)))];
            out.industry = (parts.length ? parts.join('·') : industryLine).slice(0, 60);
        }
    }
    return out;
}"""


def fetch_detail_info(context, job_link):
    """详情页下钻：一次开页同时提取「地址 + JD + 福利/关键字/公司信息/行业/规模」。

    2026-09-25 字段补采（用户对照详情页裁决）：sensorsdata 卡片只有列表字段
    （jobId/jobTitle/jobSalary/jobArea/jobYear/jobDegree/jobTime），公司信息/
    福利标签/关键字/行业/规模都在详情页 DOM；job-corp 与 corp-card 懒加载，
    必须先滚动。返回 dict（键见 _DETAIL_EXTRA_JS + address + jd_text），
    任一字段失败落空串不抛异常。
    """
    result = {"address": "", "jd_text": "", "welfare_tags": "", "hr_skill_tags": "",
              "company_intro": "", "industry": "", "company_size": ""}
    page = None
    try:
        page = context.new_page()
        page.goto(job_link, wait_until="domcontentloaded", timeout=20000)

        # 1. 优先尝试获取地图完整地址 (如截图所示的新版UI)
        map_address_loc = page.locator("*:has-text('地图完整地址：')").last
        if map_address_loc.count() > 0:
            result["address"] = map_address_loc.inner_text().replace('地图完整地址：', '').strip()

        if not result["address"]:
            map_address_loc_en = page.locator("*:has-text('地图完整地址:')").last
            if map_address_loc_en.count() > 0:
                result["address"] = map_address_loc_en.inner_text().replace('地图完整地址:', '').strip()

        if not result["address"]:
            # 2. 回退到传统的 上班地址
            address_loc = page.locator("p.fp:has-text('上班地址')")
            if address_loc.count() > 0:
                result["address"] = address_loc.first.inner_text().replace('上班地址：', '').replace('查看地图', '').strip()

        # 3. JD 正文：div.bmsg.job_msg（Vue SSR 异步渲染，首次未命中再等 5s）。
        #    JD 提取独立 try：其异常只落空 jd_text，不抹除已提取成功的地址（R1 P2-5）。
        try:
            _jd_sel = "div.bmsg.job_msg"
            jd_loc = page.locator(_jd_sel)
            if jd_loc.count() == 0:
                page.wait_for_selector(_jd_sel, timeout=5000)
            if jd_loc.count() > 0:
                result["jd_text"] = jd_loc.first.inner_text().strip()
        except Exception:
            result["jd_text"] = ""

        # 4. 懒加载区块：逐步滚动触发渲染后整块提取（独立 try，失败不拖累前两步）。
        try:
            for _ in range(4):
                page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.8))")
                page.wait_for_timeout(600)
            result.update({k: v for k, v in page.evaluate(_DETAIL_EXTRA_JS).items() if v})
        except Exception:
            pass

        return result
    except Exception:
        return result
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
        # 2026-09-24 SSR-DOM 双源键名兼容：sensorsdata 新键（jobTitle/jobArea/jobSalary/
        # jobDegree/jobYear/jobTime）与旧接口键（jobName/jobAreaString/provideSalaryString...）
        # 双读——哪边有值用哪边，两条数据源零改动共存。
        title = item.get('jobTitle') or item.get('jobName', '未知')
        company = item.get('companyName', '未知')
        city = item.get('jobArea') or item.get('jobAreaString', '')
        # 2026-09-24 详情链接修正：卡片整卡 <a> 的加密串 href 落地是「公司简介页」非岗位详情，
        # 统一改用纯数字 jobId 拼 https://jobs.51job.com/all/{jobId}.html（真机验证直落岗位页含 JD）。
        # sensorsdata 的 jobId 是纯数字（如 170250651）；含非数字字符时视为异常弃用。
        _job_id = str(item.get('jobId') or '').strip()
        link = f"https://jobs.51job.com/all/{_job_id}.html" if _job_id.isdigit() else item.get('jobHref')

        if check_exists(company, title, city):
            print(f"      ⏩ [跳过] {company} - {title} (已在库)")
            continue

        print(f"      🔍 [下钻] 获取详情页信息(地址+JD+公司字段): {company} - {title}")

        detail = fetch_detail_info(context, link) if link else {}

        card_tags = item.get('jobLabel') or ', '.join(item.get('jobTags') or [])
        job_data = {
            'job_link': link,
            'job_title': title,
            'company_name': company,
            'city': city,
            # 详情页下钻值优先，sensorsdata 卡片键兜底（双源共存，2026-09-25 字段补采）
            'jd_text': detail.get('jd_text') or item.get('jobDescribe') or '无详情',
            'salary': item.get('jobSalary') or item.get('provideSalaryString', '面议'),
            'work_address': detail.get('address') if detail.get('address') else city,
            'hr_activity': ', '.join(item.get('hrLabels', [])),
            'industry': detail.get('industry') or item.get('companyIndustryType1Str', '其他'),
            'welfare_tags': detail.get('welfare_tags') or card_tags,
            'company_size': detail.get('company_size') or item.get('companySizeString', '未知规模'),
            'education_req': item.get('jobDegree') or item.get('degreeString', '不限'),
            'experience_req': item.get('jobYear') or item.get('workYearString', '不限'),
            'hr_skill_tags': detail.get('hr_skill_tags') or card_tags,
            'company_intro': detail.get('company_intro') or item.get('companyInfo', ''),
            'role': 'HR',
            'publish_date': (item.get('jobTime') or item.get('issueDateString') or '').split(' ')[0] or datetime.datetime.now().strftime("%Y-%m-%d"),
        }

        if save_to_raw_db(job_data):
            success_count += 1
            print(f"   🕷️ [抓取成功] 🏢 {job_data.get('company_name', '未知公司')} | 💼 {job_data.get('job_title', '未知岗位')} | 💰 {job_data.get('salary', '未知薪资')}")
        
        sleep_time = secrets.SystemRandom().randint(15, 35) # 原来是 5-15，现在改为 15-35
        print(f"   💤 深度潜行，随机休眠 {sleep_time} 秒...")
        time.sleep(sleep_time)
        
    return success_count

# L3 全平台终止信号（进程内）：start_collector 每词循环前检查，命中即停止后续词
_PLATFORM_BLOCKED: list = []


def _collect_via_api(context, keyword, city_code, salary_code, target_page, target=0):
    """SSR-DOM 采集主路径（2026-09-24 真机修正，feature flag 51JOB_API_COLLECT 默认开）。

    真机结论：现版搜索页是 Vue SSR，岗位数据在 DOM 的 sensorsdata 属性里，
    无 JSON 接口可调（旧 search-pc 已废弃，请求返回 200+text/html 首页）。
    主路径改为：打开搜索页 → DOM 提取 → 点「下一页」→ 再提取——
    每页零数据请求（暴露面最小），JD 由 process_job_items 逐条详情页补采。
    风控处置（fail-closed，plan §3.4/§3.7）不变：
      L3（滑块/封禁）→ 立即终止本词并向上传播信号；
      L2（限流）→ 停止当前词（调用方冷却 30 分钟）；
      L1（技术异常）→ 重试 1 次后允许降级 DOM（_collect_via_dom）。
    返回 (success_count, risk_level)。
    """
    from api_client import fetch_search_page, real_last_page, HARD_MAX_PAGES
    from risk_guard import RiskLevel, should_terminate_task, L2_COOLDOWN_SECS
    import progress_tracker

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        progress_tracker.ensure_table(conn)
    finally:
        conn.close()

    search_page = context.new_page()
    try:
        # 打开一次搜索页：保住登录上下文与 cookie 刷新（页内 fetch 才有效）
        url = f"https://we.51job.com/pc/search?keyword={keyword}&jobArea={city_code}&salary={salary_code}"
        try:
            search_page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception:
            print("      💡 搜索页加载超时，核心上下文可能已建立，强制放行...")

        collected = 0
        max_page = min(target_page, HARD_MAX_PAGES)
        retry_used = 0
        # 修复（2026-09-24 指定页码未生效）：SSR 搜索 URL 不支持页码参数，必须点击翻页。
        # 先导航到第 1 页 → 连点「下一页」(start_page-1) 次跳到目标起始页（跳页阶段只导航不采集）
        # → 从 target_page 开始逐页提取。
        page_num = max_page = min(target_page, HARD_MAX_PAGES)
        if target_page > 1:
            print(f"      ⏭️ 跳页导航：第 1 页 → 第 {target_page} 页（不采集，纯导航）...")
            # 2026-09-24 真机修正：直达页码 li（.el-pager li.number 精确匹配），
            # 弃用 btn-next 逐步点（此前选择器误中 disabled 的 btn-prev 导致"第1页触底"假象）
            try:
                search_page.wait_for_selector(".el-pager li.number", timeout=10000)  # 分页条渲染完成再点
            except Exception:
                pass
            goto_ok = search_page.evaluate("""(n) => {
                for (const l of document.querySelectorAll('.el-pager li.number')) {
                    if (l.innerText.trim() === String(n)) { l.click(); return true; }
                }
                return false;
            }""", target_page)
            if goto_ok:
                try:
                    search_page.wait_for_selector(".joblist-item", timeout=15000)
                except Exception:
                    pass
                time.sleep(secrets.SystemRandom().randint(3, 6))
                page_num = max_page = target_page
                print(f"      ✅ 已直达第 {target_page} 页，开始采集")
            else:
                # 页码 li 不在（页码 > 展示范围）→ btn-next 翻到可见再点，或目标页超界改从1页起
                print(f"      ⚠️ 页码 {target_page} 不在分页条展示范围，改从第 1 页开始采集")
                page_num = max_page = 1
        while page_num <= max_page:
            if page_num > target_page:
                # 采集中正常翻页：点「下一页」按钮触发页面更新（无数据请求）
                next_ok = search_page.evaluate("""() => {
                    const btn = document.querySelector('.el-pagination button.btn-next');
                    if (btn && !btn.disabled) { btn.click(); return true; }
                    return false;
                }""")
                if not next_ok:
                    print(f"      ⚠️ 已到最后一页（无更多数据），第 {page_num} 页停止翻页")
                    break
                try:
                    search_page.wait_for_selector(".joblist-item", timeout=15000)
                except Exception:
                    print(f"      ⚠️ 翻页后卡片未渲染，停止翻页")
                    break
                time.sleep(secrets.SystemRandom().randint(4, 8))  # 翻页间轻休眠
            result = fetch_search_page(search_page, keyword, city_code, salary_code, page_num)
            level = result["level"]

            if level == RiskLevel.L3_BLOCKED:
                print(f"      🚨 [L3] 风控信号（{result['reason']}）→ 立即终止任务（fail-closed，绝不硬刚）")
                if should_terminate_task(level):
                    _PLATFORM_BLOCKED.append(True)  # 全平台终止信号，start_collector 消费
                return collected, level
            if level == RiskLevel.L2_THROTTLE:
                print(f"      ⏸️ [L2] 限流信号（{result['reason']}）→ 停止当前词，冷却 {L2_COOLDOWN_SECS//60} 分钟")
                return collected, level
            if level == RiskLevel.L1_SOFT:
                if retry_used < 1:
                    retry_used += 1
                    print(f"      🔁 [L1] 技术异常（{result['reason']}），重试 1/1 ...")
                    time.sleep(8)
                    continue
                # P1 修复：L1 重试后必须真的降级 DOM——返回 (collected, None) 哨兵，
                # 外层 collect_51job_task 见 level=None 走 _collect_via_dom（此前返回数字
                # 被外层当成功直接 return，降级分支沦为死代码）
                print(f"      ⬇️ [L1] 重试后仍异常 → 降级 DOM 路径（仅 L1 可降级）")
                return (collected if collected else None), None

            # L0：正常响应
            items = result["items"]
            total = result["total"]
            if page_num == 1:
                if total:
                    real_end = real_last_page(total)
                    print(f"      📊 搜索总数 {total} → 真实末页 {real_end}")
                    # P1 修复：末页收窄必须落到循环边界，否则仍会越界请求
                    max_page = min(max_page, real_end)
                elif not items:
                    print("      ✅ 合法零结果（totalCount=0），本词完成")
                    _mark_progress(keyword, city_code, salary_code)
                    return 0, level

            if not items:
                print(f"      ⚠️ 第 {page_num} 页空（越界或末页），停止翻页")
                break

            print(f"      ✅ [API] 第 {page_num}/{min(max_page, real_last_page(total) if total else max_page)} 页捕获 {len(items)} 岗位")
            collected += process_job_items(context, items, target=max(0, target - collected))
            touch_heartbeat()
            if target > 0 and collected >= target:
                print(f"\n🎯 [51job 配额达成] 已入库 {collected} 条，提前收工。")
                break

            page_num += 1
            sleep_time = secrets.SystemRandom().randint(15, 35)
            print(f"   💤 深度潜行，随机休眠 {sleep_time} 秒...")
            time.sleep(sleep_time)

        _mark_progress(keyword, city_code, salary_code)
        return collected, RiskLevel.L0_OK
    finally:
        try:
            search_page.close()
        except Exception:
            pass


def _mark_progress(keyword, city_code, salary_code):
    """词级检查点落库（同词 24h 内跳过）。失败只告警不阻断。"""
    try:
        import progress_tracker
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            key = progress_tracker.combo_key(keyword, city_code, salary_code)
            progress_tracker.mark_collected(conn, key)
            print(f"      📌 词级检查点已记录: {key}（24h 内跳过）")
        finally:
            conn.close()
    except Exception as e:
        print(f"      ⚠️ 词级检查点写入失败（不阻断）: {e}")


def collect_51job_task(context, keyword, city_name, target_page, target_salary, target=0) -> bool:
    """执行单一搜索任务。API 路径优先（flag 控制），L1 降级 DOM，L2/L3 fail-closed。

    返回 True=本页真实采集过（含零结果页，DOM 已触碰，可记账 last_touched）；
    返回 False=被词级检查点跳过（本页数据未触碰，调用方不得记账 last_touched）。
    """
    city_code = get_city_code(city_name)
    salary_code = get_salary_code(target_salary)

    print(f"🚀 启动采集任务 | 关键词: {keyword} | 城市: {city_name} (代码: {city_code}) | 薪资: {target_salary} | 目标页码: {target_page}")
    print(f"\n{'='*40}")

    # 词级检查点：同词 24h 内跳过（账号级节流，防重复高频抓同一词）
    try:
        import progress_tracker
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            key = progress_tracker.combo_key(keyword, city_code, salary_code)
            if progress_tracker.should_skip(conn, key):
                print(f"⏭️ [词级检查点] {key} 24h 内已采集过，跳过（防重复触发风控）")
                return False  # 本页数据未触碰：调用方不得记账 last_touched
        finally:
            conn.close()
    except Exception as e:
        print(f"⚠️ 词级检查点读取失败（不阻断，继续采集）: {e}")

    api_enabled = os.environ.get("51JOB_API_COLLECT", "1") == "1"
    if api_enabled:
        print("📍 [51job] 站内 API 采集模式（请求暴露面最小化）")
        try:
            collected, level = _collect_via_api(context, keyword, city_code, salary_code, target_page, target=target)
        except Exception as e:
            # API 通道整体崩溃（页内执行环境故障）→ 按 L1 降级，绝不静默吞掉
            print(f"      ⬇️ [L1] API 通道异常（{str(e)[:80]}）→ 降级 DOM 路径")
            collected, level = None, None
        if collected is not None and level is not None:
            if int(level) >= 2:
                # L2/L3 已 fail-closed 停止：记录检查点失败状态由上层任务调度感知（打印告警）
                print(f"      🛑 本词以风险等级 {int(level)} 终止，当日不再自动重试（fail-closed）")
            print(f"      🎯 本词 API 模式采集入库 {collected} 条。")
            return True
        # collected is None → API 通道崩溃，落入 DOM 降级

    _collect_via_dom(context, keyword, city_code, salary_code, target_page, target_salary, target)
    return True

def _collect_via_dom(context, keyword, city_code, salary_code, target_page, target_salary, target=0):
    """旧 DOM 路径（降级用，2026-09-24 起为 L1 技术异常专用；原 collect_51job_task 主体）。

    已适配 patchright 持久化上下文：无 CDP、无 cookie 注入，登录态由 Profile 自持。
    """
    print(f"📍 [51job] DOM 降级模式（仅在 L1 技术异常时允许；L2/L3 严禁走此路径硬刚风控）")
    print(f"📍 [51job] 正在准备抓取第 {target_page} 页...")

    captured_data = []
    def on_response(response):
        if "api/job/search" in response.url and response.status == 200:
            try:
                captured_data.append(response.json())
            except Exception:
                pass

    search_page = context.new_page()
    try:  # R3 P2 兑现：页生命周期由 finally 保证（goto 超时/异常分支不再泄漏 Page）
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
            return

        if target_page > 1:
            if not navigate_to_target_page(search_page, target_page, captured_data):
                return

        job_items, search_total = extract_job_items(captured_data)
        if not job_items:
            return

        if search_total and search_total > 0:
            print(f"搜索总数 {search_total} 个")

        print(f"      ✅ 成功到达目标第 {target_page} 页！本页捕获到 {len(job_items)} 个岗位，开始深度处理...")

        success_count = process_job_items(context, job_items, target=target)

        print(f"      🎯 本页成功采集并入库 {success_count} 条数据。")
        _mark_progress(keyword, city_code, salary_code)
    finally:
        try:
            search_page.close()
        except Exception:
            pass


def _inject_cookies_if_available(context):
    """【已废弃】cookie 注入下线（2026-09-24 反爬改造）：注入 cookie 与环境指纹不一致是风控泄漏点。

    登录态现由持久化 Profile 原生承载；legacy cookie 的一次性迁移在 engine.launch_or_fail
    内完成（migrate_legacy_cookies_if_needed，Profile 无 51job cookie 时才执行）。
    保留空壳仅为兼容可能的旧调用点，永远返回 False。
    """
    return False


def start_collector(target_page, keyword=None, city=None, salary=None, target=0) -> bool:
    """启动采集矩阵。返回 True=至少一页真实采集过；False=全部页被词级检查点跳过。"""

    if not keyword:
        print("❌ 错误：缺少搜索关键词。请在调度器或命令行中传入 keyword 参数。")
        return False

    print(f"🎯 使用调度器传入的搜索条件：keyword={keyword}, city={city}, salary={salary}")
    tasks = [{'keyword': keyword, 'city': city or '', 'salary': salary or ''}]

    # 🛡️ 2026-09-24 反爬改造：patchright 直启真实 Edge（持久化 Profile），替代 CDP 附着。
    # 互斥走 .engine_lock（单一持有者模型）；登录态双确认（标记+DOM），失效即停绝不硬刚。
    try:
        ctx_mgr = launch_or_fail(purpose="collect")
    except RuntimeError as e:
        print(f"⛔ [引擎守卫] {e}")
        return False

    with ctx_mgr as context:
        # legacy cookie 迁移已在 engine.launch_or_fail 内完成（幂等单点），此处不再重复调用
        for i, task in enumerate(tasks):
            kw = task.get('keyword', '')
            city_name = task.get('city', '')
            target_salary = task.get('salary', '')

            if _PLATFORM_BLOCKED:
                print(f"🛑 [fail-closed] 前序关键词触发 L3 风控，终止全部后续任务（当日不再自动重试）")
                break
            print(f"\n▶️ 执行任务 [{i+1}/{len(tasks)}]: 【{kw} | {city_name} | 薪资: {target_salary}】")
            touched = collect_51job_task(context, kw, city_name, target_page, target_salary, target=target)
            touch_heartbeat()  # 刷新引擎锁心跳，防长任务被误判 stale

            if i < len(tasks) - 1:
                print("💤 任务切换，休眠 60 秒...")
                time.sleep(60)

        # with 退出即优雅关闭：cookie 落盘 + 释放引擎锁
        return touched

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="51job 指定页码单页抓取工具")
    parser.add_argument('-p', '--page', type=int, required=True, help="需要抓取的页码，例如: -p 3")
    parser.add_argument('--platform', type=str, default=None, help="指定平台名称（兼容调度器）")
    parser.add_argument('--keyword', type=str, default=None, help="搜索关键词")
    parser.add_argument('--city', type=str, default=None, help="搜索城市")
    parser.add_argument('--salary', type=str, default=None, help="薪资范围")
    parser.add_argument('--target', type=int, default=0, help="剩余入库配额（0=不限制），凑满即停防超收")

    args = parser.parse_args()
    touched = start_collector(args.page, args.keyword, args.city, args.salary, target=args.target)
    # 退出码契约（nl_controller 记账依赖）：
    #   0 = 本页真实采集过（可记账 last_touched）
    #   3 = 词级检查点跳过（数据未触碰，不记账）
    #   2 = 配置/守卫错误（缺关键词、引擎锁拒绝等，不记账且需人工介入）
    sys.exit(0 if touched else 3)