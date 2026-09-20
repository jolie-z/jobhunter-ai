#!/usr/bin/env python3
"""
Scrape BOSS直聘 "编辑个人信息" form - v3 (final).
Parses the form HTML directly for dropdown options and date picker structure.
Also extracts Vue component data.
"""

import json
import os
import re
import time
import datetime
import traceback
from html.parser import HTMLParser
from DrissionPage import ChromiumPage, ChromiumOptions

PORT = 19222
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "boss_userinfo_dialog.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------- connect ----------
print("[1] Connecting ...")
co = ChromiumOptions()
co.set_local_port(PORT)
page = ChromiumPage(co)
if "zhipin.com/web/geek/resume" not in page.url:
    page.get("https://www.zhipin.com/web/geek/resume")
    page.wait.load_start()
    time.sleep(3)
print(f"    URL: {page.url}")

# ---------- locate the form ----------
print("[2] Locating form ...")
form = None
for f in page.eles("css:.item-form"):
    try:
        t = f.ele("css:.title", timeout=0.5)
        if t and "编辑个人信息" in t.text:
            form = f
            break
    except:
        continue

if not form:
    print("    ERROR: form not found")
    exit(1)

form_html = form.html
form_html_path = os.path.join(OUTPUT_DIR, "boss_userinfo_form_full.html")
with open(form_html_path, "w", encoding="utf-8") as f:
    f.write(form_html)
print(f"    Form HTML saved ({len(form_html)} chars)")

# ---------- extract form items ----------
print("[3] Parsing form items ...")
form_items = form.eles("css:.form-item")
field_overview = []
for i, item in enumerate(form_items):
    lbl = item.ele("css:.item-label", timeout=0.3)
    label = lbl.text.strip() if lbl else f"field_{i}"
    ka = item.attr("ka") or ""
    field_overview.append({"index": i, "label": label, "ka_attr": ka})
    print(f"    [{i}] {label} (ka={ka})")

# ============================================================
# PARSE HTML DIRECTLY for reliable extraction
# ============================================================

# ---------- 求职状态 ----------
print("\n[4] 求职状态 (Job Status) ...")
# Find the ui-select for job status
status_select = form.ele("css:[ka='resume_form_edit_applyStatus']", timeout=1)
job_status = {}
if status_select:
    # Hidden input value
    hidden = status_select.ele("css:input[type='hidden']", timeout=0.5)
    if hidden:
        job_status["hidden_value"] = hidden.attr("value")

    # Current display value
    display = status_select.ele("css:.ui-select-selected-value", timeout=0.5)
    if display:
        job_status["current_display"] = display.text.strip()

    # Options from the dropdown list (already in HTML even if hidden)
    items = status_select.eles("css:.ui-dropdown-list .ui-select-item")
    options = []
    for it in items:
        cls = it.attr("class") or ""
        options.append({
            "text": it.text.strip(),
            "selected": "ui-select-item-selected" in cls,
        })
    job_status["options"] = options
    job_status["is_editable"] = True
    job_status["select_class"] = status_select.ele("css:.ui-select", timeout=0.3).attr("class") if status_select.ele("css:.ui-select", timeout=0.3) else ""

    # Also verify by clicking to open dropdown
    try:
        trigger = status_select.ele("css:.ui-select-selection", timeout=0.5)
        if trigger:
            trigger.scroll.to_see()
            time.sleep(0.3)
            trigger.click()
            time.sleep(1)

            # Read visible dropdown
            dd = status_select.ele("css:.ui-select-dropdown", timeout=0.5)
            if dd:
                style = dd.attr("style") or ""
                job_status["dropdown_visible"] = "display: none" not in style
                visible_items = dd.eles("css:.ui-dropdown-list .ui-select-item")
                live_options = []
                for vi in visible_items:
                    cls = vi.attr("class") or ""
                    live_options.append({
                        "text": vi.text.strip(),
                        "selected": "ui-select-item-selected" in cls,
                    })
                if live_options:
                    job_status["live_options"] = live_options
                    print(f"    Live options: {[o['text'] for o in live_options]}")

            # Close
            page.ele("tag:body").click(offset=(0, 0))
            time.sleep(0.5)
    except Exception as e:
        job_status["click_note"] = str(e)

