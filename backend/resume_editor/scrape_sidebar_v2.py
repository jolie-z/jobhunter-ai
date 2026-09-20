#!/usr/bin/env python3
"""
Enriched sidebar scraper - uses JSON.stringify to avoid DrissionPage serialization issues.
"""

import json
import os
import time
from DrissionPage import ChromiumPage, ChromiumOptions

PORT = 19222
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "boss_sidebar_structure.json")

co = ChromiumOptions()
co.set_local_port(PORT)
page = ChromiumPage(co)
print(f"Connected. URL: {page.url}")

def run_js_json(page, js_code):
    """Run JS that returns JSON.stringify result, then parse in Python."""
    wrapper = f"return JSON.stringify((function(){{ {js_code} }})());"
    raw = page.run_js(wrapper)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"    JSON parse error: {e}, raw[:200]={str(raw)[:200]}")
        return None


# [1] Full sidebar HTML
print("\n[1] Getting sidebar HTML ...")
sidebar_info = run_js_json(page, """
    var el = document.querySelector('.resume-catalogue');
    if (!el) return null;
    return {
        outerHTML: el.outerHTML,
        className: el.className,
        tagName: el.tagName,
        id: el.id,
        computedStyle: {
            display: getComputedStyle(el).display,
            position: getComputedStyle(el).position,
            width: getComputedStyle(el).width,
            height: getComputedStyle(el).height,
        }
    };
""")
print(f"    Sidebar: {sidebar_info['tagName']}.{sidebar_info['className']}")

# [2] Detailed nav items
print("\n[2] Extracting nav items ...")
nav_items = run_js_json(page, """
    var sidebar = document.querySelector('.resume-catalogue');
    if (!sidebar) return [];
    var items = sidebar.querySelectorAll('li.catalogue-item');
    var results = [];
    for (var i = 0; i < items.length; i++) {
        var li = items[i];
        var attrs = {};
        for (var j = 0; j < li.attributes.length; j++) {
            attrs[li.attributes[j].name] = li.attributes[j].value;
        }
        var group = li.closest('.resume-catalogue-group');
        var groupTitle = group ? group.querySelector('.catalogue-title') : null;
        var span = li.querySelector('span');
        var tip = li.querySelector('.catalogue-tip');
        var icon = li.querySelector('i.catalogue-icon, i');
        results.push({
            index: i,
            text: span ? span.textContent.trim() : li.textContent.trim(),
            fullText: li.textContent.trim(),
            tag: li.tagName,
            className: li.className,
            allAttributes: attrs,
            ka: attrs['ka'] || null,
            isActive: /active|current|selected/i.test(li.className),
            groupTitle: groupTitle ? groupTitle.textContent.trim() : '',
            groupClassName: group ? group.className : '',
            hasTip: !!tip,
            tipText: tip ? tip.textContent.trim() : null,
            hasIcon: !!icon,
            iconClass: icon ? icon.className : null,
            outerHTML: li.outerHTML,
        });
    }
    return results;
""")
print(f"    Found {len(nav_items)} items:")
for it in nav_items:
    active = " [ACTIVE]" if it['isActive'] else ""
    ka = f" (ka={it['ka']})" if it['ka'] else ""
    group = f" [{it['groupTitle']}]" if it['groupTitle'] else ""
    print(f"      {it['index']}. {it['text']}{active}{ka}{group}")

