"""
爬取BOSS直聘资格证书分类数据（v3 - 使用DrissionPage原生点击绕过isTrusted）
"""
import os, sys, time, json, re

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_address('127.0.0.1:19222')
page = ChromiumPage(co)
print("已连接浏览器")

# 确保弹窗打开
dialog = page.ele('css:.certification-dialog', timeout=3)
if not dialog:
    print("弹窗未打开，尝试点击...")
    # 用DrissionPage原生点击
    cert_section = page.ele('css:.resume-certification', timeout=3)
    if cert_section:
        add_btn = cert_section.ele('text:添加', timeout=2) or cert_section.ele('text:编辑', timeout=2)
        if add_btn:
            add_btn.click()
            time.sleep(2)
    dialog = page.ele('css:.certification-dialog', timeout=3)

if not dialog:
    print("错误：无法打开弹窗")
    sys.exit(1)

print("弹窗已打开!")

# 获取分类列表（用DrissionPage原生方式）
menu_items = page.eles('css:.certification-content-menu li')
categories = []
for item in menu_items:
    span = item.ele('tag:span')
    if span:
        text = span.text.strip()
        if text:
            categories.append(text)

print(f"分类: {len(categories)} 个 → {categories}")

# 逐个分类用原生点击并获取证书
cert_data = {}

for i, cat_name in enumerate(categories):
    # 用DrissionPage原生点击（生成trusted事件）
    menu_items = page.eles('css:.certification-content-menu li')
    clicked = False
    for item in menu_items:
        span = item.ele('tag:span')
        if span and span.text.strip() == cat_name:
            item.click()
            clicked = True
            break

    if not clicked:
        print(f"  [{i+1}/{len(categories)}] {cat_name} → 未找到")
        continue

    time.sleep(0.8)

    # 获取右侧证书（用JS读取DOM，这不需要trusted事件）
    certs = page.run_js('''
        const results = [];
        // 找当前显示的 content-main
        const mains = document.querySelectorAll('.certification-content-main');
        let target = null;
        for (const main of mains) {
            if (main.classList.contains('current') || main.offsetHeight > 0) {
                target = main;
                break;
            }
        }
        if (!target) target = mains[0];
        if (!target) return JSON.stringify([]);

        const labels = target.querySelectorAll('label.checkbox');
        labels.forEach(el => {
            const clone = el.cloneNode(true);
            const inner = clone.querySelector('.checkbox-inner');
            if (inner) inner.remove();
            const text = clone.textContent.trim();
            if (text && text.length < 40 && !results.includes(text)) {
                results.push(text);
            }
        });
        return JSON.stringify(results);
    ''')

    try:
        cert_list = json.loads(certs)
        if cert_list:
            cert_data[cat_name] = cert_list
            print(f"  [{i+1}/{len(categories)}] {cat_name} → {len(cert_list)} 个: {cert_list[:3]}...")
        else:
            print(f"  [{i+1}/{len(categories)}] {cat_name} → 空")
    except Exception as e:
        print(f"  [{i+1}/{len(categories)}] {cat_name} → 错误: {e}")

# 保存
output_file = os.path.join(DATA_DIR, "boss_certificates.json")
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(cert_data, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in cert_data.values())
print(f"\n完成! {len(cert_data)} 个分类, {total} 个证书")
print(f"保存到: {output_file}")