print(f"    Options: {[o['text'] for o in job_status.get('options', [])]}")
print(f"    Current: {job_status.get('current_display')}")

# ---------- 性别 ----------
print("\n[5] 性别 (Gender) ...")
gender_section = None
for item in form_items:
    lbl = item.ele("css:.item-label", timeout=0.3)
    if lbl and "性别" in lbl.text:
        gender_section = item
        break

gender = {}
if gender_section:
    content = gender_section.ele("css:.item-content", timeout=0.5)
    if content:
        # Radio group
        radio_group = content.ele("css:.radio-group", timeout=0.5)
        if radio_group:
            gender["radio_group_class"] = radio_group.attr("class")
            gender["radio_group_name"] = radio_group.attr("name")

        labels = content.eles("css:label.radio-item")
        options = []
        for lbl in labels:
            cls = lbl.attr("class") or ""
            txt = lbl.text.strip()
            options.append({
                "text": txt,
                "checked": "radio-checked" in cls,
                "class": cls,
            })
        gender["options"] = options
        gender["is_editable"] = True
        gender["type"] = "radio_group"

        # Hidden input for value
        hidden = content.ele("css:input[type='hidden']", timeout=0.3)
        if hidden:
            gender["hidden_value"] = hidden.attr("value")

print(f"    Options: {gender.get('options', [])}")

# ---------- 牛人身份 ----------
print("\n[6] 牛人身份 (Identity) ...")
identity_section = None
for item in form_items:
    lbl = item.ele("css:.item-label", timeout=0.3)
    if lbl and "牛人身份" in lbl.text:
        identity_section = item
        break

identity = {}
if identity_section:
    content = identity_section.ele("css:.item-content", timeout=0.5)
    if content:
        select_el = content.ele("css:.ui-select", timeout=0.5)
        if select_el:
            select_cls = select_el.attr("class") or ""
            identity["select_class"] = select_cls
            identity["is_disabled"] = "ui-select-disabled" in select_cls

            # Current value
            display = select_el.ele("css:.ui-select-selected-value", timeout=0.3)
            if display:
                identity["current_display"] = display.text.strip()

            # Hidden input
            hidden = select_el.ele("css:input[type='hidden']", timeout=0.3)
            if hidden:
                identity["hidden_value"] = hidden.attr("value")

            # Options
            items = select_el.eles("css:.ui-dropdown-list .ui-select-item")
            options = []
            for it in items:
                cls = it.attr("class") or ""
                options.append({
                    "text": it.text.strip(),
                    "selected": "ui-select-item-selected" in cls,
                })
            identity["options"] = options

        # Append tip about needing APP
        tip = content.ele("css:.append-tip", timeout=0.3)
        if tip:
            identity["edit_note"] = tip.text.strip()

        identity["is_editable"] = False if identity.get("is_disabled") else True
        identity["type"] = "ui-select (disabled)" if identity.get("is_disabled") else "ui-select"

print(f"    Options: {[o['text'] for o in identity.get('options', [])]}")
print(f"    Disabled: {identity.get('is_disabled')}")
print(f"    Note: {identity.get('edit_note')}")

# ---------- 出生年月 ----------
print("\n[7] 出生年月 (Birth Date) ...")
birth_section = None
for item in form_items:
    lbl = item.ele("css:.item-label", timeout=0.3)
    if lbl and "出生" in lbl.text:
        birth_section = item
        break

