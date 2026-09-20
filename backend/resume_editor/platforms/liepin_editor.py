"""
猎聘网在线简历字段采集器

功能：
1. 导航到猎聘简历编辑页面
2. 扒取所有字段（必填/选填）
3. 导出到 JSON
"""

import os
import sys
import json
import time
import re

# 路径配置
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from liepin_scraper.liepin_auto_delivery import get_browser_page, _inject_cookies_if_needed

# 猎聘简历编辑页面
LIEPIN_RESUME_URL = "https://c.liepin.com/resume/preview"


def scrape_liepin_resume_fields() -> dict:
    """
    扒取猎聘在线简历的所有字段

    Returns:
        dict: 简历字段字典
    """
    _inject_cookies_if_needed()
    # 句柄是懒加载且会在失联后重建的，禁止 from-import 缓存，必须每次动态获取
    page = get_browser_page()

    print("\n🔄 正在导航到猎聘简历页面...")
    page.get(LIEPIN_RESUME_URL)
    time.sleep(5)

    # 获取页面源码
    html = page.html

    resume_data = {}

    # ============================================================
    # 1. 基本信息
    # ============================================================
    print("\n📋 1. 正在解析基本信息...")

    # 姓名
    name_match = re.search(r'class="name"[^>]*>([^<]+)', html)
    resume_data['name'] = {
        'label': '姓名',
        'required': True,
        'type': 'text',
        'current_value': name_match.group(1).strip() if name_match else ''
    }

    # 手机号
    phone_match = re.search(r'class="phone"[^>]*>([^<]+)', html)
    if not phone_match:
        phone_match = re.search(r'1[3-9]\d{9}', html)
    resume_data['phone'] = {
        'label': '手机号',
        'required': True,
        'type': 'text',
        'current_value': phone_match.group(1).strip() if phone_match and phone_match.lastindex else (phone_match.group() if phone_match else '')
    }

    # 邮箱
    email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html)
    resume_data['email'] = {
        'label': '邮箱',
        'required': False,
        'type': 'text',
        'current_value': email_match.group() if email_match else ''
    }

    # 求职状态
    status_match = re.search(r'求职状态[：:]\s*([^<]+)', html)
    if not status_match:
        status_match = re.search(r'class="status"[^>]*>([^<]+)', html)
    resume_data['job_status'] = {
        'label': '求职状态',
        'required': False,
        'type': 'select',
        'options': ['在职-月内到岗', '在职-考虑机会', '在职-暂不考虑', '离职'],
        'current_value': status_match.group(1).strip() if status_match else ''
    }

    # 年龄
    age_match = re.search(r'(\d+)岁', html)
    resume_data['age'] = {
        'label': '年龄',
        'required': False,
        'type': 'text',
        'current_value': age_match.group(1) + '岁' if age_match else ''
    }

    # 学历
    degree_match = re.search(r'(本科|硕士|博士|大专|高中|中专)', html)
    resume_data['education_degree'] = {
        'label': '最高学历',
        'required': False,
        'type': 'select',
        'options': ['初中及以下', '中专/中技', '高中', '大专', '本科', '硕士', '博士'],
        'current_value': degree_match.group(1) if degree_match else ''
    }

    # 工作年限
    work_years_match = re.search(r'(\d+)年工作经验', html)
    resume_data['work_years'] = {
        'label': '工作年限',
        'required': False,
        'type': 'text',
        'current_value': work_years_match.group(1) + '年' if work_years_match else ''
    }

    print(f"  ✅ 基本信息：采集到 {len(resume_data)} 个字段")

    # ============================================================
    # 2. 求职期望
    # ============================================================
    print("\n📋 2. 正在解析求职期望...")

    # 期望职位
    expected_job_match = re.search(r'期望职位[：:]\s*([^<]+)', html)
    resume_data['expected_job'] = {
        'label': '期望职位',
        'required': True,
        'type': 'text',
        'current_value': expected_job_match.group(1).strip() if expected_job_match else ''
    }

    # 期望城市
    expected_city_match = re.search(r'期望城市[：:]\s*([^<]+)', html)
    resume_data['expected_city'] = {
        'label': '期望城市',
        'required': True,
        'type': 'text',
        'current_value': expected_city_match.group(1).strip() if expected_city_match else ''
    }

    # 期望薪资
    expected_salary_match = re.search(r'期望薪资[：:]\s*([^<]+)', html)
    resume_data['expected_salary'] = {
        'label': '期望薪资',
        'required': False,
        'type': 'text',
        'current_value': expected_salary_match.group(1).strip() if expected_salary_match else ''
    }

    print(f"  ✅ 求职期望：采集到 3 个字段")

    # ============================================================
    # 3. 工作经历
    # ============================================================
    print("\n📋 3. 正在解析工作经历...")

    # 查找工作经历区域
    work_section_match = re.search(
        r'class="work-experience"[^>]*>(.*?)</section>',
        html,
        re.DOTALL
    )

    work_experiences = []
    if work_section_match:
        work_html = work_section_match.group(1)
        # 查找工作经历条目
        work_pattern = r'class="work-item"[^>]*>(.*?)</div>\s*</div>'
        work_items = re.findall(work_pattern, work_html, re.DOTALL)

        for work_html in work_items:
            company_match = re.search(r'class="company"[^>]*>([^<]+)', work_html)
            position_match = re.search(r'class="position"[^>]*>([^<]+)', work_html)
            period_match = re.search(r'class="period"[^>]*>([^<]+)', work_html)
            desc_match = re.search(r'class="description"[^>]*>(.*?)</div>', work_html, re.DOTALL)

            work_experiences.append({
                'company': company_match.group(1).strip() if company_match else '',
                'position': position_match.group(1).strip() if position_match else '',
                'period': period_match.group(1).strip() if period_match else '',
                'description': desc_match.group(1).strip() if desc_match else ''
            })

    resume_data['work_experience'] = {
        'label': '工作经历',
        'required': True,
        'type': 'array',
        'fields': {
            'company': {'label': '公司名称', 'required': True, 'type': 'text'},
            'position': {'label': '职位名称', 'required': True, 'type': 'text'},
            'period': {'label': '在职时间', 'required': True, 'type': 'text'},
            'description': {'label': '工作描述', 'required': False, 'type': 'textarea', 'max_length': 1000}
        },
        'current_value': work_experiences
    }

    print(f"  ✅ 工作经历：采集到 {len(work_experiences)} 条记录")

    # ============================================================
    # 4. 教育经历
    # ============================================================
    print("\n📋 4. 正在解析教育经历...")

    # 查找教育经历区域
    edu_section_match = re.search(
        r'class="education"[^>]*>(.*?)</section>',
        html,
        re.DOTALL
    )

    education = []
    if edu_section_match:
        edu_html = edu_section_match.group(1)
        # 查找教育条目
        edu_pattern = r'class="edu-item"[^>]*>(.*?)</div>\s*</div>'
        edu_items = re.findall(edu_pattern, edu_html, re.DOTALL)

        for edu_html in edu_items:
            school_match = re.search(r'class="school"[^>]*>([^<]+)', edu_html)
            major_match = re.search(r'class="major"[^>]*>([^<]+)', edu_html)
            degree_match = re.search(r'class="degree"[^>]*>([^<]+)', edu_html)
            period_match = re.search(r'class="period"[^>]*>([^<]+)', edu_html)

            education.append({
                'school': school_match.group(1).strip() if school_match else '',
                'major': major_match.group(1).strip() if major_match else '',
                'degree': degree_match.group(1).strip() if degree_match else '',
                'period': period_match.group(1).strip() if period_match else ''
            })

    resume_data['education'] = {
        'label': '教育经历',
        'required': True,
        'type': 'array',
        'fields': {
            'school': {'label': '学校名称', 'required': True, 'type': 'text'},
            'major': {'label': '专业', 'required': True, 'type': 'text'},
            'degree': {'label': '学历', 'required': True, 'type': 'select',
                      'options': ['初中及以下', '中专/中技', '高中', '大专', '本科', '硕士', '博士']},
            'period': {'label': '在读时间', 'required': True, 'type': 'text'}
        },
        'current_value': education
    }

    print(f"  ✅ 教育经历：采集到 {len(education)} 条记录")

    # ============================================================
    # 5. 项目经历
    # ============================================================
    print("\n📋 5. 正在解析项目经历...")

    # 查找项目经历区域
    project_section_match = re.search(
        r'class="project-experience"[^>]*>(.*?)</section>',
        html,
        re.DOTALL
    )

    projects = []
    if project_section_match:
        project_html = project_section_match.group(1)
        # 查找项目条目
        project_pattern = r'class="project-item"[^>]*>(.*?)</div>\s*</div>'
        project_items = re.findall(project_pattern, project_html, re.DOTALL)

        for proj_html in project_items:
            name_match = re.search(r'class="project-name"[^>]*>([^<]+)', proj_html)
            role_match = re.search(r'class="role"[^>]*>([^<]+)', proj_html)
            period_match = re.search(r'class="period"[^>]*>([^<]+)', proj_html)
            desc_match = re.search(r'class="description"[^>]*>(.*?)</div>', proj_html, re.DOTALL)

            projects.append({
                'project_name': name_match.group(1).strip() if name_match else '',
                'project_role': role_match.group(1).strip() if role_match else '',
                'period': period_match.group(1).strip() if period_match else '',
                'project_description': desc_match.group(1).strip() if desc_match else ''
            })

    resume_data['projects'] = {
        'label': '项目经历',
        'required': False,
        'type': 'array',
        'fields': {
            'project_name': {'label': '项目名称', 'required': True, 'type': 'text'},
            'project_role': {'label': '担任角色', 'required': False, 'type': 'text'},
            'period': {'label': '项目时间', 'required': True, 'type': 'text'},
            'project_description': {'label': '项目描述', 'required': False, 'type': 'textarea', 'max_length': 1000}
        },
        'current_value': projects
    }

    print(f"  ✅ 项目经历：采集到 {len(projects)} 条记录")

    # ============================================================
    # 6. 技能标签
    # ============================================================
    print("\n📋 6. 正在解析技能标签...")

    skill_match = re.search(r'class="skill-tags"[^>]*>(.*?)</div>', html, re.DOTALL)
    skill_tags = []
    if skill_match:
        skill_html = skill_match.group(1)
        tag_pattern = r'class="skill-tag"[^>]*>([^<]+)'
        skill_tags = [tag.strip() for tag in re.findall(tag_pattern, skill_html)]

    resume_data['skill_tags'] = {
        'label': '技能标签',
        'required': False,
        'type': 'tags',
        'current_value': skill_tags
    }

    print(f"  ✅ 技能标签：采集到 {len(skill_tags)} 个标签")

    # ============================================================
    # 7. 自我评价
    # ============================================================
    print("\n📋 7. 正在解析自我评价...")

    self_eval_match = re.search(r'class="self-evaluation"[^>]*>(.*?)</div>', html, re.DOTALL)
    resume_data['self_evaluation'] = {
        'label': '自我评价',
        'required': False,
        'type': 'textarea',
        'max_length': 500,
        'current_value': self_eval_match.group(1).strip() if self_eval_match else ''
    }

    print(f"  ✅ 自我评价：采集到 1 个字段")

    return resume_data