# [3] Find section anchors on the page
print("\n[3] Finding section anchors ...")
sections = run_js_json(page, """
    var allWithId = document.querySelectorAll('[id]');
    var sections = [];
    for (var i = 0; i < allWithId.length; i++) {
        var el = allWithId[i];
        var id = el.id;
        if (/resume|base.?info|user.?desc|expect|work|project|education|certif|stay|abroad|volunteer|custom|geek/i.test(id)) {
            sections.push({
                id: id,
                tag: el.tagName,
                className: el.className,
                textPreview: (el.textContent || '').trim().substring(0, 80),
                rect_top: Math.round(el.getBoundingClientRect().top),
            });
        }
    }
    // Also find resume content area children
    var resumeContent = document.querySelector('.resume-content, .resume-main, .resume-body, .resume-edit-main, [class*="resume-edit"]');
    var contentInfo = null;
    var contentChildren = [];
    if (resumeContent) {
        contentInfo = { tag: resumeContent.tagName, className: resumeContent.className, id: resumeContent.id };
        for (var i = 0; i < resumeContent.children.length; i++) {
            var c = resumeContent.children[i];
            var dattrs = {};
            for (var j = 0; j < c.attributes.length; j++) {
                if (c.attributes[j].name.startsWith('data-')) {
                    dattrs[c.attributes[j].name] = c.attributes[j].value;
                }
            }
            contentChildren.push({
                index: i,
                tag: c.tagName,
                id: c.id || '',
                className: (c.className || '').toString().substring(0, 100),
                dataAttributes: dattrs,
                textPreview: (c.textContent || '').trim().substring(0, 60),
                rect_top: Math.round(c.getBoundingClientRect().top),
            });
        }
    }
    return { sections: sections, contentContainer: contentInfo, contentChildren: contentChildren };
""")
if sections:
    print(f"    IDs found: {len(sections['sections'])}")
    for s in sections['sections']:
        print(f"      #{s['id']}  ({s['tag']}.{s['className'][:50]})  top={s['rect_top']}px")
    print(f"    Content container: {sections.get('contentContainer')}")
    print(f"    Content children: {len(sections.get('contentChildren', []))}")
    for c in sections.get('contentChildren', [])[:15]:
        print(f"      [{c['index']}] {c['tag']}#{c['id'] or '-'} .{c['className'][:50]}  top={c['rect_top']}px")

# [4] Test active state by clicking each item
print("\n[4] Testing active states by clicking each item ...")
active_tests = []
for item in nav_items:
    text = item['text']
    if not text or '\n' in text:
        # Use the ka attribute to find the element instead
        continue
    try:
        # Find the specific li
        ka = item.get('ka')
        if ka:
            el = page.ele(f"css:li[ka='{ka}']", timeout=1)
        else:
            el = page.ele(f"css:li.catalogue-item span:text('{text}')", timeout=1)

        if el:
            el.click()
            time.sleep(0.5)
            # Check active state
            active_info = run_js_json(page, """
                var sidebar = document.querySelector('.resume-catalogue');
                if (!sidebar) return [];
                var items = sidebar.querySelectorAll('li.catalogue-item');
                var active = [];
                for (var i = 0; i < items.length; i++) {
                    if (/active|current|selected/i.test(items[i].className)) {
                        var span = items[i].querySelector('span');
                        active.push({
                            text: span ? span.textContent.trim() : items[i].textContent.trim(),
                            className: items[i].className,
                        });
                    }
                }
                return active;
            """)
            active_tests.append({
                "clicked": text,
                "ka": ka,
                "active_after": active_info or [],
            })
            for a in (active_info or []):
                print(f"      Clicked '{text}' -> active: '{a['text']}' class={a['className']}")
    except Exception as e:
        active_tests.append({"clicked": text, "error": str(e)})
        print(f"      Click '{text}' error: {e}")

# [5] Explore 自定义添加
print("\n[5] Exploring 自定义添加 ...")
custom_add = run_js_json(page, """
    var customGroup = document.querySelector('.resume-catalogue-group.custom-add');
    if (!customGroup) return { found: false };
    var title = customGroup.querySelector('.catalogue-title');
    var lis = customGroup.querySelectorAll('li');
    var items = [];
    for (var i = 0; i < lis.length; i++) {
        var span = lis[i].querySelector('span');
        var tip = lis[i].querySelector('.catalogue-tip');
        var icon = lis[i].querySelector('i');
        var attrs = {};
        for (var j = 0; j < lis[i].attributes.length; j++) {
            attrs[lis[i].attributes[j].name] = lis[i].attributes[j].value;
        }
        items.push({
            text: span ? span.textContent.trim() : lis[i].textContent.trim(),
            tipText: tip ? tip.textContent.trim() : null,
            hasIcon: !!icon,
            iconClass: icon ? icon.className : null,
            allAttributes: attrs,
            outerHTML: lis[i].outerHTML,
        });
    }
    return {
        found: true,
        className: customGroup.className,
        isExpand: customGroup.classList.contains('expand'),
        title: title ? title.textContent.trim() : null,
        titleClassName: title ? title.className : null,
        items: items,
        outerHTML: customGroup.outerHTML,
    };
""")
if custom_add.get('found'):
    print(f"    Title: {custom_add['title']}")
    print(f"    Expanded: {custom_add['isExpand']}")
    print(f"    Items ({len(custom_add['items'])}):")
    for ci in custom_add['items']:
        print(f"      - {ci['text']} (tip: {ci.get('tipText')})")