birth = {}
if birth_section:
    content = birth_section.ele("css:.item-content", timeout=0.5)
    if content:
        dp = content.ele("css:.datepicker-wrap", timeout=0.5)
        if dp:
            birth["datepicker_ka"] = dp.attr("ka")

            # Input
            inp = dp.ele("css:input", timeout=0.3)
            if inp:
                birth["input_placeholder"] = inp.attr("placeholder")
                birth["input_readonly"] = True
                birth["input_value"] = inp.attr("value") or ""

            # Month panel
            month_panel = dp.ele("css:.datepicker-month", timeout=0.3)
            if month_panel:
                year_btn = month_panel.ele("css:.month-year-btn", timeout=0.3)
                if year_btn:
                    birth["month_panel_year_label"] = year_btn.text.strip()

                months = []
                for cell in month_panel.eles("css:.cell.month"):
                    cls = cell.attr("class") or ""
                    months.append({
                        "text": cell.text.strip(),
                        "selected": "selected" in cls,
                    })
                birth["months"] = months

            # Year panel
            year_panel = dp.ele("css:.datepicker-year", timeout=0.3)
            if year_panel:
                header = year_panel.ele("css:.picker-header", timeout=0.3)
                if header:
                    spans = header.eles("css:span")
                    for sp in spans:
                        txt = sp.text.strip()
                        if txt and ("年" in txt or "-" in txt):
                            birth["year_panel_range"] = txt
                            break
                    # Check prev/next buttons
                    prev_btn = header.ele("css:.prev", timeout=0.3)
                    next_btn = header.ele("css:.next", timeout=0.3)
                    birth["year_prev_disabled"] = prev_btn.attr("class") == "prev disabled" if prev_btn else None
                    birth["year_next_disabled"] = "disabled" in (next_btn.attr("class") or "") if next_btn else None

                years = []
                for cell in year_panel.eles("css:.cell.year"):
                    cls = cell.attr("class") or ""
                    years.append({
                        "text": cell.text.strip(),
                        "selected": "selected" in cls,
                    })
                birth["years"] = years

            # Click to open datepicker and check year range navigation
            if inp:
                try:
                    inp.scroll.to_see()
                    time.sleep(0.3)
                    inp.click()
                    time.sleep(1)

                    # Check which panel is visible
                    panels = dp.eles("css:.datepicker-pannel")
                    for panel in panels:
                        style = panel.attr("style") or ""
                        cls = panel.attr("class") or ""
                        if "display: none" not in style:
                            birth["visible_panel_on_open"] = "year" if "year" in cls else "month" if "month" in cls else cls

                    # Try clicking the year button to switch to year panel
                    if month_panel:
                        year_btn = month_panel.ele("css:.month-year-btn", timeout=0.3)
                        if year_btn:
                            try:
                                year_btn.click()
                                time.sleep(0.5)
                                # Now check year panel
                                for panel in dp.eles("css:.datepicker-pannel"):
                                    try:
                                        style = panel.attr("style") or ""
                                        cls = panel.attr("class") or ""
                                        if "year" in cls and "display: none" not in style:
                                            # Get the range
                                            spans = panel.ele("css:.picker-header", timeout=0.3)
                                            if spans:
                                                for sp in spans.eles("css:span"):
                                                    txt = sp.text.strip()
                                                    if txt and ("年" in txt or "-" in txt):
                                                        birth["year_panel_range_live"] = txt

                                            # Try clicking prev to see if we can go earlier
                                            prev = panel.ele("css:.prev", timeout=0.3)
                                            if prev and "disabled" not in (prev.attr("class") or ""):
                                                prev.click()
                                                time.sleep(0.5)
                                                # Read new range
                                                for sp in panel.ele("css:.picker-header", timeout=0.3).eles("css:span"):
                                                    txt = sp.text.strip()
                                                    if txt and ("年" in txt or "-" in txt):
                                                        birth["year_range_after_prev"] = txt
                                                cells = panel.eles("css:.cell.year")
                                                birth["years_after_prev"] = [c.text.strip() for c in cells]

                                            # Reset: click next to go back
                                            nxt = panel.ele("css:.next", timeout=0.3)
                                            if nxt and "disabled" not in (nxt.attr("class") or ""):
                                                nxt.click()
                                                time.sleep(0.3)
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                    # Close
                    page.ele("tag:body").click(offset=(0, 0))
                    time.sleep(0.5)
                except Exception as e:
                    birth["click_note"] = str(e)

            birth["is_editable"] = True
            birth["type"] = "datepicker (month+year panels)"

print(f"    Months: {[m['text'] for m in birth.get('months', [])]}")
print(f"    Years: {[y['text'] for y in birth.get('years', [])]}")
print(f"    Year range: {birth.get('year_panel_range')}")

# ---------- 参加工作时间 ----------
print("\n[8] 参加工作时间 (Work Start Date) ...")
work_section = None
for item in form_items:
    lbl = item.ele("css:.item-label", timeout=0.3)
    if lbl and "工作时间" in lbl.text:
        work_section = item
        break

