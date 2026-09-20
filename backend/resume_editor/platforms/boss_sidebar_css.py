"""获取BOSS侧边栏的CSS样式"""
import json, os, time
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_local_port(19222)
page = ChromiumPage(co)

# 获取CSS样式
js_css = """
var result = {};

function getStyles(selector) {
    var el = document.querySelector(selector);
    if (!el) return null;
    var style = window.getComputedStyle(el);
    var rect = el.getBoundingClientRect();
    return {
        position: style.position,
        top: style.top,
        bottom: style.bottom,
        left: style.left,
        right: style.right,
        width: style.width,
        height: style.height,
        padding: style.padding,
        margin: style.margin,
        background: style.backgroundColor,
        borderRadius: style.borderRadius,
        boxShadow: style.boxShadow,
        fontSize: style.fontSize,
        color: style.color,
        fontWeight: style.fontWeight,
        lineHeight: style.lineHeight,
        overflow: style.overflow,
        zIndex: style.zIndex,
        display: style.display,
        flexDirection: style.flexDirection,
        rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
    };
}

result.catalogue = getStyles('.resume-catalogue');
result.catalogueGroup = getStyles('.resume-catalogue-group');
result.catalogueTitle = getStyles('.catalogue-title');
result.catalogueList = getStyles('.catalogue-list');
result.catalogueItem = getStyles('.catalogue-item');

// 获取active状态的item样式
var activeItem = document.querySelector('.catalogue-item.active, .catalogue-item-active, .catalogue-item.is-active');
result.activeItem = activeItem ? getStyles('.catalogue-item.active, .catalogue-item-active') : null;

// 获取hover伪类效果 - 检查CSS规则
var sheets = document.styleSheets;
var relevantRules = [];
try {
    for (var i = 0; i < sheets.length; i++) {
        try {
            var rules = sheets[i].cssRules || sheets[i].rules;
            for (var j = 0; j < rules.length; j++) {
                var ruleText = rules[j].cssText || '';
                if (ruleText.indexOf('catalogue') >= 0) {
                    relevantRules.push(ruleText.substring(0, 300));
                }
            }
        } catch(e) {}
    }
} catch(e) {}
result.cssRules = relevantRules;

// 检查整体布局：sidebar + content的flex/grid结构
var layout = document.querySelector('.resume-edit, .resume-wrap, .resume-container, [class*="resume-edit"]');
if (layout) {
    var layoutStyle = window.getComputedStyle(layout);
    result.layout = {
        class: layout.className,
        display: layoutStyle.display,
        flexDirection: layoutStyle.flexDirection,
        justifyContent: layoutStyle.justifyContent,
        alignItems: layoutStyle.alignItems,
        gap: layoutStyle.gap
    };
}

// 找到侧边栏和内容区的父级flex容器
var catalogue = document.querySelector('.resume-catalogue');
if (catalogue) {
    var p = catalogue.parentElement;
    while (p && p.tagName !== 'BODY') {
        var ps = window.getComputedStyle(p);
        if (ps.display === 'flex' || ps.display === 'grid') {
            result.flexParent = {
                tag: p.tagName,
                class: p.className,
                id: p.id,
                display: ps.display,
                flexDirection: ps.flexDirection,
                gap: ps.gap,
                children: Array.from(p.children).map(function(c) {
                    return {tag: c.tagName, class: c.className, id: c.id};
                })
            };
            break;
        }
        p = p.parentElement;
    }
}

return JSON.stringify(result);
"""
raw = page.run_js(js_css)
if raw:
    result = json.loads(raw)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 保存
    output = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "boss_sidebar_css.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
else:
    print("No result")
