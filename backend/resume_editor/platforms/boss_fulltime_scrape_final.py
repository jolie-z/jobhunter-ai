"""
BOSS直聘全职职位三级树爬取器（正式版）

DOM结构（已验证）：
- 左栏大类(28个): .position-category-wrap ul li
- 右栏子分类: .position-list-wrap .navs span.stage-three
- 第三级职位: .position-list .position-tooltip（点击子分类后展开）

前提：全职职位选择弹窗已打开（标题"请选择职位类型"）
"""

import os, sys, time, json
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)

from DrissionPage import ChromiumPage, ChromiumOptions

DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "boss_fulltime_positions.json")

co = ChromiumOptions()
co.set_address('127.0.0.1:19222')
page = ChromiumPage(co)
print("已连接浏览器")

# 确认弹窗
title = page.ele('text:请选择职位类型', timeout=5)
if not title:
    print("错误：全职职位弹窗未打开！")
    sys.exit(1)
print("弹窗已确认打开\n")

# ========== 第一步：爬取左栏大类 ==========
print("[1] 爬取左栏大类...")
li_elements = page.eles('css:.position-category-wrap ul li', timeout=5)
level1_names = [li.text.strip() for li in li_elements if li.text.strip()]
print(f"  共 {len(level1_names)} 个大类: {level1_names}")

# ========== 第二步：逐个点击大类，爬取右栏子分类和第三级 ==========
result = {}

for i, l1_name in enumerate(level1_names, 1):
    print(f"\n[{i}/{len(level1_names)}] 大类: {l1_name}")

    # 点击左栏大类
    try:
        li_els = page.eles('css:.position-category-wrap ul li', timeout=3)
        target_li = None
        for li in li_els:
            if li.text.strip() == l1_name:
                target_li = li
                break
        if target_li:
            target_li.click()
            time.sleep(1.2)
        else:
            print(f"  未找到li元素: {l1_name}")
            result[l1_name] = {}
            continue
    except Exception as e:
        print(f"  点击失败: {e}")
        result[l1_name] = {}
        continue

    # 爬取右栏子分类（二级）
    nav_spans = page.eles('css:.position-list-wrap .navs span.stage-three', timeout=3)
    level2_names = [sp.text.strip() for sp in nav_spans if sp.text.strip()]
    print(f"  二级分类: {len(level2_names)} 个")

    # 逐个点击二级分类，爬取第三级
    l2_data = {}
    for j, l2_name in enumerate(level2_names, 1):
        try:
            # 重新获取span列表（DOM可能刷新）
            spans = page.eles('css:.position-list-wrap .navs span.stage-three', timeout=2)
            target_span = None
            for sp in spans:
                if sp.text.strip() == l2_name:
                    target_span = sp
                    break

            if target_span:
                target_span.click()
                time.sleep(0.8)

                # 爬取展开的第三级职位
                tooltips = page.eles('css:.position-list .position-tooltip', timeout=2)
                level3_names = [t.text.strip() for t in tooltips if t.text.strip()]
                l2_data[l2_name] = level3_names

                if level3_names:
                    print(f"    {l2_name} → {len(level3_names)} 个")
            else:
                l2_data[l2_name] = []
        except Exception as e:
            l2_data[l2_name] = []
            continue

    result[l1_name] = l2_data

# ========== 第三步：保存 ==========
print(f"\n{'='*60}")
with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

total_l2 = sum(len(v) for v in result.values())
total_l3 = sum(len(l3) for l2 in result.values() for l3 in l2.values())
print(f"爬取完成！")
print(f"  一级大类: {len(result)} 个")
print(f"  二级分类: {total_l2} 个")
print(f"  三级职位: {total_l3} 个")
print(f"  输出: {OUTPUT_PATH}")
print(f"{'='*60}")
