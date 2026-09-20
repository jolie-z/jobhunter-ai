"""
前程无忧(51job) - 简历数据采集脚本
连接 51job 专用 Edge 浏览器（端口由全项目统一配置区 backend/app/session/registry.py 提供），
从51job官网抓取最新简历数据，写入 51job_fields.json

用法：python job51_collector.py
前提：51job 浏览器已启动且已登录
"""

import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "51job_fields.json")

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port, connect_page, save_fields_json

PORT = get_platform_port("51job")
JOB51_RESUME_URL = "https://www.51job.com/resume/center"


def connect_browser():
    """连接已启动的浏览器（端口 PORT），端口无响应直接报错，绝不自动拉起新浏览器"""
    return connect_page(PORT)


def collect_resume(page):
    """从51job简历中心采集数据"""
    print("  [1/3] 导航到简历中心...")
    if not page.get(JOB51_RESUME_URL):
        print("  [ERROR] 简历页加载失败（网络超时），请检查网络后重试")
        sys.exit(1)
    time.sleep(5)

    # 检查登录（login 页与 passport 登录域都要拦）
    if "login" in page.url.lower() or "passport" in page.url.lower():
        print("  [ERROR] 未登录，请先在浏览器中登录51job")
        sys.exit(1)

    # 等待 personalSkills 数据异步加载（最多额外等 10 秒）
    print("  [1.5/3] 等待数据加载...")
    for _wait in range(10):
        check = page.run_js("""
        return (function() {
            var nuxt = document.querySelector('#__nuxt');
            if (!nuxt || !nuxt.__vue__) return 'no';
            var vm = nuxt.__vue__;
            function findByName(c, n, d) {
                if (d > 8) return null;
                if ((c.$options.name || '') === n) return c;
                var ch = c.$children || [];
                for (var i = 0; i < ch.length; i++) { var f = findByName(ch[i], n, d+1); if (f) return f; }
                return null;
            }
            var pc = findByName(vm, 'PCResume', 0);
            if (!pc || !pc.$data.resumeInfo) return 'no';
            var ps = pc.$data.resumeInfo.personalSkills;
            return (Array.isArray(ps) && ps.length > 0) ? 'yes' : 'no';
        })();
        """)
        if check == "yes":
            print(f"  [OK] personalSkills 已加载 (等了 {_wait} 秒)")
            break
        time.sleep(1)
    else:
        print("  [WARN] personalSkills 未加载，继续采集其他数据...")

    print("  [2/3] 从 PCResume 组件提取数据...")

    # 51job 是 Vue2 + Nuxt SSR，核心数据在 PCResume 组件的 $data 和 $data.resumeInfo 中
    js_code = """
    return (function() {
        var nuxt = document.querySelector('#__nuxt');
        if (!nuxt || !nuxt.__vue__) return JSON.stringify({error: 'no nuxt vue'});
        var vm = nuxt.__vue__;

        // 按组件名递归查找
        function findByName(comp, name, depth) {
            if (depth > 8) return null;
            if ((comp.$options.name || '') === name) return comp;
            var children = comp.$children || [];
            for (var i = 0; i < children.length; i++) {
                var found = findByName(children[i], name, depth + 1);
                if (found) return found;
            }
            return null;
        }

        var pc = findByName(vm, 'PCResume', 0);
        if (!pc) return JSON.stringify({error: 'PCResume component not found'});

        var d = pc.$data;
        var ri = d.resumeInfo;
        if (!ri || typeof ri !== 'object' || Object.keys(ri).length === 0) return JSON.stringify({error: 'resumeInfo is empty or null'});

        // 安全序列化（处理循环引用）
        function safeClone(obj) {
            try { return JSON.parse(JSON.stringify(obj)); }
            catch(e) { return null; }
        }

        var result = {
            accountInfo: safeClone(ri.accountInfo),
            selfIntroduction: safeClone(ri.selfIntroduction),
            intentions: safeClone(ri.intentions || []),
            works: safeClone(ri.works || []),
            projects: safeClone(ri.projects || []),
            educations: safeClone(ri.educations || []),
            skills: safeClone(ri.skills || []),
            language: safeClone(ri.language || []),
            certifications: safeClone(ri.certifications || []),
            avatarUrl: ri.avatarUrl || '',
            topDegreeEducation: safeClone(ri.topDegreeEducation),
            personalSkills: safeClone(ri.personalSkills || []),
        };

        return JSON.stringify(result);
    })();
    """

    raw = page.run_js(js_code)
    if not raw:
        print("  [ERROR] JS 提取返回空")
        sys.exit(1)

    vue_data = json.loads(raw)

    if vue_data.get("error"):
        print(f"  [ERROR] Vue 提取失败: {vue_data['error']}")
        sys.exit(1)

    # ===== 异步加载语言证书选择数据 =====
    # skillCertificationQueries 需要调用 getCertificationsInfo 后才会填充
    lang_items = vue_data.get("language") or []
    if lang_items:
        print("  [2.5/3] 加载语言证书数据...")
        certs_by_lang = {}
        for item in lang_items:
            skill_code = item.get("skillType") or item.get("skill") or ""
            if not skill_code:
                continue
            # 触发异步加载（json.dumps 转义，防官网数据中的引号破坏 JS 字面量）
            skill_code_js = json.dumps(str(skill_code))
            page.run_js(f"""
                return (function(){{
                    function findByName(root, name, depth) {{
                        if (!root || depth > 15) return null;
                        if (root.$options && root.$options.name === name) return root;
                        var children = root.$children || [];
                        for (var i = 0; i < children.length; i++) {{
                            var found = findByName(children[i], name, depth + 1);
                            if (found) return found;
                        }}
                        return null;
                    }}
                    var app = document.querySelector('#app');
                    var vm = app.__vue__;
                    var la = findByName(vm, 'LanguageAbility', 0);
                    if (la) {{
                        la.$data.formData.skill = {skill_code_js};
                        la.getCertificationsInfo({skill_code_js});
                    }}
                    return 'ok';
                }})();
            """)
            time.sleep(2)
            # 读取已选证书
            certs_raw = page.run_js("""
                return (function(){
                    function findByName(root, name, depth) {
                        if (!root || depth > 15) return null;
                        if (root.$options && root.$options.name === name) return root;
                        var children = root.$children || [];
                        for (var i = 0; i < children.length; i++) {
                            var found = findByName(children[i], name, depth + 1);
                            if (found) return found;
                        }
                        return null;
                    }
                    var app = document.querySelector('#app');
                    var vm = app.__vue__;
                    var la = findByName(vm, 'LanguageAbility', 0);
                    if (la && la.$data && la.$data.formData) {
                        return JSON.stringify(la.$data.formData.skillCertificationQueries || []);
                    }
                    return '[]';
                })();
            """)
            try:
                certs = json.loads(certs_raw) if certs_raw else []
                # 按语种分桶（历史版本把所有语种的证书累加成全局并集，
                # 转换时赋给每个语言条目，回写会交叉污染线上证书选择）
                certs_by_lang[skill_code] = certs
                if certs:
                    print(f"    语种 {skill_code}: 已选 {len(certs)} 个证书")
            except (json.JSONDecodeError, TypeError):
                pass
        vue_data["languageCertsByLang"] = certs_by_lang

    print("  [3/3] 转换数据格式...")
    return transform_data(vue_data)


