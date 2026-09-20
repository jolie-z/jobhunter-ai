"""
51job简历页面 - 深度数据提取脚本

功能：
1. 连接已登录的 Edge 浏览器（端口由全项目统一配置区 registry 提供）
2. 提取 Vue 实例完整数据树（$data, Vuex store, computed）
3. 提取 10 个简历模块的 DOM 结构和文本内容
4. 逐个触发编辑交互，捕获 Element UI 弹窗表单结构
5. 提取每个模块的 CSS 样式信息
6. 生成完整的字段 schema
7. 保存到 backend/resume_editor/data/51job_deep_extract.json

技术要点：
- 页面使用 Nuxt.js (Vue 2 SSR) + Element UI
- Vue 根节点: document.getElementById('__nuxt').__vue__
- DrissionPage run_js 不支持 IIFE，必须用直接 return
"""

import os
import sys
import json
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RESUME_EDITOR_DIR = os.path.dirname(_SCRIPT_DIR)
_DATA_DIR = os.path.join(_RESUME_EDITOR_DIR, "data")

from DrissionPage import ChromiumPage, ChromiumOptions

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port

PORT = get_platform_port("51job")
JOB51_RESUME_URL = "https://www.51job.com/resume/center"
OUTPUT_FILE = os.path.join(_DATA_DIR, "51job_deep_extract.json")

# 10 个简历模块
RESUME_MODULES = [
    {"name": "基本信息", "component": "PCBaseInfo"},
    {"name": "个人优势", "component": "PersonalAdvantage"},
    {"name": "求职意向", "component": "anon"},  # career objective is anonymous
    {"name": "工作经历", "component": "WorkExperience"},
    {"name": "项目经历", "component": "ProjectExperience"},
    {"name": "教育经历", "component": "EducationalExperience"},
    {"name": "语言能力", "component": "LanguageAbility"},
    {"name": "个人作品", "component": "WePersonalworks"},
    {"name": "专业技能", "component": "Skills"},
    {"name": "资格证书", "component": "Certificate"},
]


def connect_browser():
    """连接已启动的浏览器（端口 PORT），端口无响应直接报错，绝不自动拉起新浏览器"""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from browser_common import connect_page
    return connect_page(PORT)

