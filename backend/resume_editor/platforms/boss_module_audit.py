"""BOSS直聘简历编辑器 - 全模块字段审计
爬取每个section的所有字段（label, value, type, 可编辑性）
然后与本地实现对比"""
import json, os, time
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_local_port(19222)
page = ChromiumPage(co)

# 确保在简历编辑页
if "resume" not in page.url:
    page.get("https://www.zhipin.com/web/geek/resume")
    page.wait.load_start()
    time.sleep(4)

sections_data = {}

# === 1. 个人信息 (userinfo) ===
js_userinfo = """
var section = document.querySelector('#userinfo, .resume-baseInfo, .resume-userinfo');
if (!section) return JSON.stringify({error: 'userinfo section not found'});

var result = {title: '', fields: [], html: ''};

// 标题
var title = section.querySelector('.title, h3, h2');
result.title = title ? (title.innerText || '').trim() : '';

// 所有info行
var rows = section.querySelectorAll('.info-primary, .info-item, .resume-item-content, li');
for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    var label = row.querySelector('.label, .item-label, .info-label');
    var value = row.querySelector('.value, .item-value, .info-value, .text');
    var editLink = row.querySelector('.link-edit, .edit, [ka*="edit"]');
    
    if (label || value) {
        result.fields.push({
            label: label ? (label.innerText || '').trim() : '',
            value: value ? (value.innerText || '').trim().substring(0, 100) : '',
            hasEdit: !!editLink,
            editKa: editLink ? (editLink.getAttribute('ka') || '') : '',
            class: row.className
        });
    }
}

// 所有form-item（如果有展开的表单）
var formItems = section.querySelectorAll('.form-item, .item-form .form-item');
for (var j = 0; j < formItems.length; j++) {
    var fi = formItems[j];
    var fiLabel = fi.querySelector('label, .label');
    var fiInput = fi.querySelector('input, select, textarea');
    result.fields.push({
        type: 'form-item',
        label: fiLabel ? (fiLabel.innerText || '').trim() : '',
        inputType: fiInput ? fiInput.type || fiInput.tagName : '',
        class: fi.className
    });
}

result.html = section.innerHTML.substring(0, 5000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_userinfo)
    sections_data["userinfo"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["userinfo"] = {"error": str(e)}

# === 2. 个人优势 (summary) ===
js_summary = """
var section = document.querySelector('#summary, .resume-summary, .resume-userDesc');
if (!section) return JSON.stringify({error: 'summary not found'});

var result = {title: '', fields: [], hasEdit: false, hasContent: false};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';

var content = section.querySelector('.text, .info-text, .content');
result.hasContent = !!content;
result.content = content ? (content.innerText || '').trim().substring(0, 500) : '';

var editLink = section.querySelector('.link-edit, [ka*="edit"]');
result.hasEdit = !!editLink;
result.editKa = editLink ? (editLink.getAttribute('ka') || '') : '';