work = {}
if work_section:
    content = work_section.ele("css:.item-content", timeout=0.5)
    if content:
        dp = content.ele("css:.datepicker-wrap", timeout=0.5)
        if dp:
            work["datepicker_ka"] = dp.attr("ka")

            inp = dp.ele("css:input", timeout=0.3)
            if inp:
                work["input_placeholder"] = inp.attr("placeholder")
                work["input_readonly"] = True
                work["input_value"] = inp.attr("value") or ""

            # Month panel
            month_panel = dp.ele("css:.datepicker-month", timeout=0.3)
            if month_panel:
                year_btn = month_panel.ele("css:.month-year-btn", timeout=0.3)
                if year_btn:
                    work["month_panel_label"] = year_btn.text.strip()

                months = []
                for cell in month_panel.eles("css:.cell.month"):
                    cls = cell.attr("class") or ""
                    months.append({
                        "text": cell.text.strip(),
                        "selected": "selected" in cls,
                    })
                work["months"] = months

            # Year panel
            year_panel = dp.ele("css:.datepicker-year", timeout=0.3)
            if year_panel:
                header = year_panel.ele("css:.picker-header", timeout=0.3)
                if header:
                    spans = header.eles("css:span")
                    for sp in spans:
                        txt = sp.text.strip()
                        if txt and ("年" in txt or "-" in txt or "工作" in txt):
                            work["year_panel_label"] = txt
                            break
                    next_btn = header.ele("css:.next", timeout=0.3)
                    work["year_next_disabled"] = "disabled" in (next_btn.attr("class") or "") if next_btn else None

                years = []
                for cell in year_panel.eles("css:.cell.year"):
                    cls = cell.attr("class") or ""
                    years.append({
                        "text": cell.text.strip(),
                        "selected": "selected" in cls,
                    })
                work["years"] = years

            # Click to open
            if inp:
                try:
                    inp.scroll.to_see()
                    time.sleep(0.3)
                    inp.click()
                    time.sleep(1)

                    panels = dp.eles("css:.datepicker-pannel")
                    for panel in panels:
                        style = panel.attr("style") or ""
                        cls = panel.attr("class") or ""
                        if "display: none" not in style:
                            work["visible_panel_on_open"] = "year" if "year" in cls else "month" if "month" in cls else cls

                    page.ele("tag:body").click(offset=(0, 0))
                    time.sleep(0.5)
                except Exception as e:
                    work["click_note"] = str(e)

            work["is_editable"] = True
            work["type"] = "datepicker (month+year panels)"

print(f"    Months: {[m['text'] for m in work.get('months', [])]}")
print(f"    Years: {[y['text'] for y in work.get('years', [])]}")

# ---------- Vue component data ----------
print("\n[9] Vue component data ...")
vue_data = {}

# Try to find Vue instance on the form or its parent
vue_js_result = page.run_js("""
    function findVue(el) {
        if (!el) return null;
        if (el.__vue__) return el.__vue__;
        return findVue(el.parentElement);
    }

    var formEl = arguments[0];
    var vm = findVue(formEl);
    if (!vm) return JSON.stringify({error: 'no vue instance'});

    var result = {};
    result.componentName = vm.$options.name || 'unknown';

    // Get $data
    var data = vm.$data || {};
    result.dataKeys = Object.keys(data);

    // Serialize key fields
    result.values = {};
    var importantKeys = ['infoData', 'ruleData', 'fieldMapCode', 'selectedCity',
                          'birthCheckInfo', 'userCheck', 'suggestTips',
                          'nameLeftCount', 'wechatLeftCount',
                          'emailValue', 'weixinValue',
                          'modifyTipShow', 'showAiOptimize'];
    for (var i = 0; i < importantKeys.length; i++) {
        var k = importantKeys[i];
        if (data[k] !== undefined) {
            try {
                var s = JSON.stringify(data[k]);
                result.values[k] = s.length > 3000 ? s.substring(0, 3000) + '...' : s;
            } catch(e) {
                result.values[k] = '[err]';
            }
        }
    }

    // Get all data keys with short previews
    result.allDataPreview = {};
    for (var key in data) {
        try {
            var s = JSON.stringify(data[key]);
            result.allDataPreview[key] = s.length > 500 ? s.substring(0, 500) + '...' : s;
        } catch(e) {
            result.allDataPreview[key] = '[unserializable]';
        }
    }

    // Props, computed, methods
    if (vm.$options.props) result.props = Object.keys(vm.$options.props);
    if (vm.$options.computed) result.computed = Object.keys(vm.$options.computed);
    if (vm.$options.methods) result.methods = Object.keys(vm.$options.methods);

    return JSON.stringify(result);
""", form)

