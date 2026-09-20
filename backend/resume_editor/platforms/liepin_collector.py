"""
猎聘 - 简历数据采集脚本
连接猎聘专用 Edge 浏览器（端口由全项目统一配置区 backend/app/session/registry.py 提供），
从猎聘官网抓取最新简历数据，写入 liepin_fields.json

用法：python liepin_collector.py
前提：猎聘浏览器已启动且已登录
"""

import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "liepin_fields.json")

sys.path.insert(0, _SCRIPT_DIR)
from browser_common import get_platform_port, connect_page, save_fields_json

PORT = get_platform_port("liepin")
LIEPIN_RESUME_URL = "https://c.liepin.com/resume/edit"


def connect_browser():
    """连接已启动的浏览器（端口 PORT），端口无响应直接报错，绝不自动拉起新浏览器"""
    return connect_page(PORT)


def collect_resume(page):
    """通过拦截猎聘内部 API 获取完整简历 JSON 数据"""
    print("  [1/3] 启动 API 监听...")
    page.listen.start("web-resume-detail")

    print("  [2/3] 导航到简历页触发 API 请求...")
    if not page.get(LIEPIN_RESUME_URL):
        page.listen.stop()
        print("  [ERROR] 简历页加载失败（网络超时），请检查网络后重试")
        sys.exit(1)

    # 等待 API 响应
    packet = page.listen.wait(timeout=15)
    page.listen.stop()

    if not packet:
        print("  [ERROR] 未捕获到简历 API 响应，请确认已登录")
        sys.exit(1)

    # 检查登录
    if "login" in page.url.lower() or "passport" in page.url.lower():
        print("  [ERROR] 未登录，请先在浏览器中登录猎聘")
        sys.exit(1)

    body = packet.response.body
    try:
        api_data = json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError) as e:
        print(f"  [ERROR] API 响应解析失败（可能被反爬拦截）: {e}")
        sys.exit(1)
    resume = api_data.get("data", {}) if isinstance(api_data, dict) else {}

    if not resume:
        print("  [ERROR] API 返回数据为空")
        sys.exit(1)

    print(f"  [3/3] 解析 API 数据 (keys: {len(resume)})...")
    fields = build_liepin_fields(resume)
    return fields


