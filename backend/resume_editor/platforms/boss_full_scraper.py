"""
BOSS直聘职位分类完整爬取器

功能：
1. 访问BOSS直聘简历页面
2. 点击编辑按钮
3. 点击期望职位输入框
4. 遍历一级分类，记录名称
5. 点击每个一级分类，遍历二级分类，记录
6. 点击每个二级分类，遍历三级分类，记录
7. 保存到JSON文件
"""

import os
import sys
import time
import json

# 路径配置
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from DrissionPage import ChromiumPage, ChromiumOptions

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port, get_platform_profile


def create_browser():
    """创建浏览器实例"""
    print("🚀 启动 DrissionPage (Edge)...")
    co = ChromiumOptions()
    co.set_local_port(get_platform_port("boss"))

    # 🛡️ profile 统一走 registry（与主链路同一份登录态）；私有 profile 会与主链路抢端口、互不见登录
    profile_dir = get_platform_profile("boss")
    os.makedirs(profile_dir, exist_ok=True)
    co.set_user_data_path(profile_dir)

    mac_edge_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
    if os.path.exists(mac_edge_path):
        co.set_browser_path(mac_edge_path)

    page = ChromiumPage(co)
    return page


def scrape_all_categories():
    """
    完整爬取BOSS直聘的所有职位分类

    Returns:
        dict: 树形结构的职位分类数据
    """
    print("="*60)
    print("🔍 BOSS直聘职位分类完整爬取器")
    print("="*60)

    page = None
    try:
        page = create_browser()

        # 访问BOSS直聘首页
        print("\n1. 访问BOSS直聘首页...")
        page.get("https://www.zhipin.com")
        time.sleep(3)

        # 检查登录状态
        print("\n2. 检查登录状态...")
        is_logged_in = page.ele('css:.user-nav', timeout=3) or page.ele('text:退出登录', timeout=3)

        if is_logged_in:
            print("   ✅ 已登录")
        else:
            print("   ⚠️ 未登录，请手动登录BOSS直聘")
            print("   请在浏览器窗口中扫码登录")
            print("   登录完成后，脚本将继续执行...")

            # 等待登录
            while True:
                time.sleep(3)
                if page.ele('css:.user-nav', timeout=1) or page.ele('text:退出登录', timeout=1):
                    print("   ✅ 登录成功！")
                    break

        # 访问简历页面
        print("\n3. 访问BOSS直聘简历页面...")
        page.get("https://www.zhipin.com/web/geek/resume")
        time.sleep(5)

        # 点击期望职位的编辑按钮
        print("\n4. 点击期望职位编辑按钮...")
        page.scroll.to_bottom()
        time.sleep(3)

        # 关闭可能打开的编辑表单
        try:
            page.run_js('document.querySelectorAll(".btn-outline").forEach(btn => btn.click())')
            time.sleep(1)
        except:
            pass

        # 尝试多种选择器
        edit_btn = None
        selectors = [
            'css:a[ka="user-resume-edit-expectation0"]',
            'ka:user-resume-edit-expectation0',
            'css:.link-edit',
            'css:a[href="javascript:;"]',
            'text:编辑',
        ]

        for selector in selectors:
            try:
                elements = page.eles(selector, timeout=3)
                if elements:
                    print(f"   ✅ 找到元素: {selector} ({len(elements)} 个)")
                    edit_btn = elements[0]
                    break
                else:
                    print(f"   ❌ {selector}: 未找到")
            except Exception as e:
                print(f"   ❌ {selector}: 失败 - {e}")

        if edit_btn:
            print("   ✅ 找到编辑按钮，准备点击...")
            try:
                edit_btn.click(by_js=True)
                time.sleep(5)
                print("   ✅ 点击成功")
            except Exception as e:
                print(f"   ❌ 点击失败: {e}")
                return None
        else:
            print("   ❌ 未找到编辑按钮")
            return None

        # 点击期望职位输入框
        print("\n5. 点击期望职位输入框...")
        input_box = page.ele('css:input[placeholder="选择期望职位"]', timeout=5)
        if input_box:
            print("   ✅ 找到输入框，准备点击...")
            input_box.click()
            time.sleep(10)
            print("   ✅ 点击成功")
        else:
            print("   ❌ 未找到输入框")
            return None

        # 开始遍历分类
        print("\n6. 开始遍历职位分类...")
        job_categories = {}

        # 获取一级分类
        level1_elements = page.eles('css:.position-category-item', timeout=5)
        if not level1_elements:
            level1_elements = page.eles('css:[class*="category-item"]', timeout=5)

        print(f"   找到 {len(level1_elements)} 个一级分类")

        for level1_elem in level1_elements:
            try:
                level1_name = level1_elem.text.strip()
                if not level1_name:
                    continue

                print(f"\n   📂 一级分类: {level1_name}")
                job_categories[level1_name] = {}

                # 点击一级分类
                level1_elem.click()
                time.sleep(2)

                # 获取二级分类
                level2_elements = page.eles('css:.position-sub-category-item', timeout=3)
                if not level2_elements:
                    level2_elements = page.eles('css:[class*="sub-category-item"]', timeout=3)

                print(f"      找到 {len(level2_elements)} 个二级分类")

                for level2_elem in level2_elements:
                    try:
                        level2_name = level2_elem.text.strip()
                        if not level2_name:
                            continue

                        print(f"      📁 二级分类: {level2_name}")
                        job_categories[level1_name][level2_name] = []

                        # 点击二级分类
                        level2_elem.click()
                        time.sleep(2)

                        # 获取三级分类
                        level3_elements = page.eles('css:.position-job-item', timeout=3)
                        if not level3_elements:
                            level3_elements = page.eles('css:[class*="job-item"]', timeout=3)

                        print(f"         找到 {len(level3_elements)} 个三级分类")

                        for level3_elem in level3_elements:
                            try:
                                level3_name = level3_elem.text.strip()
                                if level3_name:
                                    job_categories[level1_name][level2_name].append(level3_name)
                                    print(f"         📄 三级分类: {level3_name}")
                            except Exception as e:
                                print(f"         ❌ 获取三级分类失败: {e}")

                    except Exception as e:
                        print(f"      ❌ 获取二级分类失败: {e}")

            except Exception as e:
                print(f"   ❌ 获取一级分类失败: {e}")

        # 保存到JSON
        print("\n7. 保存到JSON文件...")
        output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_categories_full.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(job_categories, f, ensure_ascii=False, indent=2)
        print(f"   ✅ 已保存到: {output_path}")

        # 打印统计
        print("\n" + "="*60)
        print("📊 爬取统计")
        print("="*60)
        print(f"✅ 一级分类: {len(job_categories)} 个")
        total_level2 = sum(len(v) for v in job_categories.values())
        total_level3 = sum(len(vv) for v in job_categories.values() for vv in v.values())
        print(f"✅ 二级分类: {total_level2} 个")
        print(f"✅ 三级分类: {total_level3} 个")
        print("="*60)

        return job_categories

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == '__main__':
    scrape_all_categories()