if vue_js_result:
    vue_data = json.loads(vue_js_result)
    print(f"    Component: {vue_data.get('componentName')}")
    print(f"    Data keys: {vue_data.get('dataKeys')}")
    print(f"    Methods: {vue_data.get('methods', [])}")
else:
    print("    No Vue data returned")
    vue_data = {"error": "no result"}

# ---------- field editability ----------
print("\n[10] Field editability ...")
editability_summary = {}
all_inputs = form.eles("css:input")
for i, inp in enumerate(all_inputs):
    inp_type = inp.attr("type") or "text"
    placeholder = inp.attr("placeholder") or ""
    readonly = inp.attr("readonly") is not None
    disabled = inp.attr("disabled") is not None
    value = inp.attr("value") or ""
    cls = inp.attr("class") or ""

    # Find label by walking up to form-item
    parent = inp
    label = ""
    for _ in range(10):
        parent = parent.parent()
        if not parent:
            break
        p_cls = parent.attr("class") or ""
        if "form-item" in p_cls:
            lbl = parent.ele("css:.item-label", timeout=0.2)
            if lbl:
                label = lbl.text.strip()
            break

    if not label:
        label = placeholder

    status = "EDITABLE"
    if disabled:
        status = "DISABLED"
    elif readonly:
        status = "READONLY"
    elif inp_type == "hidden":
        status = "HIDDEN (backing field)"

    editability_summary[label] = {
        "input_index": i,
        "type": inp_type,
        "status": status,
        "placeholder": placeholder,
        "value": value,
        "class": cls,
    }
    print(f"    {label}: {status} (type={inp_type})")

# ---------- compile final results ----------
print("\n[11] Saving results ...")