def extract_vue_data(page) -> dict:
    """提取 Vue 实例完整数据树"""
    print("\n[1/5] 提取 Vue 实例数据...")

    # Step 1: Detect Vue
    detected = page.run_js(
        'var el = document.getElementById("__nuxt");'
        'return el ? !!el.__vue__ : false;'
    )
    if not detected:
        print("  ✗ 未检测到 Vue 实例")
        return {}

    print("  ✓ Vue 2 (Nuxt.js) 检测成功")

    result = {"vue_detected": True}

    # Step 2: Get route info
    route = page.run_js(
        'var vm = document.getElementById("__nuxt").__vue__;'
        'return vm.$route ? JSON.stringify({path: vm.$route.path, name: vm.$route.name}) : null;'
    )
    result["route"] = json.loads(route) if route else None

    # Step 3: Get Vuex store modules
    store_raw = page.run_js(
        'var vm = document.getElementById("__nuxt").__vue__;'
        'if (!vm.$store) return null;'
        'var result = {modules: Object.keys(vm.$store.state)};'
        'if (vm.$store.state.resumeStore) {'
        '  try { result.resumeStore = JSON.parse(JSON.stringify(vm.$store.state.resumeStore)); } catch(e) {}'
        '}'
        'if (vm.$store.state.dictStore) {'
        '  result.dictStore_keys = Object.keys(vm.$store.state.dictStore);'
        '  result.dictStore_preview = {};'
        '  for (var k in vm.$store.state.dictStore) {'
        '    var v = vm.$store.state.dictStore[k];'
        '    if (Array.isArray(v) && v.length > 0) {'
        '      result.dictStore_preview[k] = {length: v.length, sample: JSON.stringify(v[0]).substring(0,100)};'
        '    }'
        '  }'
        '}'
        'return JSON.stringify(result);'
    )
    if store_raw:
        result["store"] = json.loads(store_raw)
        modules = result["store"].get("modules", [])
        print(f"  ✓ Vuex store: {len(modules)} 个模块 → {modules}")
        preview = result["store"].get("dictStore_preview", {})
        print(f"  ✓ dictStore 字典: {len(preview)} 个")

    # Step 4: Get PCResume component data
    resume_raw = page.run_js(
        'var nuxt = document.getElementById("__nuxt").__vue__;'
        'var app = nuxt.$children[0];'
        'var nuxtChild = null;'
        'for (var i = 0; i < app.$children.length; i++) {'
        '  if (app.$children[i].$options.name === "Nuxt") { nuxtChild = app.$children[i]; break; }'
        '}'
        'if (!nuxtChild) nuxtChild = app.$children[1];'
        'var pcResume = null;'
        'for (var i = 0; i < nuxtChild.$children.length; i++) {'
        '  if (nuxtChild.$children[i].$options.name === "PCResume") { pcResume = nuxtChild.$children[i]; break; }'
        '}'
        'if (!pcResume) pcResume = nuxtChild.$children[0];'
        'if (!pcResume) return null;'
        'var d = pcResume.$data;'
        'var result = {'
        '  data_keys: Object.keys(d),'
        '  component_children: []'
        '};'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  var c = pcResume.$children[i];'
        '  result.component_children.push({'
        '    name: c.$options.name || "anon",'
        '    data_keys: c.$data ? Object.keys(c.$data) : [],'
        '    methods: c.$options.methods ? Object.keys(c.$options.methods) : []'
        '  });'
        '}'
        'try { result.resumeInfo = JSON.parse(JSON.stringify(d.resumeInfo)); } catch(e) {}'
        'try { result.accountInfo = JSON.parse(JSON.stringify(d.accountInfo)); } catch(e) {}'
        'try { result.intentions = JSON.parse(JSON.stringify(d.intentions)); } catch(e) {}'
        'try { result.selfIntroduction = JSON.parse(JSON.stringify(d.selfIntroduction)); } catch(e) {}'
        'try { result.works = JSON.parse(JSON.stringify(d.works)); } catch(e) {}'
        'try { result.projects = JSON.parse(JSON.stringify(d.projects)); } catch(e) {}'
        'try { result.educations = JSON.parse(JSON.stringify(d.educations)); } catch(e) {}'
        'try { result.skills = JSON.parse(JSON.stringify(d.skills)); } catch(e) {}'
        'try { result.certifications = JSON.parse(JSON.stringify(d.certifications)); } catch(e) {}'
        'try { result.leftNavResume = JSON.parse(JSON.stringify(d.leftNavResume)); } catch(e) {}'
        'try { result.portfolio = JSON.parse(JSON.stringify(d.portfolio)); } catch(e) {}'
        'try { result.schoolAwards = JSON.parse(JSON.stringify(d.schoolAwards)); } catch(e) {}'
        'try { result.attachments = JSON.parse(JSON.stringify(d.attachments)); } catch(e) {}'
        'return JSON.stringify(result);'
    )
    if resume_raw:
        result["pc_resume"] = json.loads(resume_raw)
        keys = result["pc_resume"].get("data_keys", [])
        print(f"  ✓ PCResume 组件: {len(keys)} 个数据键")
        children = result["pc_resume"].get("component_children", [])
        print(f"  ✓ 子组件: {len(children)} 个")
        for c in children:
            print(f"    - {c['name']}: {len(c['data_keys'])} data, {len(c['methods'])} methods")

    # Step 5: Get PCBaseInfo component data (ruleForm + rules)
    baseinfo_raw = page.run_js(
        'var nuxt = document.getElementById("__nuxt").__vue__;'
        'var app = nuxt.$children[0];'
        'var nuxtChild = null;'
        'for (var i = 0; i < app.$children.length; i++) {'
        '  if (app.$children[i].$options.name === "Nuxt") { nuxtChild = app.$children[i]; break; }'
        '}'
        'if (!nuxtChild) nuxtChild = app.$children[1];'
        'var pcResume = null;'
        'for (var i = 0; i < nuxtChild.$children.length; i++) {'
        '  if (nuxtChild.$children[i].$options.name === "PCResume") { pcResume = nuxtChild.$children[i]; break; }'
        '}'
        'if (!pcResume) return null;'
        'var baseInfo = null;'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  if (pcResume.$children[i].$options.name === "PCBaseInfo") { baseInfo = pcResume.$children[i]; break; }'
        '}'
        'if (!baseInfo) return null;'
        'var result = {};'
        'try { result.ruleForm = JSON.parse(JSON.stringify(baseInfo.$data.ruleForm)); } catch(e) {}'
        'try { result.rules = JSON.parse(JSON.stringify(baseInfo.$data.rules)); } catch(e) {}'
        'result.data_keys = Object.keys(baseInfo.$data || {});'
        'return JSON.stringify(result);'
    )
    if baseinfo_raw:
        result["pc_base_info"] = json.loads(baseinfo_raw)
        print(f"  ✓ PCBaseInfo: ruleForm, rules 提取成功")

    return result


