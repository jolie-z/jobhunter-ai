"""
智联招聘 - 简历数据采集脚本
连接 registry 统一配置的智联 Edge 浏览器端口，从智联招聘官网抓取最新简历数据，
写入 zhilian_fields.json

用法：python zhilian_collector.py
前提：智联浏览器已启动且已登录
"""

import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "zhilian_fields.json")

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port, connect_page, dismiss_overlay_popup, save_fields_json, wait_resume_filled

PORT = get_platform_port("zhilian")
ZHILIAN_RESUME_URL = "https://i.zhaopin.com/resume"


def connect_browser():
    """连接已启动的浏览器（端口 PORT），端口无响应直接报错，绝不自动拉起新浏览器"""
    return connect_page(PORT)


def collect_resume(page):
    """从智联招聘简历页采集数据（Vuex store 提取）"""
    print("  [1/3] 导航到简历页面...")
    if not page.get(ZHILIAN_RESUME_URL):
        print("  [ERROR] 简历页加载失败（网络超时），请检查网络后重试")
        sys.exit(1)

    # 等内容节点真正填充（2026-08-31 修复：原固定 sleep 5s 会读到你半截数据——
    # store 对象先出现、业务节点后填充，曾导致官网既有内容整块丢失进采集结果）
    state = wait_resume_filled(page, tries=30)
    if state == "timeout":
        print("  [ERROR] 简历数据 30s 内未填充完成（疑似软拦截/网络异常），已中止采集以防空/残数据覆盖本地")
        sys.exit(1)
    if state == "empty":
        # 双读确认：6s 后仍未填充才按「真·空简历」放行
        time.sleep(6)
        if wait_resume_filled(page, tries=10) == "yes":
            state = "yes"
        else:
            print("  [WARN] 官网在线简历两次读取均为空壳，按空简历采集。")
            print("         若在线简历实际有内容，可能是软拦截——请人工打开 i.zhaopin.com/resume 确认后再试。")
    time.sleep(2)  # 渲染稳定余量

    # 「附件可同步」弹窗自动关闭（只点 ×，绝不点「同步至在线简历」）
    pr = dismiss_overlay_popup(page, "同步至在线简历")
    if pr not in ("no-popup", "none"):
        print(f"  [OK] 已自动关闭附件同步弹窗（{pr}）")

    # 检查登录
    if "login" in page.url.lower() or "passport" in page.url.lower():
        print("  [ERROR] 未登录，请先在浏览器中登录智联招聘")
        sys.exit(1)

    print("  [2/3] 从 Vuex store 提取数据...")

    # 智联招聘是 Vue2 + iView，数据存在 Vuex store 的 currentResume 中
    js_code = """
    return (function() {
        var root = document.querySelector('#root');
        if (!root || !root.__vue__) {
            return JSON.stringify({error: 'no vue instance on #root'});
        }

        var vm = root.__vue__;
        var store = vm.$store;
        if (!store || !store.state || !store.state.resume) {
            return JSON.stringify({error: 'no resume store found'});
        }

        var cr = store.state.resume.currentResume;
        if (!cr || typeof cr !== 'object' || Object.keys(cr).length === 0) {
            return JSON.stringify({error: 'currentResume is empty'});
        }

        function safeClone(obj) {
            try { return JSON.parse(JSON.stringify(obj)); }
            catch(e) { return null; }
        }

        var result = {
            Profile: safeClone(cr.Profile || []),
            WorkExperience: safeClone(cr.WorkExperience || []),
            EducationExperience: safeClone(cr.EducationExperience || []),
            ProjectExperience: safeClone(cr.ProjectExperience || []),
            TrainExperience: safeClone(cr.TrainExperience || []),
            LanguageSkill: safeClone(cr.LanguageSkill || []),
            ProfessionalSkill: safeClone(cr.ProfessionalSkill || []),
            Certificate: safeClone(cr.Certificate || []),
            SelfEvaluate: safeClone(cr.SelfEvaluate || []),
            purpose: safeClone(cr.purpose || []),
            UnifiedPurpose: safeClone(cr.UnifiedPurpose || []),
            Business: safeClone(cr.Business || {}),
            extend: safeClone(cr.extend || {}),
            EnglishCertificate: safeClone(cr.EnglishCertificate || []),
        };

        return JSON.stringify(result);
    })();
    """

    raw = page.run_js(js_code)
    if not raw:
        print("  [ERROR] JS 提取返回空")
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [ERROR] JSON 解析失败: {raw[:200]}")
        sys.exit(1)

    if data.get("error"):
        print(f"  [ERROR] Vuex 提取失败: {data['error']}")
        sys.exit(1)

    profile = data.get("Profile", [{}])[0] if data.get("Profile") else {}
    print(f"  [OK] Vuex 提取成功: name={profile.get('name', '?')}, "
          f"work={len(data.get('WorkExperience', []))}, "
          f"edu={len(data.get('EducationExperience', []))}, "
          f"proj={len(data.get('ProjectExperience', []))}")

    return data


