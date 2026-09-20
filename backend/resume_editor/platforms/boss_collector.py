"""
BOSS直聘 - 简历数据采集脚本
连接端口 19222 的 Edge 浏览器，通过拦截 BOSS 内部 API (geek/preview/data.json)
获取完整简历 JSON 数据，写入 boss_fields.json。

用法：python boss_collector.py
前提：BOSS 浏览器已启动且已登录（端口 19222）
"""

import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "boss_fields.json")

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port, connect_page, save_fields_json

PORT = get_platform_port("boss")
BOSS_RESUME_URL = "https://www.zhipin.com/web/geek/resume"


def connect_browser():
    """连接已启动的浏览器（端口 PORT），端口无响应直接报错，绝不自动拉起新浏览器"""
    return connect_page(PORT)


def collect_resume(page):
    """通过拦截 BOSS 内部 API 获取完整简历 JSON 数据"""
    import time as _time

    print("  [1/4] 启动 API 监听 (geek/preview/data.json)...")
    page.listen.start("geek/preview/data.json")
    print("  [2/4] 导航到简历页触发 API 请求...")
    if not page.get(BOSS_RESUME_URL):
        page.listen.stop()
        print("  [ERROR] 简历页加载失败（网络超时），请检查网络后重试")
        sys.exit(1)

    packet = page.listen.wait(timeout=20)
    page.listen.stop()

    if not packet:
        print("  [ERROR] 未捕获到简历 API 响应。请确认已在浏览器中登录 BOSS 直聘。")
        sys.exit(1)

    # 检查是否被重定向到登录页
    if "login" in page.url.lower():
        print("  [ERROR] 未登录，请先在浏览器中登录 BOSS 直聘")
        sys.exit(1)

    body = packet.response.body
    try:
        api_data = json.loads(body) if isinstance(body, str) else body
    except Exception as e:
        print(f"  [ERROR] API 响应解析失败: {e}")
        sys.exit(1)

    zp = api_data.get("zpData", api_data.get("data", {}))
    if not zp or not isinstance(zp, dict):
        api_msg = api_data.get("message", "") if isinstance(api_data, dict) else ""
        if api_msg or "/user" in page.url:
            print(f"  [ERROR] 登录状态失效（官网提示: {api_msg or f'页面跳转到 {page.url}'}），请在 BOSS 浏览器中重新登录")
        else:
            print(f"  [ERROR] 简历数据为空（API 响应: {str(api_data)[:120]}）")
        sys.exit(1)

    print(f"  [3/4] 解析 API 数据 (zpData keys: {len(zp)})...")

    # 抓取兼职偏好/时间数据
    print("  [4/4] 抓取兼职偏好/时间数据...")
    parttime_data = collect_parttime_data(page)

    fields = transform_preview(zp, parttime_data, page)
    return fields


def collect_parttime_data(page):
    """抓取兼职偏好（preferenceSelectList）和兼职时间（parttime filter API）的已选数据"""
    import time as _time

    result = {"parttime_preference": [], "parttime_time": []}

    try:
        # 1) 监听兼职时间 API
        page.listen.start("preference/parttime/filter")

        # 2) 触发兼职期望的编辑按钮（通过 JS dispatch click）
        page.run_js("""
        var items = document.querySelectorAll('[ka*="user-resume-edit-expectation"]');
        for (var i = 0; i < items.length; i++) {
            var text = items[i].innerText || '';
            // 兼职条目：没有薪资描述（全职有如"15-20K"）
            if (text.indexOf('K') === -1 && text.indexOf('行业不限') !== -1) {
                var link = items[i].querySelector('a.link-edit');
                if (link) { link.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); }
                return 'clicked';
            }
        }
        // fallback: 找包含多个职位名用顿号分隔的条目
        for (var i = 0; i < items.length; i++) {
            var text = items[i].innerText || '';
            if (text.indexOf('、') !== -1 && text.indexOf('K') === -1) {
                var link = items[i].querySelector('a.link-edit');
                if (link) { link.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); }
                return 'clicked-fallback';
            }
        }
        return 'no-parttime';
        """)
        _time.sleep(4)

        # 3) 获取兼职时间 API 响应
        p = page.listen.wait(timeout=10)
        page.listen.stop()
        if p:
            body = p.response.body
            if isinstance(body, str):
                body = json.loads(body)
            zp_time = body.get("zpData", {})
            # 提取 flag=1 的已选项（去重，因为"时间灵活"可能出现在多个列表中）
            seen = set()
            for item in zp_time.get("workDayList", []):
                if item.get("flag") == 1 and item["name"] not in seen:
                    result["parttime_time"].append(item["name"])
                    seen.add(item["name"])
            for item in zp_time.get("workShiftList", []):
                if item.get("flag") == 1 and item["name"] not in seen:
                    result["parttime_time"].append(item["name"])
                    seen.add(item["name"])
            for item in zp_time.get("daysPerWeekList", []):
                if item.get("flag") == 1 and item["name"] not in seen:
                    result["parttime_time"].append(item["name"])
                    seen.add(item["name"])
            print(f"    兼职时间已选: {result['parttime_time']}")

        # 4) 从 Vue 组件提取兼职偏好已选数据
        pref_json = page.run_js("""
        var allEls = document.querySelectorAll('*');
        for (var i = 0; i < allEls.length; i++) {
            var el = allEls[i];
            if (el.__vue__ && el.__vue__.$data && el.__vue__.$data.preferenceSelectList) {
                return JSON.stringify(el.__vue__.$data.preferenceSelectList);
            }
        }
        return null;
        """)
        if pref_json:
            pref_list = json.loads(pref_json)
            for question in pref_list:
                for opt in question.get("options", []):
                    if opt.get("chosen") == 1:
                        result["parttime_preference"].append(opt["content"])
            print(f"    兼职偏好已选: {result['parttime_preference']}")
        else:
            print("    [WARN] 未能从 Vue 组件提取兼职偏好数据")

    except Exception as e:
        print(f"    [WARN] 兼职数据抓取异常: {e}")

    return result