results = {
    "scrape_time": datetime.datetime.now().isoformat(),
    "page_url": page.url,
    "form_html_file": form_html_path,
    "form_html_length": len(form_html),

    "form_fields_overview": field_overview,

    "job_status": {
        "field_label": "当前求职状态",
        "type": "ui-select dropdown",
        "is_editable": job_status.get("is_editable", True),
        "hidden_input_value": job_status.get("hidden_value"),
        "current_display": job_status.get("current_display"),
        "options": job_status.get("options", []),
        "option_texts": [o["text"] for o in job_status.get("options", [])],
        "select_class": job_status.get("select_class"),
        "ka_attr": "resume_form_edit_applyStatus",
    },

    "gender": {
        "field_label": "性别",
        "type": gender.get("type", "radio_group"),
        "is_editable": gender.get("is_editable", True),
        "options": gender.get("options", []),
        "option_texts": [o["text"] for o in gender.get("options", [])],
        "radio_group_class": gender.get("radio_group_class"),
        "hidden_value": gender.get("hidden_value"),
    },

    "identity": {
        "field_label": "我的牛人身份",
        "type": identity.get("type", "ui-select"),
        "is_editable": identity.get("is_editable", False),
        "is_disabled": identity.get("is_disabled", True),
        "hidden_input_value": identity.get("hidden_value"),
        "current_display": identity.get("current_display"),
        "options": identity.get("options", []),
        "option_texts": [o["text"] for o in identity.get("options", [])],
        "edit_note": identity.get("edit_note", "牛人身份需要到BOSS直聘APP中修改"),
        "ka_attr": "resume_form_edit_freshGraduate",
    },

    "birth_date": {
        "field_label": "出生年月",
        "type": birth.get("type", "datepicker"),
        "is_editable": birth.get("is_editable", True),
        "input_placeholder": birth.get("input_placeholder"),
        "input_readonly": birth.get("input_readonly", True),
        "datepicker_ka": birth.get("datepicker_ka"),
        "months": birth.get("months", []),
        "month_texts": [m["text"] for m in birth.get("months", [])],
        "years": birth.get("years", []),
        "year_texts": [y["text"] for y in birth.get("years", [])],
        "year_panel_range": birth.get("year_panel_range"),
        "year_panel_range_live": birth.get("year_panel_range_live"),
        "year_range_after_prev": birth.get("year_range_after_prev"),
        "years_after_prev": birth.get("years_after_prev"),
        "month_panel_year_label": birth.get("month_panel_year_label"),
        "visible_panel_on_open": birth.get("visible_panel_on_open"),
        "selected_month": next((m["text"] for m in birth.get("months", []) if m.get("selected")), None),
        "selected_year": next((y["text"] for y in birth.get("years", []) if y.get("selected")), None),
    },

    "work_start_date": {
        "field_label": "参加工作时间",
        "type": work.get("type", "datepicker"),
        "is_editable": work.get("is_editable", True),
        "input_placeholder": work.get("input_placeholder"),
        "input_readonly": work.get("input_readonly", True),
        "datepicker_ka": work.get("datepicker_ka"),
        "months": work.get("months", []),
        "month_texts": [m["text"] for m in work.get("months", [])],
        "years": work.get("years", []),
        "year_texts": [y["text"] for y in work.get("years", [])],
        "year_panel_label": work.get("year_panel_label"),
        "year_next_disabled": work.get("year_next_disabled"),
        "visible_panel_on_open": work.get("visible_panel_on_open"),
        "selected_month": next((m["text"] for m in work.get("months", []) if m.get("selected")), None),
        "selected_year": next((y["text"] for y in work.get("years", []) if y.get("selected")), None),
    },

    "phone": {
        "field_label": "电话",
        "is_editable": False,
        "note": "电话即为登录账号，如需修改可直接在账号设置中修改",
    },

    "wechat": {
        "field_label": "微信号 (选填)",
        "is_editable": True,
        "type": "text_input",
    },

    "email": {
        "field_label": "邮箱 (选填)",
        "is_editable": True,
        "type": "text_input",
    },

    "field_editability": editability_summary,

    "vue_component_data": vue_data,
}

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"DONE - Results saved to {OUTPUT_PATH}")
print(f"{'='*60}")

# Print summary
print(f"\n=== SUMMARY ===")
print(f"\n求职状态 (Job Status):")
print(f"  Type: ui-select dropdown")
print(f"  Options: {results['job_status']['option_texts']}")
print(f"  Current: {results['job_status']['current_display']}")
print(f"  Editable: {results['job_status']['is_editable']}")

print(f"\n性别 (Gender):")
print(f"  Type: radio group")
print(f"  Options: {results['gender']['option_texts']}")
print(f"  Editable: {results['gender']['is_editable']}")

print(f"\n牛人身份 (Identity):")
print(f"  Type: ui-select (DISABLED)")
print(f"  Options: {results['identity']['option_texts']}")
print(f"  Current: {results['identity']['current_display']}")
print(f"  Editable: {results['identity']['is_editable']}")
print(f"  Note: {results['identity']['edit_note']}")

print(f"\n出生年月 (Birth Date):")
print(f"  Type: datepicker (month+year)")
print(f"  Months: {results['birth_date']['month_texts']}")
print(f"  Years (current decade): {results['birth_date']['year_texts']}")
print(f"  Year range: {results['birth_date']['year_panel_range']}")
print(f"  Selected: {results['birth_date']['selected_year']}/{results['birth_date']['selected_month']}")
print(f"  Editable: {results['birth_date']['is_editable']}")

print(f"\n参加工作时间 (Work Start Date):")
print(f"  Type: datepicker (month+year)")
print(f"  Months: {results['work_start_date']['month_texts']}")
print(f"  Years: {results['work_start_date']['year_texts']}")
print(f"  Selected: {results['work_start_date']['selected_year']}/{results['work_start_date']['selected_month']}")
print(f"  Editable: {results['work_start_date']['is_editable']}")

print(f"\nVue Component: {vue_data.get('componentName', 'N/A')}")
print(f"Vue Data Keys: {vue_data.get('dataKeys', [])}")