# [6] Click 自定义添加 title and check for dropdown/dialog
print("\n[6] Clicking 自定义添加 title ...")
try:
    custom_title_el = page.ele("css:.resume-catalogue-group.custom-add .catalogue-title", timeout=2)
    if custom_title_el:
        custom_title_el.click()
        time.sleep(1.5)
        after_click = run_js_json(page, """
            var modals = document.querySelectorAll('[class*="modal"], [class*="dialog"], [class*="popup"], [class*="popover"], [class*="dropdown"], [role="dialog"]');
            var visible = [];
            for (var i = 0; i < modals.length; i++) {
                var s = getComputedStyle(modals[i]);
                if (s.display !== 'none' && s.visibility !== 'hidden') {
                    visible.push({
                        tag: modals[i].tagName,
                        className: modals[i].className,
                        text: (modals[i].textContent || '').trim().substring(0, 300),
                        html: modals[i].outerHTML.substring(0, 1000),
                    });
                }
            }
            var cg = document.querySelector('.resume-catalogue-group.custom-add');
            return {
                visibleModals: visible,
                expandedAfterClick: cg ? cg.classList.contains('expand') : null,
                itemsAfterClick: (function() {
                    if (!cg) return [];
                    var lis = cg.querySelectorAll('li');
                    var r = [];
                    for (var i = 0; i < lis.length; i++) {
                        var span = lis[i].querySelector('span');
                        r.push(span ? span.textContent.trim() : lis[i].textContent.trim());
                    }
                    return r;
                })(),
            };
        """)
        print(f"    Visible modals: {len(after_click.get('visibleModals', []))}")
        for vm in after_click.get('visibleModals', []):
            print(f"      {vm['tag']}.{vm['className'][:60]}: {vm['text'][:100]}")
        print(f"    Expanded after click: {after_click.get('expandedAfterClick')}")
        print(f"    Items after click: {after_click.get('itemsAfterClick')}")
except Exception as e:
    print(f"    Error: {e}")
    after_click = {"error": str(e)}

# [7] All sidebar groups
print("\n[7] All sidebar groups ...")
groups = run_js_json(page, """
    var groups = document.querySelectorAll('.resume-catalogue-group');
    var result = [];
    for (var i = 0; i < groups.length; i++) {
        var g = groups[i];
        var title = g.querySelector('.catalogue-title');
        var lis = g.querySelectorAll('li');
        var items = [];
        for (var j = 0; j < lis.length; j++) {
            var span = lis[j].querySelector('span');
            var attrs = {};
            for (var k = 0; k < lis[j].attributes.length; k++) {
                attrs[lis[j].attributes[k].name] = lis[j].attributes[k].value;
            }
            items.push({
                text: span ? span.textContent.trim() : lis[j].textContent.trim(),
                allAttributes: attrs,
                outerHTML: lis[j].outerHTML,
            });
        }
        result.push({
            index: i,
            className: g.className,
            title: title ? title.textContent.trim() : null,
            titleClassName: title ? title.className : null,
            itemCount: lis.length,
            items: items,
            outerHTML: g.outerHTML,
        });
    }
    return result;
""")
for g in groups:
    print(f"    Group [{g['index']}]: '{g['title']}' ({g['itemCount']} items, class={g['className']})")

# ---------- Compile final JSON ----------
print("\n[8] Saving final enriched JSON ...")

final = {
    "page_url": page.url,
    "page_title": page.title,
    "sidebar": {
        "selector": ".resume-catalogue",
        "tag": sidebar_info["tagName"],
        "className": sidebar_info["className"],
        "id": sidebar_info.get("id", ""),
        "computedStyle": sidebar_info.get("computedStyle", {}),
        "outerHTML": sidebar_info["outerHTML"],
    },
    "groups": groups,
    "nav_items": nav_items,
    "section_anchors": sections,
    "active_state_tests": active_tests,
    "custom_add": custom_add,
    "custom_add_click_result": after_click if 'after_click' in dir() else None,
}

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(final, f, ensure_ascii=False, indent=2)

print(f"\nSaved to: {OUTPUT_PATH}")
print(f"Nav items: {len(nav_items)}")
print(f"Groups: {len(groups)}")
print(f"Section anchors: {len(sections.get('sections', [])) if sections else 0}")
print("Done!")
