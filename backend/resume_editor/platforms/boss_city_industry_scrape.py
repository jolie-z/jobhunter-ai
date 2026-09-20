"""
爬取完整城市列表（省份→城市二级）和行业列表
"""
import os, sys, time, json
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)

from DrissionPage import ChromiumPage, ChromiumOptions

DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, "data")

co = ChromiumOptions()
co.set_address('127.0.0.1:19222')
page = ChromiumPage(co)
print("已连接浏览器")

# ========== 城市：展开每个省份获取子城市 ==========
print("\n[1] 爬取完整城市列表...")

# 先点击城市选择器展开
city_input = page.ele('css:.city-cascader .city-input', timeout=5)
if not city_input:
    city_input = page.ele('css:.city-cascader input', timeout=3)

if city_input:
    city_input.click()
    time.sleep(2)
    print("  城市选择器已展开")

    # 获取第一级（省份/热门城市）
    level1_items = page.eles('css:.ui-cascader-menu li', timeout=3)
    if not level1_items:
        level1_items = page.eles('css:[class*="cascader"] li', timeout=2)

    provinces = [li.text.strip() for li in level1_items if li.text.strip()]
    print(f"  一级选项: {len(provinces)} 个")

    # 逐个点击省份获取子城市
    city_data = {}
    for i, province in enumerate(provinces, 1):
        if province == '热门城市':
            # 热门城市本身就是城市列表，不需要展开
            continue

        try:
            # 重新获取li列表
            items = page.eles('css:.ui-cascader-menu li', timeout=2)
            if not items:
                items = page.eles('css:[class*="cascader"] li', timeout=1)

            target = None
            for item in items:
                if item.text.strip() == province:
                    target = item
                    break

            if target:
                target.click()
                time.sleep(0.8)

                # 获取第二级城市（第二个 cascader-menu）
                menus = page.eles('css:.ui-cascader-menu', timeout=2)
                if len(menus) >= 2:
                    sub_items = menus[1].eles('tag:li')
                    cities = [s.text.strip() for s in sub_items if s.text.strip()]
                    city_data[province] = cities
                    if cities:
                        print(f"  [{i}/{len(provinces)}] {province} → {len(cities)} 个城市")
                else:
                    city_data[province] = []
            else:
                city_data[province] = []
        except Exception as e:
            city_data[province] = []
            continue

    # 保存
    with open(os.path.join(DATA_DIR, "boss_city_full.json"), 'w', encoding='utf-8') as f:
        json.dump(city_data, f, ensure_ascii=False, indent=2)

    total_cities = sum(len(v) for v in city_data.values())
    print(f"\n  城市爬取完成: {len(city_data)} 个省份, {total_cities} 个城市")

    # 关闭
    page.actions.key_down('Escape').key_up('Escape')
    time.sleep(0.5)
else:
    print("  未找到城市选择器")

# ========== 行业：尝试用JS点击 ==========
print("\n[2] 爬取期望行业...")

# 用JS找到行业相关元素并点击
result = page.run_js('''
    // 找"期望行业"标签
    const labels = document.querySelectorAll('.item-label');
    for (const label of labels) {
        if (label.textContent.includes('期望行业')) {
            // 找同行的可点击元素
            const parent = label.parentElement;
            const clickable = parent.querySelector('.ui-select-selection, .input, [class*="select"], [class*="industry"]');
            if (clickable) {
                clickable.click();
                return 'clicked: ' + clickable.className.substring(0, 50);
            }
            // 备用：点击 item-content
            const content = parent.querySelector('.item-content');
            if (content) {
                content.click();
                return 'clicked content';
            }
        }
    }
    return 'not found';
''')
print(f"  JS点击结果: {result}")
time.sleep(2)

# 检查行业弹窗
title = page.ele('text:请选择行业类别', timeout=3)
if title:
    print("  行业弹窗已打开!")
    time.sleep(1)

    # 爬取行业列表 - 分析DOM
    html = page.html
    with open(os.path.join(DATA_DIR, "boss_industry_open.html"), 'w', encoding='utf-8') as f:
        f.write(html)

    # 尝试多种选择器
    industry_items = []
    for sel in [
        'css:.dialog-interest-position li',
        'css:[class*="interest-position"] li',
        'css:[class*="industry"] li',
        'css:.position-list .position-tooltip',
    ]:
        try:
            els = page.eles(sel, timeout=2)
            if els and len(els) > 5:
                texts = [el.text.strip() for el in els if el.text.strip()]
                if texts:
                    industry_items = texts
                    print(f"  选择器 {sel} → {len(texts)} 个行业")
                    break
        except Exception:
            continue

    if industry_items:
        with open(os.path.join(DATA_DIR, "boss_industry_options.json"), 'w', encoding='utf-8') as f:
            json.dump(industry_items, f, ensure_ascii=False, indent=2)
        print(f"  已保存 {len(industry_items)} 个行业选项")
    else:
        print("  未找到行业列表，请检查 boss_industry_open.html")
else:
    print("  行业弹窗未出现")
    # 保存当前HTML供分析
    html = page.html
    with open(os.path.join(DATA_DIR, "boss_industry_debug2.html"), 'w', encoding='utf-8') as f:
        f.write(html)
    print("  已保存HTML供分析")

print("\n完成!")