def extract_module_structure(page) -> list:
    """提取 10 个简历模块的 DOM 结构"""
    print("\n[2/5] 提取简历模块结构...")

    raw = page.run_js(
        'var modules = [];'
        'var sections = document.querySelectorAll(".moduleRight-content > .mb22");'
        'for (var i = 0; i < sections.length; i++) {'
        '  var sec = sections[i];'
        '  var inner = sec.children[0];'
        '  if (!inner) continue;'
        '  var rect = sec.getBoundingClientRect();'
        '  var titleEl = inner.querySelector("[class*=title], [class*=Title]");'
        '  var title = titleEl ? titleEl.textContent.trim().substring(0, 30) : "";'
        '  var editBtns = inner.querySelectorAll("[class*=edit], [class*=Edit], [class*=add], [class*=Add]");'
        '  var editButtons = [];'
        '  for (var j = 0; j < editBtns.length; j++) {'
        '    var b = editBtns[j];'
        '    editButtons.push({'
        '      tag: b.tagName,'
        '      text: (b.textContent || "").trim().substring(0, 30),'
        '      className: String(b.className || "").substring(0, 100)'
        '    });'
        '  }'
        '  modules.push({'
        '    index: i,'
        '    className: String(sec.className || "").substring(0, 150),'
        '    inner_class: String(inner.className || "").substring(0, 150),'
        '    title: title,'
        '    text_content: (sec.textContent || "").trim().substring(0, 500),'
        '    rect: {width: Math.round(rect.width), height: Math.round(rect.height),'
        '           top: Math.round(rect.top), left: Math.round(rect.left)},'
        '    child_count: inner.children.length,'
        '    edit_buttons: editButtons,'
        '    outer_html: sec.outerHTML.substring(0, 2000)'
        '  });'
        '}'
        'return JSON.stringify(modules);'
    )

    if raw:
        try:
            modules = json.loads(raw)
            print(f"  ✓ 找到 {len(modules)} 个内容模块")
            for m in modules:
                title = m['title'] or m['inner_class'][:40]
                btns = [b['text'] for b in m.get('edit_buttons', [])]
                print(f"    [{m['index']}] {title} ({m['rect']['width']}x{m['rect']['height']})")
                if btns:
                    print(f"        编辑按钮: {btns}")
            return modules
        except Exception as e:
            print(f"  ✗ 解析失败: {e}")
    return []