def build_liepin_fields(resume):
    """从猎聘 web-resume-detail API 响应构建 ResumeData 结构化格式"""
    fields = {}

    # ===== 基本信息 =====
    bi = resume.get("baseInfo", {})
    photo = bi.get("photo", "")
    avatar_url = f"https://image0.lietou-static.com/img/{photo}" if photo else ""

    # 显示先生/女士：showName 含"女士"/"先生"后缀即为勾选
    show_name = bi.get("showName", "")
    show_gender_suffix = ("女士" in show_name) or ("先生" in show_name)
    # 我的身份：fromStudent=False -> 职场人，True -> 学生
    identity = "学生" if bi.get("fromStudent") else "职场人"
    # 薪资保密：nowSalarySecret == "1" 表示保密
    salary_confidential = str(bi.get("nowSalarySecret", "")) == "1"
    now_salary = bi.get("nowSalary", "")
    now_salary_months = bi.get("nowSalaryMonths", "")

    basic_info = {
        "name": bi.get("realName", show_name),
        "gender": bi.get("sex", bi.get("sexName", "")),
        "age": str(bi.get("age", "")),
        "work_years": str(bi.get("workAge", "")),
        "city": bi.get("cityName", ""),
        "job_status": bi.get("workStatusName", ""),
        "political_status": bi.get("politicalStatusName", ""),
        "phone": bi.get("mobile", ""),
        "email": bi.get("email", ""),
        "wechat": bi.get("wechat", ""),
        "avatar": avatar_url,
        "birth": bi.get("birthYearMonth", ""),
        "work_start_date": f"{bi.get('startJob', '')}/{bi.get('startJobMonth', '')}",
        "identity": identity,
        "show_gender_suffix": show_gender_suffix,
        "current_salary_month": str(now_salary) if now_salary else "",
        "current_salary_months": str(now_salary_months) if now_salary_months else "",
        "salary_confidential": salary_confidential,
        "education_degree": bi.get("eduLevel", ""),
        "current_company": bi.get("nowCompName", ""),
        "current_title": bi.get("nowTitle", ""),
        "current_industry": bi.get("nowIndustryName", ""),
        "household": bi.get("houseHoldName", ""),
        "nationality": bi.get("nationalityName", ""),
    }
    fields["basic_info"] = {
        "label": "基本信息", "required": True, "type": "object",
        "current_value": basic_info,
    }

    # ===== 优势亮点 =====
    fields["self_assessment"] = {
        "label": "优势亮点", "required": False, "type": "textarea",
        "max_length": 1000,
        "current_value": resume.get("selfDescr", ""),
    }

    # ===== 求职期望 =====
    expectations = []
    for jw in resume.get("jobWants") or []:
        salary_low = jw.get("wantSalaryLow", 0)
        salary_high = jw.get("wantSalaryHigh", 0)
        inds = jw.get("industryNames") or []
        if isinstance(inds, str):
            inds = [s.strip() for s in inds.split("、") if s.strip()]
        elif not isinstance(inds, list):
            inds = [str(inds)] if inds else []
        expectations.append({
            "position": jw.get("jobtitleName", jw.get("jobTitleName", "")),
            "city": jw.get("dqName", ""),
            "other_cities": jw.get("otherExpectDqNames", []),
            "industries": inds,
            "salary_min": f"{salary_low // 1000}k" if salary_low else "",
            "salary_max": f"{salary_high // 1000}k" if salary_high else "",
            "salary_months": jw.get("wantSalaryMonths", 12),
        })
    fields["expectations"] = {
        "label": "求职期望", "required": True, "type": "array",
        "current_value": expectations,
    }

    # ===== 工作经历 =====
    work_items = []
    for we in resume.get("workExperiences") or []:
        end_year = str(we.get("endYear", "") or "")
        end_month = str(we.get("endMonth", "") or "")
        is_to_date = (end_year == "9999") or (not end_year) or (str(we.get("end", "")) == "999999")
        if is_to_date:
            end_date = "至今"
        else:
            end_date = f"{end_year}/{end_month}"

        work_items.append({
            "company": we.get("compName", ""),
            "position": we.get("title", ""),
            "job_category": we.get("jobtitleName", we.get("jobTitleName", "")),
            "department": we.get("dept", ""),
            "start_date": f"{we.get('startYear', '')}/{we.get('startMonth', '')}",
            "end_date": end_date,
            "responsibilities": we.get("duty", ""),
            "industry": we.get("industryName", ""),
            "work_city": we.get("dqName", ""),
            "report_to": we.get("report", ""),
            "is_internship": we.get("workTypeName", "工作经历") == "实习经历",
            "hide_resume": we.get("shieldComp", False),
            "team_size": str(we.get("subordinate", "")) if we.get("subordinate") is not None else "",
            "salary_amount": "",
            "salary_months": str(we.get("salaryMonths", "")) if we.get("salaryMonths") else "",
        })
    fields["work_experience"] = {
        "label": "工作经历", "required": True, "type": "array",
        "current_value": work_items,
    }

    # ===== 项目经历 =====
    project_items = []
    for pe in resume.get("projectExperiences") or []:
        # endYear/endMonth = "9999"/"99" 或 end == "999999" 表示"至今"
        start_year = str(pe.get("startYear", "") or "").strip()
        start_month = str(pe.get("startMonth", "") or "").strip()
        end_year = str(pe.get("endYear", "") or "").strip()
        end_month = str(pe.get("endMonth", "") or "").strip()
        raw_end = str(pe.get("end", "") or "").strip()

        start_date = f"{start_year}/{start_month}" if start_year and start_month else (start_year or "")
        is_to_date = (end_year == "9999") or (raw_end == "999999")
        if is_to_date:
            end_date = "至今"
        elif end_year and end_month:
            end_date = f"{end_year}/{end_month}"
        else:
            # 只有单个时间，结束时间等于开始时间
            end_date = start_date

        project_items.append({
            "project_name": pe.get("projectName", ""),
            "company": pe.get("compName", ""),
            "role": pe.get("title", ""),
            "start_date": start_date,
            "end_date": end_date,
            "description": pe.get("descr", ""),
            "responsibilities": pe.get("duty", ""),
            "achievements": pe.get("achievement", ""),
        })
    fields["projects"] = {
        "label": "项目经历", "required": False, "type": "array",
        "current_value": project_items,
    }

    # ===== 教育经历 =====
    edu_items = []
    for edu in resume.get("eduExperiences") or []:
        edu_items.append({
            "school": edu.get("school", ""),
            "start_date": f"{edu.get('startYear', '')}/{edu.get('startMonth', '')}",
            "end_date": f"{edu.get('endYear', '')}/{edu.get('endMonth', '')}",
            "degree": edu.get("degreeName", ""),
            "major": edu.get("special", ""),
            "is_tongzhao": edu.get("tz") == "1" or edu.get("tzName") == "统招",
            "campus_experience": edu.get("experience", "") or edu.get("campus_experience", ""),
        })
    fields["education"] = {
        "label": "教育经历", "required": True, "type": "array",
        "current_value": edu_items,
    }

    # ===== 资格证书 =====
    credential = resume.get("credential", {})
    cert_names = credential.get("names", []) if isinstance(credential, dict) else []
    fields["certificates"] = {
        "label": "资格证书", "required": False, "type": "array",
        "current_value": cert_names,
    }

    # ===== 技能标签 =====
    labels = resume.get("labels", [])
    skill_tags = []
    for lb in labels:
        if isinstance(lb, dict):
            skill_tags.append(lb.get("label", lb.get("name", lb.get("labelName", ""))))
        elif isinstance(lb, str):
            skill_tags.append(lb)
    fields["skill_tags"] = {
        "label": "技能标签", "required": False, "type": "array",
        "current_value": [s for s in skill_tags if s],
    }

    # ===== 语言能力 =====
    lang_items = []
    for lang in resume.get("languages") or []:
        lang_items.append({
            "language": lang.get("name", lang.get("content", "")),
            "proficiency": lang.get("degreeName", ""),
            "certificate": lang.get("levelName", ""),
            "level": lang.get("levelName", ""),
            "code": lang.get("code", ""),
            "degreeCode": lang.get("degreeCode", ""),
            "levelCode": lang.get("levelCode", ""),
        })
    fields["languages"] = {
        "label": "语言能力", "required": False, "type": "array",
        "current_value": lang_items,
    }

    # ===== 附加信息 =====
    fields["additional_info"] = {
        "label": "附加信息", "required": False, "type": "textarea",
        "max_length": 1000,
        "current_value": resume.get("additionalInfo", ""),
    }

    return fields


def save_data(fields):
    """保存采集数据（统一安全策略：空数据拦截 + 备份 + 原子写）"""
    save_fields_json("liepin", OUTPUT_PATH, fields)


def main():
    print("=" * 50)
    print("  猎聘 - 简历数据采集")
    print("=" * 50)

    try:
        page = connect_browser()
        print(f"  已连接浏览器 (端口 {PORT})")
    except Exception as e:
        print(f"  [ERROR] 无法连接浏览器: {e}")
        print(f"  请确保猎聘浏览器已启动 (端口 {PORT})")
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
