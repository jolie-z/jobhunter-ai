"""
BOSS直聘在线简历字段采集器 - 精确版

基于实际页面HTML结构编写
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

from boss_scraper.boss_auto_delivery import get_browser_page, _ensure_login


def scrape_boss_resume_precise() -> dict:
    """
    精确采集 BOSS 直聘在线简历的所有字段

    Returns:
        dict: 简历字段字典
    """
    page = get_browser_page()
    _ensure_login()

    print("\n🔄 正在访问 BOSS 直聘简历页面...")
    page.get("https://www.zhipin.com/web/geek/resume")
    time.sleep(8)

    # 获取页面源码
    html = page.html

    resume_data = {}

    # ============================================================
    # 1. 基本信息区域
    # ============================================================
    print("\n📋 1. 正在解析基本信息...")

    # 姓名
    name_match = re.search(r'class="name">\s*([^<]+)', html)
    resume_data['name'] = {
        'label': '姓名',
        'required': True,
        'type': 'text',
        'current_value': name_match.group(1).strip() if name_match else ''
    }

    # 手机号
    tel_match = re.search(r'class="fz-resume fz-tel"></i>([^<]+)', html)
    resume_data['phone'] = {
        'label': '手机号',
        'required': True,
        'type': 'text',
        'current_value': tel_match.group(1).strip() if tel_match else ''
    }

    # 邮箱
    mail_match = re.search(r'class="fz-resume fz-mail"></i>([^<]+)', html)
    resume_data['email'] = {
        'label': '邮箱',
        'required': False,
        'type': 'text',
        'current_value': mail_match.group(1).strip() if mail_match else ''
    }

    # 微信号
    weixin_match = re.search(r'class="fz-resume fz-weixin"></i>([^<]+)', html)
    resume_data['wechat'] = {
        'label': '微信号',
        'required': False,
        'type': 'text',
        'current_value': weixin_match.group(1).strip() if weixin_match else ''
    }

    # 求职状态
    status_match = re.search(r'class="fz-resume fz-status"></i>([^<]+)', html)
    resume_data['job_status'] = {
        'label': '求职状态',
        'required': False,
        'type': 'select',
        'options': ['在职-月内到岗', '在职-考虑机会', '在职-暂不考虑', '离职'],
        'current_value': status_match.group(1).strip() if status_match else ''
    }

    # 经验年限
    exp_match = re.search(r'class="fz-resume fz-experience"></i>([^<]+)', html)
    resume_data['experience_years'] = {
        'label': '经验年限',
        'required': False,
        'type': 'text',
        'current_value': exp_match.group(1).strip() if exp_match else ''
    }

    # 学历
    degree_match = re.search(r'class="fz-resume fz-degree"></i>([^<]+)', html)
    resume_data['education_degree'] = {
        'label': '最高学历',
        'required': False,
        'type': 'select',
        'options': ['初中及以下', '中专/中技', '高中', '大专', '本科', '硕士', '博士'],
        'current_value': degree_match.group(1).strip() if degree_match else ''
    }

    print(f"  ✅ 基本信息：采集到 {len(resume_data)} 个字段")

    # ============================================================
    # 2. 个人优势
    # ============================================================
    print("\n📋 2. 正在解析个人优势...")

    advantage_match = re.search(
        r'class="info-text advantage-text">(.*?)</div>',
        html,
        re.DOTALL
    )
    resume_data['personal_advantage'] = {
        'label': '个人优势',
        'required': False,
        'type': 'textarea',
        'max_length': 500,
        'current_value': advantage_match.group(1).strip() if advantage_match else ''
    }

    print(f"  ✅ 个人优势：采集到 1 个字段")

    # ============================================================
    # 3. 期望职位
    # ============================================================
    print("\n📋 3. 正在解析期望职位...")

    # 查找所有期望职位
    expect_pattern = r'class="expect-list-item">(.*?)</div>'
    expect_items = re.findall(expect_pattern, html, re.DOTALL)

    expectations = []
    for idx, expect_html in enumerate(expect_items):
        # 提取职位
        job_match = re.search(r'class="label-text">(.*?)<!', expect_html)
        # 提取薪资
        salary_match = re.search(r'class="split-line money-item">(.*?)</span>', expect_html)
        # 提取城市
        city_match = re.search(r'class="split-line city-item">(.*?)</span>', expect_html)

        expectations.append({
            'position': job_match.group(1).strip() if job_match else '',
            'salary': salary_match.group(1).strip() if salary_match else '',
            'city': city_match.group(1).strip() if city_match else ''
        })

    resume_data['expectations'] = {
        'label': '期望职位',
        'required': True,
        'type': 'array',
        'fields': {
            'position': {'label': '期望职位', 'required': True, 'type': 'text'},
            'salary': {'label': '期望薪资', 'required': False, 'type': 'text'},
            'city': {'label': '期望城市', 'required': True, 'type': 'text'}
        },
        'current_value': expectations
    }

    print(f"  ✅ 期望职位：采集到 {len(expectations)} 条记录")

    # ============================================================
    # 4. 工作经历
    # ============================================================
    print("\n📋 4. 正在解析工作经历...")

    # 查找工作经历区域 - 使用更宽松的匹配
    work_section_match = re.search(
        r'id="history" class="resume-item resume-history resume-workExpList">(.*?)</ul>\s*</div>\s*</div>',
        html,
        re.DOTALL
    )

    work_experiences = []
    if work_section_match:
        work_html = work_section_match.group(1)
        # 查找工作经历条目 - 使用 ka 属性
        work_pattern = r'ka="user-resume-edit-workexp\d+"[^>]*>(.*?)</li>'
        work_items = re.findall(work_pattern, work_html, re.DOTALL)

        for work_html in work_items:
            company_match = re.search(r'class="name">(.*?)</span>', work_html)
            position_match = re.search(r'class="position-name">(.*?)</span>', work_html)
            period_match = re.search(r'class="gray period">(.*?)</span>', work_html)
            desc_match = re.search(r'class="text-desc">(.*?)</span>', work_html, re.DOTALL)

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
    # 5. 项目经历
    # ============================================================
    print("\n📋 5. 正在解析项目经历...")

    # 查找项目经历区域
    project_section_match = re.search(
        r'class="resume-item resume-project resume-projectExpList">(.*?)</div>\s*<!---->\s*</div>',
        html,
        re.DOTALL
    )

    projects = []
    if project_section_match:
        project_html = project_section_match.group(1)
        # 查找项目条目
        project_pattern = r'ka="user-resume-edit-project\d+"[^>]*>(.*?)</li>'
        project_items = re.findall(project_pattern, project_html, re.DOTALL)

        for proj_html in project_items:
            name_match = re.search(r'class="name">(.*?)</span>', proj_html)
            role_match = re.search(r'class="role-name">(.*?)</span>', proj_html)
            period_match = re.search(r'class="gray period">(.*?)</span>', proj_html)
            desc_match = re.search(r'class="text-desc">(.*?)</span>', proj_html, re.DOTALL)

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
    # 6. 教育经历
    # ============================================================
    print("\n📋 6. 正在解析教育经历...")

    # 查找教育经历区域
    edu_section_match = re.search(
        r'id="education" class="resume-item resume-education resume-educationExpList">(.*?)</div>\s*<!---->\s*</div>',
        html,
        re.DOTALL
    )

    education = []
    if edu_section_match:
        edu_html = edu_section_match.group(1)
        # 查找教育条目 - 使用 ka 属性
        edu_pattern = r'ka="user-resume-edit-eduexp\d+"[^>]*>(.*?)</li>'
        edu_items = re.findall(edu_pattern, edu_html, re.DOTALL)

        for edu_html in edu_items:
            school_match = re.search(r'class="school-name">(.*?)</span>', edu_html)
            period_match = re.search(r'class="school-period">(.*?)</span>', edu_html)

            # 专业和学历在 school-attr-list 中
            attr_list_match = re.search(r'class="school-attr-list">(.*?)</ul>', edu_html, re.DOTALL)
            major = ''
            degree = ''
            if attr_list_match:
                attr_html = attr_list_match.group(1)
                li_items = re.findall(r'<li[^>]*>(.*?)</li>', attr_html)
                if len(li_items) >= 1:
                    major = re.sub(r'<[^>]+>', '', li_items[0]).strip()
                if len(li_items) >= 2:
                    degree = re.sub(r'<[^>]+>', '', li_items[1]).strip()

            education.append({
                'school': school_match.group(1).strip() if school_match else '',
                'major': major,
                'degree': degree,
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
    # 7. 资格证书
    # ============================================================
    print("\n📋 7. 正在解析资格证书...")

    # 查找证书区域
    cert_section_match = re.search(
        r'id="certification" class="resume-item resume-certification resume-certificationList">(.*?)</div>\s*<!---->\s*</div>',
        html,
        re.DOTALL
    )

    certificates = []
    if cert_section_match:
        cert_html = cert_section_match.group(1)
        # 查找证书标签 - 使用 resume-cert-tag 类
        cert_pattern = r'class="resume-cert-tag">(.*?)<!'
        cert_items = re.findall(cert_pattern, cert_html)

        for cert_name in cert_items:
            certificates.append({
                'cert_name': cert_name.strip(),
                'obtain_time': ''
            })

    resume_data['certificates'] = {
        'label': '资格证书',
        'required': False,
        'type': 'array',
        'fields': {
            'cert_name': {'label': '证书名称', 'required': True, 'type': 'text'},
            'obtain_time': {'label': '获得时间', 'required': False, 'type': 'text'}
        },
        'current_value': certificates
    }

    print(f"  ✅ 资格证书：采集到 {len(certificates)} 条记录")

    # ============================================================
    # 8. 技能标签
    # ============================================================
    print("\n📋 8. 正在解析技能标签...")

    # 查找技能标签区域
    skill_match = re.search(r'class="skill-tag-list">(.*?)</div>', html, re.DOTALL)
    skill_tags = []
    if skill_match:
        skill_html = skill_match.group(1)
        tag_pattern = r'class="skill-tag-item">(.*?)</span>'
        skill_tags = re.findall(tag_pattern, skill_html)

    resume_data['skill_tags'] = {
        'label': '技能标签',
        'required': False,
        'type': 'tags',
        'current_value': skill_tags
    }

    print(f"  ✅ 技能标签：采集到 {len(skill_tags)} 个标签")

    # ============================================================
    # 9. 驻外选项
    # ============================================================
    print("\n📋 9. 正在解析驻外选项...")

    overseas_match = re.search(r'class="resume-item resume-stayAbroad">(.*?)</div>', html, re.DOTALL)
    resume_data['overseas'] = {
        'label': '驻外选项',
        'required': False,
        'type': 'select',
        'options': ['不接受驻外', '接受驻外'],
        'current_value': '接受驻外' if overseas_match and '接受' in overseas_match.group(1) else '不接受驻外'
    }

    print(f"  ✅ 驻外选项：采集完成")

    return resume_data


def save_boss_fields(data: dict, output_path: str = None):
    """保存字段到 JSON 文件"""
    if output_path is None:
        output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_fields.json')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 字段已保存到: {output_path}")


def main():
    """主入口"""
    print("=" * 60)
    print("🔍 BOSS直聘在线简历字段采集器（精确版）")
    print("=" * 60)

    try:
        # 采集字段
        fields = scrape_boss_resume_precise()

        if fields:
            # 保存到文件
            save_boss_fields(fields)

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
    main()