def transform_data(raw):
    """将 Vuex currentResume 数据转换为 zhilian_fields.json 格式"""

    # ---- Profile（个人信息） ----
    profile = raw.get("Profile", [{}])[0] if raw.get("Profile") else {}
    business = raw.get("Business", {})

    # 手机号: "1|138****8000" → "138****8000"
    mobile_raw = profile.get("mobile", "") or ""
    mobile = mobile_raw.split("|")[-1] if "|" in mobile_raw else mobile_raw

    # 年龄: 从 birthyear 计算
    birthyear = profile.get("birthyear", "")
    age_str = ""
    if birthyear:
        try:
            import datetime
            age_str = str(datetime.datetime.now().year - int(birthyear))
        except (ValueError, TypeError):
            pass

    # ---- 求职状态 (from Profile, not purpose) ----
    job_status_code = str(profile.get("currentStatus", ""))
    job_status_label = profile.get("currentStatusTranslation", "") or profile.get("currentStatusTranslationCN", "")

    # ---- 求职意向 (from UnifiedPurpose, each item is one intention) ----
    wanna = []
    for item in (raw.get("UnifiedPurpose") or []):
        wanna.append({
            "path": item.get("path", ""),
            "preferredJobNature": item.get("preferredJobNature", ""),
            "preferredJobNatureTranslation": item.get("preferredJobNatureTranslation", ""),
            "pnewPreferredJobType": item.get("pnewPreferredJobType", ""),
            "pnewPreferredJobTypeTranslation": item.get("pnewPreferredJobTypeTranslation", ""),
            "pnewPreferredJobTypeFirstTranslation": item.get("pnewPreferredJobTypeFirstTranslation", ""),
            "preferredLocation": item.get("preferredLocation", ""),
            "preferredLocationTranslation": item.get("preferredLocationTranslation", ""),
            "preferredCityDistrict": item.get("preferredCityDistrict", ""),
            "preferredCityDistrictTranslation": item.get("preferredCityDistrictTranslation", ""),
            "pnewPreferredIndustry": item.get("pnewPreferredIndustry", ""),
            "pnewPreferredIndustryTranslation": item.get("pnewPreferredIndustryTranslation", ""),
            "preferredSalaryMin": item.get("preferredSalaryMin", 0),
            "preferredSalaryMax": item.get("preferredSalaryMax", 0),
            "preferredSalaryTranslation": item.get("preferredSalaryTranslation", ""),
            "preferredJobTypeSerial": item.get("preferredJobTypeSerial", ""),
            "preferredIndustrySerial": item.get("preferredIndustrySerial", ""),
            "preferredIndustrySerialList": item.get("preferredIndustrySerialList", []),
            "title": item.get("title", ""),
        })

    # ---- 工作经历 ----
    work_experience = []
    for w in (raw.get("WorkExperience") or []):
        # 保留原始全部字段（含 wnewIndustry, wnewJobSubType, skillTagList 等）
        entry = dict(w)
        # 计算日期格式字符串供前端解析 (YYYY/MM/DD HH:MM:SS)
        sd = w.get("startDate", 0)
        ed = w.get("endDate", 0)
        if sd and not w.get("startDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(sd / 1000)
            entry["startDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        if ed and not w.get("endDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(ed / 1000)
            entry["endDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        work_experience.append(entry)

    # ---- 教育经历 ----
    education = []
    for e in (raw.get("EducationExperience") or []):
        entry = dict(e)
        sd = e.get("eduStartDate", 0)
        ed = e.get("eduEndDate", 0)
        if sd and not e.get("eduStartDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(sd / 1000)
            entry["eduStartDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        if ed and not e.get("eduEndDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(ed / 1000)
            entry["eduEndDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        education.append(entry)

    # ---- 项目经历 ----
    projects = []
    for p in (raw.get("ProjectExperience") or []):
        entry = dict(p)
        sd = p.get("proExpStartDate", 0)
        ed = p.get("proExpEndDate", 0)
        if sd and not p.get("proExpStartDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(sd / 1000)
            entry["proExpStartDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        if ed and not p.get("proExpEndDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(ed / 1000)
            entry["proExpEndDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        projects.append(entry)

    # ---- 培训经历 ----
    training = []
    for t in (raw.get("TrainExperience") or []):
        entry = dict(t)
        sd = t.get("trainStartDate", 0)
        ed = t.get("trainEndDate", 0)
        if sd and not t.get("trainStartDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(sd / 1000)
            entry["trainStartDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        if ed and not t.get("trainEndDateFormat"):
            from datetime import datetime
            dt = datetime.fromtimestamp(ed / 1000)
            entry["trainEndDateFormat"] = dt.strftime("%Y/%m/%d %H:%M:%S")
        training.append(entry)

    # ---- 语言能力 ----
    languages = []
    for l in (raw.get("LanguageSkill") or []):
        certs_format = l.get("langCertificatesFormat", [])
        if not isinstance(certs_format, list):
            certs_format = []
        languages.append({
            "path": l.get("path", ""),
            "langType": l.get("langType", ""),
            "langLanguageT": l.get("langLanguageT", ""),
            # 与 langSkillLevelTranslation 对称的官网翻译键；缺失时回退语言原名
            "langTypeTranslation": l.get("langTypeTranslation") or l.get("langLanguageT", ""),
            "langLSProficiency": l.get("langLSProficiency", ""),
            "langRWProficiency": l.get("langRWProficiency", ""),
            "langSkillLevel": l.get("langSkillLevel", ""),
            "langSkillLevelTranslation": l.get("langSkillLevelTranslation", ""),
            "certificates": certs_format,
        })

    # ---- 专业技能 ----
    skills = []
    for s in (raw.get("ProfessionalSkill") or []):
        skills.append({
            "path": s.get("path", ""),
            "proskillName": s.get("proskillName", ""),
            "proskillLevel": s.get("proskillLevel", ""),
            "proskillType": s.get("proskillType", "13"),
            "proskillUseTime": s.get("proskillUseTime", ""),
        })

    # ---- 获得证书 ----
    certificates = []
    for c in (raw.get("Certificate") or []):
        certificates.append({
            "path": c.get("path", ""),
            "certificateId": c.get("certificateId", ""),
            "certType": c.get("certType", ""),
            "certSubType": c.get("certSubType", ""),
            "certUserdefName": c.get("certUserdefName", ""),
            "certDate": c.get("certDate", 0),
            "certDateFormat": c.get("certDateFormat", ""),
        })

    # ---- 自我评价 ----
    self_eval_list = raw.get("SelfEvaluate", [])
    self_evaluation = self_eval_list[0].get("selfEvaContent", "") if self_eval_list else ""

    # ---- 构建 fields ----
    fields = {
        # === 个人信息 ===
        "name": {
            "label": "姓名", "required": True, "type": "text",
            "current_value": profile.get("name", "")
        },
        "gender": {
            "label": "性别", "required": True, "type": "select",
            "current_value": str(profile.get("gender", ""))
        },
        "genderTranslation": {
            "label": "性别", "required": False, "type": "text",
            "current_value": profile.get("genderTranslation", "")
        },
        "currentIdentity": {
            "label": "当前身份", "required": True, "type": "select",
            "current_value": str(profile.get("currentIdentity", ""))
        },
        "currentIdentityTranslation": {
            "label": "当前身份", "required": False, "type": "text",
            "current_value": profile.get("currentIdentityTranslation", "")
        },
        "birthyear": {
            "label": "出生年份", "required": False, "type": "number",
            "current_value": profile.get("birthyear", "")
        },
        "birthmonth": {
            "label": "出生月份", "required": False, "type": "number",
            "current_value": profile.get("birthmonth", "")
        },
        "yearStartWorking": {
            "label": "参加工作年份", "required": False, "type": "number",
            "current_value": profile.get("yearStartWorking", "")
        },
        "monthStartWorking": {
            "label": "参加工作月份", "required": False, "type": "number",
            "current_value": profile.get("monthStartWorking", "")
        },
        "hukouProvinceId": {
            "label": "户口省编码", "required": False, "type": "text",
            "current_value": str(profile.get("hukouProvinceId", ""))
        },
        "hukouProvinceIdTranslation": {
            "label": "户口所在省", "required": False, "type": "text",
            "current_value": profile.get("hukouProvinceIdTranslation", "")
        },
        "hukouCityId": {
            "label": "户口城市编码", "required": False, "type": "text",
            "current_value": str(profile.get("hukouCityId", ""))
        },
        "hukouCityIdTranslation": {
            "label": "户口所在城市", "required": False, "type": "text",
            "current_value": profile.get("hukouCityIdTranslation", "")
        },
        "currentProvince": {
            "label": "现居住省编码", "required": False, "type": "text",
            "current_value": str(profile.get("currentProvince", ""))
        },
        "currentProvinceTranslation": {
            "label": "现居住省", "required": False, "type": "text",
            "current_value": profile.get("currentProvinceTranslation", "")
        },
        "currentCity": {
            "label": "现居住城市编码", "required": False, "type": "text",
            "current_value": str(profile.get("currentCity", ""))
        },
        "currentCityTranslation": {
            "label": "现居住城市", "required": False, "type": "text",
            "current_value": profile.get("currentCityTranslation", "")
        },
        "currentCityDistrictId": {
            "label": "现居住区编码", "required": False, "type": "text",
            "current_value": str(profile.get("currentCityDistrictId", ""))
        },
        "currentCityDistrictIdTranslation": {
            "label": "现居住区", "required": False, "type": "text",
            "current_value": profile.get("currentCityDistrictIdTranslation", "")
        },
        "politicalAffiliation": {
            "label": "政治面貌编码", "required": False, "type": "select",
            "current_value": str(profile.get("politicalAffiliation", ""))
        },
        "politicalAffiliationTranslation": {
            "label": "政治面貌", "required": False, "type": "text",
            "current_value": profile.get("politicalAffiliationTranslation", "")
        },
        "phone": {
            "label": "手机号", "required": True, "type": "text",
            "current_value": mobile
        },
        "email": {
            "label": "邮箱", "required": False, "type": "text",
            "current_value": profile.get("email", "")
        },
        "job_status": {
            "label": "求职状态", "required": False, "type": "select",
            "current_value": {
                "jobStateCode": job_status_code,
                "jobState": job_status_label
            }
        },
        "age": {
            "label": "年龄", "required": False, "type": "text",
            "current_value": age_str
        },
        "education_degree": {
            "label": "最高学历", "required": False, "type": "select",
            "options": ["初中及以下", "中专/中技", "高中", "大专", "本科", "硕士", "博士"],
            "current_value": profile.get("eduHighestLevelTranslation", "") or profile.get("eduHighestLevel", "")
        },
        "work_years": {
            "label": "工作年限", "required": False, "type": "text",
            "current_value": (raw.get("extend", {}) or {}).get("workYearShow", "") or business.get("workyears", "")
        },
        "wanna": {
            "label": "求职意向", "required": True, "type": "list",
            "current_value": wanna
        },
        "work_experience": {
            "label": "工作经历", "required": True, "type": "list",
            "current_value": work_experience
        },
        "education": {
            "label": "教育经历", "required": True, "type": "list",
            "current_value": education
        },
        "projects": {
            "label": "项目经历", "required": False, "type": "list",
            "current_value": projects
        },
        "training": {
            "label": "培训经历", "required": False, "type": "list",
            "current_value": training
        },
        "language": {
            "label": "语言能力", "required": False, "type": "list",
            "current_value": languages
        },
        "skill_tags": {
            "label": "技能标签", "required": False, "type": "list",
            "current_value": skills
        },
        "certificates": {
            "label": "获得证书", "required": False, "type": "list",
            "current_value": certificates
        },
        "self_evaluation": {
            "label": "自我评价", "required": False, "type": "textarea",
            "current_value": self_evaluation
        }
    }

    return fields


def save_data(fields):
    """保存 zhilian_fields.json（统一安全策略：空数据拦截 + 备份 + 原子写）"""
    print("  [3/3] 保存数据...")
    save_fields_json("zhilian", OUTPUT_PATH, fields)


def main():
    print("=" * 50)
    print("  智联招聘 简历采集器")
    print(f"  端口: {PORT}")
    print("=" * 50)

    try:
        page = connect_browser()
    except Exception as e:
        print(f"  [ERROR] 无法连接浏览器: {e}")
        print(f"  请先在页面点击「启动」打开智联浏览器 (端口 {PORT}) 并登录")
        sys.exit(1)
    print(f"  [OK] 已连接浏览器，当前页面: {page.url}")

    raw_data = collect_resume(page)
    fields = transform_data(raw_data)
    try:
        save_data(fields)
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        sys.exit(1)

    print("\n  智联招聘简历采集完成！")


if __name__ == "__main__":
    main()
