"""
51job简历页面 - 全量结构审计脚本

功能：
1. 连接已登录的 Edge 浏览器（端口由全项目统一配置区 registry 提供）
2. 导航到简历编辑页面
3. 全量扫描 DOM 结构、CSS 布局、交互元素
4. 探测前端框架（React/Vue/Angular）
5. 提取所有表单字段和选项
6. 截图保存
7. 导出审计报告 JSON

用法：
    python 51job_resume_audit.py
"""

import os
import sys
import json
import time
import re

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_BACKEND_DIR = os.path.dirname(_RESUME_EDITOR_DIR)
_DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, "data")

from DrissionPage import ChromiumPage, ChromiumOptions

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port

# 配置
PORT = get_platform_port("51job")
JOB51_RESUME_URL = "https://www.51job.com/resume/center"
AUDIT_OUTPUT = os.path.join(_DATA_DIR, "51job_audit_report.json")
SCREENSHOT_DIR = os.path.join(_DATA_DIR, "51job_screenshots")


def connect_browser():
    """连接已启动的浏览器（端口 PORT），端口无响应直接报错，绝不自动拉起新浏览器"""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from browser_common import connect_page
    return connect_page(PORT)

def detect_framework(page) -> dict:
    """探测前端框架"""
    print("\n[1/6] 探测前端框架...")

    result = {"framework": "unknown", "details": {}}

    # 检测 React
    react_check = page.run_js("""
        const root = document.getElementById('root') || document.getElementById('app') || document.getElementById('__next');
        if (root && root._reactRootContainer) return 'react-legacy';
        if (root && root.__reactFiber$) return 'react-18';
        const allEls = document.querySelectorAll('*');
        for (let i = 0; i < Math.min(allEls.length, 100); i++) {
            const keys = Object.keys(allEls[i]);
            const fiberKey = keys.find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
            if (fiberKey) return 'react-fiber';
        }
        return null;
    """)
    if react_check:
        result["framework"] = "react"
        result["details"]["type"] = react_check
        print(f"  检测到 React ({react_check})")

    # 检测 Vue
    vue_check = page.run_js("""
        const allEls = document.querySelectorAll('*');
        for (let i = 0; i < Math.min(allEls.length, 100); i++) {
            if (allEls[i].__vue__) return 'vue2';
            if (allEls[i].__vue_app__) return 'vue3';
        }
        if (window.__VUE_DEVTOOLS_GLOBAL_HOOK__) return 'vue-devtools';
        return null;
    """)
    if vue_check:
        result["framework"] = "vue"
        result["details"]["type"] = vue_check
        print(f"  检测到 Vue ({vue_check})")

    # 检测 Angular
    angular_check = page.run_js("""
        if (window.ng) return 'angular';
        const root = document.querySelector('[ng-version]') || document.querySelector('[_nghost]');
        if (root) return 'angular-component';
        return null;
    """)
    if angular_check:
        result["framework"] = "angular"
        result["details"]["type"] = angular_check
        print(f"  检测到 Angular ({angular_check})")

    # 检测 jQuery
    jquery_check = page.run_js("""
        if (window.jQuery) return window.jQuery.fn.jquery;
        if (window.$ && window.$.fn && window.$.fn.jquery) return window.$.fn.jquery;
        return null;
    """)
    if jquery_check:
        result["details"]["jquery"] = jquery_check
        print(f"  检测到 jQuery ({jquery_check})")

    # 检测其他框架/构建工具
    other = page.run_js("""
        const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
        const frameworks = [];
        scripts.forEach(s => {
            if (s.includes('vue')) frameworks.push('vue-script');
            if (s.includes('react')) frameworks.push('react-script');
            if (s.includes('angular')) frameworks.push('angular-script');
            if (s.includes('next')) frameworks.push('nextjs');
            if (s.includes('webpack')) frameworks.push('webpack');
            if (s.includes('vite')) frameworks.push('vite');
        });
        // 检查 meta 标签
        const gen = document.querySelector('meta[name="generator"]');
        if (gen) frameworks.push('generator:' + gen.content);
        return JSON.stringify(frameworks);
    """)
    if other:
        try:
            other_list = json.loads(other)
            if other_list:
                result["details"]["scripts"] = other_list
                print(f"  脚本框架线索: {other_list}")
        except:
            pass

    if result["framework"] == "unknown":
        print("  未检测到主流框架")
    return result


