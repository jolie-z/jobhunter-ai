"""
使用 Playwright 获取 BOSS 直聘简历页面
"""

import asyncio
from playwright.async_api import async_playwright
import json
import os
import sys

# 路径配置
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)
_DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, 'data')
os.makedirs(_DATA_DIR, exist_ok=True)

if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_profile

# 🛡️ profile 统一走 registry（与主链路同一份登录态）；私有 profile 会与主链路互不见登录
BOSS_PROFILE_DIR = get_platform_profile("boss")


async def scrape_boss_resume_with_playwright():
    """使用 Playwright 获取 BOSS 简历页面"""
    print("\n🔄 启动 Playwright 浏览器...")

    async with async_playwright() as p:
        # 启动浏览器，复用现有的登录态
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=BOSS_PROFILE_DIR,
            headless=False,  # 显示浏览器窗口
            args=['--disable-blink-features=AutomationControlled']
        )

        page = await browser.new_page()

        print("正在访问 BOSS 简历管理页面...")
        await page.goto("https://www.zhipin.com/web/geek/resume", timeout=60000)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(5)

        # 截图
        screenshot_path = os.path.join(_DATA_DIR, 'boss_resume_screenshot.png')
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"✅ 截图已保存到: {screenshot_path}")

        # 获取页面源码
        html = await page.content()
        html_path = os.path.join(_DATA_DIR, 'boss_resume.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"✅ 页面源码已保存到: {html_path}")

        # 解析简历字段
        resume_data = await parse_resume_from_page(page)

        # 保存字段数据
        json_path = os.path.join(_DATA_DIR, 'boss_fields.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(resume_data, f, ensure_ascii=False, indent=2)
        print(f"✅ 字段数据已保存到: {json_path}")

        await browser.close()

        return resume_data


async def parse_resume_from_page(page) -> dict:
    """从页面解析简历字段"""
    print("\n📋 正在解析页面简历字段...")

    resume_data = {}

    # ============================================================
    # 1. 基本信息
    # ============================================================
    print("  1. 解析基本信息...")

    # 姓名
    name_selectors = [
        'css:.user-info-name',
        'css:.name',
        'css:[class*="name"]',
        'xpath://*[@class="user-info-name"]',
    ]

    name = ''
    for selector in name_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                name = await elem.text_content()
                if name and name.strip():
                    name = name.strip()
                    break
        except:
            continue

    resume_data['name'] = {
        'label': '姓名',
        'required': True,
        'type': 'text',
        'current_value': name
    }

    # 联系方式（手机号、邮箱）
    contact_selectors = [
        'css:.user-info-contact',
        'css:.contact-info',
        'css:[class*="contact"]',
    ]

    contact_text = ''
    for selector in contact_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                contact_text = await elem.text_content()
                if contact_text:
                    break
        except:
            continue

    import re
    phone_match = re.search(r'1[3-9]\d{9}', contact_text) if contact_text else None
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', contact_text) if contact_text else None

    resume_data['phone'] = {
        'label': '手机号',
        'required': True,
        'type': 'text',
        'current_value': phone_match.group() if phone_match else ''
    }

    resume_data['email'] = {
        'label': '邮箱',
        'required': False,
        'type': 'text',
        'current_value': email_match.group() if email_match else ''
    }

    # 求职状态
    status_selectors = [
        'css:.job-status',
        'css:[class*="status"]',
        'css:.user-status',
    ]

    status = ''
    for selector in status_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                status = await elem.text_content()
                if status:
                    status = status.strip()
                    break
        except:
            continue

    resume_data['job_status'] = {
        'label': '求职状态',
        'required': False,
        'type': 'select',
        'options': ['在职-月内到岗', '在职-考虑机会', '在职-暂不考虑', '离职'],
        'current_value': status
    }

    # ============================================================
    # 2. 求职期望
    # ============================================================
    print("  2. 解析求职期望...")

    expect_selectors = [
        'css:.expect-section',
        'css:.job-expect',
        'css:[class*="expect"]',
    ]

    expect_text = ''
    for selector in expect_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                expect_text = await elem.text_content()
                if expect_text:
                    break
        except:
            continue

    if expect_text:
        # 解析期望职位、城市、薪资
        job_match = re.search(r'期望职位[：:]\s*(.+?)(?:,|，|$)', expect_text)
        city_match = re.search(r'期望城市[：:]\s*(.+?)(?:,|，|$)', expect_text)
        salary_match = re.search(r'期望薪资[：:]\s*(.+?)(?:,|，|$)', expect_text)

        resume_data['expected_job'] = {
            'label': '期望职位',
            'required': True,
            'type': 'text',
            'current_value': job_match.group(1).strip() if job_match else ''
        }

        resume_data['expected_city'] = {
            'label': '期望城市',
            'required': True,
            'type': 'text',
            'current_value': city_match.group(1).strip() if city_match else ''
        }

        resume_data['expected_salary'] = {
            'label': '期望薪资',
            'required': False,
            'type': 'text',
            'current_value': salary_match.group(1).strip() if salary_match else ''
        }

    # ============================================================
    # 3. 教育经历
    # ============================================================
    print("  3. 解析教育经历...")

    edu_selectors = [
        'css:.edu-section',
        'css:.education-section',
        'css:[class*="edu"]',
    ]

    edu_text = ''
    for selector in edu_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                edu_text = await elem.text_content()
                if edu_text:
                    break
        except:
            continue

    if edu_text:
        resume_data['education'] = {
            'label': '教育经历',
            'required': True,
            'type': 'array',
            'fields': {
                'school': {'label': '学校名称', 'required': True, 'type': 'text'},
                'major': {'label': '专业', 'required': True, 'type': 'text'},
                'degree': {'label': '学历', 'required': True, 'type': 'select',
                          'options': ['初中及以下', '中专/中技', '高中', '大专', '本科', '硕士', '博士']},
                'start_date': {'label': '入学时间', 'required': True, 'type': 'date'},
                'end_date': {'label': '毕业时间', 'required': False, 'type': 'date'},
                'description': {'label': '描述', 'required': False, 'type': 'textarea', 'max_length': 500}
            },
            'current_value': []
        }

    # ============================================================
    # 4. 工作经历
    # ============================================================
    print("  4. 解析工作经历...")

    work_selectors = [
        'css:.work-section',
        'css:.experience-section',
        'css:[class*="work"]',
    ]

    work_text = ''
    for selector in work_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                work_text = await elem.text_content()
                if work_text:
                    break
        except:
            continue

    if work_text:
        resume_data['work_experience'] = {
            'label': '工作经历',
            'required': True,
            'type': 'array',
            'fields': {
                'company': {'label': '公司名称', 'required': True, 'type': 'text'},
                'position': {'label': '职位名称', 'required': True, 'type': 'text'},
                'start_date': {'label': '入职时间', 'required': True, 'type': 'date'},
                'end_date': {'label': '离职时间', 'required': False, 'type': 'date'},
                'description': {'label': '工作描述', 'required': False, 'type': 'textarea', 'max_length': 1000}
            },
            'current_value': []
        }

    # ============================================================
    # 5. 项目经历
    # ============================================================
    print("  5. 解析项目经历...")

    project_selectors = [
        'css:.project-section',
        'css:[class*="project"]',
    ]

    project_text = ''
    for selector in project_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                project_text = await elem.text_content()
                if project_text:
                    break
        except:
            continue

    if project_text:
        resume_data['projects'] = {
            'label': '项目经历',
            'required': False,
            'type': 'array',
            'fields': {
                'project_name': {'label': '项目名称', 'required': True, 'type': 'text'},
                'project_role': {'label': '担任角色', 'required': False, 'type': 'text'},
                'start_date': {'label': '开始时间', 'required': True, 'type': 'date'},
                'end_date': {'label': '结束时间', 'required': False, 'type': 'date'},
                'project_description': {'label': '项目描述', 'required': False, 'type': 'textarea', 'max_length': 1000}
            },
            'current_value': []
        }

    # ============================================================
    # 6. 优势亮点
    # ============================================================
    print("  6. 解析优势亮点...")

    advantage_selectors = [
        'css:.advantage-section',
        'css:.self-evaluation',
        'css:[class*="advantage"]',
    ]

    advantage_text = ''
    for selector in advantage_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                advantage_text = await elem.text_content()
                if advantage_text:
                    break
        except:
            continue

    resume_data['personal_advantage'] = {
        'label': '优势亮点',
        'required': False,
        'type': 'textarea',
        'max_length': 500,
        'current_value': advantage_text.strip() if advantage_text else ''
    }

    # ============================================================
    # 7. 技能标签
    # ============================================================
    print("  7. 解析技能标签...")

    skill_selectors = [
        'css:.skill-section',
        'css:.skills-section',
        'css:[class*="skill"]',
    ]

    skill_text = ''
    for selector in skill_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                skill_text = await elem.text_content()
                if skill_text:
                    break
        except:
            continue

    resume_data['skill_tags'] = {
        'label': '技能标签',
        'required': False,
        'type': 'tags',
        'current_value': []
    }

    # ============================================================
    # 8. 证书
    # ============================================================
    print("  8. 解析证书...")

    cert_selectors = [
        'css:.cert-section',
        'css:.certificate-section',
        'css:[class*="cert"]',
    ]

    cert_text = ''
    for selector in cert_selectors:
        try:
            elem = await page.query_selector(selector)
            if elem:
                cert_text = await elem.text_content()
                if cert_text:
                    break
        except:
            continue

    resume_data['certificates'] = {
        'label': '证书',
        'required': False,
        'type': 'array',
        'fields': {
            'cert_name': {'label': '证书名称', 'required': True, 'type': 'text'},
            'issuing_authority': {'label': '颁发机构', 'required': False, 'type': 'text'},
            'obtain_date': {'label': '获得时间', 'required': False, 'type': 'date'}
        },
        'current_value': []
    }

    return resume_data


async def main():
    """主入口"""
    print("=" * 60)
    print("🔍 BOSS直聘在线简历字段采集器（Playwright版）")
    print("=" * 60)

    try:
        resume_data = await scrape_boss_resume_with_playwright()

        if resume_data:
            # 打印统计
            total_fields = len(resume_data)
            required_fields = sum(
                1 for field_info in resume_data.values()
                if isinstance(field_info, dict) and field_info.get('required', False)
            )

            print("\n" + "=" * 60)
            print("📊 采集统计")
            print("=" * 60)
            print(f"✅ 总字段数: {total_fields}")
            print(f"✅ 必填字段: {required_fields}")
            print(f"✅ 选填字段: {total_fields - required_fields}")
            print("=" * 60)

            # 打印字段概览
            print("\n📋 字段概览:")
            for field_name, field_info in resume_data.items():
                if isinstance(field_info, dict):
                    required_tag = "⭐必填" if field_info.get('required') else "  选填"
                    field_type = field_info.get('type', 'unknown')
                    label = field_info.get('label', field_name)
                    print(f"  {required_tag} {label} ({field_type})")

                    # 显示数组类型的子字段
                    if field_type == 'array' and 'fields' in field_info:
                        for sub_name, sub_info in field_info['fields'].items():
                            sub_required = "⭐必填" if sub_info.get('required') else "  选填"
                            print(f"      {sub_required} {sub_info.get('label', sub_name)} ({sub_info.get('type', 'unknown')})")
        else:
            print("\n⚠️ 未采集到任何字段，请检查页面结构或登录状态。")

    except Exception as e:
        print(f"\n❌ 采集失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())