// 获取完整HTML结构
result.html = section.innerHTML.substring(0, 3000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_summary)
    sections_data["summary"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["summary"] = {"error": str(e)}

# === 3. 期望职位 (purpose) ===
js_purpose = """
var section = document.querySelector('#purpose, .resume-purpose, .resume-expectList');
if (!section) return JSON.stringify({error: 'purpose not found'});

var result = {title: '', items: [], html: ''};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';

// 期望职位可能有多个（全职+兼职）
var expectItems = section.querySelectorAll('.expect-item, .resume-expect-item, .info-primary');
for (var i = 0; i < expectItems.length; i++) {
    var item = expectItems[i];
    var labels = item.querySelectorAll('.label, .item-label');
    var values = item.querySelectorAll('.value, .text, .info-text');
    var itemData = {};
    for (var j = 0; j < labels.length; j++) {
        var key = (labels[j].innerText || '').trim();
        var val = values[j] ? (values[j].innerText || '').trim() : '';
        itemData[key] = val;
    }
    result.items.push(itemData);
}

// 获取所有 .form-item labels 和 values
var allText = section.querySelectorAll('.info-text, .text, .value');
result.textValues = [];
for (var k = 0; k < allText.length; k++) {
    result.textValues.push((allText[k].innerText || '').trim().substring(0, 100));
}

result.html = section.innerHTML.substring(0, 5000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_purpose)
    sections_data["purpose"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["purpose"] = {"error": str(e)}

# === 4. 工作经历 (history) ===
js_history = """
var section = document.querySelector('#history, .resume-history, .resume-workExpList');
if (!section) return JSON.stringify({error: 'history not found'});

var result = {title: '', entries: [], hasAdd: false};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';

// 每条工作经历
var entries = section.querySelectorAll('.resume-item-content, .work-item, .exp-item');
result.entryCount = entries.length;

// 获取所有可见文本
var texts = section.querySelectorAll('.text, .info-text, .name, .company, .position, .date, .period');
result.textValues = [];
for (var i = 0; i < texts.length; i++) {
    var t = (texts[i].innerText || '').trim();
    if (t) result.textValues.push(t.substring(0, 100));
}

// 添加按钮
var addBtn = section.querySelector('.link-add, [ka*="add"], .btn-add');
result.hasAdd = !!addBtn;
result.addKa = addBtn ? (addBtn.getAttribute('ka') || '') : '';

// 编辑/删除按钮
var editBtns = section.querySelectorAll('.link-edit, [ka*="edit"]');
var delBtns = section.querySelectorAll('.link-del, [ka*="del"]');
result.editCount = editBtns.length;
result.delCount = delBtns.length;

result.html = section.innerHTML.substring(0, 5000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_history)
    sections_data["history"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["history"] = {"error": str(e)}

# === 5. 项目经历 (project) ===
js_project = """
var section = document.querySelector('#project, .resume-project, .resume-projectExpList');
if (!section) return JSON.stringify({error: 'project not found'});

var result = {title: '', entryCount: 0, texts: []};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';

var entries = section.querySelectorAll('.resume-item-content, .project-item');
result.entryCount = entries.length;

var texts = section.querySelectorAll('.text, .info-text, .name, .date, .period, .link');
for (var i = 0; i < texts.length; i++) {
    var t = (texts[i].innerText || '').trim();
    if (t) result.texts.push(t.substring(0, 100));
}

var addBtn = section.querySelector('.link-add, [ka*="add"]');
result.hasAdd = !!addBtn;

result.html = section.innerHTML.substring(0, 3000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_project)
    sections_data["project"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["project"] = {"error": str(e)}

# === 6. 教育经历 (education) ===
js_edu = """
var section = document.querySelector('#education, .resume-education, .resume-educationExpList');
if (!section) return JSON.stringify({error: 'education not found'});

var result = {title: '', entryCount: 0, texts: []};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';

var entries = section.querySelectorAll('.resume-item-content, .edu-item');
result.entryCount = entries.length;

var texts = section.querySelectorAll('.text, .info-text, .school, .major, .degree, .date, .period');
for (var i = 0; i < texts.length; i++) {
    var t = (texts[i].innerText || '').trim();
    if (t) result.texts.push(t.substring(0, 100));
}

var addBtn = section.querySelector('.link-add, [ka*="add"]');
result.hasAdd = !!addBtn;

result.html = section.innerHTML.substring(0, 3000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_edu)
    sections_data["education"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["education"] = {"error": str(e)}

# === 7. 资格证书 (certification) ===
js_cert = """
var section = document.querySelector('#certification, .resume-certification, .resume-certificationList');
if (!section) return JSON.stringify({error: 'certification not found'});

var result = {title: '', tags: []};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';

// 证书标签
var tags = section.querySelectorAll('.tag, .badge, .cert-tag, .certificate-item');
for (var i = 0; i < tags.length; i++) {
    result.tags.push((tags[i].innerText || '').trim());
}

// 所有文本
var texts = section.querySelectorAll('.text, .info-text');
result.textValues = [];
for (var j = 0; j < texts.length; j++) {
    var t = (texts[j].innerText || '').trim();
    if (t) result.textValues.push(t.substring(0, 100));
}

result.html = section.innerHTML.substring(0, 3000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_cert)
    sections_data["certification"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["certification"] = {"error": str(e)}

# === 8. 驻外选项 (stay-abroad) ===
js_overseas = """
var section = document.querySelector('#stay-abroad, .resume-stayAbroad, .resume-stay-abroad');
if (!section) return JSON.stringify({error: 'stay-abroad not found'});

var result = {title: '', fields: []};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';

// 表单字段
var formItems = section.querySelectorAll('.form-item');
for (var i = 0; i < formItems.length; i++) {
    var fi = formItems[i];
    var label = fi.querySelector('label, .label');
    var value = fi.querySelector('.text, .info-text, .value, .list-select-text, .ui-select-selected-value');
    result.fields.push({
        label: label ? (label.innerText || '').trim() : '',
        value: value ? (value.innerText || '').trim().substring(0, 200) : '',
        class: fi.className
    });
}

// 所有可见文本
var texts = section.querySelectorAll('.text, .info-text, .list-select-text');
result.textValues = [];
for (var j = 0; j < texts.length; j++) {
    var t = (texts[j].innerText || '').trim();
    if (t) result.textValues.push(t.substring(0, 200));
}

result.html = section.innerHTML.substring(0, 5000);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_overseas)
    sections_data["overseas"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["overseas"] = {"error": str(e)}

# === 9. 自定义添加 (custom-add) ===
js_custom = """
var section = document.querySelector('#custom-add, .resume-custom-add');
if (!section) return JSON.stringify({error: 'custom-add not found'});

var result = {title: ''};
var title = section.querySelector('.title');
result.title = title ? (title.innerText || '').trim() : '';
result.html = section.innerHTML.substring(0, 2000);
result.text = (section.innerText || '').trim().substring(0, 500);
return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_custom)
    sections_data["custom_add"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["custom_add"] = {"error": str(e)}

# === 10. 全局：获取所有 edit/add/delete 按钮 ===
js_global = """
var result = {
    allEditButtons: [],
    allAddButtons: [],
    allDelButtons: []
};

var edits = document.querySelectorAll('[ka*="edit"], .link-edit');
for (var i = 0; i < edits.length; i++) {
    var el = edits[i];
    var parent = el.closest('.resume-item');
    result.allEditButtons.push({
        ka: el.getAttribute('ka') || '',
        text: (el.innerText || '').trim().substring(0, 50),
        sectionId: parent ? parent.id : ''
    });
}

var adds = document.querySelectorAll('[ka*="add"], .link-add');
for (var j = 0; j < adds.length; j++) {
    var ael = adds[j];
    var aparent = ael.closest('.resume-item');
    result.allAddButtons.push({
        ka: ael.getAttribute('ka') || '',
        text: (ael.innerText || '').trim().substring(0, 50),
        sectionId: aparent ? aparent.id : ''
    });
}

var dels = document.querySelectorAll('[ka*="del"], .link-del');
for (var k = 0; k < dels.length; k++) {
    var del = dels[k];
    var dparent = del.closest('.resume-item');
    result.allDelButtons.push({
        ka: del.getAttribute('ka') || '',
        text: (del.innerText || '').trim().substring(0, 50),
        sectionId: dparent ? dparent.id : ''
    });
}

return JSON.stringify(result);
"""
try:
    raw = page.run_js(js_global)
    sections_data["global_buttons"] = json.loads(raw) if raw else {"error": "no result"}
except Exception as e:
    sections_data["global_buttons"] = {"error": str(e)}

# 保存审计结果
output = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "boss_module_audit.json")
with open(output, "w", encoding="utf-8") as f:
    json.dump(sections_data, f, ensure_ascii=False, indent=2)

print("=== 审计完成 ===")
for section, data in sections_data.items():
    error = data.get("error", "")
    if error:
        print(f"  [{section}] ERROR: {error}")
    else:
        title = data.get("title", "?")
        fields_count = len(data.get("fields", data.get("items", data.get("texts", data.get("tags", [])))))
        html_len = len(data.get("html", ""))
        print(f"  [{section}] title='{title}' fields={fields_count} html_len={html_len}")
