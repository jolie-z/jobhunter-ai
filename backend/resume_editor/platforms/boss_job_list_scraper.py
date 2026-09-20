"""
BOSS直聘期望职位列表爬虫 - 逐步调试版

使用方法：
1. 运行脚本
2. 按照提示操作
3. 查看输出，选择正确的方法
"""

import os
import sys
import time
import json
import re

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

    profile_dir = os.path.join(_BACKEND_DIR, "data", ".boss_job_list_profile")
    os.makedirs(profile_dir, exist_ok=True)
    co.set_user_data_path(profile_dir)

    mac_edge_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)

    page = ChromiumPage(co)
    return page


def method1_find_input_box(page):
    """
    方法1：查找期望职位输入框并点击

    步骤：
    1. 访问简历页面
    2. 点击期望职位的编辑按钮
    3. 查找输入框并点击
    4. 等待职位列表加载
    """
    print("\n" + "="*60)
    print("📋 方法1：查找期望职位输入框并点击")
    print("="*60)

    # 访问简历页面
    print("\n1. 访问BOSS直聘简历页面...")
    page.get("https://www.zhipin.com/web/geek/resume")
    time.sleep(5)

    # 查找期望职位区域
    print("\n2. 查找期望职位区域...")
    expect_section = page.ele('text:期望职位', timeout=5)
    if expect_section:
        print(f"   ✅ 找到期望职位区域")
    else:
        print("   ❌ 未找到期望职位区域")
        return False

    # 查找编辑按钮
    print("\n3. 查找期望职位编辑按钮...")
    edit_btn = page.ele('ka:user-resume-edit-expectation0', timeout=3)
    if not edit_btn:
        edit_btn = page.ele('css:.link-edit', timeout=3)

    if edit_btn:
        print(f"   ✅ 找到编辑按钮，准备点击...")
        try:
            edit_btn.click(by_js=True)
            time.sleep(5)
            print("   ✅ 点击成功")
        except Exception as e:
            print(f"   ❌ 点击失败: {e}")
            return False
    else:
        print("   ❌ 未找到编辑按钮")
        return False

    # 查找输入框
    print("\n4. 查找期望职位输入框...")
    input_box = page.ele('css:input[placeholder="选择期望职位"]', timeout=5)
    if not input_box:
        input_box = page.ele('css:input[readonly="readonly"]', timeout=3)

    if input_box:
        print(f"   ✅ 找到输入框，准备点击...")
        try:
            input_box.click()
            time.sleep(5)
            print("   ✅ 点击成功")

            # 检查是否有职位列表弹出
            print("\n5. 检查职位列表是否弹出...")
            html = page.html

            # 搜索可能的职位列表元素
            possible_selectors = [
                'css:.job-category',
                'css:.position-category',
                'css:.job-list',
                'css:.category-list',
                'css:[class*="category"]',
                'css:[class*="job"]',
            ]

            for selector in possible_selectors:
                elements = page.eles(selector, timeout=2)
                if elements:
                    print(f"   ✅ 找到元素: {selector} ({len(elements)} 个)")

            return True
        except Exception as e:
            print(f"   ❌ 点击失败: {e}")
            return False
    else:
        print("   ❌ 未找到输入框")
        return False


def method2_try_different_selectors(page):
    """
    方法2：尝试不同的选择器

    步骤：
    1. 尝试多种CSS选择器
    2. 查找可能的职位列表元素
    """
    print("\n" + "="*60)
    print("📋 方法2：尝试不同的选择器")
    print("="*60)

    # 访问简历页面
    print("\n1. 访问BOSS直聘简历页面...")
    page.get("https://www.zhipin.com/web/geek/resume")
    time.sleep(5)

    # 尝试多种选择器
    print("\n2. 尝试多种选择器...")
    selectors = [
        # 期望职位相关
        'text:期望职位',
        'ka:user-resume-edit-expectation0',
        'css:.link-edit',
        'css:input[placeholder="选择期望职位"]',
        'css:input[readonly="readonly"]',

        # 可能的职位列表
        'css:.job-category',
        'css:.position-category',
        'css:.job-list',
        'css:.category-list',
        'css:[class*="category"]',
        'css:[class*="job"]',
        'css:[class*="position"]',
        'css:[class*="list"]',
    ]

    for selector in selectors:
        try:
            elements = page.eles(selector, timeout=2)
            if elements:
                print(f"   ✅ {selector}: {len(elements)} 个元素")
                # 打印第一个元素的文本
                if elements:
                    text = elements[0].text[:100] if elements[0].text else "无文本"
                    print(f"      文本: {text}")
        except Exception as e:
            print(f"   ❌ {selector}: 失败 - {e}")

    return True