def extract_edit_dialogs(page) -> dict:
    """通过 Vue 方法触发编辑交互，提取弹窗表单结构"""
    print("\n[3/5] 提取编辑弹窗表单...")

    dialogs = {}

    # Install XHR/Fetch interceptor
    page.run_js(
        'window.__dialog_requests = [];'
        'if (!window.__dialog_intercepted) {'
        '  window.__dialog_intercepted = true;'
        '  var origOpen = XMLHttpRequest.prototype.open;'
        '  var origSend = XMLHttpRequest.prototype.send;'
        '  XMLHttpRequest.prototype.open = function(method, url) {'
        '    this.__url2 = url; this.__method2 = method;'
        '    return origOpen.apply(this, arguments);'
        '  };'
        '  XMLHttpRequest.prototype.send = function(body) {'
        '    var xhr = this;'
        '    xhr.addEventListener("load", function() {'
        '      try {'
        '        window.__dialog_requests.push({'
        '          method: xhr.__method2, url: xhr.__url2,'
        '          body: body ? String(body).substring(0,500) : null,'
        '          status: xhr.status,'
        '          response: (xhr.responseText || "").substring(0,3000)'
        '        });'
        '      } catch(e) {}'
        '    });'
        '    return origSend.apply(this, arguments);'
        '  };'
        '}'
    )

    # For each module, trigger edit and capture dialog
    trigger_scripts = {
        "基本信息": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "PCBaseInfo") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'comp.$set(comp, "showEditInput", true);'
            'return JSON.stringify({component: "PCBaseInfo", triggered: true});'
        ),
        "个人优势": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "PersonalAdvantage") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'if (comp.handleEdit) comp.handleEdit();'
            'return JSON.stringify({component: "PersonalAdvantage", triggered: true});'
        ),
        "求职意向": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  var c = pcResume.$children[i];'
            '  if (c.$options.methods && c.$options.methods.careerObjectiveAdd) { comp = c; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'if (comp.careerObjectiveAdd) comp.careerObjectiveAdd();'
            'return JSON.stringify({component: "CareerObjective", triggered: true});'
        ),
        "工作经历": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "WorkExperience") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'comp.$set(comp, "workExperienceFlag", "add");'
            'comp.$set(comp, "workExperienceVisible", true);'
            'return JSON.stringify({component: "WorkExperience", triggered: true});'
        ),
        "项目经历": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "ProjectExperience") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'if (comp.handledAddOnClick) comp.handledAddOnClick();'
            'return JSON.stringify({component: "ProjectExperience", triggered: true});'
        ),
        "教育经历": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "EducationalExperience") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'if (comp.handledAddOnClick) comp.handledAddOnClick();'
            'return JSON.stringify({component: "EducationalExperience", triggered: true});'
        ),
        "语言能力": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "LanguageAbility") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'if (comp.addItem) comp.addItem();'
            'return JSON.stringify({component: "LanguageAbility", triggered: true});'
        ),
        "个人作品": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "WePersonalworks") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'return JSON.stringify({component: "WePersonalworks", triggered: true, note: "file upload based"});'
        ),
        "专业技能": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "Skills") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'if (comp.handledAddOnClick) comp.handledAddOnClick();'
            'return JSON.stringify({component: "Skills", triggered: true});'
        ),
        "资格证书": (
            'var comp = null;'
            'for (var i = 0; i < pcResume.$children.length; i++) {'
            '  if (pcResume.$children[i].$options.name === "Certificate") { comp = pcResume.$children[i]; break; }'
            '}'
            'if (!comp) return JSON.stringify({error: "component not found"});'
            'if (comp.handleEdit) comp.handleEdit();'
            'return JSON.stringify({component: "Certificate", triggered: true});'
        ),
    }

    for module in RESUME_MODULES:
        module_name = module['name']
        print(f"\n  [{module_name}] 触发编辑交互...")

        trigger_code = trigger_scripts.get(module_name)
        if not trigger_code:
            print(f"    ⚠ 无触发代码")
            dialogs[module_name] = {'error': 'no_trigger'}
            continue

        # Clear request log
        page.run_js('window.__dialog_requests = [];')

        # Build full trigger script with PCResume lookup
        full_script = (
            'var nuxt = document.getElementById("__nuxt").__vue__;'
            'var app = nuxt.$children[0];'
            'var nuxtChild = null;'
            'for (var i = 0; i < app.$children.length; i++) {'
            '  if (app.$children[i].$options.name === "Nuxt") { nuxtChild = app.$children[i]; break; }'
            '}'
            'if (!nuxtChild) nuxtChild = app.$children[1];'
            'var pcResume = null;'
            'for (var i = 0; i < nuxtChild.$children.length; i++) {'
            '  if (nuxtChild.$children[i].$options.name === "PCResume") { pcResume = nuxtChild.$children[i]; break; }'
            '}'
            'if (!pcResume) return JSON.stringify({error: "PCResume not found"});'
        ) + trigger_code

        try:
            trigger_result = page.run_js(full_script)
        except Exception as e:
            print(f"    ✗ 触发失败: {e}")
            dialogs[module_name] = {'error': str(e)}
            continue

        if trigger_result:
            try:
                td = json.loads(trigger_result)
                if 'error' in td:
                    print(f"    ✗ {td['error']}")
                    dialogs[module_name] = td
                    continue
                print(f"    ✓ 触发: {td.get('component', '?')}")
            except:
                pass
        else:
            print(f"    ⚠ 触发返回空")
            dialogs[module_name] = {'error': 'no_return'}
            continue

        time.sleep(1.5)

        # Check for visible dialogs
        dialog_raw = page.run_js(
            'var result = {dialog_found: false, dialogs: []};'
            'var allDialogs = document.querySelectorAll(".el-dialog__wrapper");'
            'for (var di = 0; di < allDialogs.length; di++) {'
            '  var d = allDialogs[di];'
            '  var style = window.getComputedStyle(d);'
            '  if (style.display === "none") continue;'
            '  var titleEl = d.querySelector(".el-dialog__title");'
            '  var bodyEl = d.querySelector(".el-dialog__body");'
            '  var footerEl = d.querySelector(".el-dialog__footer");'
            '  var dialogInfo = {'
            '    title: titleEl ? titleEl.textContent.trim() : "",'
            '    className: String(d.className || "").substring(0, 200),'
            '    form_fields: [], buttons: []'
            '  };'
            '  if (bodyEl) {'
            '    var formItems = bodyEl.querySelectorAll(".el-form-item");'
            '    for (var fi = 0; fi < formItems.length; fi++) {'
            '      var item = formItems[fi];'
            '      var label = item.querySelector(".el-form-item__label");'
            '      var input = item.querySelector("input.el-input__inner");'
            '      var textarea = item.querySelector("textarea.el-textarea__inner");'
            '      var select = item.querySelector(".el-select");'
            '      var datePicker = item.querySelector(".el-date-editor");'
            '      var radio = item.querySelector(".el-radio-group");'
            '      var checkbox = item.querySelector(".el-checkbox-group");'
            '      var field = {'
            '        label: label ? label.textContent.trim() : "",'
            '        type: "unknown", required: item.classList.contains("is-required"),'
            '        value: "", placeholder: "", options: []'
            '      };'
            '      if (input) {'
            '        field.type = "input:" + (input.type || "text");'
            '        field.value = (input.value || "").substring(0, 100);'
            '        field.placeholder = input.placeholder || "";'
            '        field.maxLength = input.maxLength > 0 ? input.maxLength : null;'
            '      } else if (textarea) {'
            '        field.type = "textarea";'
            '        field.value = (textarea.value || "").substring(0, 200);'
            '        field.placeholder = textarea.placeholder || "";'
            '      } else if (select) {'
            '        field.type = "select";'
            '        var selInput = select.querySelector(".el-input__inner");'
            '        field.value = selInput ? selInput.value : "";'
            '      } else if (datePicker) {'
            '        field.type = "date";'
            '        var dpInput = datePicker.querySelector("input");'
            '        field.value = dpInput ? dpInput.value : "";'
            '      } else if (radio) {'
            '        field.type = "radio";'
            '        var labels = radio.querySelectorAll(".el-radio");'
            '        for (var ri = 0; ri < labels.length; ri++) field.options.push(labels[ri].textContent.trim());'
            '      } else if (checkbox) {'
            '        field.type = "checkbox";'
            '        var labels = checkbox.querySelectorAll(".el-checkbox");'
            '        for (var ci = 0; ci < labels.length; ci++) field.options.push(labels[ci].textContent.trim());'
            '      }'
            '      if (field.label || field.type !== "unknown") dialogInfo.form_fields.push(field);'
            '    }'
            '    var btns = footerEl ? footerEl.querySelectorAll("button, .el-button") : [];'
            '    for (var bi = 0; bi < btns.length; bi++) {'
            '      dialogInfo.buttons.push({'
            '        text: btns[bi].textContent.trim(),'
            '        className: String(btns[bi].className || "").substring(0, 100)'
            '      });'
            '    }'
            '  }'
            '  result.dialog_found = true;'
            '  result.dialogs.push(dialogInfo);'
            '}'
            'return JSON.stringify(result);'
        )

        if dialog_raw:
            try:
                dd = json.loads(dialog_raw)
                if dd.get('dialog_found') and dd.get('dialogs'):
                    dialogs[module_name] = dd
                    print(f"    ✓ 找到 {len(dd['dialogs'])} 个弹窗")
                    for d in dd['dialogs']:
                        print(f"      标题: {d.get('title', '无标题')}")
                        for f in d.get('form_fields', []):
                            print(f"        {f['label']}: {f['type']} (required={f['required']})")
                        print(f"      按钮: {[b['text'] for b in d.get('buttons', [])]}")
                else:
                    # Also check for inline form expansion (some modules don't use dialogs)
                    print(f"    ⚠ 未找到弹窗（可能是内联编辑）")
                    dialogs[module_name] = {'dialog_found': False, 'note': 'inline_editing_or_no_dialog'}
            except Exception as e:
                print(f"    ✗ 解析失败: {e}")
                dialogs[module_name] = {'error': str(e)}

        # Collect API requests
        api_raw = page.run_js('return JSON.stringify(window.__dialog_requests || []);')
        if api_raw:
            try:
                apis = json.loads(api_raw)
                if apis:
                    if module_name in dialogs:
                        dialogs[module_name]['api_requests'] = apis
                    print(f"    ✓ API 请求: {len(apis)} 个")
                    for a in apis:
                        print(f"      {a.get('method', '?')} {a.get('url', '?')[:80]}")
            except:
                pass

        # Close all visible dialogs
        page.run_js(
            'var closeBtn = document.querySelector(".el-dialog__wrapper:not([style*=none]) .el-dialog__headerbtn");'
            'if (closeBtn) closeBtn.click();'
        )
        time.sleep(0.5)
        # Press Escape as fallback
        page.run_js(
            'document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", keyCode: 27, bubbles: true}));'
        )
        time.sleep(0.5)

    return dialogs