def scan_page_structure(page) -> dict:
    """扫描页面整体结构"""
    print("\n[2/6] 扫描页面结构...")

    # 获取页面标题和URL
    info = {
        "url": page.url,
        "title": page.title,
    }

    # 扫描主要容器
    structure = page.run_js("""
        (function() {
            const result = {
                body_children: [],
                main_containers: [],
                all_sections: []
            };

            // body 直接子元素
            const body = document.body;
            Array.from(body.children).forEach(child => {
                result.body_children.push({
                    tag: child.tagName,
                    id: child.id || '',
                    className: child.className || '',
                    childCount: child.children.length,
                    rect: {
                        width: child.offsetWidth,
                        height: child.offsetHeight
                    }
                });
            });

            // 查找主要容器 (宽度 > 600px 且有子元素)
            const allDivs = document.querySelectorAll('div, section, article, main, aside, nav');
            allDivs.forEach(el => {
                if (el.offsetWidth > 600 && el.children.length >= 2) {
                    const style = window.getComputedStyle(el);
                    result.main_containers.push({
                        tag: el.tagName,
                        id: el.id || '',
                        className: el.className || '',
                        childCount: el.children.length,
                        rect: {
                            width: el.offsetWidth,
                            height: el.offsetHeight,
                            left: el.offsetLeft,
                            top: el.offsetTop
                        },
                        display: style.display,
                        flexDirection: style.flexDirection || ''
                    });
                }
            });

            // 查找所有 section 级元素
            document.querySelectorAll('section, [class*="section"], [class*="module"], [class*="card"]').forEach(el => {
                result.all_sections.push({
                    tag: el.tagName,
                    id: el.id || '',
                    className: el.className || '',
                    childCount: el.children.length,
                    rect: { width: el.offsetWidth, height: el.offsetHeight },
                    text_preview: (el.innerText || '').substring(0, 100)
                });
            });

            return JSON.stringify(result);
        })();
    """)

    if structure:
        try:
            info["structure"] = json.loads(structure)
            nc = len(info["structure"].get("main_containers", []))
            ns = len(info["structure"].get("all_sections", []))
            print(f"  主容器: {nc}, 区块: {ns}")
        except:
            info["structure"] = {}
    else:
        info["structure"] = {}

    return info