def save_liepin_fields(data: dict, output_path: str = None):
    """保存字段到 JSON 文件"""
    if output_path is None:
        output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'liepin_fields.json')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 字段已保存到: {output_path}")


def main():
    """主入口"""
    print("=" * 60)
    print("🔍 猎聘网在线简历字段采集器")
    print("=" * 60)

    try:
        # 采集字段
        fields = scrape_liepin_resume_fields()

        if fields:
            # 保存到文件
            save_liepin_fields(fields)

            # 打印统计
            total_fields = len(fields)
            required_fields = sum(
                1 for field_info in fields.values()
                if isinstance(field_info, dict) and field_info.get('required', False)
            )

            # 计算数组类型的必填子字段
            array_required = 0
            for field_info in fields.values():
                if isinstance(field_info, dict) and field_info.get('type') == 'array':
                    for sub_field in field_info.get('fields', {}).values():
                        if sub_field.get('required', False):
                            array_required += 1

            print("\n" + "=" * 60)
            print("📊 采集统计")
            print("=" * 60)
            print(f"✅ 总字段数: {total_fields}")
            print(f"✅ 必填字段: {required_fields} (顶级) + {array_required} (数组子字段)")
            print(f"✅ 选填字段: {total_fields - required_fields}")
            print("=" * 60)

            # 打印字段概览
            print("\n📋 字段概览:")
            for field_name, field_info in fields.items():
                if isinstance(field_info, dict):
                    required_tag = "⭐必填" if field_info.get('required') else "  选填"
                    field_type = field_info.get('type', 'unknown')
                    label = field_info.get('label', field_name)
                    print(f"  {required_tag} {label} ({field_type})")

                    # 显示当前值
                    current_value = field_info.get('current_value')
                    if current_value:
                        if isinstance(current_value, list):
                            print(f"      当前值: {len(current_value)} 条记录")
                        elif isinstance(current_value, str) and len(current_value) > 0:
                            print(f"      当前值: {current_value[:50]}...")
        else:
            print("\n⚠️ 未采集到任何字段，请检查页面结构或登录状态。")

    except Exception as e:
        print(f"\n❌ 采集失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
