#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智联招聘 - 本地数据回写官网在线简历
读取本地 zhilian_writeback.json 快照（优先，writeback-save 生成）或 zhilian_fields.json，
通过官网页面内 Vuex action（resume/updateResumeAction 自带加密与鉴权，
底层 fe-api.zhaopin.com/c/i/resume/node-encrypt）回写。

回写范围（--paths 逗号分隔模块名；不传 = 全部模块）：
  ✅ self_evaluation -> SelfEvaluate 节点 updateResumeAction
  ✅ wanna           -> UnifiedPurpose 节点 updateResumeAction（add/edit/del）
  ✅ work_experience -> WorkExperience 节点（add/edit/del）
  ✅ education       -> EducationExperience 节点
  ✅ projects        -> ProjectExperience 节点
  ✅ training        -> TrainExperience 节点
  ✅ language        -> LanguageSkill 节点
  ✅ skill_tags      -> ProfessionalSkill 节点
  ✅ certificates    -> 批量接口 cgate/resumeapi/resumeCertification/saveCertificationList（整列表替换）
  条目匹配：优先按官网 path，回退业务键匹配（删除会导致 path 索引漂移，执行时逐条重新定位）
  语义：全量覆盖 —— 匹配上 edit / 本地多出 add / 官网多余 del
  ⛔ HARD_SKIP：basic_info（手机/邮箱为官网脱敏值，基本信息独立保存流未标定）