def scan_resume_modules(page) -> list:
    """扫描简历编辑页的所有模块"""
    print("\n[3/6] 扫描简历模块...")

    # 先导航到简历编辑页
    if "resume/center" not in page.url:
        print("  正在导航到简历编辑页...")
        page.get(JOB51_RESUME_URL)
        time.sleep(3)

    modules_raw = page.run_js("""
        (function() {
            const modules = [];

            // 策略1: 查找带有明确 class 的模块容器
            const selectors = [
                '[class*="resume"] [class*="module"]',
                '[class*="resume"] [class*="section"]',
                '[class*="resume"] [class*="card"]',
                '[class*="resume"] [class*="item"]',
                '[class*="resume"] [class*="block"]',
                '[class*="resume"] [class*="wrap"]',
                '[class*="resume"] > div',
                '.resume-content > div',
                '[class*="content"] > div',
                'main > div',
                '#resumeContent > div',
                '.my-resume > div',
                '[class*="myresume"] > div'
            ];

            const seen = new Set();
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const key = el.tagName + '.' + (el.className || '').split(' ')[0] + el.offsetTop;
                    if (seen.has(key)) return;
                    if (el.offsetWidth < 200) return;  // 太小的跳过
                    if (el.offsetHeight < 30) return;
                    seen.add(key);

                    // 查找模块标题
                    let title = '';
                    const h = el.querySelector('h1, h2, h3, h4, h5, h6, [class*="title"], [class*="header"]');
                    if (h) title = (h.innerText || '').trim();

                    // 查找编辑按钮
                    const editBtn = el.querySelector('[class*="edit"], [class*="modify"], button, a[class*="edit"]');
                    let editInfo = null;
                    if (editBtn) {
                        editInfo = {
                            tag: editBtn.tagName,
                            text: (editBtn.innerText || '').trim(),
                            className: editBtn.className || ''
                        };
                    }

                    modules.push({
                        tag: el.tagName,
                        id: el.id || '',
                        className: el.className || '',
                        title: title,
                        text_preview: (el.innerText || '').substring(0, 200),
                        childCount: el.children.length,
                        rect: {
                            width: el.offsetWidth,
                            height: el.offsetHeight,
                            left: el.offsetLeft,
                            top: el.offsetTop
                        },
                        hasEditButton: !!editBtn,
                        editButton: editInfo,
                        html_preview: el.outerHTML.substring(0, 500)
                    });
                });
            });

            // 按 top 排序
            modules.sort((a, b) => a.rect.top - b.rect.top);

            return JSON.stringify(modules);
        })();
    """)

    modules = []
    if modules_raw:
        try:
            modules = json.loads(modules_raw)
            print(f"  发现 {len(modules)} 个候选模块")
            for i, m in enumerate(modules):
                print(f"    [{i}] {m['title'] or m['className'][:50]} ({m['rect']['width']}x{m['rect']['height']})")
        except:
            modules = []
    return modules


def extract_form_fields(page) -> dict:
    """提取页面中所有表单字段"""
    print("\n[4/6] 提取表单字段...")

    fields_raw = page.run_js("""
        (function() {
            const fields = {
                inputs: [],
                textareas: [],
                selects: [],
                labels: []
            };

            // 提取所有 input
            document.querySelectorAll('input').forEach(el => {
                const label = el.closest('label') || el.parentElement;
                fields.inputs.push({
                    type: el.type || 'text',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    value: el.value || '',
                    className: el.className || '',
                    required: el.required || false,
                    maxLength: el.maxLength > 0 ? el.maxLength : null,
                    labelText: label ? (label.innerText || '').trim().substring(0, 50) : '',
                    rect: { width: el.offsetWidth, height: el.offsetHeight }
                });
            });

            // 提取所有 textarea
            document.querySelectorAll('textarea').forEach(el => {
                const label = el.closest('label') || el.parentElement;
                fields.textareas.push({
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    value: (el.value || '').substring(0, 100),
                    className: el.className || '',
                    maxLength: el.maxLength > 0 ? el.maxLength : null,
                    labelText: label ? (label.innerText || '').trim().substring(0, 50) : '',
                    rect: { width: el.offsetWidth, height: el.offsetHeight }
                });
            });

            // 提取所有 select
            document.querySelectorAll('select').forEach(el => {
                const options = Array.from(el.options).map(o => ({
                    value: o.value,
                    text: o.text,
                    selected: o.selected
                }));
                fields.selects.push({
                    name: el.name || '',
                    id: el.id || '',
                    className: el.className || '',
                    options: options,
                    labelText: (el.closest('label') || el.parentElement || {}).innerText || '',
                    rect: { width: el.offsetWidth, height: el.offsetHeight }
                });
            });

            // 提取所有 label 文本
            document.querySelectorAll('label, [class*="label"], [class*="field-name"]').forEach(el => {
                const text = (el.innerText || '').trim();
                if (text && text.length < 30) {
                    fields.labels.push({
                        text: text,
                        tag: el.tagName,
                        className: el.className || '',
                        htmlFor: el.htmlFor || ''
                    });
                }
            });

            return JSON.stringify(fields);
        })();
    """)

    fields = {}
    if fields_raw:
        try:
            fields = json.loads(fields_raw)
            ni = len(fields.get("inputs", []))
            nt = len(fields.get("textareas", []))
            ns = len(fields.get("selects", []))
            nl = len(fields.get("labels", []))
            print(f"  Input: {ni}, Textarea: {nt}, Select: {ns}, Label: {nl}")
        except:
            fields = {}
    return fields