def method3_check_page_structure(page):
    """
    方法3：检查页面结构

    步骤：
    1. 获取页面源码
    2. 搜索关键词
    3. 分析HTML结构
    """
    print("\n" + "="*60)
    print("📋 方法3：检查页面结构")
    print("="*60)

    # 访问简历页面
    print("\n1. 访问BOSS直聘简历页面...")
    page.get("https://www.zhipin.com/web/geek/resume")
    time.sleep(5)

    # 获取页面源码
    print("\n2. 获取页面源码...")
    html = page.html
    print(f"   页面源码长度: {len(html)} 字符")

    # 搜索关键词
    print("\n3. 搜索关键词...")
    keywords = [
        '期望职位',
        '选择期望职位',
        'job-category',
        'position-category',
        'category',
        'job-list',
        'position-list',
    ]

    for keyword in keywords:
        count = html.count(keyword)
        if count > 0:
            print(f"   ✅ '{keyword}': 出现 {count} 次")

    # 搜索可能的职位分类
    print("\n4. 搜索可能的职位分类...")
    categories = ['技术', '产品', '设计', '运营', '市场', '销售', '职能', '金融']

    for category in categories:
        if category in html:
            print(f"   ✅ '{category}': 存在")

    # 保存页面源码
    output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_resume_page.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n5. 页面源码已保存到: {output_path}")

    return True


def method4_manual_interaction(page):
    """
    方法4：手动交互

    步骤：
    1. 打开浏览器
    2. 等待用户手动操作
    3. 获取操作后的页面
    """
    print("\n" + "="*60)
    print("📋 方法4：手动交互")
    print("="*60)

    # 访问简历页面
    print("\n1. 访问BOSS直聘简历页面...")
    page.get("https://www.zhipin.com/web/geek/resume")
    time.sleep(5)

    print("\n2. 请手动操作：")
    print("   - 点击期望职位的编辑按钮")
    print("   - 点击期望职位的输入框")
    print("   - 等待职位列表弹出")
    print("   - 操作完成后，按回车键继续...")

    input()  # 等待用户操作

    # 获取页面源码
    print("\n3. 获取操作后的页面源码...")
    html = page.html
    print(f"   页面源码长度: {len(html)} 字符")

    # 搜索职位分类
    print("\n4. 搜索职位分类...")
    categories = ['技术', '产品', '设计', '运营', '市场', '销售', '职能', '金融']

    for category in categories:
        if category in html:
            print(f"   ✅ '{category}': 存在")

    # 保存页面源码
    output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_resume_manual.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n5. 页面源码已保存到: {output_path}")

    return True


def main():
    """主入口"""
    print("="*60)
    print("🔍 BOSS直聘期望职位列表爬虫 - 逐步调试版")
    print("="*60)

    # 检查命令行参数
    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        print("\n选择方法：")
        print("1. 方法1：查找期望职位输入框并点击")
        print("2. 方法2：尝试不同的选择器")
        print("3. 方法3：检查页面结构")
        print("4. 方法4：手动交互")
        print("5. 运行所有方法")

        try:
            choice = input("\n请选择 (1-5): ").strip()
        except EOFError:
            # 如果无法读取输入，默认运行方法3
            print("\n⚠️ 无法读取输入，默认运行方法3...")
            choice = "3"

    page = None
    try:
        page = create_browser()

        if choice == "1":
            method1_find_input_box(page)
        elif choice == "2":
            method2_try_different_selectors(page)
        elif choice == "3":
            method3_check_page_structure(page)
        elif choice == "4":
            method4_manual_interaction(page)
        elif choice == "5":
            method1_find_input_box(page)
            method2_try_different_selectors(page)
            method3_check_page_structure(page)
        else:
            print("无效选择，运行方法3...")
            method3_check_page_structure(page)

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
