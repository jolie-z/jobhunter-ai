"""
BOSS直聘期望职位分类树爬取器（正式版）

DOM结构：
- 弹窗容器: .part-time-position-dialog 或 .position-dialog
- 一级分类: .navs span.stage-three（每行4个，多行）
- 二级职位: .position-list .position-tooltip
- 点击一级分类span → .position-list 刷新为对应二级列表
"""

import os
import sys
import json
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from DrissionPage import ChromiumPage, ChromiumOptions

OUTPUT_PATH = os.path.join(_RESUME_EDITOR_DIR, "data", "boss_job_categories_full.json")


def connect_browser():
    co = ChromiumOptions()
    co.set_address('127.0.0.1:19222')
    return ChromiumPage(co)


def find_visible_dialog(page):
    """找到当前可见的职位选择弹窗"""
    # 优先找兼职职位弹窗（当前打开的）
    dialogs = [
        'css:.part-time-position-dialog .position-selector',
        'css:.position-dialog .position-selector',
        'css:.dialog-interest-position .position-selector',
    ]
    for sel in dialogs:
        try:
            el = page.ele(sel, timeout=2)
            if el:
                # 检查是否可见
                style = el.attr('style') or ''
                if 'display: none' not in style:
                    print(f"  找到可见弹窗: {sel}")
                    return el
        except Exception:
            continue
    return None


def scrape_level1(page):
    """爬取所有一级分类名称"""
    # 一级分类在 .navs 下的 span.stage-three
    spans = page.eles('css:.position-list-wrap .navs span', timeout=5)
    if not spans:
        # 备用：直接找所有 stage-three
        spans = page.eles('css:span.stage-three', timeout=3)

    categories = []
    for span in spans:
        text = span.text.strip()
        if text and text not in categories:
            categories.append(text)

    return categories


def scrape_level2_for(page, category_name):
    """点击某个一级分类，爬取其二级职位列表"""
    # 找到对应的 span 并点击
    spans = page.eles('css:.position-list-wrap .navs span', timeout=3)
    if not spans:
        spans = page.eles('css:span.stage-three', timeout=2)

    target = None
    for span in spans:
        if span.text.strip() == category_name:
            target = span
            break

    if not target:
        print(f"    未找到: {category_name}")
        return []

    target.click()
    time.sleep(1)  # 等待二级列表渲染

    # 读取当前 .position-list 下的所有 .position-tooltip
    tooltips = page.eles('css:.position-list .position-tooltip', timeout=3)
    if not tooltips:
        # 备用选择器
        tooltips = page.eles('css:.position-list span div', timeout=2)

    subs = []
    for tip in tooltips:
        text = tip.text.strip()
        if text and text not in subs:
            subs.append(text)

    return subs


def main():
    print("=" * 60)
    print("BOSS直聘期望职位分类树爬取器")
    print("=" * 60)

    # 1. 连接浏览器
    print("\n[1] 连接浏览器...")
    page = connect_browser()
    print(f"  当前URL: {page.url}")

    # 2. 确认弹窗可见
    print("\n[2] 检查职位选择弹窗...")
    dialog = find_visible_dialog(page)
    if not dialog:
        print("  弹窗不可见，尝试点击'选择期望职位'打开...")
        trigger = page.ele('text:选择期望职位', timeout=3)
        if trigger:
            trigger.click()
            time.sleep(3)
            dialog = find_visible_dialog(page)

    if not dialog:
        print("  错误：无法打开职位选择弹窗，请手动打开后重试")
        return

    # 3. 爬取一级分类
    print("\n[3] 爬取一级分类...")
    level1 = scrape_level1(page)
    print(f"  共 {len(level1)} 个一级分类:")
    for i, cat in enumerate(level1, 1):
        print(f"    {i}. {cat}")

    if len(level1) < 5:
        print("  一级分类数量异常，请检查弹窗状态")
        return

    # 4. 逐个爬取二级分类
    print(f"\n[4] 逐个爬取二级职位...")
    result = {}
    for i, cat in enumerate(level1, 1):
        print(f"  [{i}/{len(level1)}] {cat}...", end=" ", flush=True)
        subs = scrape_level2_for(page, cat)
        result[cat] = subs
        print(f"→ {len(subs)} 个")
        time.sleep(0.3)

    # 5. 保存
    print(f"\n[5] 保存结果...")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 6. 统计
    total_l2 = sum(len(v) for v in result.values())
    empty_cats = [k for k, v in result.items() if not v]

    print(f"\n{'=' * 60}")
    print(f"爬取完成！")
    print(f"  一级分类: {len(result)} 个")
    print(f"  二级职位总计: {total_l2} 个")
    if empty_cats:
        print(f"  空分类（无二级）: {empty_cats}")
    print(f"  输出: {OUTPUT_PATH}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