def _split_ym(date_str):
    """将 '2024.04' 或 '202404' 拆成 (year, month)"""
    if not date_str:
        return "", ""
    s = str(date_str).replace(".", "")
    if len(s) >= 6:
        return s[:4], s[4:6]
    if len(s) == 4:
        return s, ""
    return s, ""


def extract_project_items(zp):
    """从 preview zpData 提取项目经历条目（纯函数，可单测）。
    注意：项目业绩在 preview 中的键是 performance（非 achievement）。"""
    items = []
    for p in zp.get("projectExpList", []) or []:
        sy, sm = _split_ym(p.get("startDate") or "")
        ey, em = _split_ym(p.get("endDate") or "")
        items.append({
            "project_name": p.get("name", ""),
            "project_role": p.get("roleName", ""),
            "project_link": p.get("url", ""),
            "startYear": sy,
            "startMonth": sm,
            "endYear": ey,
            "endMonth": em,
            "project_description": p.get("projectDesc", ""),
            "achievement": p.get("performance", ""),
        })
    return items


def _map_apply_status(code):
    """applyStatus 数值 → BOSS 求职状态文本；缺失/未知码返回空串（不伪造默认值，
    否则反爬骨架响应会被捏成 3 个"非空模块"恰好击穿采集拦截与回写守卫）"""
    m = {
        0: "离职-随时到岗",
        1: "在职-月内到岗",
        2: "在职-考虑机会",
        3: "在职-暂不考虑",
    }
    return m.get(code, "")


def _map_gender(code):
    """gender 数值 → 男/女；字段缺失返回空串（同上，不伪造）"""
    if code is None:
        return ""
    return "男" if code == 1 else "女"


