"""
BOSS直聘期望职位分类爬取器（三级联动版本）

功能：
1. 访问BOSS直聘简历页面
2. 点击期望职位的"添加"按钮
3. 点击"选择期望职位"输入框，打开职位选择器
4. 遍历一级分类（左侧栏），记录名称
5. 点击每个一级分类，遍历二级分类（中间栏），记录名称
6. 点击每个二级分类，遍历三级分类（右侧栏），记录名称
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


def scrape_add_button_categories():
    """
    爬取"添加"按钮下的三级联动职位分类

    流程：
    1. 访问简历页面
    2. 点击"添加"按钮
    3. 点击"选择期望职位"输入框
    4. 遍历一级分类 -> 二级分类 -> 三级分类

    Returns:
        dict: 树形结构的职位分类数据
              {
                "一级分类1": {
                  "二级分类1": ["三级分类1", "三级分类2"],
                  "二级分类2": ["三级分类1"]
                }
              }
    """
    print("="*60)
    print("🔍 BOSS直聘期望职位分类爬取器（添加按钮版本）")
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

        # 步骤3：直接访问简历页面
        print("\n3. 直接访问简历页面...")
        page.get("https://www.zhipin.com/web/geek/resume")
        time.sleep(5)
        print("   ✅ 访问成功")

        # 步骤5：找到期望职位模块
        print("\n5. 找到期望职位模块...")
        page.scroll.to_bottom()
        time.sleep(3)

        # 尝试多种选择器
        expect_section = None
        selectors = [
            'text:期望职位',
            'css:.expectList',
            'css:#purpose',
            'css:[class*="expect"]',
            'css:[class*="purpose"]',
        ]

        for selector in selectors:
            try:
                elements = page.eles(selector, timeout=3)
                if elements:
                    print(f"   ✅ 找到元素: {selector} ({len(elements)} 个)")
                    expect_section = elements[0]
                    break
                else:
                    print(f"   ❌ {selector}: 未找到")
            except Exception as e:
                print(f"   ❌ {selector}: 失败 - {e}")

        if expect_section:
            print("   ✅ 找到期望职位模块")
        else:
            print("   ❌ 未找到期望职位模块")
            return None

        # 步骤6：点击期望职位的"添加"按钮
        print("\n6. 点击期望职位的'添加'按钮...")

        # 查找"添加"按钮 - 尝试多种选择器
        add_btn = None
        selectors = [
            'css:a[ka="user-resume-add-expectation"]',
            'ka:user-resume-add-expectation',
            'css:.link-add',
            'css:a[href="javascript:;"]',
            'text:添加',
        ]

        for selector in selectors:
            try:
                elements = page.eles(selector, timeout=3)
                if elements:
                    print(f"   ✅ 找到元素: {selector} ({len(elements)} 个)")
                    add_btn = elements[0]
                    break
                else:
                    print(f"   ❌ {selector}: 未找到")
            except Exception as e:
                print(f"   ❌ {selector}: 失败 - {e}")

        if add_btn:
            print("   ✅ 找到添加按钮，准备点击...")
            add_btn.click(by_js=True)
            time.sleep(15)  # 等待选择器加载
            print("   ✅ 点击成功")

            # 保存页面源码以便分析
            print("\n   保存页面源码...")
            html = page.html
            output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_after_add_click.html')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"   页面源码已保存到: {output_path}")
            print(f"   页面源码长度: {len(html)} 字符")

            # 检查是否打开了职位选择器
            print("\n   检查是否打开了职位选择器...")
            job_selector = page.ele('css:.position-selector', timeout=3)
            if not job_selector:
                job_selector = page.ele('css:.job-selector', timeout=3)
            if not job_selector:
                job_selector = page.ele('css:[class*="position"]', timeout=3)

            if job_selector:
                print("   ✅ 职位选择器已打开")
            else:
                print("   ⚠️ 职位选择器未打开，可能需要手动操作")
        else:
            print("   ❌ 未找到添加按钮")
            return None

        # 步骤7：点击"选择期望职位"输入框
        print("\n7. 点击'选择期望职位'输入框...")

        # 使用正确的选择器：ka="resume_form_edit_positionName"
        job_input = page.ele('css:[ka="resume_form_edit_positionName"]', timeout=5)
        if not job_input:
            job_input = page.ele('css:.list-select-input', timeout=3)

        if job_input:
            print("   ✅ 找到期望职位输入框，准备点击...")
            # 使用JavaScript点击
            page.run_js('arguments[0].click()', job_input)
            time.sleep(5)

            # 如果弹窗没出来，尝试多种方式触发
            dialog = page.ele('css:.position-dialog', timeout=2)
            if not dialog or not dialog.states.is_displayed:
                print("   ⚠️ 弹窗未显示，尝试其他方式触发...")

                # 方式1: 直接触发Vue组件的click事件
                page.run_js('''
                    var el = document.querySelector('[ka=\"resume_form_edit_positionName\"]');
                    if (el) {
                        el.click();
                        el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    }
                ''')
                time.sleep(3)

            # 检查弹窗是否显示
            dialog = page.ele('css:.position-dialog', timeout=2)
            if dialog and dialog.states.is_displayed:
                print("   ✅ 职位选择弹窗已显示")
            else:
                print("   ⚠️ 弹窗仍未显示，尝试其他方式...")
                # 方式2: 直接访问职位选择API
                # 这里我们先尝试手动等待，看看弹窗是否会出现
                time.sleep(5)
                dialog = page.ele('css:.position-dialog', timeout=2)
                if dialog and dialog.states.is_displayed:
                    print("   ✅ 职位选择弹窗已显示")
                else:
                    print("   ❌ 弹窗仍未显示")

            # 保存页面源码
            html_after_input = page.html
            output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_after_job_input_click.html')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_after_input)
            print(f"   页面源码已保存到: {output_path}")
        else:
            print("   ❌ 未找到期望职位输入框")
            return None

        # 步骤8：开始遍历一级分类
        print("\n8. 开始遍历一级分类...")
        job_categories = {}

        # 等待弹窗完全加载
        time.sleep(3)

        # 尝试多种方式获取一级分类
        level1_elements = None

        # 方法1：从弹窗中提取
        position_dialog = page.ele('css:.position-dialog', timeout=3)
        if position_dialog and position_dialog.states.is_displayed:
            print("   ✅ 找到职位选择弹窗")
            # 获取弹窗中的一级分类
            level1_elements = position_dialog.eles('css:li', timeout=3)
        else:
            print("   ⚠️ 未找到职位选择弹窗，尝试其他方式...")

        # 方法2：从position-content中提取
        if not level1_elements:
            position_content = page.ele('css:.position-content', timeout=3)
            if position_content:
                print("   ✅ 找到职位内容区域")
                level1_elements = position_content.eles('css:li', timeout=3)

        # 方法3：直接从页面提取
        if not level1_elements:
            print("   ⚠️ 尝试从页面直接提取...")
            level1_elements = page.eles('css:.position-content li', timeout=3)

        if not level1_elements:
            print("   ❌ 未找到一级分类")
            return None

        print(f"   找到 {len(level1_elements)} 个一级分类")

        for level1_elem in level1_elements:
            try:
                level1_name = level1_elem.text.strip()
                if not level1_name or len(level1_name) < 2 or len(level1_name) > 30:
                    continue
                # 跳过非分类项
                if level1_name in ['无匹配数据', '确定', '取消']:
                    continue

                print(f"\n   📂 一级分类: {level1_name}")
                job_categories[level1_name] = {}

                # 点击一级分类
                level1_elem.click()
                time.sleep(3)

                # 获取二级分类 - 从弹窗中提取
                level2_elements = []
                position_dialog = page.ele('css:.position-dialog', timeout=2)
                if position_dialog:
                    # 查找中间栏的分类
                    all_items = position_dialog.eles('css:li', timeout=2)
                    for item in all_items:
                        text = item.text.strip()
                        if text and len(text) >= 2 and len(text) <= 30 and text != level1_name:
                            level2_elements.append(item)

                if not level2_elements:
                    # 备用方案：从页面直接提取
                    all_items = page.eles('css:.position-content li', timeout=2)
                    for item in all_items:
                        text = item.text.strip()
                        if text and len(text) >= 2 and len(text) <= 30 and text != level1_name:
                            level2_elements.append(item)

                print(f"      找到 {len(level2_elements)} 个二级分类")

                for level2_elem in level2_elements:
                    try:
                        level2_name = level2_elem.text.strip()
                        if not level2_name or len(level2_name) < 2:
                            continue

                        print(f"      📁 二级分类: {level2_name}")
                        job_categories[level1_name][level2_name] = []

                        # 点击二级分类
                        level2_elem.click()
                        time.sleep(2)

                        # 获取三级分类 - 从弹窗中提取
                        level3_elements = []
                        position_dialog = page.ele('css:.position-dialog', timeout=2)
                        if position_dialog:
                            all_items = position_dialog.eles('css:li', timeout=2)
                            for item in all_items:
                                text = item.text.strip()
                                if text and len(text) >= 2 and len(text) <= 30:
                                    level3_elements.append(item)

                        if not level3_elements:
                            # 备用方案
                            all_items = page.eles('css:.position-content li', timeout=2)
                            for item in all_items:
                                text = item.text.strip()
                                if text and len(text) >= 2 and len(text) <= 30:
                                    level3_elements.append(item)

                        print(f"         找到 {len(level3_elements)} 个三级分类")

                        for level3_elem in level3_elements:
                            try:
                                level3_name = level3_elem.text.strip()
                                if level3_name and len(level3_name) >= 2:
                                    job_categories[level1_name][level2_name].append(level3_name)
                                    print(f"         📄 三级分类: {level3_name}")
                            except Exception as e:
                                print(f"         ❌ 获取三级分类失败: {e}")

                    except Exception as e:
                        print(f"      ❌ 获取二级分类失败: {e}")

            except Exception as e:
                print(f"   ❌ 获取一级分类失败: {e}")

        # 保存到JSON
        print("\n9. 保存到JSON文件...")
        output_path = os.path.join(_RESUME_EDITOR_DIR, 'data', 'boss_job_categories_full.json')
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

        # 打印所有一级分类
        print("\n📂 一级分类列表:")
        for cat in job_categories.keys():
            print(f"  - {cat}")

        return job_categories

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == '__main__':
    scrape_add_button_categories()