用法：python zhilian_write_back.py [--dry-run] [--json] [--paths work_experience,projects]
前提：智联 Edge 已启动且已登录（端口 9250）；macOS 需 NO_PROXY=127.0.0.1,localhost
"""

import json
import os
import re
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from browser_common import connect_page, get_platform_port, dismiss_overlay_popup, wait_resume_filled

PORT = get_platform_port("zhilian")
RESUME_URL = "https://i.zhaopin.com/resume"
DATA_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "zhilian_writeback.json")
FIELDS_PATH = os.path.join(DATA_DIR, "zhilian_fields.json")
OFFICIAL_NOW_PATH = os.path.join(DATA_DIR, "zhilian_official_now.json")

# 可回写模块（key 对应 zhilian_fields.json 顶层键）
ALL_MODULES = ["basic_info", "job_status", "self_evaluation", "wanna", "work_experience", "education",
               "projects", "training", "language", "skill_tags", "certificates"]

# HARD_SKIP 为空（基本信息已打通：开放字段正常回写，锁定/安全字段 birth/phone/email 自动保护）
HARD_SKIP = {}

# 列表模块配置：node=官网 Vuex 节点名；keys=业务键（no-op 判定+复核+目标重定位）；
# pick=updateResumeAction values 保留键（官网组件逆向所得）
NODE_CFG = {
    "work_experience": {
        "node": "WorkExperience",
        "keys": ["companyName", "jobTitle", "startDate", "endDate", "workDesc",
                 "skillTagStandard", "skillTagsTranslation"],
        "pick": ["newCompanyId", "companyName", "wnewIndustry", "industrySerial",
                 "jobTitle", "wnewJobSubType", "jobTypeSerial", "startDate", "endDate",
                 "realSalary", "workdays", "dailyWage", "workDesc", "path",
                 "skillTagStandard", "skillTagCustomized", "preferenceQuestionAndAnswer",
                 "skillTags", "skillTagList", "skillTagsTranslation",
                 "internshipWork"],
    },
    "education": {
        "node": "EducationExperience",
        "keys": ["eduSchoolName", "eduMajorV", "eduBackground",
                 "eduStartDateFormat", "eduEndDateFormat"],
        "pick": ["newEduMajorSmallType", "newEduSchoolId", "eduSchoolName",
                 "eduStartDateFormat", "eduEndDateFormat", "eduBackground", "eduMajorV",
                 "path", "eduFullTime", "eduOverseaseExperience", "degreeCertificate"],
    },
    "projects": {
        "node": "ProjectExperience",
        "keys": ["proExpProjectName", "proExpPosition", "proExpStartDate",
                 "proExpEndDate", "proExpProjectDuty", "proExpProjectDesc",
                 "affiliatedCompany"],
        "pick": ["affiliatedCompany", "path", "proExpDevTool", "proExpEndDate",
                 "proExpEndDateFormat", "proExpHardwareEnv", "proExpIsCurrent",
                 "proExpIsIt", "proExpPosition", "proExpProjectDesc",
                 "proExpProjectDuty", "proExpProjectName", "proExpSoftwareEnv",
                 "proExpStartDate", "proExpStartDateFormat"],
    },
    "training": {
        "node": "TrainExperience",
        "keys": ["trainAgency", "trainCourse", "trainStartDate", "trainEndDate"],
        "pick": ["path", "trainAddress", "trainAgency", "trainCertificate",
                 "trainCourse", "trainDesc", "trainEndDate", "trainEndDateFormat",
                 "trainStartDate", "trainStartDateFormat"],
    },
    "language": {
        "node": "LanguageSkill",
        "keys": ["langLanguageT", "langLSProficiency", "langRWProficiency"],
        "pick": None,  # 特殊构造，见 _build_lang_values
    },
    "skill_tags": {
        "node": "ProfessionalSkill",
        "keys": ["proskillName", "proskillLevel", "proskillUseTime"],
        "pick": None,  # 特殊构造，见 _build_skill_values
    },
    "wanna": {
        "node": "UnifiedPurpose",
        "keys": ["preferredJobNature", "pnewPreferredJobType", "pnewPreferredIndustry",
                 "preferredLocation", "preferredCityDistrict",
                 "preferredSalaryMin", "preferredSalaryMax"],
        "pick": None,  # 特殊构造，见 _build_wanna_values
    },
}

CERT_KEYS = ["certUserdefName", "certDateFormat"]

# 官网实测：自我评价超过 500 字保存静默失败（code≠success），截断保护
SELF_EVAL_MAX_LEN = 500

# 「至今」占位（官网组件约定：endDate=0 + 1970 格式串）
_ZH_EPOCH_FMT = "1970/01/01 08:00:00"


# ============================================================
# 数据加载与归一化（纯函数）
# ============================================================

def load_local():
    """优先读回写快照 zhilian_writeback.json，回退 zhilian_fields.json。
    返回 ({module: current_value}, 来源路径, freshness 新鲜度信息)"""
    from browser_common import load_writeback_source
    fields, src, freshness = load_writeback_source("zhilian", SNAPSHOT_PATH, FIELDS_PATH)

    def extract_val(v):
        if isinstance(v, dict) and "current_value" in v:
            return v["current_value"]
        return v

    out = {}
    for k, v in fields.items():
        out[k] = extract_val(v)

    # 兼容 camelCase / alias -> snake_case 标准化
    key_aliases = {
        "jobStatus": "job_status",
        "selfEvaluation": "self_evaluation",
        "workExperience": "work_experience",
        "project": "projects",
        "projectExperience": "projects",
        "project_experience": "projects",
        "languageSkills": "language",
        "languageSkill": "language",
        "languages": "language",
        "skillTags": "skill_tags",
        "skills": "skill_tags",
        "professionalSkills": "skill_tags",
        "ProfessionalSkill": "skill_tags",
        "certificate": "certificates",
        "Certificate": "certificates",
    }
    for alias, canonical in key_aliases.items():
        if alias in out and canonical not in out:
            out[canonical] = out[alias]
        elif alias in out and out.get(canonical) is None:
            out[canonical] = out[alias]

    # 特殊处理 self_evaluation：如果是一组条目 [{selfEvaContent: ...}] 或单个字符串
    if "self_evaluation" in out:
        se = out["self_evaluation"]
        if isinstance(se, list) and se:
            out["self_evaluation"] = se[0].get("selfEvaContent", "") if isinstance(se[0], dict) else str(se[0])
        elif isinstance(se, dict):
            out["self_evaluation"] = se.get("selfEvaContent", "") or se.get("current_value", "")

    # 提取基本信息 profile_data（兼容 profile 字典、basic_info 字段以及顶层扁平字段）
    profile_data = {}
    if "profile" in out and isinstance(out["profile"], dict):
        profile_data = dict(out["profile"])
    elif "basic_info" in out and isinstance(out["basic_info"], dict):
        profile_data = dict(out["basic_info"])
    else:
        for k in ["name", "gender", "currentIdentity", "yearStartWorking", "monthStartWorking",
                  "hukouProvinceId", "hukouCityId", "currentProvince", "currentCity",
                  "currentCityDistrictId", "politicalAffiliation", "maritalStatus",
                  "birthyear", "birthmonth", "mobile", "email", "phone",
                  "isOverseas", "foreign", "nationality"]:
            if k in out:
                profile_data[k] = out[k]
    out["basic_info"] = profile_data
    return out, src, freshness


def _val(fields, module):
    if not isinstance(fields, dict):
        return None
    v = fields.get(module)
    if v is None:
        ALIASES = {
            "skill_tags": ["professionalSkills", "skills", "skillTags", "ProfessionalSkill"],
            "certificates": ["certificate", "Certificate"],
            "projects": ["project", "projectExperience", "ProjectExperience"],
            "work_experience": ["workExperience", "works", "WorkExperience"],
            "education": ["educations", "EducationExperience"],
            "language": ["languageSkills", "languageSkill", "LanguageSkill"],
            "training": ["trainExperience", "TrainExperience"],
            "self_evaluation": ["selfEvaluation", "SelfEvaluate"],
            "basic_info": ["profile", "basicInfo", "Profile"],
            "job_status": ["jobStatus"],
        }
        for alt in ALIASES.get(module, []):
            if alt in fields:
                v = fields[alt]
                break
    if isinstance(v, dict):
        return v.get("current_value", v)
    return v


def _norm(v):
    if v is None:
        return ""
    return str(v).strip()


def _as_dict(x):
    """LLM 输出异常防御：数组元素若为 str(dict) repr（如「沿用官网原值」被字符串化），
    用 literal_eval 还原为 dict；解析失败返回 None。"""
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                import ast
                d = ast.literal_eval(s)
                if isinstance(d, dict):
                    return d
            except Exception:
                return None
    return None


def _xss_norm(s):
    """官网保存时会过滤 HTML 敏感字符（XSS 防护，如 '<12H' → '12H'、
    箭头 '->' → '-'），比对前先剔除符号类字符，避免假阴性。"""
    import re
    return re.sub(r"[<>`'\"\\/|\-_=+*&^%$#@!~\[\]{}]", "", s)


def _is_date_key(k):
    return k.endswith("Date") or k.endswith("DateFormat")


def _extract_work_skills(item):
    """提取工作经历的技能信息，区分标准技能（ID与名称）与自定义技能（名称与自定义ID）"""
    if not isinstance(item, dict):
        return {"std_ids": set(), "std_names": set(), "custom_names": set(), "custom_ids": set()}
    
    std_ids = set()
    std_names = set()
    custom_names = set()
    custom_ids = set()

    # 1. 从 skillTagList 结构提取
    raw_list = item.get("skillTagList")
    if isinstance(raw_list, list):
        for s in raw_list:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name") or s.get("tagValue") or "").strip()
            sid = str(s.get("skillId") or s.get("id") or "").strip()
            is_custom = bool(s.get("customize") or s.get("isCustom") or (sid.isdigit() and len(sid) >= 12))
            if is_custom:
                if name:
                    custom_names.add(name)
                if sid:
                    custom_ids.add(sid)
            else:
                if sid:
                    std_ids.add(sid)
                if name:
                    std_names.add(name)

    # 2. 从 skillTagCustomized 提取自定义名称
    raw_custom = str(item.get("skillTagCustomized") or "").strip()
    if raw_custom:
        for c in raw_custom.split(","):
            if c.strip():
                custom_names.add(c.strip())

    # 3. 从 skillTagStandard 提取标准 ID（过滤掉时间戳长度的自定义ID）
    raw_std = str(item.get("skillTagStandard") or "").strip()
    if raw_std:
        for c in raw_std.split(","):
            c = c.strip()
            if not c:
                continue
            if c.isdigit() and len(c) >= 12:
                custom_ids.add(c)
            else:
                std_ids.add(c)

    # 4. 从 skillTags 提取
    raw_tags = item.get("skillTags")
    if isinstance(raw_tags, str) and raw_tags.strip().startswith("["):
        try:
            arr = json.loads(raw_tags)
            if isinstance(arr, list):
                for s in arr:
                    if not isinstance(s, dict):
                        continue
                    name = str(s.get("tagValue") or s.get("name") or "").strip()
                    sid = str(s.get("intKey") or s.get("strKey") or s.get("skillId") or "").strip()
                    is_std = bool(s.get("standard"))
                    if is_std and sid and not (sid.isdigit() and len(sid) >= 12):
                        std_ids.add(sid)
                        if name:
                            std_names.add(name)
                    else:
                        if name:
                            custom_names.add(name)
                        if sid:
                            custom_ids.add(sid)
        except Exception:
            pass

    # 5. 从 preferenceQuestionAndAnswer 提取
    raw_qa = item.get("preferenceQuestionAndAnswer")
    if isinstance(raw_qa, str) and raw_qa.strip().startswith("["):
        try:
            arr = json.loads(raw_qa)
            if isinstance(arr, list):
                for q in arr:
                    if not isinstance(q, dict):
                        continue
                    qid = str(q.get("id") or "").strip()
                    pid = str(q.get("pathId") if q.get("pathId") is not None else "")
                    if pid == "-1" or (qid.isdigit() and len(qid) >= 12):
                        if qid:
                            custom_ids.add(qid)
                    elif qid:
                        std_ids.add(qid)
        except Exception:
            pass

    # 6. 从 skillTagsTranslation 提取名称（如果尚未获取）
    raw_trans = str(item.get("skillTagsTranslation") or "").strip()
    if raw_trans:
        for t in raw_trans.split(","):
            t = t.strip()
            if not t:
                continue
            if t not in custom_names:
                std_names.add(t)

    # 净化：将已明确为自定义的 ID 从 std_ids 剔除（智联官网会将自定义 ID 写入 skillTagStandard）
    std_ids = std_ids - custom_ids
    # 净化：将已明确为自定义的名称从 std_names 剔除（不区分大小写）
    custom_names_lower = {n.lower().strip() for n in custom_names}
    std_names = {n for n in std_names if n.lower().strip() not in custom_names_lower}

    return {
        "std_ids": std_ids,
        "std_names": std_names,
        "custom_names": custom_names,
        "custom_ids": custom_ids,
    }


ZHILIAN_KNOWN_SKILL_IDS = {
    "openai": 460744714,
    "fastapi": 435537990,
    "next.js": 300707521,
    "langgraph": 476460067,
    "cursor": 478605317,
    "claude": 466780584,
    "rpa": 300009259,
    "pytorch": 19297139,
    "docker": 270060182,
    "kubernetes": 270070040,
    "redis": 270063390,
    "typescript": 270064998,
    "vue.js": 270064989,
    "vue": 270064989,
    "react": 19297079,
    "tailwind css": 418441788,
    "tailwind": 418441788,
    "智能客服训练": 270072837,
    "电商类ai训练": 270072841,
    "店小蜜": 300283426,
    "自动化测试": 270060622,
    "品质督查": 300283428,
}


def _work_skills_same(local_item, off_item):
    """判定本地工作经历技能与官网工作经历技能是否一致。
    容忍智联官网对自定义技能的处理特性（官网会将自定义技能在云端识别并转为标准词典ID或标准技能，
    导致本地标记为自定义的技能在官网保存后转为标准技能）。
    核心准则：全量技能名称集合（无论标准或自定义）一致即视为一致。"""
    loc = _extract_work_skills(local_item)
    off = _extract_work_skills(off_item)

    loc_all_names = {n.lower().strip() for n in (loc["std_names"] | loc["custom_names"]) if n.strip()}
    off_all_names = {n.lower().strip() for n in (off["std_names"] | off["custom_names"]) if n.strip()}

    if not loc_all_names and not loc["std_ids"] and not loc["custom_ids"]:
        # 本地未定义技能，沿用官网
        return True

    # 1. 全量技能名称集合无序比对（不区分大小写）
    if loc_all_names and off_all_names:
        if loc_all_names == off_all_names:
            return True

    # 2. 如果官网只返回了 ID（例如未解析出名称），比对标准 ID 集合
    if loc["std_ids"] and off["std_ids"] and (loc["std_ids"] == off["std_ids"]):
        return True

    # 3. 详细分项比对兜底
    loc_std_names_lower = {n.lower().strip() for n in loc["std_names"]}
    off_std_names_lower = {n.lower().strip() for n in off["std_names"]}
    loc_custom_names_lower = {n.lower().strip() for n in loc["custom_names"]}
    off_custom_names_lower = {n.lower().strip() for n in off["custom_names"]}

    std_match = (loc["std_ids"] == off["std_ids"]) or (loc_std_names_lower == off_std_names_lower)
    if std_match:
        if not loc_custom_names_lower and not off_custom_names_lower:
            return True
        if loc_custom_names_lower and (loc_custom_names_lower == off_custom_names_lower or len(loc_custom_names_lower) == len(off["custom_ids"])):
            return True

    return False


def _item_val(item, k):
    """获取字段值，支持别名容错"""
    if not item or not isinstance(item, dict):
        return None
    v = item.get(k)
    if v is not None and v != "":
        return v
    ALIASES = {
        "trainAgency": ["trainName", "trainOrgName"],
        "trainCourse": ["trainCertName"],
        "proExpProjectName": ["projectName", "name"],
        "companyName": ["workCorpName"],
        "eduSchoolName": ["schoolName"],
        "certUserdefName": ["certificationName", "name", "certName", "title"],
        "certificateId": ["certificationType", "certType", "code"],
    }
    for alt in ALIASES.get(k, []):
        alt_v = item.get(alt)
        if alt_v is not None and alt_v != "":
            return alt_v
    return v


def _cert_name(c):
    """安全提取证书名称"""
    if isinstance(c, dict):
        return _norm(_item_val(c, "certUserdefName") or "")
    return _norm(str(c)) if c else ""


def _cert_id(c):
    """安全提取证书类型ID"""
    if isinstance(c, dict):
        return _norm(_item_val(c, "certificateId") or "")
    return ""


def _items_same(local_item, off_item, keys):
    """业务键一致性：日期（含 *DateFormat）按月归一，本地空/垃圾值不判异；
    首键（名称）容忍包含匹配（LLM 截短公司名），本地空不判异；
    文本键容忍官网 XSS 过滤（'<'/'>' 被剔除）；码值 vs 文本不判异。
    本地值为空一律视为「沿用官网」——build_values 本来就不覆盖空值。"""
    for i, k in enumerate(keys):
        lv, ov = _item_val(local_item, k), _item_val(off_item, k)
        if _is_date_key(k):
            lm = _norm_month(lv)
            om = _norm_month(ov)
            # 结束时间「至今」与具体月份差异必须判异：一方为至今而另一方为具体月份时不可判定为一致
            if "end" in k.lower():
                lv_is_pres = (lv in (0, "0", 0.0) or not lv or "至今" in str(lv) or str(local_item.get("proExpIsCurrent")).lower() in ("true", "1"))
                ov_is_pres = (ov in (0, "0", 0.0) or not ov or "至今" in str(ov) or str(off_item.get("proExpIsCurrent")).lower() in ("true", "1") or str(ov).startswith("1970"))
                if lv_is_pres != ov_is_pres:
                    return False
                if lv_is_pres and ov_is_pres:
                    continue
            if not lm:
                continue  # 本地起始日期缺失/垃圾模板 → 沿用官网，不判异
            if lm != om:
                return False
        elif k in ("skillTagStandard", "skillTagsTranslation", "skillTags"):
            if not _work_skills_same(local_item, off_item):
                return False
        elif k == "pnewPreferredIndustry":
            def _ind_set(val):
                if val in (None, "", "-1", "-99", -1, -99):
                    return set()
                if isinstance(val, list):
                    return {str(c).strip() for c in val if str(c).strip() and str(c).strip() not in ("-1", "-99")}
                s = str(val).strip()
                return {c.strip() for c in s.split(",") if c.strip() and c.strip() not in ("-1", "-99")}
            if _ind_set(lv) != _ind_set(ov):
                return False
        elif k == "eduFullTime":
            def _norm_ft(val):
                if val in ("y", "统招", True, 1, "1"):
                    return "y"
                if val in ("n", "非统招", False, 0, "0", "2"):
                    return "n"
                return "y" if str(val).strip() else ""
            if _norm_ft(lv) and _norm_ft(ov) and _norm_ft(lv) != _norm_ft(ov):
                return False
        elif k == "eduOverseaseExperience":
            def _norm_os(val):
                if val in ("1", "y", "有", True, 1):
                    return "1"
                if val in ("2", "n", "无", False, 0, "0", "2", ""):
                    return "2"
                return "2"
            if _norm_os(lv) != _norm_os(ov):
                return False
        elif k == "degreeCertificate":
            def _norm_dc(val):
                if val in ("1", "有", True, 1):
                    return "1"
                if val in ("2", "无", False, 0, "0", "2", ""):
                    return "2"
                return "1"
            if _norm_dc(lv) != _norm_dc(ov):
                return False
        elif k == "eduBackground":
            EDU_DEGREE_MAP = {
                "博士": "1", "MBA": "2", "EMBA": "2", "硕士": "3", "研究生": "3",
                "本科": "4", "大专": "5", "专科": "5", "中专": "6", "中技": "7",
                "高中": "8", "初中": "9", "初中及以下": "9"
            }
            bg_l = EDU_DEGREE_MAP.get(str(lv).strip(), str(lv).strip())
            bg_o = EDU_DEGREE_MAP.get(str(ov).strip(), str(ov).strip())
            if bg_l and bg_o and bg_l != bg_o:
                return False
        elif k == "proskillUseTime":
            # 智联专业技能使用时长（月数）：纯数字比对，"5" 与 "5年" 必须判异以触发回写修正官网 NaN月
            raw_l = re.sub(r"[^\d]", "", str(lv or "").strip())
            raw_o = re.sub(r"[^\d]", "", str(ov or "").strip())
            if raw_l and (str(ov or "").strip() != raw_o or raw_l != raw_o):
                return False
        elif i == 0:
            if _norm(lv) and not (_norm(lv) == _norm(ov) or _name_hit(lv, ov)):
                return False
        else:
            a, b = _norm(lv), _norm(ov)
            if not a:
                continue
            if b and a.isdigit() != b.isdigit():
                continue  # 码值/文本形态差异不判异
            # 官网字数上限截断保护（工作描述 3000字截断，项目描述/职责 2000字截断，自我评价 500字截断）
            if k in ("proExpProjectDuty", "proExpProjectDesc"):
                if _xss_norm(a[:2000]) != _xss_norm(b[:2000]):
                    return False
            elif k == "workDesc":
                if _xss_norm(a[:3000]) != _xss_norm(b[:3000]):
                    return False
            elif _xss_norm(a) != _xss_norm(b):
                return False
    return True


def _norm_month(v):
    """日期归一为 'YYYY-MM'；'至今'/0/1970 占位/格式模板垃圾值（如 'yyyy-MM'）→ ''。"""
    if v in (None, "", 0):
        return ""
    if isinstance(v, (int, float)):
        if v <= 0:
            return ""
        import datetime
        return datetime.datetime.fromtimestamp(v / 1000).strftime("%Y-%m")
    s = str(v).strip()
    if s.isdigit() and len(s) >= 10:
        # 官网日期以毫秒时间戳字符串存储（如 '1561910400000'）
        import datetime
        return datetime.datetime.fromtimestamp(int(s) / 1000).strftime("%Y-%m")
    if "至今" in s or s.startswith("1970"):
        return ""
    if "yyyy" in s.lower():
        return ""
    s = s.replace(".", "-").replace("/", "-")
    if len(s) >= 7 and s[4] == "-" and s[:4].isdigit():
        return s[:7]
    return ""


def _month_ms(m):
    import datetime
    return int(datetime.datetime(int(m[:4]), int(m[5:7]), 1).timestamp() * 1000)


def _month_fmt(m):
    return f"{m[:4]}/{m[5:7]}/01 00:00:00"


def _name_hit(a, b):
    """名称命中：精确或包含（LLM 可能截短公司名，如 '某美妆集团' ⊂ 官网全称）。

    比对前剔除全部空白——官网会自动在中英文之间插入空格（如 'AI驱动的' 存为
    'AI 驱动的'），不剔除会把刚写成功的内容误判为「未找到匹配条目」。
    """
    a = "".join(_norm(a).split())
    b = "".join(_norm(b).split())
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _match_official(item, off_items, used_paths, cfg):
    """加权配对（借鉴 51job 经验）：名称键权重 3 且必须命中才认可；
    名称缺失/未命中时仅当起始月在未占用官网条目中唯一才配对，
    防止同时间不同条目互串（51job 真实事故教训）。"""
    keys = cfg["keys"]
    name_key = keys[0]
    st_key = next((k for k in keys if "start" in k.lower() and _is_date_key(k)), None)
    en_key = next((k for k in keys if "end" in k.lower() and _is_date_key(k)), None)
    best, best_score = None, 0
    for o in off_items:
        if o.get("path") in used_paths:
            continue
        score, named = 0, False
        if _name_hit(_item_val(item, name_key), _item_val(o, name_key)):
            score += 3
            named = True
        # 课程/职务副键加分
        if len(keys) > 1 and keys[1] in ("trainCourse", "proExpPosition"):
            if _name_hit(_item_val(item, keys[1]), _item_val(o, keys[1])):
                score += 2
        ls = _norm_month(_item_val(item, st_key)) if st_key else ""
        if ls and ls == _norm_month(_item_val(o, st_key)):
            score += 2
        le = _norm_month(_item_val(item, en_key)) if en_key else ""
        if le and le == _norm_month(_item_val(o, en_key)):
            score += 1
        if named and score > best_score:
            best, best_score = o, score
    if best is not None:
        return best
    if st_key:
        ls = _norm_month(_item_val(item, st_key))
        if ls:
            cands = [o for o in off_items
                     if o.get("path") not in used_paths and _norm_month(_item_val(o, st_key)) == ls]
            if len(cands) == 1:
                return cands[0]
    return None


def _fix_dates(merged):
    """日期对（*Date 毫秒 + *DateFormat 格式串）按月份重算，保证两者一致；
    '至今' → 0 + 1970 占位（官网组件约定）。垃圾模板值（'yyyy-MM'）被 _norm_month 过滤。"""
    for dk in [k for k in list(merged) if k.endswith("Date") and not k.endswith("DateFormat")]:
        fk = dk + "Format"
        raw = merged.get(dk)
        if isinstance(raw, str) and "至今" in raw:
            merged[dk] = 0
            merged[fk] = _ZH_EPOCH_FMT
            continue
        if raw in (None, ""):
            # 结束日期空缺 = 至今（官网约定 0 + 1970 占位）；起始日期空缺不动
            if dk.lower().endswith("enddate"):
                merged[dk] = 0
                merged[fk] = _ZH_EPOCH_FMT
            continue
        m = _norm_month(raw) or _norm_month(merged.get(fk))
        if not m:
            continue
        merged[dk] = _month_ms(m)
        merged[fk] = _month_fmt(m)
    return merged


def _match_key_of(item, keys):
    """业务键指纹（用于执行时重新定位目标条目）"""
    return {k: _norm(item.get(k)) for k in keys}


# ---- values 构造（edit 时先合并官网条目保留 serial/id，再按官网组件字段 pick） ----

def _pick_values(merged, pick):
    out = {}
    for k in pick:
        if k in merged and merged[k] is not None:
            out[k] = merged[k]
        elif k == "path":
            out[k] = None
    return out


def _build_lang_values(local_item, official_item):
    """LanguageSkill values：langCertificates 需 [{certificateId,...}] 列表"""
    merged = dict(official_item or {})
    merged.update({k: v for k, v in local_item.items() if v not in (None, "")})
    certs = merged.get("langCertificatesFormat") or local_item.get("certificates") or []
    if not isinstance(certs, list):
        certs = []
    cert_list = []
    for c in certs:
        if isinstance(c, dict) and c.get("certificateId"):
            cert_list.append({"certificateId": c.get("certificateId"),
                              "certificateName": c.get("certificateName", ""),
                              "certificateScore": c.get("certificateScore", "")})
    return {"path": merged.get("path"),
            "langLanguageT": merged.get("langLanguageT", ""),
            "langRWProficiency": merged.get("langRWProficiency", ""),
            "langLSProficiency": merged.get("langLSProficiency", ""),
            "langCertificates": cert_list}


def _build_skill_values(local_item, official_item):
    merged = dict(official_item or {})
    merged.update({k: v for k, v in local_item.items() if v not in (None, "")})
    raw_time = str(merged.get("proskillUseTime") or "").strip()
    clean_time = re.sub(r"[^\d]", "", raw_time) if raw_time else ""
    return {"eduFullTime": "-1",
            "proskillName": merged.get("proskillName", ""),
            "proskillLevel": merged.get("proskillLevel") or "熟练",
            "proskillType": merged.get("proskillType") or 13,
            "proskillUseTime": clean_time,
            "path": merged.get("path")}


def _build_wanna_values(local_item, official_item):
    merged = dict(official_item or {})
    merged.update({k: v for k, v in local_item.items() if v not in (None, "")})

    # 处理行业字段（支持列表、逗号分隔串或 preferredIndustrySerialList）
    raw_ind = local_item.get("pnewPreferredIndustry")
    serial_list = local_item.get("preferredIndustrySerialList")

    codes = []
    if isinstance(raw_ind, list):
        codes = [str(c).strip() for c in raw_ind if str(c).strip() and str(c).strip() not in ("-1", "-99")]
    elif isinstance(raw_ind, str) and raw_ind.strip() and raw_ind.strip() not in ("-1", "-99"):
        codes = [c.strip() for c in raw_ind.split(",") if c.strip() and c.strip() not in ("-1", "-99")]
    elif isinstance(serial_list, list) and serial_list:
        codes = [str(x.get("code")).strip() for x in serial_list if isinstance(x, dict) and str(x.get("code")).strip() not in ("-1", "-99", "None", "")]

    if codes:
        industry_unlimited = False
        pnew_industry = ",".join(codes)
        ind_serial_list = [{"code": c, "serial": ""} for c in codes]
    else:
        industry_unlimited = True
        pnew_industry = "-99"
        ind_serial_list = [{"code": "-99", "serial": ""}]

    return {
        "path": merged.get("path"),
        "preferredJobNature": str(merged.get("preferredJobNature") or "2"),
        "pnewPreferredJobType": str(merged.get("pnewPreferredJobType") or ""),
        "preferredJobTypeSerial": str(merged.get("preferredJobTypeSerial") or ""),
        "preferredLocation": str(merged.get("preferredLocation") or ""),
        "preferredCityDistrict": str(merged.get("preferredCityDistrict") or ""),
        "preferredSalaryMin": int(merged.get("preferredSalaryMin") or 0) if str(merged.get("preferredSalaryMin") or "").isdigit() else merged.get("preferredSalaryMin"),
        "preferredSalaryMax": int(merged.get("preferredSalaryMax") or 0) if str(merged.get("preferredSalaryMax") or "").isdigit() else merged.get("preferredSalaryMax"),
        "pnewPreferredIndustry": pnew_industry,
        "preferredIndustrySerial": json.dumps(ind_serial_list, ensure_ascii=False),
        "preferredIndustrySerialList": ind_serial_list,
        "industryUnlimited": industry_unlimited,
        "industryState": "1",
        "preferenceQuestionAndAnswer": merged.get("preferenceQuestionAndAnswer") or "",
    }


def _build_work_values(local_item, official_item):
    """构建工作经历回写 values：
    - 日期、公司、职位、描述、薪资等基础字段沿用/覆盖并经过 _fix_dates 重算；
    - 拥有技能全套字段（preferenceQuestionAndAnswer / skillTags / skillTagList / skillTagStandard /
      skillTagCustomized / skillTagsTranslation）做闭环序列化，避免沿用官网旧技能。
    """
    merged = dict(official_item or {})
    # 官网打底：本地空值不覆盖；日期垃圾值由 _fix_dates 统一重算
    for k, v in local_item.items():
        if v in (None, ""):
            continue
        ov = (official_item or {}).get(k)
        if isinstance(v, bool):
            if k == "internshipWork":
                if ov in ("1", "2"):
                    continue
                v = "1" if v else "2"
            else:
                v = "true" if v else "false"
        if isinstance(ov, str) and ov.isdigit() and not str(v).isdigit():
            continue
        merged[k] = v

    # 拥有技能深度同步与清洗
    skill_list = local_item.get("skillTagList")
    if skill_list is None and isinstance(local_item.get("skillTags"), str) and local_item.get("skillTags").strip().startswith("["):
        try:
            raw_tags = json.loads(local_item.get("skillTags"))
            skill_list = [{
                "skillId": str(s.get("intKey") or s.get("strKey") or ""),
                "name": s.get("tagValue") or s.get("name") or "",
                "customize": not s.get("standard", True),
                "skillParentId": str(s.get("pathId") if s.get("pathId") is not None else -1)
            } for s in raw_tags if isinstance(s, dict)]
        except Exception:
            pass

    if skill_list is not None and isinstance(skill_list, list):
        std_ids = []
        custom_names = []
        pref_qa = []
        tags = []
        tag_list = []
        names = []
        for s in skill_list:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("skillId") or s.get("id") or "").strip()
            name = str(s.get("name") or s.get("tagValue") or "").strip()
            is_custom = bool(s.get("customize") or s.get("isCustom"))
            raw_pid = s.get("skillParentId") if s.get("skillParentId") is not None else s.get("pathId")
            try:
                pid_int = int(raw_pid) if raw_pid not in (None, "") else -1
            except (ValueError, TypeError):
                pid_int = -1
            try:
                sid_int = int(sid) if sid else 0
            except (ValueError, TypeError):
                sid_int = 0

            if is_custom:
                known_id = ZHILIAN_KNOWN_SKILL_IDS.get(name.lower().strip())
                if known_id:
                    sid_int = known_id
                    sid = str(sid_int)
                elif sid_int > 2147483647 or sid_int <= 0 or len(str(sid_int)) > 9:
                    # 兼容旧时间戳/缺失ID：规范化映射为 9 位整型（300000000~389999999），避免 SQL 溢出
                    sid_int = 300000000 + (abs(hash(name)) % 90000000)
                    sid = str(sid_int)

            if not name:
                continue
            names.append(name)
            if is_custom:
                custom_names.append(name)
            elif sid:
                std_ids.append(sid)

            pref_qa.append({"id": sid_int, "pathId": pid_int})
            tags.append({
                "intKey": sid_int,
                "standard": not is_custom,
                "strKey": sid or str(sid_int),
                "tagValue": name,
            })
            tag_list.append({
                "customize": is_custom,
                "name": name,
                "skillId": sid,
                "skillParentId": str(pid_int) if pid_int != -1 else "",
            })

        # 官网官方协议：当存在问答/自定义技能列表时，skillTagStandard 与 skillTagCustomized 置为 -1，
        # 全部技能项由 preferenceQuestionAndAnswer 统一部署（自定义项挂载 pathId: -1）
        if pref_qa:
            merged["skillTagStandard"] = -1
            merged["skillTagCustomized"] = -1
            merged["preferenceQuestionAndAnswer"] = json.dumps(pref_qa, ensure_ascii=False)
        else:
            merged["skillTagStandard"] = ",".join(std_ids) if std_ids else -1
            merged["skillTagCustomized"] = -1
            merged["preferenceQuestionAndAnswer"] = "[]"
        merged["skillTags"] = json.dumps(tags, ensure_ascii=False)
        merged["skillTagList"] = tag_list
        merged["skillTagsTranslation"] = ",".join(names)
    elif "skillTagsTranslation" in local_item and not local_item.get("skillTagsTranslation"):
        merged["skillTagStandard"] = -1
        merged["skillTagCustomized"] = -1
        merged["preferenceQuestionAndAnswer"] = "[]"
        merged["skillTags"] = "[]"
        merged["skillTagList"] = []
        merged["skillTagsTranslation"] = ""

    return _pick_values(_fix_dates(merged), NODE_CFG["work_experience"]["pick"])


def _build_education_values(local_item, official_item):
    """构建教育经历回写 values：
    - eduFullTime 统招/非统招严格映射为 'y'/'n'；
    - eduOverseaseExperience 海外经历映射为 '1'/'2'；
    - degreeCertificate 学位证映射为 '1'/'2'；
    - eduBackground 学历映射为智联标准码值 ('1' 博士, '3' 硕士, '4' 本科, '5' 大专等)；
    - 日期由 _fix_dates 统一重算为 YYYY/MM/01 00:00:00。
    """
    merged = dict(official_item or {})
    for k, v in (local_item or {}).items():
        if v not in (None, ""):
            merged[k] = v

    # 1. 统招/非统招归一化（官网严格接收 'y' 或 'n'）
    ft = (local_item or {}).get("eduFullTime")
    if ft is None and official_item:
        ft = official_item.get("eduFullTime")
    if ft in ("y", "统招", True, 1, "1"):
        merged["eduFullTime"] = "y"
    elif ft in ("n", "非统招", False, 0, "0", "2"):
        merged["eduFullTime"] = "n"
    else:
        merged["eduFullTime"] = "y"

    # 2. 学历代码归一化（支持 硕士 -> '3', 本科 -> '4' 等）
    EDU_DEGREE_MAP = {
        "博士": "1", "MBA": "2", "EMBA": "2", "硕士": "3", "研究生": "3",
        "本科": "4", "大专": "5", "专科": "5", "中专": "6", "中技": "7",
        "高中": "8", "初中": "9", "初中及以下": "9"
    }
    bg = str((local_item or {}).get("eduBackground") or (official_item or {}).get("eduBackground") or "4").strip()
    merged["eduBackground"] = EDU_DEGREE_MAP.get(bg, bg)

    # 3. 海外经历归一化（'1' 有, '2' 无）
    os_exp = (local_item or {}).get("eduOverseaseExperience")
    if os_exp is None and official_item:
        os_exp = official_item.get("eduOverseaseExperience")
    if os_exp in ("1", "y", "有", True, 1):
        merged["eduOverseaseExperience"] = "1"
    else:
        merged["eduOverseaseExperience"] = "2"

    # 4. 学位证归一化（'1' 有, '2' 无）
    dc = (local_item or {}).get("degreeCertificate")
    if dc is None and official_item:
        dc = official_item.get("degreeCertificate")
    if dc in ("1", "有", True, 1):
        merged["degreeCertificate"] = "1"
    elif dc in ("2", "无", False, 0, "0"):
        merged["degreeCertificate"] = "2"
    else:
        merged["degreeCertificate"] = "1"

    # 5. 学校 ID 与 专业分类默认打底
    if not merged.get("newEduSchoolId"):
        merged["newEduSchoolId"] = str((official_item or {}).get("newEduSchoolId") or "501")
    if not merged.get("newEduMajorSmallType"):
        merged["newEduMajorSmallType"] = str((official_item or {}).get("newEduMajorSmallType") or "783")

    return _pick_values(_fix_dates(merged), NODE_CFG["education"]["pick"])


def _build_project_values(local_item, official_item):
    """构建项目经历回写 values：
    - proExpIsCurrent / proExpEndDate / proExpEndDateFormat 精准对齐「至今」状态：
      当 local_item 指定至今（proExpEndDate==0 或 '至今' 或 proExpIsCurrent=='true'）时，
      严格重置 proExpEndDate=0, proExpEndDateFormat='1970/01/01 08:00:00', proExpIsCurrent='true'，
      绝不沿用官网旧的结束日期！
    - proExpProjectName / proExpProjectDesc / proExpPosition / proExpProjectDuty 覆盖并做字数保护；
    - proExpDevTool / proExpSoftwareEnv / affiliatedCompany / proExpIsIt 完整保留并规范化。
    """
    merged = dict(official_item or {})
    for k, v in (local_item or {}).items():
        if v not in (None, ""):
            merged[k] = v

    # 1. 判断是否为「至今」
    is_to_present = False
    raw_end = (local_item or {}).get("proExpEndDate")
    raw_end_fmt = (local_item or {}).get("proExpEndDateFormat")
    raw_cur = (local_item or {}).get("proExpIsCurrent")

    if raw_cur in (True, "true", 1, "1") or (isinstance(raw_end, str) and "至今" in raw_end) or (isinstance(raw_end_fmt, str) and "至今" in raw_end_fmt):
        is_to_present = True
    elif raw_end in (0, "0", 0.0):
        is_to_present = True
    elif "proExpEndDateFormat" in (local_item or {}) and raw_end_fmt in (None, "", _ZH_EPOCH_FMT):
        is_to_present = True

    if is_to_present:
        merged["proExpIsCurrent"] = "true"
        merged["proExpEndDate"] = 0
        merged["proExpEndDateFormat"] = _ZH_EPOCH_FMT
    else:
        merged["proExpIsCurrent"] = "false"
        if raw_end not in (None, "", 0, "0"):
            merged["proExpEndDate"] = raw_end
        if raw_end_fmt not in (None, "", _ZH_EPOCH_FMT):
            merged["proExpEndDateFormat"] = raw_end_fmt
        if not merged.get("proExpEndDate") or merged.get("proExpEndDate") == 0:
            merged["proExpEndDate"] = merged.get("proExpStartDate") or 0
            merged["proExpEndDateFormat"] = merged.get("proExpStartDateFormat") or ""

    # 2. IT 标识与其他布尔值归一
    is_it = (local_item or {}).get("proExpIsIt")
    if is_it is not None:
        merged["proExpIsIt"] = "true" if is_it in (True, "true", 1, "1") else "false"
    elif "proExpIsIt" not in merged:
        merged["proExpIsIt"] = "true"

    # 3. 描述与名称字数截断与修剪保护
    if "proExpProjectDesc" in local_item:
        merged["proExpProjectDesc"] = str(local_item.get("proExpProjectDesc") or "").strip()[:2000]
    if "proExpProjectName" in local_item:
        merged["proExpProjectName"] = str(local_item.get("proExpProjectName") or "").strip()[:100]
    if "proExpProjectDuty" in local_item:
        merged["proExpProjectDuty"] = str(local_item.get("proExpProjectDuty") or "").strip()[:2000]
    if "proExpPosition" in local_item:
        merged["proExpPosition"] = str(local_item.get("proExpPosition") or "").strip()[:100]

    return _pick_values(_fix_dates(merged), NODE_CFG["projects"]["pick"])


def _build_training_values(local_item, official_item):
    """构建培训经历回写 values：
    - trainAgency / trainName / trainOrgName 归一化为 trainAgency；
    - trainCourse / trainCertName 归一化为 trainCourse；
    - trainStartDate / trainStartDateFormat 格式化；
    - trainEndDate / trainEndDateFormat 对齐「至今」（0 / 1970 占位）与具体月份；
    - trainDesc / trainCertificate / trainAddress 完整保留。
    """
    merged = dict(official_item or {})
    for k, v in (local_item or {}).items():
        if v not in (None, ""):
            merged[k] = v

    # 1. 机构名称归一化
    agency = _item_val(local_item, "trainAgency") or _item_val(official_item, "trainAgency")
    if agency:
        merged["trainAgency"] = str(agency).strip()

    # 2. 课程名称归一化
    course = _item_val(local_item, "trainCourse") or _item_val(official_item, "trainCourse")
    if course:
        merged["trainCourse"] = str(course).strip()

    # 3. 「至今」状态判定与时间重算
    is_to_present = False
    raw_end = (local_item or {}).get("trainEndDate")
    raw_end_fmt = (local_item or {}).get("trainEndDateFormat")
    if raw_end in (0, "0", 0.0) or (isinstance(raw_end, str) and "至今" in raw_end):
        is_to_present = True
    elif "trainEndDateFormat" in (local_item or {}) and (raw_end_fmt in (None, "", _ZH_EPOCH_FMT) or "至今" in str(raw_end_fmt)):
        is_to_present = True
    elif raw_end in (None, "") and "trainEndDate" in (local_item or {}):
        is_to_present = True

    if is_to_present:
        merged["trainEndDate"] = 0
        merged["trainEndDateFormat"] = _ZH_EPOCH_FMT
    else:
        if raw_end not in (None, ""):
            merged["trainEndDate"] = raw_end
        if raw_end_fmt not in (None, ""):
            merged["trainEndDateFormat"] = raw_end_fmt

    # 4. 可选字段兜底
    for opt_k in ("trainDesc", "trainCertificate", "trainAddress"):
        if opt_k not in merged:
            merged[opt_k] = str((local_item or {}).get(opt_k) or (official_item or {}).get(opt_k) or "")

    return _pick_values(_fix_dates(merged), NODE_CFG["training"]["pick"])


def build_values(mod, local_item, official_item):
    cfg = NODE_CFG[mod]
    if mod == "work_experience":
        return _build_work_values(local_item, official_item)
    if mod == "education":
        return _build_education_values(local_item, official_item)
    if mod == "projects":
        return _build_project_values(local_item, official_item)
    if mod == "training":
        return _build_training_values(local_item, official_item)
    if mod == "language":
        return _build_lang_values(local_item, official_item)
    if mod == "skill_tags":
        return _build_skill_values(local_item, official_item)
    if mod == "wanna":
        return _build_wanna_values(local_item, official_item)
    merged = dict(official_item or {})
    # 官网打底：本地空值不覆盖；日期垃圾值由 _fix_dates 统一重算
    for k, v in local_item.items():
        if v in (None, ""):
            continue
        ov = (official_item or {}).get(k)
        # 布尔归一（LLM 常输出 true/false）：官网布尔字段存 'true'/'false' 字符串；
        # internshipWork 例外，用 '1'/'2' 码
        if isinstance(v, bool):
            if k == "internshipWork":
                if ov in ("1", "2"):
                    continue  # 用户官网显式选择优先于 LLM 推断
                v = "1" if v else "2"
            else:
                v = "true" if v else "false"
        # 码值保护（借鉴 51job 经验）：官网纯数字码值不被本地文本覆盖，否则诊断不通过
        if isinstance(ov, str) and ov.isdigit() and not str(v).isdigit():
            continue
        merged[k] = v
    return _pick_values(_fix_dates(merged), cfg["pick"])


# ============================================================
# 计划构建（纯函数）
# ============================================================

def plan_writeback(local, official, selected_modules=None):
    """构建回写计划。official 为官网 currentResume 快照（键=Vuex 节点名）。
    返回 {actions, skipped}"""
    modules = selected_modules if selected_modules else ALL_MODULES
    actions, skipped = [], []

    # ---- 基本信息（Profile 节点：覆盖开放修改字段，锁定/安全字段保留官网原值） ----
    if "basic_info" in modules:
        local_bi = _val(local, "basic_info") or {}
        off_profile = official.get("Profile") or [{}]
        off_p = off_profile[0] if off_profile else {}

        # 国外 (isOverseas / foreign / 480) 状态统一映射
        is_foreign = bool(local_bi.get("isOverseas") is True or str(local_bi.get("isOverseas")) in ("1", "true") or
                          local_bi.get("foreign") is True or str(local_bi.get("foreign")) in ("1", "true") or
                          str(local_bi.get("currentProvince")) == "480" or str(local_bi.get("currentCity")) == "480")
        if is_foreign:
            local_bi["currentProvince"] = "480"
            local_bi["currentCity"] = "480"
            local_bi["currentCityDistrictId"] = "0"
            local_bi["foreign"] = True

        editable_keys = [
            ("name", "姓名"),
            ("gender", "性别"),
            ("currentIdentity", "当前身份"),
            ("birthyear", "出生年份"),
            ("birthmonth", "出生月份"),
            ("yearStartWorking", "参加工作年份"),
            ("monthStartWorking", "参加工作月份"),
            ("hukouProvinceId", "户口省份"),
            ("hukouCityId", "户口城市"),
            ("currentProvince", "现居住省份"),
            ("currentCity", "现居住城市"),
            ("currentCityDistrictId", "现居住区县"),
            ("politicalAffiliation", "政治面貌"),
            ("maritalStatus", "婚姻状况"),
        ]

        diffs = []
        for k, label in editable_keys:
            lv = _norm(local_bi.get(k))
            ov = _norm(off_p.get(k))
            if lv and lv != ov:
                diffs.append(f"{label}: {ov}→{lv}")

        if not diffs:
            skipped.append({"module": "basic_info", "reason": "与官网一致，无需回写"})
        else:
            profile_values = dict(off_p)
            for k, _ in editable_keys:
                lv = local_bi.get(k)
                if lv not in (None, ""):
                    if k in ("gender", "yearStartWorking", "monthStartWorking") and str(lv).isdigit():
                        profile_values[k] = int(lv)
                    else:
                        profile_values[k] = str(lv)

            if is_foreign:
                profile_values["currentProvince"] = "480"
                profile_values["currentCity"] = "480"
                profile_values["currentCityDistrictId"] = "0"
                profile_values["foreign"] = True
            else:
                profile_values["foreign"] = False

            profile_values["path"] = off_p.get("path") or "Profile[0]"

            actions.append({
                "module": "basic_info",
                "op": "edit",
                "node": "Profile",
                "values": profile_values,
                "matchKeys": {},
                "hintPath": off_p.get("path") or "Profile[0]",
                "detail": f"基本信息 edit（{', '.join(diffs)}）",
            })

    # ---- 求职状态 ----
    if "job_status" in modules:
        local_js = _val(local, "job_status")
        off_profile = official.get("Profile") or [{}]
        off_p = off_profile[0] if off_profile else {}

        target_code = None
        target_label = ""
        if isinstance(local_js, dict):
            target_code = local_js.get("jobStateCode") or local_js.get("currentStatus") or local_js.get("code")
            target_label = local_js.get("jobState") or local_js.get("label") or ""
        elif local_js is not None:
            target_code = str(local_js).strip()

        STATUS_MAP = {
            "离职-正在找工作": "1", "我目前处于离职状态，可立即上岗": "1", "正在找工作": "1",
            "在职-急寻新工作": "2", "我目前在职，正考虑换个新环境": "2",
            "在职-正在找工作": "3", "我对现有工作还算满意，如有更好的工作机会，我也可以考虑": "3",
            "在职-暂不考虑": "4", "目前暂无跳槽打算": "4",
            "应届毕业生": "5",
        }
        if str(target_code) in STATUS_MAP:
            target_code = STATUS_MAP[str(target_code)]
        elif target_label in STATUS_MAP and not target_code:
            target_code = STATUS_MAP[target_label]

        off_status = str(off_p.get("currentStatus") or "").strip()
        if target_code and _norm(target_code) != _norm(off_status):
            profile_values = dict(off_p)
            profile_values["currentStatus"] = str(target_code)
            profile_values["path"] = off_p.get("path") or "Profile[0]"
            actions.append({
                "module": "job_status",
                "op": "edit",
                "node": "Profile",
                "values": profile_values,
                "matchKeys": {},
                "hintPath": off_p.get("path") or "Profile[0]",
                "detail": f"求职状态 edit（{off_status}→{target_code}）",
            })
        else:
            skipped.append({"module": "job_status", "reason": "与官网一致，无需回写"})

    # ---- 自我评价（单值） ----
    if "self_evaluation" in modules:
        want = _norm(_val(local, "self_evaluation"))
        if len(want) > SELF_EVAL_MAX_LEN:
            want = want[:SELF_EVAL_MAX_LEN]
            skipped.append({"module": "self_evaluation",
                            "reason": f"超过官网 {SELF_EVAL_MAX_LEN} 字上限，已截断"})
        off_se = (official.get("SelfEvaluate") or [{}])
        cur = _norm(off_se[0].get("selfEvaContent", "") if off_se else "")
        if not want:
            skipped.append({"module": "self_evaluation", "reason": "本地为空，跳过"})
        elif want == cur:
            skipped.append({"module": "self_evaluation", "reason": "与官网一致，无需回写"})
        else:
            actions.append({
                "module": "self_evaluation", "op": "edit", "node": "SelfEvaluate",
                "values": {"selfEvaTitle": "自我介绍", "selfEvaUserdefTitle": "自我介绍",
                           "selfEvaContent": want, "path": (off_se[0].get("path") or "") if off_se else ""},
                "matchKeys": {}, "hintPath": (off_se[0].get("path") or "") if off_se else "",
                "detail": f"自我评价 edit（{len(want)}字）"})

    # ---- 列表模块（全量覆盖：path/业务键匹配 edit、add、del） ----
    for mod in ["wanna", "work_experience", "education", "projects",
                "training", "language", "skill_tags"]:
        if mod not in modules:
            continue
        cfg = NODE_CFG[mod]
        local_items = [d for d in (_as_dict(x) for x in (_val(local, mod) or [])) if d]
        off_items = official.get(cfg["node"]) or []
        if not local_items:
            # 本地为空（主简历未提供）时绝不删官网已有条目，避免误删用户数据
            if off_items:
                skipped.append({"module": mod, "reason": f"本地为空，保留官网现有 {len(off_items)} 条（不删）"})
            continue
        off_by_path = {o.get("path"): o for o in off_items if o.get("path")}

        used_paths = set()
        edit_cnt = add_cnt = noop_cnt = 0
        for li, item in enumerate(local_items):
            path = _norm(item.get("path"))
            matched = None
            if path and path in off_by_path:
                matched = off_by_path[path]
            else:
                # path 缺失/漂移：加权配对（名称必须命中；名称缺失时起始月唯一才配）
                matched = _match_official(item, off_items, used_paths, cfg)
            if matched is not None:
                used_paths.add(matched.get("path"))
                if _items_same(item, matched, cfg["keys"]):
                    noop_cnt += 1
                    continue
                actions.append({
                    "module": mod, "op": "edit", "node": cfg["node"],
                    "values": build_values(mod, item, matched),
                    "matchKeys": _match_key_of(matched, cfg["keys"][:3]),
                    "hintPath": matched.get("path") or "",
                    "detail": f"{mod} edit path={matched.get('path')}"})
                edit_cnt += 1
            else:
                # add 载荷以官网同节点条目为模板打底（补齐服务端必需的全量字段，
                # 缺字段会报 apiCode 210 服务器异常），本地业务字段覆盖
                add_item = item
                if mod == "work_experience" and not _norm(item.get("companyName")):
                    # 空窗期条目：官网诊断要求企业名称非空
                    add_item = dict(item)
                    add_item["companyName"] = "Career Sabbatical"
                template = off_items[0] if off_items else None
                values = build_values(mod, add_item, template)
                values["path"] = None  # 新增条目不带 path，防止陈旧 path 误更新
                if mod == "work_experience" and _norm(values.get("companyName")) == "Career Sabbatical":
                    values["newCompanyId"] = ""  # 自定义公司名不挂官网公司 id
                actions.append({
                    "module": mod, "op": "add", "node": cfg["node"],
                    "values": values,
                    "matchKeys": {}, "hintPath": "",
                    "detail": f"{mod} add（本地新增条目[{li}]）"})
                add_cnt += 1

        dels = [o for o in off_items if o.get("path") not in used_paths]
        for o in dels:
            actions.append({
                "module": mod, "op": "del", "node": cfg["node"], "values": None,
                "matchKeys": _match_key_of(o, cfg["keys"][:3]),
                "hintPath": o.get("path") or "",
                "detail": f"{mod} del path={o.get('path')}（官网多余）"})

        if not (edit_cnt or add_cnt or dels):
            skipped.append({"module": mod,
                            "reason": f"与官网一致（{noop_cnt} 条 no-op），无需回写"})

    # ---- 证书（批量接口整列表替换） ----
    if "certificates" in modules:
        local_certs = [d for d in (_as_dict(c) for c in (_val(local, "certificates") or _val(local, "certificate") or _val(local, "Certificate") or [])) if d]
        off_certs = official.get("Certificate") or []
        local_set = sorted([_cert_name(c) for c in local_certs if _cert_name(c)])
        off_set = sorted([_cert_name(c) for c in off_certs if _cert_name(c)])
        if not local_certs:
            skipped.append({"module": "certificates", "reason": "本地为空，跳过"})
        elif local_set == off_set:
            skipped.append({"module": "certificates", "reason": f"与官网一致（{len(off_certs)} 条），无需回写"})
        else:
            cert_list = [{"certificationName": _cert_name(c),
                          "certificationType": _cert_id(c)}
                         for c in local_certs if _cert_name(c)]
            actions.append({
                "module": "certificates", "kind": "cert", "op": "cert", "node": "Certificate",
                "certificationList": cert_list,
                "detail": f"certificates 整列表替换（官网{len(off_certs)}条→本地{len(cert_list)}条）"})

    return {"actions": actions, "skipped": skipped}


# ============================================================
# 浏览器交互
# ============================================================

JS_WAIT_READY = r"""
return (function(){
    var root = document.querySelector('#root');
    if (!root || !root.__vue__) return 'no';
    var store = root.__vue__.$store;
    return (store && store.state && store.state.resume && store.state.resume.currentResume) ? 'yes' : 'no';
})();
"""

# 拉官网当前全量数据（currentResume 各节点）
JS_READ_OFFICIAL = r"""
return (function() {
    var root = document.querySelector('#root');
    if (!root || !root.__vue__) return JSON.stringify({error: 'no vue'});
    var store = root.__vue__.$store;
    var rs = store.state.resume;
    var cr = rs.currentResume;
    if (!cr) return JSON.stringify({error: 'currentResume 为空'});
    function clone(x) { try { return JSON.parse(JSON.stringify(x)); } catch(e) { return null; } }
    var rl = rs.resumeList[rs.resumeIndex] || {};
    var out = {resumeId: rl.resumeId, resumeNumber: rl.resumeNumber, lang: rs.lang};
    ['Profile', 'WorkExperience','EducationExperience','ProjectExperience','TrainExperience',
     'LanguageSkill','ProfessionalSkill','Certificate','SelfEvaluate','UnifiedPurpose']
        .forEach(function(k) { out[k] = clone(cr[k] || []); });
    return JSON.stringify(out);
})();
"""

# 执行单个列表动作（占位 __OP_JSON__）：重定位目标后 dispatch 官网 action
JS_EXEC_OP = r"""
return (async function() {
    var op = __OP_JSON__;
    if (!op.kind) {
        op.kind = (op.op === 'del') ? 'del' : (op.op === 'cert' ? 'cert' : 'save');
    }
    var root = document.querySelector('#root');
    if (!root || !root.__vue__) return JSON.stringify({ok: false, error: 'no vue'});
    var store = root.__vue__.$store;
    var rs = store.state.resume;
    var rl = rs.resumeList[rs.resumeIndex] || {};
    var base = {resumeId: rl.resumeId, resumeNumber: rl.resumeNumber, lang: rs.lang};
    try {
        if (op.kind === 'save') {
            var values = op.values;
            if (op.op !== 'add') {
                // 重新定位目标（删除会造成 path 索引漂移），取最新 path
                var arr = rs.currentResume[op.node] || [];
                var target = null;
                if (op.hintPath) {
                    for (var i = 0; i < arr.length; i++) if (arr[i].path === op.hintPath) { target = arr[i]; break; }
                }
                if (!target && op.matchKeys && Object.keys(op.matchKeys).length > 0) {
                    for (var j = 0; j < arr.length; j++) {
                        var okm = true;
                        for (var k in op.matchKeys) {
                            if (String(arr[j][k] == null ? '' : arr[j][k]).trim() !== op.matchKeys[k]) { okm = false; break; }
                        }
                        if (okm) { target = arr[j]; break; }
                    }
                }
                if (!target && (op.node === 'Profile' || op.node === 'SelfEvaluate') && arr.length > 0) {
                    target = arr[0];
                }
                if (!target) return JSON.stringify({ok: false, error: 'target not found: ' + op.hintPath});
                values.path = target.path;
            } else {
                values.path = null;
            }
            var payload = {resumeId: base.resumeId, resumeNumber: base.resumeNumber,
                           nodeName: op.node, lang: base.lang, values: values};
            var ok = await store.dispatch('resume/updateResumeAction', payload);
            return JSON.stringify({ok: ok === true});
        } else if (op.kind === 'del') {
            var arr2 = rs.currentResume[op.node] || [];
            var t2 = null;
            if (op.hintPath) {
                for (var a = 0; a < arr2.length; a++) if (arr2[a].path === op.hintPath) { t2 = arr2[a]; break; }
            }
            if (!t2 && op.matchKeys) {
                for (var b = 0; b < arr2.length; b++) {
                    var okm2 = true;
                    for (var k2 in op.matchKeys) {
                        if (String(arr2[b][k2] == null ? '' : arr2[b][k2]).trim() !== op.matchKeys[k2]) { okm2 = false; break; }
                    }
                    if (okm2) { t2 = arr2[b]; break; }
                }
            }
            if (!t2) return JSON.stringify({ok: false, error: 'del target not found: ' + op.hintPath});
            var ok2 = await store.dispatch('resume/deleteResumeAction',
                {resumeId: base.resumeId, resumeNumber: base.resumeNumber,
                 nodeName: op.node, lang: base.lang, path: t2.path});
            return JSON.stringify({ok: ok2 === true});
        } else if (op.kind === 'cert') {
            function ck(name) {
                var m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
                return m ? decodeURIComponent(m[1]) : '';
            }
            var qs = 'at=' + encodeURIComponent(ck('at')) + '&rt=' + encodeURIComponent(ck('rt'))
                + '&_v=' + String(Math.random()).slice(0, 10);
            var r = await fetch('https://cgate.zhaopin.com/resumeapi/resumeCertification/saveCertificationList?' + qs, {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json',
                          'x-zp-page-code': '0', 'x-zp-business-system': '1', 'x-zp-platform': '13'},
                body: JSON.stringify({resumeNumber: base.resumeNumber, resumeLanguage: base.lang,
                                      certificationList: op.certificationList, platform: 13})});
            var d = await r.json();
            var okc = r.status === 200 && d && d.statusCode === 200 && d.data && d.data.success;
            if (okc) {
                await store.dispatch('resume/getResumeAction', {resumeId: base.resumeId, resumeNumber: base.resumeNumber, lang: base.lang});
            }
            return JSON.stringify({ok: !!okc, message: JSON.stringify(d).slice(0, 200)});
        }
        return JSON.stringify({ok: false, error: 'unknown kind: ' + op.kind});
    } catch (e) {
        return JSON.stringify({ok: false, error: String(e).slice(0, 300)});
    }
})();
"""


def _wait_ready(tab, tries=15):
    for _ in range(tries):
        if tab.run_js(JS_WAIT_READY) == "yes":
            return True
        time.sleep(1)
    return False


def _is_unfilled_shell(data) -> bool:
    """冷加载空壳特征：resumeId 无效/为0，或业务节点与 Profile 姓名全空。"""
    if not isinstance(data, dict):
        return True
    rid = data.get("resumeId")
    if not rid or str(rid).strip() in ("0", ""):
        return True
    nodes = ["WorkExperience", "EducationExperience", "ProjectExperience",
             "TrainExperience", "LanguageSkill", "ProfessionalSkill", "Certificate",
             "SelfEvaluate", "UnifiedPurpose"]
    prof = data.get("Profile") or []
    has_name = bool(prof and isinstance(prof, list) and prof[0].get("name") and str(prof[0].get("name")).strip())
    has_nodes = any(bool(data.get(k)) for k in nodes)
    return not (has_name or has_nodes)


def _read_official(tab):
    if "i.zhaopin.com/resume" not in tab.url:
        tab.get(RESUME_URL)
    if not _wait_ready(tab):
        # store 未就绪：强制导航重试一次
        tab.get(RESUME_URL)
        if not _wait_ready(tab):
            raise RuntimeError("Vuex resume store 加载失败（页面未就绪）")
    # 「附件可同步」弹窗自动关闭（只点 ×，绝不点「同步至在线简历」）
    dismiss_overlay_popup(tab, "同步至在线简历")

    # 白纸事故修复（2026-08-31 / 2026-09-01）：store 对象先于业务数据出现，只等对象会读到全空壳，
    # 规划时误判「官网为空简历」→ 全量新增 → 官网拒绝/复核大面积不一致。
    # 必须等内容节点真正填充（且 resumeId > 0）再读。
    state = wait_resume_filled(tab, tries=30)
    if state == "timeout":
        raise RuntimeError("官网简历数据 30s 内未填充完成（疑似软拦截/网络异常），已中止以防按空数据误规划")

    data = json.loads(tab.run_js(JS_READ_OFFICIAL, timeout=60))
    if data.get("error"):
        raise RuntimeError(f"读取官网数据失败: {data['error']}")

    # 严格校验 resumeId 与空壳状态
    rid = data.get("resumeId")
    if (not rid or str(rid).strip() in ("0", "")) and state != "timeout":
        # 页面可能正在异步拉取 resumeList，等待后重试
        time.sleep(3)
        if wait_resume_filled(tab, tries=15) == "yes":
            data = json.loads(tab.run_js(JS_READ_OFFICIAL, timeout=60))

    if _is_unfilled_shell(data):
        # 二次确认：6s 后重读一轮，仍为空才按「官网确为空简历」放行
        time.sleep(6)
        if not _wait_ready(tab):
            tab.get(RESUME_URL)
            if not _wait_ready(tab):
                raise RuntimeError("Vuex resume store 加载失败（页面未就绪）")
        if wait_resume_filled(tab, tries=15) == "yes":
            data = json.loads(tab.run_js(JS_READ_OFFICIAL, timeout=60))
            if data.get("error"):
                raise RuntimeError(f"读取官网数据失败: {data['error']}")
        elif _is_unfilled_shell(data):
            print("  [WARN] 官网在线简历两次读取均为空壳，按空简历继续。")
            print("         若你的在线简历实际有内容，可能是软拦截——请人工打开 i.zhaopin.com/resume 确认后再试。")
    return data


def _exec_op(tab, op_obj):
    js = JS_EXEC_OP.replace("__OP_JSON__", json.dumps(op_obj, ensure_ascii=False))
    return json.loads(tab.run_js(js, timeout=120))


JS_RESOLVE_SKILLS = """
return (async function(words) {
    function ck(name) {
        var m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
        return m ? decodeURIComponent(m[1]) : '';
    }
    var at = ck('at');
    var rt = ck('rt');
    var url = 'https://fe-api.zhaopin.com/c/datanormalization/keyword-industry?at=' + encodeURIComponent(at) + '&rt=' + encodeURIComponent(rt) + '&_v=' + Math.random();

    var results = {};
    for (var w of words) {
        try {
            var r = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'x-zp-client-id': '3c6d15c8-53cf-4746-acf0-1f4a577ac567'
                },
                body: JSON.stringify({
                    isIndustry: false,
                    value: w,
                    source: 'C_WEB'
                }),
                credentials: 'include'
            });
            var d = await r.json();
            if (d && d.code === 200 && d.data && d.data.id) {
                results[w] = { id: d.data.id, name: d.data.name || w };
            }
        } catch(e) {}
    }
    return JSON.stringify(results);
})(__WORDS_JSON__);
"""


def _resolve_custom_skill_ids_via_browser(tab, local_data):
    """提取本地工作经历中的自定义技能，对尚未收录在官方字典里的技能调用智联云端规范化接口注册/获取真实官方 ID"""
    works = _val(local_data, "work_experience") or []
    if isinstance(works, dict):
        works = [works]

    needed = set()
    for w in works:
        if not isinstance(w, dict):
            continue
        # 1. 从 skillTagList
        s_list = w.get("skillTagList")
        if isinstance(s_list, list):
            for s in s_list:
                if isinstance(s, dict):
                    name = str(s.get("name") or s.get("tagValue") or "").strip()
                    is_custom = bool(s.get("customize") or s.get("isCustom"))
                    if is_custom and name and name.lower().strip() not in ZHILIAN_KNOWN_SKILL_IDS:
                        needed.add(name)
        # 2. 从 skillTagCustomized
        raw_cust = str(w.get("skillTagCustomized") or "").strip()
        if raw_cust:
            for c in raw_cust.split(","):
                c = c.strip()
                if c and c.lower().strip() not in ZHILIAN_KNOWN_SKILL_IDS:
                    needed.add(c)
        # 3. 从 skillTags
        raw_tags = w.get("skillTags")
        if isinstance(raw_tags, str) and raw_tags.strip().startswith("["):
            try:
                arr = json.loads(raw_tags)
                if isinstance(arr, list):
                    for s in arr:
                        if isinstance(s, dict) and not s.get("standard"):
                            name = str(s.get("tagValue") or s.get("name") or "").strip()
                            if name and name.lower().strip() not in ZHILIAN_KNOWN_SKILL_IDS:
                                needed.add(name)
            except Exception:
                pass

    if not needed or not tab:
        return

    js = JS_RESOLVE_SKILLS.replace("__WORDS_JSON__", json.dumps(list(needed), ensure_ascii=False))
    try:
        raw_res = tab.run_js(js, timeout=30)
        res = json.loads(raw_res) if isinstance(raw_res, str) else (raw_res or {})
        if isinstance(res, dict):
            for w, data in res.items():
                if isinstance(data, dict) and data.get("id"):
                    qid = int(data["id"])
                    ZHILIAN_KNOWN_SKILL_IDS[w.lower().strip()] = qid
                    print(f"  [云端技能注册] 已成功获取官方正版 ID: {w} -> {qid} ({data.get('name')})")
    except Exception as e:
        print(f"  [WARN] 动态注册技能 ID 失败: {e}")


ZHILIAN_FIELD_LIMITS = {
    "self_evaluation": ("自我评价", 500, lambda l: [
        ("自我评价", _val(l, "self_evaluation") if isinstance(_val(l, "self_evaluation"), str) else (((_val(l, "selfEvaluation") or [{}])[0].get("selfEvaContent") if isinstance(_val(l, "selfEvaluation"), list) and _val(l, "selfEvaluation") else "") or ""))
    ]),
    "work_experience": ("工作经历", 3000, lambda l: [
        (f"{it.get('companyName') or it.get('company') or '工作经历'}·工作内容", it.get("workDesc") or it.get("workDescription") or "")
        for it in (_val(l, "work_experience") or _val(l, "workExperience") or []) if isinstance(it, dict)
    ]),
    "projects": ("项目经历", 2000, lambda l: [
        (f"{it.get('proExpProjectName') or '项目经历'}·项目描述", it.get("proExpProjectDesc") or it.get("project_description") or "")
        for it in (_val(l, "projects") or _val(l, "project") or _val(l, "projectExperience") or []) if isinstance(it, dict)
    ] + [
        (f"{it.get('proExpProjectName') or '项目经历'}·项目职责", it.get("proExpProjectDuty") or "")
        for it in (_val(l, "projects") or _val(l, "project") or _val(l, "projectExperience") or []) if isinstance(it, dict)
    ]),
    "training": ("培训经历", 1000, lambda l: [
        (f"{it.get('trainCourse') or '培训经历'}·培训描述", it.get("trainDesc") or "")
        for it in (_val(l, "training") or []) if isinstance(it, dict)
    ]),
}


def check_length_violations(local: dict, selected: list = None) -> list:
    """前置硬性检查：扫描待回写模块的文本长度是否超出智联官网上限。
    若超限，返回详细的人性化拦截条目。"""
    violations = []
    target_mods = selected if selected else list(ZHILIAN_FIELD_LIMITS.keys())
    for mod in target_mods:
        if mod not in ZHILIAN_FIELD_LIMITS:
            continue
        mod_label, max_len, extractor = ZHILIAN_FIELD_LIMITS[mod]
        for field_label, text in extractor(local):
            if not isinstance(text, str):
                continue
            cur_len = len(text)
            if cur_len > max_len:
                overflow = cur_len - max_len
                violations.append({
                    "module": mod,
                    "module_label": mod_label,
                    "field_label": field_label,
                    "current_len": cur_len,
                    "max_len": max_len,
                    "overflow": overflow,
                    "reason": f"【{field_label}】当前字数共 {cur_len} 字，超出智联官方上限 {max_len} 字（超限 {overflow} 字）",
                    "suggestion": f"请在「{mod_label}」中将「{field_label}」删减精简至 {max_len} 字以内后重试",
                })
    return violations


# ============================================================
# 复核（回写后重新读官网，逐模块比对）
# ============================================================

def verify_results(verify_off, local, plan):
    out = []
    touched = {a["module"] for a in plan.get("actions", [])}
    for mod in ALL_MODULES:
        if mod not in touched:
            continue
        if mod == "basic_info":
            local_bi = dict(_val(local, "basic_info") or {})
            off_profile = verify_off.get("Profile") or [{}]
            off_p = off_profile[0] if off_profile else {}
            is_foreign = bool(local_bi.get("isOverseas") is True or str(local_bi.get("isOverseas")) in ("1", "true") or
                              local_bi.get("foreign") is True or str(local_bi.get("foreign")) in ("1", "true") or
                              str(local_bi.get("currentProvince")) == "480" or str(local_bi.get("currentCity")) == "480")
            if is_foreign:
                local_bi["currentProvince"] = "480"
                local_bi["currentCity"] = "480"
                local_bi["currentCityDistrictId"] = "0"

            editable_keys = [
                ("name", "姓名"), ("gender", "性别"), ("currentIdentity", "当前身份"),
                ("birthyear", "出生年份"), ("birthmonth", "出生月份"),
                ("yearStartWorking", "工作年份"), ("monthStartWorking", "工作月份"),
                ("hukouProvinceId", "户口省份"), ("hukouCityId", "户口城市"),
                ("currentProvince", "现居省份"), ("currentCity", "现居城市"),
                ("currentCityDistrictId", "现居区县"), ("politicalAffiliation", "政治面貌"),
                ("maritalStatus", "婚姻状况"),
            ]
            bad = []
            for k, label in editable_keys:
                lv = _norm(local_bi.get(k))
                ov = _norm(off_p.get(k))
                if lv and lv != ov:
                    bad.append(f"{label}未生效({lv}!={ov})")
            match = not bad
            out.append({
                "module": mod,
                "match": match,
                "note": "基本信息已生效" if match else "; ".join(bad),
            })
            continue
        if mod == "job_status":
            local_js = _val(local, "job_status")
            target_code = None
            if isinstance(local_js, dict):
                target_code = local_js.get("jobStateCode") or local_js.get("currentStatus") or local_js.get("code")
            elif local_js is not None:
                target_code = str(local_js).strip()
            STATUS_MAP = {
                "离职-正在找工作": "1", "我目前处于离职状态，可立即上岗": "1", "正在找工作": "1",
                "在职-急寻新工作": "2", "我目前在职，正考虑换个新环境": "2",
                "在职-正在找工作": "3", "我对现有工作还算满意，如有更好的工作机会，我也可以考虑": "3",
                "在职-暂不考虑": "4", "目前暂无跳槽打算": "4",
                "应届毕业生": "5",
            }
            if str(target_code) in STATUS_MAP:
                target_code = STATUS_MAP[str(target_code)]

            off_profile = verify_off.get("Profile") or [{}]
            off_p = off_profile[0] if off_profile else {}
            off_status = str(off_p.get("currentStatus") or "").strip()

            match = (not target_code) or (_norm(target_code) == _norm(off_status))
            out.append({
                "module": mod,
                "match": match,
                "note": "求职状态已生效" if match else f"求职状态未生效({target_code}!={off_status})",
            })
            continue
        if mod == "self_evaluation":
            want = _norm(_val(local, "self_evaluation"))[:SELF_EVAL_MAX_LEN]
            off_se = verify_off.get("SelfEvaluate") or []
            cur = _norm(off_se[0].get("selfEvaContent", "") if off_se else "")
            match = (want == cur) or not want
            out.append({"module": mod, "match": match,
                        "note": "已生效" if match else "官网值不一致"})
            continue
        if mod == "certificates":
            local_certs = _val(local, "certificates") or _val(local, "certificate") or _val(local, "Certificate") or []
            off_certs = verify_off.get("Certificate") or []
            local_set = sorted([_cert_name(c) for c in local_certs if _cert_name(c)])
            off_set = sorted([_cert_name(c) for c in off_certs if _cert_name(c)])
            # 语义（用户拍板 2026-08-31）：官网=快照，多余条目应被删除；删不干净=异常
            missing = [c for c in local_set if c not in off_set]
            extra = [c for c in off_set if c not in local_set]
            notes = []
            if missing:
                notes.append(f"本地 {len(missing)} 条未生效（{'; '.join(missing[:3])}）")
            if extra:
                notes.append(f"官网仍有 {len(extra)} 条快照未含内容（删除未生效）")
            out.append({"module": mod, "match": not missing and not extra,
                        "note": "；".join(notes) if notes else f"{len(local_set)} 条已生效"})
            continue
        cfg = NODE_CFG[mod]
        local_items = _val(local, mod) or []
        off_items = verify_off.get(cfg["node"]) or []
        bad = []
        used = set()
        for item in local_items:
            matched = None
            for o in off_items:
                if o.get("path") in used:
                    continue
                if _items_same(item, o, cfg["keys"]):
                    matched = o
                    break
            if matched is not None:
                used.add(matched.get("path"))
            else:
                item_title = _norm(_item_val(item, cfg['keys'][0]))[:24]
                diff_reason = None
                candidate_o = None
                best_cand_score = 0
                for o in off_items:
                    score = 0
                    if _norm(_item_val(item, cfg['keys'][0])) == _norm(_item_val(o, cfg['keys'][0])):
                        score += 3
                    if len(cfg['keys']) > 1 and _norm(_item_val(item, cfg['keys'][1])) == _norm(_item_val(o, cfg['keys'][1])):
                        score += 2
                    if score > best_cand_score and score >= 3:
                        candidate_o, best_cand_score = o, score
                if candidate_o:
                    for k in cfg["keys"]:
                        if not _items_same(item, candidate_o, [k]):
                            lv = _norm(_item_val(item, k))
                            ov = _norm(_item_val(candidate_o, k))
                            if len(lv) > len(ov) and lv.startswith(ov):
                                diff_reason = f"官网内容被截断（本地{len(lv)}字 vs 官网{len(ov)}字，超出限制）"
                            else:
                                diff_reason = f"字段内容与官网不一致({k})"
                            break
                if diff_reason:
                    bad.append(f"「{item_title}」{diff_reason}")
                else:
                    bad.append(f"未找到匹配条目（{item_title}）")
        # 语义（用户拍板 2026-08-31）：官网=快照；快照未含的条目本应被删除，
        # 复核仍见到 = 删除未生效，属异常（区别于本条目内容不一致）
        extra_n = sum(1 for o in off_items if o.get("path") not in used)
        extra_note = f"；官网仍有 {extra_n} 条快照未含内容（删除未生效）" if extra_n else ""
        out.append({"module": mod, "match": not bad and not extra_n,
                    "note": ("; ".join(bad) + extra_note) if (bad or extra_n) else f"{len(local_items)} 条已生效"})
    return out


# ============================================================
# 主流程
# ============================================================

def run_write_back(dry_run=False, selected_paths=None):
    print("=" * 56)
    print("  智联招聘 · 本地简历数据回写官网")
    print("=" * 56)

    selected = None
    if selected_paths:
        selected = [m for m in selected_paths if m in ALL_MODULES]
        for p in selected_paths:
            if p in HARD_SKIP:
                print(f"  [跳过] {p}: {HARD_SKIP[p]}")
            elif p not in ALL_MODULES:
                print(f"  [警告] 未知模块: {p}")
        if not selected:
            print("  [错误] 勾选的模块全部不可回写")
            sys.exit(1)

    if not os.path.exists(SNAPSHOT_PATH) and not os.path.exists(FIELDS_PATH):
        print("  [错误] 本地数据源不存在（zhilian_writeback.json / zhilian_fields.json）")
        sys.exit(1)
    local, src, freshness = load_local()
    print(f"  📂 数据源: {os.path.basename(src)}")
    # 回写全局空数据守卫：本地近乎为空时拒绝，防止把空内容推上官网
    from browser_common import ensure_writable_data
    ensure_writable_data("zhilian", local)
    if freshness.get("stale"):
        print(f"  [WARN] {freshness['warning']}")

    # ── 阶段 1: 前置安全检查（字数上限硬性校验） ──
    print("\n  ── 【阶段 1: 前置字数字数检查】 ──")
    violations = check_length_violations(local, selected)
    if violations:
        print(f"  ❌ 检测到 {len(violations)} 处字段字数超出智联官网上限，已自动拦截回写以防官网截断丢字：")
        for idx, v in enumerate(violations, 1):
            print(f"     {idx}. {v['reason']}")
            print(f"        💡 解决指引: {v['suggestion']}")
        print("=" * 56)
        return {
            "success": False,
            "error": "字数超限拦截",
            "message": f"回写已被安全拦截：检测到 {len(violations)} 处内容超出智联官网上限（例如：{violations[0]['field_label']} 超出 {violations[0]['overflow']} 字）。请删减后重试！",
            "overflow_violations": violations,
            "diagnostic": {
                "type": "OVERFLOW_ERROR",
                "title": "内容字数超出智联官方限制",
                "root_cause": "\n".join([f"• {v['reason']}" for v in violations]),
                "suggestion": "请在对应模块中精简删减超出字数的内容，确保在官方字数限制内后再点击回写。",
                "items": violations,
            },
            "plan": {"actions": [], "skipped": []},
            "results": [],
            "verify": []
        }
    print("  ✓ 待回写字段字数校验全部合格 (未发现超限内容)")

    page = connect_page(PORT)
    print(f"  ✓ 已连接浏览器 (端口 {PORT})")
    tab = page.latest_tab
    if "login" in tab.url.lower() or "passport" in tab.url.lower():
        print("  ❌ 未登录智联招聘平台，请先在浏览器登录")
        sys.exit(1)

    official = _read_official(tab)
    rid = official.get('resumeId')
    print(f"  ✓ 已读取官网当前在线简历 (resumeId={rid})")

    # 白纸误写熔断守卫：如果官网 resumeId 无效（0 或空），而本地快照有实质经历（>=2项），坚决熔断
    local_entity_count = sum(len(_val(local, m) or []) for m in ["work_experience", "projects", "education", "wanna"])
    if (not rid or str(rid).strip() in ("0", "")) and local_entity_count >= 2:
        raise RuntimeError(
            f"智联官网在线简历数据尚未就绪 (resumeId={rid})，检测到本地有 {local_entity_count} 条经历，"
            "为防止误将官网视作空白简历而生成全量重复新增，已自动熔断拦截！\n"
            "请确认 Edge 浏览器已完全加载 i.zhaopin.com/resume 并显示完整简历内容后，再点击回写。"
        )

    with open(OFFICIAL_NOW_PATH, "w", encoding="utf-8") as f:
        json.dump(official, f, ensure_ascii=False, indent=2)

    # 回写计划规划前：对自定义技能发起智联云端正版 ID 批量解析/注册
    _resolve_custom_skill_ids_via_browser(tab, local)

    plan = plan_writeback(local, official, selected)

    print("\n  ── 【阶段 2: 规划与执行回写】 ──")
    for a in plan["actions"]:
        print(f"    [写入计划] {a['module']:16} {a['detail']}")
    for s in plan["skipped"]:
        print(f"    [保持一致] {s['module']:16} {s['reason']}")

    if dry_run:
        print("\n  [预演模式] 规划完成，未执行实际回写")
        return {"plan": plan}

    if not plan["actions"]:
        print("\n  ✓ 无需回写（所有勾选模块均与官网完全一致）")
        return {"plan": plan, "results": [], "verify": []}

    results = []
    for a in plan["actions"]:
        if a.get("kind") == "cert" or a.get("op") in ("cert", "replace"):
            op_obj = {"kind": "cert", "certificationList": a.get("certificationList", [])}
        elif a["op"] == "del":
            op_obj = {"kind": "del", "node": a["node"],
                      "matchKeys": a.get("matchKeys") or {}, "hintPath": a.get("hintPath", "")}
        else:
            op_obj = {"kind": "save", "op": a["op"], "node": a["node"],
                      "values": a.get("values", {}),
                      "matchKeys": a.get("matchKeys") or {}, "hintPath": a.get("hintPath", "")}
        r = _exec_op(tab, op_obj)
        ok = bool(r.get("ok"))
        tag = "✓ 成功" if ok else "✗ 失败"
        extra = r.get("message") or r.get("error") or ""
        print(f"    [{tag}] {a['module']:16} {a['detail']} {extra}")
        results.append({**a, "resp_message": extra or None, "ok": ok})
        time.sleep(1.2)  # 等官网 action 内部 getResumeAction 刷新 store

    # ── 阶段 3: 官网数据复核与人话诊断 ──
    print("\n  ── 【阶段 3: 官网生效复核与诊断】 ──")
    time.sleep(5)
    verify_off = _read_official(tab)
    verify = verify_results(verify_off, local, plan)
    for v in verify:
        tag = "✓ 已生效" if v["match"] else "✗ 未生效"
        print(f"    [{tag}] {v['module']:16} {v['note']}")

    succ = sum(1 for r in results if r["ok"])
    print(f"\n  📊 回写汇总：共 {len(results)} 项操作，{succ} 项写入成功")
    # 顶层 success/message 契约（用户案例 2026-08-30）：统一路由按 data["success"] 判定，
    # 历史载荷缺这两个键导致批量回写把成功误判为失败。
    # 文案（2026-08-31）：「写入失败」与「复核不一致」分开陈述，不再互相掩盖
    ok_results = [r for r in results if r.get("ok")]
    verify_bad = [v for v in verify if not v.get("match")]
    fail_n = len(results) - len(ok_results)
    if not results:
        summary = "无需回写（本地与官网一致或无可回写模块）"
    elif fail_n and verify_bad:
        summary = f"写入成功 {len(ok_results)}/{len(results)}、失败 {fail_n} 项；复核不一致 {len(verify_bad)} 项"
    elif fail_n:
        summary = f"写入失败 {fail_n}/{len(results)} 项"
    elif verify_bad:
        summary = f"回写完成 {len(results)}/{len(results)}，复核不一致 {len(verify_bad)} 项"
    else:
        summary = f"回写成功 {len(ok_results)}/{len(results)}"
    return {
        "success": len(ok_results) == len(results) and not verify_bad,
        "message": summary,
        "plan": plan, "results": results, "verify": verify, "data_source": freshness,
    }


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    as_json = "--json" in sys.argv
    paths = None
    for i, a in enumerate(sys.argv):
        if a == "--paths" and i + 1 < len(sys.argv):
            paths = [p for p in sys.argv[i + 1].split(",") if p]
    result = run_write_back(dry_run=dry, selected_paths=paths)
    if as_json:
        print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    if dry:
        sys.exit(0)
    ok_all = all(r.get("ok") for r in result.get("results", []))
    verify_bad = [v for v in result.get("verify", []) if not v.get("match")]
    sys.exit(0 if ok_all and not verify_bad else 2)