def extract_css_styles(page) -> dict:
    """提取每个模块的 CSS 样式信息"""
    print("\n[4/5] 提取 CSS 样式...")

    raw = page.run_js(
        'var result = {modules: {}, global_styles: {}};'
        'var sections = document.querySelectorAll(".moduleRight-content > .mb22");'
        'for (var i = 0; i < sections.length; i++) {'
        '  var sec = sections[i];'
        '  var inner = sec.children[0];'
        '  if (!inner) continue;'
        '  var titleEl = inner.querySelector("[class*=title], [class*=Title]");'
        '  var title = titleEl ? titleEl.textContent.trim().substring(0, 20) : "module_" + i;'
        '  var style = window.getComputedStyle(sec);'
        '  var innerStyle = window.getComputedStyle(inner);'
        '  var modStyle = {'
        '    container: {'
        '      width: style.width, height: style.height,'
        '      padding: style.padding, margin: style.margin,'
        '      backgroundColor: style.backgroundColor,'
        '      borderRadius: style.borderRadius, boxShadow: style.boxShadow'
        '    },'
        '    inner: {'
        '      className: String(inner.className || "").substring(0, 100),'
        '      padding: innerStyle.padding, backgroundColor: innerStyle.backgroundColor,'
        '      borderRadius: innerStyle.borderRadius'
        '    }'
        '  };'
        '  if (titleEl) {'
        '    var titleStyle = window.getComputedStyle(titleEl);'
        '    modStyle.title = {'
        '      fontSize: titleStyle.fontSize, fontWeight: titleStyle.fontWeight,'
        '      color: titleStyle.color, marginBottom: titleStyle.marginBottom'
        '    };'
        '  }'
        '  result.modules[title || "module_" + i] = modStyle;'
        '}'
        'var bodyStyle = window.getComputedStyle(document.body);'
        'result.global_styles = {'
        '  body_background: bodyStyle.backgroundColor,'
        '  body_font_family: bodyStyle.fontFamily.substring(0, 100),'
        '  body_font_size: bodyStyle.fontSize, body_color: bodyStyle.color'
        '};'
        'var moduleRight = document.querySelector(".moduleRight");'
        'if (moduleRight) {'
        '  var mrStyle = window.getComputedStyle(moduleRight);'
        '  result.global_styles.moduleRight = {'
        '    width: mrStyle.width, padding: mrStyle.padding,'
        '    backgroundColor: mrStyle.backgroundColor'
        '  };'
        '}'
        'var moduleLeft = document.querySelector(".moduleLeft");'
        'if (moduleLeft) {'
        '  var mlStyle = window.getComputedStyle(moduleLeft);'
        '  result.global_styles.moduleLeft = {'
        '    width: mlStyle.width, padding: mlStyle.padding,'
        '    backgroundColor: mlStyle.backgroundColor'
        '  };'
        '}'
        'return JSON.stringify(result);'
    )

    if raw:
        try:
            data = json.loads(raw)
            mod_count = len(data.get('modules', {}))
            print(f"  ✓ 提取了 {mod_count} 个模块的样式")
            for name in data.get('modules', {}):
                print(f"    - {name}")
            return data
        except Exception as e:
            print(f"  ✗ 解析失败: {e}")
    return {}