def transform_data(raw):
    """将 PCResume 数据转换为前端 ResumeData 格式"""
    fields = {}

    # ===== 1. 基本信息 =====
    ai = raw.get("accountInfo") or {}
    # 补充 avatarUrl
    if not ai.get("avatarUrl") and raw.get("avatarUrl"):
        ai["avatarUrl"] = raw["avatarUrl"]
    # 补充 topDegreeString
    tde = raw.get("topDegreeEducation") or {}
    if tde.get("degreeString") and not ai.get("topDegreeString"):
        ai["topDegreeString"] = tde["degreeString"]

    fields["basic_info"] = {
        "label": "基本信息", "required": True, "type": "object",
        "current_value": ai
    }

    # ===== 2. 自我介绍 =====
    si = raw.get("selfIntroduction") or {}
    si_text = si.get("selfIntroduction", "") if isinstance(si, dict) else str(si)
    fields["self_introduction"] = {
        "label": "自我介绍", "required": False, "type": "object",
        "current_value": {"selfIntroduction": si_text}
    }

    # ===== 3. 求职意向 =====
    # API字段: expectAreaString, expectFunctionString, expectIndustryString, salaryMonth(string), preferenceValues
    # 前端期望: expectAreaNames, expectFunctionName, industryNames, salaryMonth(number), preferenceValues
    intentions = []
    for item in (raw.get("intentions") or []):
        mapped = dict(item)
        # 映射字段名（API→前端双向兼容）
        if "expectAreaString" in mapped and "expectAreaNames" not in mapped:
            mapped["expectAreaNames"] = mapped["expectAreaString"]
        if "expectFunctionString" in mapped and "expectFunctionName" not in mapped:
            mapped["expectFunctionName"] = mapped["expectFunctionString"]
        if "expectIndustryString" in mapped and "industryNames" not in mapped:
            mapped["industryNames"] = mapped["expectIndustryString"]
        if "expectIndustry" in mapped and "industry" not in mapped:
            mapped["industry"] = mapped["expectIndustry"]
        elif "industry" in mapped and "expectIndustry" not in mapped:
            mapped["expectIndustry"] = mapped["industry"]
        if "industryNames" in mapped and "expectIndustryString" not in mapped:
            mapped["expectIndustryString"] = mapped["industryNames"]
        # salaryMonth 转为数字（解析失败保留官网原值，不伪造默认值）
        if isinstance(mapped.get("salaryMonth"), str):
            try:
                mapped["salaryMonth"] = int(mapped["salaryMonth"])
            except (ValueError, TypeError):
                print(f"    [WARN] salaryMonth 非数字，保留原值: {mapped['salaryMonth']!r}")
        # 清理不需要的嵌套对象（保留 preferenceValues）
        mapped.pop("diagnosis", None)
        intentions.append(mapped)

    fields["intentions"] = {
        "label": "求职意向", "required": True, "type": "array",
        "current_value": intentions
    }

    # ===== 4. 工作经历 =====
    # API字段: workType, workTypeString, workFunctionString, workDescription,
    #          workIndustry(code), workIndustryString, position
    # 前端期望: seekType, workFunctionString, industry(code), industryName, position
    works = []
    for item in (raw.get("works") or []):
        mapped = dict(item)
        # workType → seekType (前端用seekType/workType判断全职/兼职/实习)
        if "workType" in mapped and "seekType" not in mapped:
            mapped["seekType"] = mapped["workType"]
        if "workTypeString" in mapped and "seekTypeString" not in mapped:
            mapped["seekTypeString"] = mapped["workTypeString"]
        # workIndustry → industry (前端用 industry/industryName 显示行业)
        if "workIndustry" in mapped and "industry" not in mapped:
            mapped["industry"] = mapped["workIndustry"]
        if "workIndustryString" in mapped and "industryName" not in mapped:
            mapped["industryName"] = mapped["workIndustryString"]
        # 相关技能提取
        vskills = mapped.get("workVocationalSkills") or []
        mapped["workVocationalSkills"] = vskills
        if "skills" not in mapped:
            mapped["skills"] = [
                (s if isinstance(s, str) else (s.get("skill") or s.get("value") or ""))
                for s in vskills if s
            ]
        # 清理
        mapped.pop("diagnosis", None)
        works.append(mapped)

    fields["works"] = {
        "label": "工作经历", "required": True, "type": "array",
        "current_value": works
    }

    # ===== 5. 项目经历 =====
    # API字段: projectName, companyName, describe, startTimeString, endTimeString
    # 前端期望: projectName, company, describe, startTime, endTime
    projects = []
    for item in (raw.get("projects") or []):
        mapped = dict(item)
        # companyName → company (前端用 projectForm.company)
        if "companyName" in mapped and "company" not in mapped:
            mapped["company"] = mapped["companyName"] or ""
        # startTimeString/endTimeString → startTime/endTime
        if "startTimeString" in mapped and "startTime" not in mapped:
            mapped["startTime"] = mapped["startTimeString"]
        if "endTimeString" in mapped and "endTime" not in mapped:
            mapped["endTime"] = mapped["endTimeString"]
        mapped.pop("diagnosis", None)
        projects.append(mapped)

    fields["projects"] = {
        "label": "项目经历", "required": False, "type": "array",
        "current_value": projects
    }

    # ===== 6. 教育经历 =====
    # API字段: degree, degreeString, schoolName, major(code), majorString(分类名),
    #         majorDescribe(实际专业名), describe(专业描述文本),
    #         isFullTime, isOverseas, startTimeString, endTimeString, complete
    # 前端期望: degree(=code), degreeString, schoolName, majorName(=majorDescribe),
    #          majorString(分类), describe(专业描述), studyType, startTime, endTime
    educations = []
    for item in (raw.get("educations") or []):
        # 过滤未完成/空的占位条目
        if not item.get("complete") and not item.get("schoolName"):
            continue
        mapped = dict(item)
        # majorDescribe 是实际专业名（如"社会工作"），majorString 是分类名（如"心理学类"）
        if "majorDescribe" in mapped and mapped["majorDescribe"]:
            mapped["majorName"] = mapped["majorDescribe"]
        elif "majorString" in mapped and "majorName" not in mapped:
            mapped["majorName"] = mapped["majorString"]
        # isFullTime → studyType
        if "isFullTime" in mapped and "studyType" not in mapped:
            mapped["studyType"] = "全日制" if mapped["isFullTime"] else "非全日制"
        # startTimeString/endTimeString → startTime/endTime
        if "startTimeString" in mapped and "startTime" not in mapped:
            mapped["startTime"] = mapped["startTimeString"]
        if "endTimeString" in mapped and "endTime" not in mapped:
            mapped["endTime"] = mapped["endTimeString"]
        educations.append(mapped)

    fields["educations"] = {
        "label": "教育经历", "required": True, "type": "array",
        "current_value": educations
    }

    # ===== 7. 语言能力 =====
    # API: skillType, skillTypeString, ability, abilityString
    # LanguageAbility formData: skillCertificationQueries [{code, value}]
    certs_by_lang = raw.get("languageCertsByLang") or {}
    language = []
    for item in (raw.get("language") or []):
        mapped = dict(item)
        # 只合并本语种自己的证书（按 skillType 取桶，避免跨语种交叉污染）
        lang_certs = certs_by_lang.get(item.get("skillType") or item.get("skill") or "", [])
        if lang_certs:
            mapped["certifications"] = [c.get("code", "") for c in lang_certs]
            mapped["certificationDetails"] = lang_certs
        language.append(mapped)

    fields["language"] = {
        "label": "语言能力", "required": False, "type": "array",
        "current_value": language
    }

    # ===== 8. 专业技能 =====
    # API: skillType(code), skillTypeString(name), ability(code), abilityString(text)
    # 前端: skillType(code), skillName(name), ability(code), abilityString(text)
    skills = []
    for item in (raw.get("skills") or []):
        mapped = dict(item)
        # skillTypeString → skillName (前端展示用; API 常返回空字符串 skillName)
        if "skillTypeString" in mapped and not mapped.get("skillName"):
            mapped["skillName"] = mapped["skillTypeString"]
        skills.append(mapped)

    fields["skills"] = {
        "label": "专业技能", "required": False, "type": "array",
        "current_value": skills
    }

    # ===== 9. 资格证书 =====
    # API: [{cert: "code", certString: "名称", ...}]
    # 前端: 保存为 cert code 数组, 展示用 certNameMap[code]
    certs = []
    for item in (raw.get("certifications") or []):
        if isinstance(item, dict):
            certs.append(item)
        elif isinstance(item, str):
            certs.append({"cert": item, "certString": item})

    fields["certifications"] = {
        "label": "资格证书", "required": False, "type": "array",
        "current_value": certs
    }

    # ===== 10. 求职偏好选项（按职位） =====
    # personalSkills: [{function: "code", functionString: "name", questions: [...]}]
    # 前端根据 intention.expectFunction 匹配对应职位的偏好选项
    personal_skills = raw.get("personalSkills") or []
    fields["personalSkills"] = {
        "label": "求职偏好选项", "required": False, "type": "array",
        "current_value": personal_skills
    }

    return fields


def save_data(fields):
    """保存采集数据（统一安全策略：空数据拦截 + 备份 + 原子写）"""
    save_fields_json("51job", OUTPUT_PATH, fields)


def main():
    print("=" * 50)
    print("  前程无忧(51job) - 简历数据采集")
    print("=" * 50)

    try:
        page = connect_browser()
        print(f"  已连接浏览器 (端口 {PORT})")
    except Exception as e:
        print(f"  [ERROR] 无法连接浏览器: {e}")
        print(f"  请确保 51job 浏览器已启动 (端口 {PORT})")
        sys.exit(1)

    fields = collect_resume(page)
    try:
        save_data(fields)
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        sys.exit(1)

    print("\n  采集完成！")


if __name__ == "__main__":
    main()