def extract_css_styles(page) -> dict:
    """提取页面关键 CSS 样式信息"""
    print("\n[5/6] 提取 CSS 样式...")

    css_raw = page.run_js("""
        (function() {
            const result = {
                primary_colors: [],
                fonts: [],
                layout_info: {}
            };

            // 提取页面主要颜色
            const colorSet = new Set();
            const fontSet = new Set();
            const elements = document.querySelectorAll('body, header, main, nav, .btn, button, [class*="primary"], [class*="header"], [class*="title"]');

            elements.forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.color) colorSet.add(style.color);
                if (style.backgroundColor && style.backgroundColor !== 'rgba(0, 0, 0, 0)') colorSet.add(style.backgroundColor);
                if (style.fontFamily) fontSet.add(style.fontFamily);
            });

            result.primary_colors = Array.from(colorSet).slice(0, 20);
            result.fonts = Array.from(fontSet).slice(0, 5);

            // 页面布局信息
            const body = document.body;
            const bodyStyle = window.getComputedStyle(body);
            result.layout_info = {
                body_width: body.offsetWidth,
                body_min_width: bodyStyle.minWidth,
                body_bg: bodyStyle.backgroundColor
            };

            // 查找主内容区
            const mainContent = document.querySelector('main, [class*="content"], [class*="main"], .container');
            if (mainContent) {
                const cs = window.getComputedStyle(mainContent);
                result.layout_info.main_content = {
                    tag: mainContent.tagName,
                    className: mainContent.className,
                    width: mainContent.offsetWidth,
                    max_width: cs.maxWidth,
                    margin: cs.margin,
                    padding: cs.padding,
                    display: cs.display
                };
            }

            return JSON.stringify(result);
        })();
    """)

    css = {}
    if css_raw:
        try:
            css = json.loads(css_raw)
            nc = len(css.get("primary_colors", []))
            print(f"  颜色数: {nc}")
        except:
            css = {}
    return css


def capture_interactive_elements(page) -> list:
    """捕获所有可交互元素（按钮、链接、编辑入口等）"""
    print("\n[6/6] 捕获交互元素...")

    interactive_raw = page.run_js("""
        (function() {
            const items = [];
            const selectors = [
                'button',
                'a[href]',
                '[onclick]',
                '[class*="edit"]',
                '[class*="add"]',
                '[class*="delete"]',
                '[class*="remove"]',
                '[class*="btn"]',
                '[class*="save"]',
                '[role="button"]',
                '[class*="dialog"]',
                '[class*="modal"]',
                '[class*="popup"]'
            ];

            const seen = new Set();
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const key = el.tagName + el.offsetLeft + el.offsetTop + (el.innerText || '').substring(0, 20);
                    if (seen.has(key)) return;
                    if (el.offsetWidth === 0 && el.offsetHeight === 0) return;
                    seen.add(key);

                    items.push({
                        tag: el.tagName,
                        text: (el.innerText || '').trim().substring(0, 50),
                        className: el.className || '',
                        id: el.id || '',
                        href: el.href || '',
                        rect: {
                            width: el.offsetWidth,
                            height: el.offsetHeight,
                            left: el.offsetLeft,
                            top: el.offsetTop
                        },
                        ariaLabel: el.getAttribute('aria-label') || '',
                        title: el.title || ''
                    });
                });
            });

            items.sort((a, b) => a.rect.top - b.rect.top);
            return JSON.stringify(items);
        })();
    """)

    items = []
    if interactive_raw:
        try:
            items = json.loads(interactive_raw)
            print(f"  发现 {len(items)} 个交互元素")
        except:
            items = []
    return items