def _get_pc_resume(page):
    """Helper JS to get PCResume component reference prefix"""
    return (
        'var nuxt = document.getElementById("__nuxt").__vue__;'
        'var app = nuxt.$children[0];'
        'var nuxtChild = null;'
        'for (var i = 0; i < app.$children.length; i++) {'
        '  if (app.$children[i].$options.name === "Nuxt") { nuxtChild = app.$children[i]; break; }'
        '}'
        'if (!nuxtChild) nuxtChild = app.$children[1];'
        'var pcResume = null;'
        'for (var i = 0; i < nuxtChild.$children.length; i++) {'
        '  if (nuxtChild.$children[i].$options.name === "PCResume") { pcResume = nuxtChild.$children[i]; break; }'
        '}'
        'if (!pcResume) return null;'
        'var d = pcResume.$data;'
    )


def build_field_schema(page) -> dict:
    """基于 Vue 数据构建完整的字段 schema (分多次小 JS 调用避免截断)"""
    print("\n[5/5] 构建字段 schema...")

    schema = {}
    prefix = _get_pc_resume(page)

    # 1. 基本信息 (accountInfo)
    raw = page.run_js(prefix +
        'if (!d.accountInfo) return null;'
        'var result = {type: "object", fields: {}, current_value: JSON.parse(JSON.stringify(d.accountInfo))};'
        'var keys = Object.keys(d.accountInfo);'
        'for (var i = 0; i < keys.length; i++) {'
        '  var k = keys[i], v = d.accountInfo[k];'
        '  var t = typeof v;'
        '  result.fields[k] = {label: k, type: t === "string" ? "text" : t === "number" ? "number" : t === "boolean" ? "boolean" : t === "object" ? "object" : "other", required: false};'
        '}'
        'return JSON.stringify(result);'
    )
    if raw:
        schema["基本信息"] = json.loads(raw)
        print(f"  ✓ 基本信息: {len(schema['基本信息']['fields'])} 个字段")

    # 2. 个人优势
    raw = page.run_js(prefix +
        'if (!d.selfIntroduction) return null;'
        'return JSON.stringify({'
        '  type: "textarea",'
        '  fields: {selfIntroduction: {label: "个人优势", type: "textarea", required: false, max_length: 1000}},'
        '  current_value: d.selfIntroduction.selfIntroduction || ""'
        '});'
    )
    if raw:
        schema["个人优势"] = json.loads(raw)
        print(f"  ✓ 个人优势: textarea")

    # 3. 求职意向 (array)
    raw = page.run_js(prefix +
        'if (!d.intentions || !Array.isArray(d.intentions) || d.intentions.length === 0) return null;'
        'var result = {type: "array", fields: {}, current_value: JSON.parse(JSON.stringify(d.intentions))};'
        'var keys = Object.keys(d.intentions[0]);'
        'for (var i = 0; i < keys.length; i++) {'
        '  var k = keys[i], v = d.intentions[0][k];'
        '  result.fields[k] = {label: k, type: Array.isArray(v) ? "array" : typeof v === "object" && v !== null ? "object" : "text", required: false};'
        '}'
        'return JSON.stringify(result);'
    )
    if raw:
        schema["求职意向"] = json.loads(raw)
        print(f"  ✓ 求职意向: {len(schema['求职意向']['current_value'])} 条, {len(schema['求职意向']['fields'])} 字段")

    # 4. 工作经历 (array)
    raw = page.run_js(prefix +
        'if (!d.works || !Array.isArray(d.works) || d.works.length === 0) return null;'
        'var result = {type: "array", fields: {}, current_value: JSON.parse(JSON.stringify(d.works))};'
        'var keys = Object.keys(d.works[0]);'
        'for (var i = 0; i < keys.length; i++) {'
        '  var k = keys[i], v = d.works[0][k];'
        '  result.fields[k] = {label: k, type: Array.isArray(v) ? "array" : typeof v === "object" && v !== null ? "object" : "text", required: false};'
        '}'
        'return JSON.stringify(result);'
    )
    if raw:
        schema["工作经历"] = json.loads(raw)
        print(f"  ✓ 工作经历: {len(schema['工作经历']['current_value'])} 条, {len(schema['工作经历']['fields'])} 字段")

    # 5. 项目经历 (array)
    raw = page.run_js(prefix +
        'if (!d.projects || !Array.isArray(d.projects) || d.projects.length === 0) return null;'
        'var result = {type: "array", fields: {}, current_value: JSON.parse(JSON.stringify(d.projects))};'
        'var keys = Object.keys(d.projects[0]);'
        'for (var i = 0; i < keys.length; i++) {'
        '  var k = keys[i], v = d.projects[0][k];'
        '  result.fields[k] = {label: k, type: Array.isArray(v) ? "array" : typeof v === "object" && v !== null ? "object" : "text", required: false};'
        '}'
        'return JSON.stringify(result);'
    )
    if raw:
        schema["项目经历"] = json.loads(raw)
        print(f"  ✓ 项目经历: {len(schema['项目经历']['current_value'])} 条, {len(schema['项目经历']['fields'])} 字段")

    # 6. 教育经历 (array)
    raw = page.run_js(prefix +
        'if (!d.educations || !Array.isArray(d.educations) || d.educations.length === 0) return null;'
        'var result = {type: "array", fields: {}, current_value: JSON.parse(JSON.stringify(d.educations))};'
        'var keys = Object.keys(d.educations[0]);'
        'for (var i = 0; i < keys.length; i++) {'
        '  var k = keys[i], v = d.educations[0][k];'
        '  result.fields[k] = {label: k, type: Array.isArray(v) ? "array" : typeof v === "object" && v !== null ? "object" : "text", required: false};'
        '}'
        'return JSON.stringify(result);'
    )
    if raw:
        schema["教育经历"] = json.loads(raw)
        print(f"  ✓ 教育经历: {len(schema['教育经历']['current_value'])} 条, {len(schema['教育经历']['fields'])} 字段")

    # 7. 专业技能 (array)
    raw = page.run_js(prefix +
        'if (!d.skills || !Array.isArray(d.skills) || d.skills.length === 0) return null;'
        'var result = {type: "array", fields: {}, current_value: JSON.parse(JSON.stringify(d.skills))};'
        'var keys = Object.keys(d.skills[0]);'
        'for (var i = 0; i < keys.length; i++) {'
        '  var k = keys[i], v = d.skills[0][k];'
        '  result.fields[k] = {label: k, type: typeof v === "string" ? "text" : "other", required: false};'
        '}'
        'return JSON.stringify(result);'
    )
    if raw:
        schema["专业技能"] = json.loads(raw)
        print(f"  ✓ 专业技能: {len(schema['专业技能']['current_value'])} 条, {len(schema['专业技能']['fields'])} 字段")

    # 8. 资格证书 (array)
    raw = page.run_js(prefix +
        'if (!d.certifications || !Array.isArray(d.certifications) || d.certifications.length === 0) return null;'
        'var result = {type: "array", fields: {}, current_value: JSON.parse(JSON.stringify(d.certifications))};'
        'var keys = Object.keys(d.certifications[0]);'
        'for (var i = 0; i < keys.length; i++) {'
        '  var k = keys[i], v = d.certifications[0][k];'
        '  result.fields[k] = {label: k, type: typeof v === "string" ? "text" : "other", required: false};'
        '}'
        'return JSON.stringify(result);'
    )
    if raw:
        schema["资格证书"] = json.loads(raw)
        print(f"  ✓ 资格证书: {len(schema['资格证书']['current_value'])} 条, {len(schema['资格证书']['fields'])} 字段")

    # 9. Extract component form models and validation rules
    print("\n  提取各组件表单模型和校验规则...")
    component_forms = {}

    # PCBaseInfo ruleForm + rules
    raw = page.run_js(prefix +
        'var comp = null;'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  if (pcResume.$children[i].$options.name === "PCBaseInfo") { comp = pcResume.$children[i]; break; }'
        '}'
        'if (!comp) return null;'
        'var result = {};'
        'try { result.ruleForm = JSON.parse(JSON.stringify(comp.$data.ruleForm)); } catch(e) {}'
        'try { result.rules = JSON.parse(JSON.stringify(comp.$data.rules)); } catch(e) {}'
        'return JSON.stringify(result);'
    )
    if raw:
        component_forms["PCBaseInfo"] = json.loads(raw)
        print(f"    ✓ PCBaseInfo: {len(component_forms['PCBaseInfo'].get('ruleForm', {}))} form fields, {len(component_forms['PCBaseInfo'].get('rules', {}))} rules")

    # PersonalAdvantage advantageForm + rules
    raw = page.run_js(prefix +
        'var comp = null;'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  if (pcResume.$children[i].$options.name === "PersonalAdvantage") { comp = pcResume.$children[i]; break; }'
        '}'
        'if (!comp) return null;'
        'var result = {};'
        'try { result.formModel = JSON.parse(JSON.stringify(comp.$data.advantageForm)); } catch(e) {}'
        'try { result.rules = JSON.parse(JSON.stringify(comp.$data.advantagerules)); } catch(e) {}'
        'return JSON.stringify(result);'
    )
    if raw:
        component_forms["PersonalAdvantage"] = json.loads(raw)
        print(f"    ✓ PersonalAdvantage: form model + rules")

    # WorkExperience form data
    raw = page.run_js(prefix +
        'var comp = null;'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  if (pcResume.$children[i].$options.name === "WorkExperience") { comp = pcResume.$children[i]; break; }'
        '}'
        'if (!comp) return null;'
        'var d = comp.$data;'
        'var result = {data_keys: Object.keys(d)};'
        'try { result.workExperienceIndustry = JSON.parse(JSON.stringify(d.workExperienceIndustry)); } catch(e) {}'
        'try { result.workExperiencePosition = JSON.parse(JSON.stringify(d.workExperiencePosition)); } catch(e) {}'
        'return JSON.stringify(result);'
    )
    if raw:
        component_forms["WorkExperience"] = json.loads(raw)
        print(f"    ✓ WorkExperience: {len(component_forms['WorkExperience'].get('data_keys', []))} data keys")

    # EducationalExperience form data
    raw = page.run_js(prefix +
        'var comp = null;'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  if (pcResume.$children[i].$options.name === "EducationalExperience") { comp = pcResume.$children[i]; break; }'
        '}'
        'if (!comp) return null;'
        'var d = comp.$data;'
        'var result = {data_keys: Object.keys(d)};'
        'try { result.formModel = JSON.parse(JSON.stringify(d.educationalExperienceForm)); } catch(e) {}'
        'try { result.rules = JSON.parse(JSON.stringify(d.educationalExperienceRules)); } catch(e) {}'
        'return JSON.stringify(result);'
    )
    if raw:
        component_forms["EducationalExperience"] = json.loads(raw)
        print(f"    ✓ EducationalExperience: form model + rules")

    # LanguageAbility form data
    raw = page.run_js(prefix +
        'var comp = null;'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  if (pcResume.$children[i].$options.name === "LanguageAbility") { comp = pcResume.$children[i]; break; }'
        '}'
        'if (!comp) return null;'
        'var d = comp.$data;'
        'var result = {};'
        'try { result.formData = JSON.parse(JSON.stringify(d.formData)); } catch(e) {}'
        'try { result.skillOptions = JSON.parse(JSON.stringify(d.skillOptions)); } catch(e) {}'
        'try { result.abilityOptions = JSON.parse(JSON.stringify(d.abilityOptions)); } catch(e) {}'
        'try { result.languageAbilityList = JSON.parse(JSON.stringify(d.languageAbilityList)); } catch(e) {}'
        'return JSON.stringify(result);'
    )
    if raw:
        component_forms["LanguageAbility"] = json.loads(raw)
        print(f"    ✓ LanguageAbility: form data + options")

    # Skills form data
    raw = page.run_js(prefix +
        'var comp = null;'
        'for (var i = 0; i < pcResume.$children.length; i++) {'
        '  if (pcResume.$children[i].$options.name === "Skills") { comp = pcResume.$children[i]; break; }'
        '}'
        'if (!comp) return null;'
        'var d = comp.$data;'
        'var result = {};'
        'try { result.formModel = JSON.parse(JSON.stringify(d.skillsOrlanguageForm)); } catch(e) {}'
        'try { result.rules = JSON.parse(JSON.stringify(d.skillsOrlanguageRules)); } catch(e) {}'
        'return JSON.stringify(result);'
    )
    if raw:
        component_forms["Skills"] = json.loads(raw)
        print(f"    ✓ Skills: form model + rules")

    schema["_component_forms"] = component_forms

    print(f"\n  ✓ 共构建 {len(schema) - 1} 个模块 schema + {len(component_forms)} 个组件表单")
    return schema


