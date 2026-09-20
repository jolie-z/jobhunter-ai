"""
爬取薪资范围、城市列表、期望行业
前提：添加求职期望表单已打开（全职模式）
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

# ========== 任务1：薪资范围 ==========
print("\n" + "="*50)
print("[任务1] 爬取薪资范围选项")
print("="*50)

# 点击薪资下拉框展开
salary_select = page.ele('css:.salary-scope .ui-select-selection', timeout=5)
if salary_select:
    salary_select.click()
    time.sleep(1.5)
    print("  已点击薪资下拉框")

    # 获取展开后的选项
    options = page.eles('css:.salary-scope .ui-dropdown-list li', timeout=3)
    if options:
        salary_list = [opt.text.strip() for opt in options if opt.text.strip()]
        print(f"  找到 {len(salary_list)} 个薪资选项: {salary_list}")
    else:
        # 备用选择器
        options = page.eles('css:.salary-scope .ui-select-dropdown li', timeout=2)
        salary_list = [opt.text.strip() for opt in options if opt.text.strip()]
        print(f"  备用选择器找到 {len(salary_list)} 个: {salary_list}")

    if salary_list:
        with open(os.path.join(DATA_DIR, "boss_salary_options.json"), 'w', encoding='utf-8') as f:
            json.dump(salary_list, f, ensure_ascii=False, indent=2)
        print("  已保存 boss_salary_options.json")

    # 关闭下拉（点击空白处）
    page.actions.key_down('Escape').key_up('Escape')
    time.sleep(0.5)
else:
    print("  未找到薪资下拉框")
    salary_list = []

# ========== 任务2：城市列表 ==========
print("\n" + "="*50)
print("[任务2] 爬取城市列表")
print("="*50)

# 点击城市选择器
city_input = page.ele('css:.city-cascader .city-input', timeout=5)
if not city_input:
    city_input = page.ele('css:.city-cascader input', timeout=3)

if city_input:
    city_input.click()
    time.sleep(2)
    print("  已点击城市选择器")

    # 城市通常是级联选择器，先获取省份/热门城市
    city_options = page.eles('css:.ui-cascader-dropdown li', timeout=3)
    if not city_options:
        city_options = page.eles('css:.city-cascader .ui-cascader-menu li', timeout=2)
    if not city_options:
        city_options = page.eles('css:[class*="cascader"] li', timeout=2)

    if city_options:
        cities = [c.text.strip() for c in city_options if c.text.strip()]
        print(f"  找到 {len(cities)} 个城市/省份选项")
        print(f"  前20个: {cities[:20]}")
    else:
        cities = []
        print("  未找到城市选项，保存HTML分析...")
        html = page.html
        with open(os.path.join(DATA_DIR, "boss_city_debug.html"), 'w', encoding='utf-8') as f:
            f.write(html)

    if cities:
        with open(os.path.join(DATA_DIR, "boss_city_options.json"), 'w', encoding='utf-8') as f:
            json.dump(cities, f, ensure_ascii=False, indent=2)
        print("  已保存 boss_city_options.json")

    page.actions.key_down('Escape').key_up('Escape')
    time.sleep(0.5)
else:
    print("  未找到城市选择器")
    cities = []

# ========== 任务3：期望行业 ==========
print("\n" + "="*50)
print("[任务3] 爬取期望行业列表")
print("="*50)

# 点击期望行业
industry_el = page.ele('text:不限', timeout=3)
if not industry_el:
    industry_el = page.ele('css:.industry-select', timeout=3)
if not industry_el:
    # 找"期望行业"标签旁边的可点击元素
    industry_el = page.ele('css:[class*="industry"]', timeout=3)

if industry_el:
    industry_el.click()
    time.sleep(2)
    print("  已点击期望行业")

    # 检查行业弹窗
    title = page.ele('text:请选择行业类别', timeout=3)
    if title:
        print("  行业弹窗已打开!")
        # 爬取行业列表
        industry_items = page.eles('css:.dialog-interest-position li', timeout=3)
        if not industry_items:
            industry_items = page.eles('css:[class*="interest"] li', timeout=2)
        if not industry_items:
            industry_items = page.eles('css:[class*="industry"] li', timeout=2)

        if industry_items:
            industries = [item.text.strip() for item in industry_items if item.text.strip()]
            print(f"  找到 {len(industries)} 个行业选项")
            print(f"  前20个: {industries[:20]}")
            with open(os.path.join(DATA_DIR, "boss_industry_options.json"), 'w', encoding='utf-8') as f:
                json.dump(industries, f, ensure_ascii=False, indent=2)
            print("  已保存 boss_industry_options.json")
        else:
            print("  未找到行业列表元素")
            html = page.html
            with open(os.path.join(DATA_DIR, "boss_industry_debug.html"), 'w', encoding='utf-8') as f:
                f.write(html)
    else:
        print("  行业弹窗未出现")
else:
    print("  未找到期望行业入口")

print("\n" + "="*50)
print("爬取结束")
print("="*50)