def transform_preview(zp, parttime_data=None, page=None):
    """将 BOSS geek/preview/data.json 的 zpData 转换为前端 ResumeData 格式"""
    fields = {}

    # ===== 基本信息（来自 baseInfo） =====
    bi = zp.get("baseInfo", {}) or {}
    job_status = _map_apply_status(bi.get("applyStatus"))
    # 工作年限
    work_years = ""
    if bi.get("workYearDesc"):
        work_years = bi["workYearDesc"]
    elif bi.get("workYears") is not None:
        work_years = f"{bi['workYears']}年经验"
    birth_month = bi.get("birthdayDesc", "")
    work_start_date = bi.get("startWorkDateDesc", "")

    fields["name"] = {
        "label": "姓名", "required": True, "type": "text",
        "current_value": bi.get("nickName", bi.get("name", "")),
    }
    fields["phone"] = {
        "label": "电话", "required": True, "type": "text",
        "current_value": bi.get("account", ""),
    }
    fields["email"] = {
        "label": "邮箱", "required": False, "type": "text",
        "current_value": bi.get("emailBlur", ""),
    }
    fields["wechat"] = {
        "label": "微信号", "required": False, "type": "text",
        "current_value": bi.get("weixinBlur", ""),
    }
    fields["gender"] = {
        "label": "性别", "required": True, "type": "radio",
        "options": ["男", "女"],
        "current_value": _map_gender(bi.get("gender")),
    }
    fields["job_status"] = {
        "label": "求职状态", "required": True, "type": "select",
        "options": ["离职-随时到岗", "在职-月内到岗", "在职-考虑机会", "在职-暂不考虑"],
        "current_value": job_status,
    }
    fields["birth_month"] = {
        "label": "出生年月", "required": False, "type": "yearmonth",
        "current_value": birth_month,
    }
    fields["work_start_date"] = {
        "label": "参加工作时间", "required": False, "type": "yearmonth",
        "current_value": work_start_date,
    }
    fields["experience_years"] = {
        "label": "工作年限", "required": False, "type": "text",
        "current_value": work_years,
    }
    fields["education_degree"] = {
        "label": "学历", "required": False, "type": "text",
        "current_value": bi.get("degreeCategory", ""),
    }

    # ===== 个人优势 =====
    fields["personal_advantage"] = {
        "label": "个人优势", "required": False, "type": "textarea",
        "max_length": 1000,
        "current_value": zp.get("userDesc", "") or "",
    }

    # ===== 求职期望 =====
    # positionType=0 → 全职（每条独立），positionType=1 → 兼职（合并为1条，多职位）
    fulltime_list = []
    parttime_positions = []
    parttime_city = ""
    parttime_industries = []
    parttime_other_cities = []

    for e in zp.get("expectList", []) or []:
        pos_type = e.get("positionType", 0)
        if pos_type == 1:
            # 兼职：收集职位名，合并为一条
            pname = e.get("positionName", "")
            if pname and pname not in parttime_positions:
                parttime_positions.append(pname)
            if not parttime_city:
                parttime_city = e.get("locationName", "")
            if not parttime_industries:
                parttime_industries = [i.get("name", "") for i in (e.get("industryList") or [])]
            if not parttime_other_cities and e.get("interestLocationList"):
                parttime_other_cities = [c.get("name", "") for c in e["interestLocationList"]]
        else:
            # 全职：每条独立
            salary = e.get("salaryDescNew") or e.get("salaryDesc") or ""
            if not salary and (e.get("lowSalary") or e.get("highSalary")):
                low = e.get("lowSalary") or 0
                high = e.get("highSalary") or 0
                salary = f"{low}-{high}" if low and high else str(low or high)
            industries = [i.get("name", "") for i in (e.get("industryList") or [])]
            other_cities = []
            if e.get("interestLocationList"):
                other_cities = [c.get("name", "") for c in e["interestLocationList"]]
            elif e.get("otherCities"):
                other_cities = list(e["otherCities"])
            fulltime_list.append({
                "jobType": "fulltime",
                "position": e.get("positionName", ""),
                "city": e.get("locationName", ""),
                "otherCities": other_cities,
                "salary": salary,
                "industries": industries,
            })

    expectations = fulltime_list[:]
    # 兼职合并为1条（如果有兼职职位）
    if parttime_positions:
        pt_pref = (parttime_data or {}).get("parttime_preference", [])
        pt_time = (parttime_data or {}).get("parttime_time", [])
        expectations.append({
            "jobType": "parttime",
            "positions": parttime_positions,       # 多选，最多5个
            "position": "、".join(parttime_positions),  # 兼容显示
            "city": parttime_city,
            "otherCities": parttime_other_cities,
            "salary": "",                          # 兼职无薪资
            "industries": parttime_industries,
            "parttime_preference": pt_pref,        # 从官网爬取的已选兼职偏好
            "parttime_time": pt_time,              # 从官网爬取的已选兼职时间
        })

    fields["expectations"] = {
        "label": "求职期望", "required": True, "type": "array",
        "current_value": expectations,
    }

    # ===== 工作经历 =====
    work_items = []
    for w in zp.get("workExpList", []) or []:
        sy, sm = _split_ym(w.get("startDate") or w.get("startDateStr") or "")
        ey, em = _split_ym(w.get("endDate") or w.get("endDateStr") or "")
        end_date_str = w.get("endDateStr", "")
        if end_date_str == "至今" or (not ey and not em):
            ey, em = "", ""
        industry_name = ""
        ind = w.get("industry")
        if isinstance(ind, dict):
            industry_name = ind.get("name", "")
        elif isinstance(ind, str):
            industry_name = ind
        raw_emphasis = w.get("emphasis") or []
        if isinstance(raw_emphasis, str):
            skill_list = [s.strip() for s in raw_emphasis.split("#&#") if s.strip()]
        elif isinstance(raw_emphasis, list):
            skill_list = [str(s).strip() for s in raw_emphasis if s]
        else:
            skill_list = []
        
        work_items.append({
            "company": w.get("companyName", ""),
            "industry": industry_name,
            "department": w.get("department", ""),
            "position": w.get("positionName", w.get("customPositionName", "")),
            "startYear": sy,
            "startMonth": sm,
            "endYear": ey,
            "endMonth": em,
            "content": w.get("workContent", ""),
            "achievement": w.get("workPerformance", ""),
            "skills": [{"name": s} for s in skill_list],
            "hideResume": bool(w.get("isPublic") == 1 or w.get("hideResume", False)),
        })
    fields["work_experience"] = {
        "label": "工作经历", "required": True, "type": "array",
        "current_value": work_items,
    }

    # ===== 项目经历 =====
    project_items = extract_project_items(zp)
    fields["projects"] = {
        "label": "项目经历", "required": False, "type": "array",
        "current_value": project_items,
    }

    # ===== 教育经历 =====
    edu_type_map = {1: "全日制", 2: "非全日制", 3: "在职"}
    edu_items = []
    for e in zp.get("educationExpList", []) or []:
        edu_type = edu_type_map.get(e.get("eduType"), "")
        degree_name = e.get("degreeName", "")
        # 组合显示：本科 / 全日制
        degree_display = f"{degree_name} / {edu_type}" if edu_type else degree_name
        edu_items.append({
            "degree": degree_display,
            "degreeName": degree_name,
            "eduType": edu_type,
            "school": e.get("school", ""),
            "major": e.get("major", ""),
            "startYear": e.get("startYear", e.get("startYearStr", "")),
            "endYear": e.get("endYear", e.get("endYearStr", "")),
            "campus_experience": e.get("educationDesc", ""),
            "thesisTitle": e.get("thesisTitle", ""),
            "thesisDesc": e.get("thesisDesc", ""),
        })
    fields["education"] = {
        "label": "教育经历", "required": True, "type": "array",
        "current_value": edu_items,
    }

    # ===== 资格证书 =====
    cert_names = []
    for c in zp.get("certificationList", []) or []:
        name = c.get("certName", "")
        if name:
            cert_names.append(name)
    fields["certificates"] = {
        "label": "资格证书", "required": False, "type": "array",
        "current_value": cert_names,
    }

    # ===== 驻外选项 =====
    # 数据来自 Vue 组件 resumeData.stayAbroad（JSON字符串）
    overseas_value = {"countries": [], "languages": [], "duration": "", "allowView": False}
    try:
        stay_abroad_json = None
        if page:
            stay_abroad_json = page.run_js("""
        var el = document.querySelector('.resume-expectList') || document.querySelector('.resume-item') || document.body;
        function getVue(el) { while(el) { if(el.__vue__) return el.__vue__; el=el.parentElement; } return null; }
        var vue = getVue(el);
        if (!vue || !vue.$data || !vue.$data.resumeData) return null;
        var sa = vue.$data.resumeData.stayAbroad;
        if (!sa) return null;
        return typeof sa === 'string' ? sa : JSON.stringify(sa);
        """)
        if stay_abroad_json:
            sa = json.loads(stay_abroad_json) if isinstance(stay_abroad_json, str) else stay_abroad_json
            overseas_value["countries"] = [c.get("name", "") for c in sa.get("countryConfigs", [])]
            overseas_value["languages"] = [l.get("name", "") for l in sa.get("languageConfigs", [])]
            dur = sa.get("durationConfig")
            overseas_value["duration"] = dur.get("name", "") if isinstance(dur, dict) else str(dur or "")
            overseas_value["allowView"] = sa.get("showStatus", 0) == 1
            print(f"    驻外选项: {overseas_value['countries']}, {overseas_value['languages']}, {overseas_value['duration']}")
    except Exception as e:
        print(f"    [WARN] 驻外选项抓取异常: {e}")

    fields["overseas"] = {
        "label": "驻外选项", "required": False, "type": "object",
        "current_value": overseas_value,
    }

    return fields


def main():
    print("=" * 50)
    print("  BOSS直聘 - 简历数据采集")
    print("=" * 50)
    try:
        page = connect_browser()
    except Exception as e:
        print(f"  [ERROR] 无法连接浏览器: {e}")
        print(f"  请先在页面点击「启动」打开 BOSS 浏览器 (端口 {PORT}) 并登录")
        sys.exit(1)
    print(f"  已连接浏览器 (端口 {PORT})")
    fields = collect_resume(page)
    try:
        save_fields_json("boss", OUTPUT_PATH, fields)
    except RuntimeError as e:
        print(f"  [ERROR] {e}")
        sys.exit(1)
    print()
    print("  采集完成！")


if __name__ == "__main__":
    main()