def take_screenshots(page):
    """对页面进行滚动截图"""
    print("\n  正在截图...")
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # 全页截图
    page.get_screenshot(path=SCREENSHOT_DIR, name="01_full_page.png", full_page=True)
    print("  全页截图已保存")

    # 顶部截图
    page.scroll.to_top()
    time.sleep(0.5)
    page.get_screenshot(path=SCREENSHOT_DIR, name="02_top.png")
    print("  顶部截图已保存")

    # 逐屏截图
    for i in range(1, 6):
        page.scroll.down(800)
        time.sleep(0.5)
        page.get_screenshot(path=SCREENSHOT_DIR, name=f"03_scroll_{i}.png")
        print(f"  滚动截图 {i} 已保存")


def get_page_html_structure(page) -> str:
    """获取页面主体HTML结构（用于后续分析）"""
    html = page.run_js("""
        (function() {
            // 获取主内容区的HTML结构（不含具体数据，只看骨架）
            const main = document.querySelector('main') ||
                        document.querySelector('[class*="content"]') ||
                        document.querySelector('[class*="resume"]') ||
                        document.body;

            // 简化HTML：只保留标签名、class、id
            function simplify(el, depth) {
                if (depth > 6) return '';
                if (!el || !el.tagName) return '';
                const tag = el.tagName.toLowerCase();
                const cls = el.className ? ` class="${el.className}"` : '';
                const id = el.id ? ` id="${el.id}"` : '';
                const indent = '  '.repeat(depth);
                let result = `${indent}<${tag}${id}${cls}>\\n`;
                if (el.children.length === 0 && el.innerText) {
                    const text = el.innerText.trim().substring(0, 50);
                    if (text) result += `${indent}  "${text}"\\n`;
                }
                Array.from(el.children).forEach(child => {
                    result += simplify(child, depth + 1);
                });
                result += `${indent}</${tag}>\\n`;
                return result;
            }

            return simplify(main, 0).substring(0, 50000);
        })();
    """)
    return html or ""


def run_audit():
    """执行完整审计"""
    print("=" * 60)
    print("  51job简历页面 - 全量审计")
    print("=" * 60)

    page = connect_browser()
    print(f"\n  已连接到浏览器 (端口 {PORT})")
    print(f"  当前 URL: {page.url}")

    # 导航到简历编辑页
    print(f"\n  正在导航到简历编辑页: {JOB51_RESUME_URL}")
    page.get(JOB51_RESUME_URL)
    time.sleep(4)
    print(f"  页面 URL: {page.url}")
    print(f"  页面标题: {page.title}")

    # 执行审计
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": page.url,
        "title": page.title,
    }

    report["framework"] = detect_framework(page)
    report["page_info"] = scan_page_structure(page)
    report["modules"] = scan_resume_modules(page)
    report["form_fields"] = extract_form_fields(page)
    report["css_styles"] = extract_css_styles(page)
    report["interactive_elements"] = capture_interactive_elements(page)

    # 截图
    take_screenshots(page)

    # 获取HTML骨架
    report["html_skeleton"] = get_page_html_structure(page)

    # 保存报告
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(AUDIT_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  审计报告已保存: {AUDIT_OUTPUT}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("  审计摘要")
    print("=" * 60)
    print(f"  框架: {report['framework']['framework']}")
    print(f"  模块数: {len(report.get('modules', []))}")
    ff = report.get('form_fields', {})
    print(f"  表单字段: input={len(ff.get('inputs', []))}, textarea={len(ff.get('textareas', []))}, select={len(ff.get('selects', []))}")
    print(f"  交互元素: {len(report.get('interactive_elements', []))}")
    print(f"  报告文件: {AUDIT_OUTPUT}")


if __name__ == "__main__":
    run_audit()