def run_deep_extract():
    print("=" * 70)
    print("  51job 简历页面 - 深度数据提取")
    print("=" * 70)

    page = connect_browser()
    print(f"\n  ✓ 已连接到浏览器 (端口 {PORT})")
    print(f"  当前 URL: {page.url}")

    if "resume" not in page.url.lower():
        print(f"\n  导航到简历页面: {JOB51_RESUME_URL}")
        page.get(JOB51_RESUME_URL)
        time.sleep(4)

    print(f"  页面标题: {page.title}")

    result = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": page.url,
        "title": page.title,
    }

    result["vue_data"] = extract_vue_data(page)
    result["module_structure"] = extract_module_structure(page)
    result["edit_dialogs"] = extract_edit_dialogs(page)
    result["css_styles"] = extract_css_styles(page)
    result["field_schema"] = build_field_schema(page)

    # Summary
    result["extraction_summary"] = {
        "vue_detected": result.get("vue_data", {}).get("vue_detected", False),
        "pc_resume_data_keys": len(result.get("vue_data", {}).get("pc_resume", {}).get("data_keys", [])),
        "store_modules": len(result.get("vue_data", {}).get("store", {}).get("modules", [])),
        "modules_found": len(result.get("module_structure", [])),
        "dialogs_extracted": len([d for d in result.get("edit_dialogs", {}).values()
                                  if isinstance(d, dict) and d.get('dialog_found')]),
        "css_modules": len(result.get("css_styles", {}).get("modules", {})),
        "schema_modules": len(result.get("field_schema", {}))
    }

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  深度提取完成！")
    print(f"{'=' * 70}")
    print(f"\n  提取摘要:")
    for key, value in result["extraction_summary"].items():
        print(f"    {key}: {value}")
    print(f"\n  输出文件: {OUTPUT_FILE}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    run_deep_extract()
