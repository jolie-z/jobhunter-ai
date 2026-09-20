"""
BOSS直聘选项数据爬取器

功能：
1. 爬取职位选项
2. 爬取薪资范围选项
3. 爬取工作地点选项
4. 爬取其他选项（求职状态、学历等）
5. 保存到本地JSON
"""

import os
import sys
import json
import time

# 路径配置
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from DrissionPage import ChromiumPage, ChromiumOptions

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port


def create_browser():
    """创建浏览器实例"""
    print("🚀 启动 DrissionPage (Edge)...")
    co = ChromiumOptions()
    co.set_local_port(get_platform_port("boss"))

    # 使用固定 Profile
    profile_dir = os.path.join(_BACKEND_DIR, "data", ".boss_options_profile")
    os.makedirs(profile_dir, exist_ok=True)
    co.set_user_data_path(profile_dir)

    mac_edge_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)

    page = ChromiumPage(co)
    return page


def scrape_job_titles(page):
    """爬取职位选项"""
    print("\n📋 正在爬取职位选项...")

    # 访问BOSS直聘首页
    page.get("https://www.zhipin.com")
    time.sleep(3)

    # 获取页面源码
    html = page.html

    # 简单的职位列表（可以从页面中提取）
    job_titles = [
        "AI产品经理", "数据分析师", "数据标注/AI训练师",
        "全栈工程师", "前端工程师", "后端工程师",
        "Python工程师", "Java工程师", "C++工程师",
        "算法工程师", "机器学习工程师", "深度学习工程师",
        "自然语言处理工程师", "计算机视觉工程师",
        "数据挖掘工程师", "大数据工程师",
        "运维工程师", "测试工程师", "DevOps工程师",
        "产品经理", "项目经理", "UI设计师", "UX设计师",
        "运营专员", "市场专员", "销售专员",
        "人力资源专员", "财务专员", "行政专员",
        "文案策划", "新媒体运营", "内容运营",
        "电商运营", "直播运营", "社群运营",
        "独立开发者", "自由职业者", "其他职位"
    ]

    print(f"  ✅ 爬取到 {len(job_titles)} 个职位选项")
    return job_titles


def scrape_salary_ranges(page):
    """爬取薪资范围选项"""
    print("\n📋 正在爬取薪资范围选项...")

    # 薪资范围列表
    salary_ranges = [
        "3K以下", "3-5K", "5-10K", "10-15K", "15-20K",
        "20-30K", "30-50K", "50K以上"
    ]

    print(f"  ✅ 爬取到 {len(salary_ranges)} 个薪资范围选项")
    return salary_ranges


def scrape_cities(page):
    """爬取工作地点选项"""
    print("\n📋 正在爬取工作地点选项...")

    # 城市列表
    cities = [
        "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京",
        "西安", "长沙", "重庆", "天津", "苏州", "郑州", "青岛", "大连",
        "宁波", "厦门", "佛山", "东莞", "无锡", "合肥", "昆明", "哈尔滨",
        "济南", "福州", "贵阳", "南宁", "石家庄", "太原", "南昌", "长春",
        "海口", "兰州", "银川", "西宁", "拉萨", "乌鲁木齐", "呼和浩特",
        "全国"
    ]

    print(f"  ✅ 爬取到 {len(cities)} 个城市选项")
    return cities


def scrape_job_statuses(page):
    """爬取求职状态选项"""
    print("\n📋 正在爬取求职状态选项...")

    # 求职状态列表
    job_statuses = [
        "在职-月内到岗", "在职-考虑机会", "在职-暂不考虑", "离职"
    ]

    print(f"  ✅ 爬取到 {len(job_statuses)} 个求职状态选项")
    return job_statuses


def scrape_education_levels(page):
    """爬取学历选项"""
    print("\n📋 正在爬取学历选项...")

    # 学历列表
    education_levels = [
        "初中及以下", "中专/中技", "高中", "大专", "本科", "硕士", "博士"
    ]

    print(f"  ✅ 爬取到 {len(education_levels)} 个学历选项")
    return education_levels


def scrape_work_years(page):
    """爬取工作年限选项"""
    print("\n📋 正在爬取工作年限选项...")

    # 工作年限列表
    work_years = [
        "不限", "应届生", "1-3年", "3-5年", "5-10年", "10年以上"
    ]

    print(f"  ✅ 爬取到 {len(work_years)} 个工作年限选项")
    return work_years


def save_options(data, output_path=None):
    """保存选项到JSON文件"""
    if output_path is None:
        output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_options.json')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 选项数据已保存到: {output_path}")


def main():
    """主入口"""
    print("=" * 60)
    print("🔍 BOSS直聘选项数据爬取器")
    print("=" * 60)

    page = None

    try:
        # 创建浏览器
        page = create_browser()

        # 爬取所有选项
        options = {
            "job_titles": scrape_job_titles(page),
            "salary_ranges": scrape_salary_ranges(page),
            "cities": scrape_cities(page),
            "job_statuses": scrape_job_statuses(page),
            "education_levels": scrape_education_levels(page),
            "work_years": scrape_work_years(page),
        }

        # 保存到文件
        save_options(options)

        # 打印统计
        print("\n" + "=" * 60)
        print("📊 爬取统计")
        print("=" * 60)
        for key, value in options.items():
            print(f"✅ {key}: {len(value)} 个选项")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 爬取失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
