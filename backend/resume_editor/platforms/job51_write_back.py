#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
51job - 本地数据回写官网在线简历
读取本地 51job_writeback.json 快照（优先，writeback-save 生成）或 51job_fields.json，
逐模块通过官网页面内 vm.$api.resumeApi（自动鉴权，底层 cupid.51job.com）回写。

回写范围（--paths 逗号分隔模块名；不传 = 全部模块）：
  ✅ self_introduction -> editSelfIntroduction（POST /open/resumes/{rid}/self-introduction）
  ✅ intentions        -> editIntention/addIntention/delIntention（/open/intentions）
  ✅ works             -> editWorkExp/addWorkExp/delWorkExp（/open/resumes/{rid}/works）
  ✅ projects          -> getProjectEdit/Add/Del（/open/resumes/{rid}/projects）
  ✅ educations        -> editEducation/addEducation/delEducation（/open/resumes/{rid}/educations）
  ✅ skills            -> getSkillItEdit/Add/Del（/open/resumes/{rid}/skill-it）
  ✅ language          -> languageEdit/Add/Del（languageDel 官网源码实际打 /skill-it/{id}）
  ✅ certifications    -> getCertificateEdit/Del 单条（multi-edit 参数格式未标定，不用）
  条目匹配：全部按官网 id（本地数据采自官网，id 确定性匹配）
  语义：全量覆盖 —— 同 id edit / 本地无 id add / 官网多余 del
  ⛔ HARD_SKIP：basic_info（editBaseInfo 触发「版本升级请重新选择」校验失败，
     且 name/mobile/email/wechat 为脱敏值）；personalSkills（偏好问卷，无标定端点）

用法：python job51_write_back.py [--dry-run] [--json] [--paths works,skills]
前提：51job Edge 已启动且已登录（端口读 registry）；macOS 需 NO_PROXY=127.0.0.1,localhost
"""

import json
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from browser_common import connect_page, get_platform_port

PORT = get_platform_port("51job")
RESUME_URL = "https://www.51job.com/resume/center"
DATA_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "data")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "51job_writeback.json")
FIELDS_PATH = os.path.join(DATA_DIR, "51job_fields.json")

# 可回写模块（顺序即前端勾选顺序）
ALL_MODULES = ["basic_info", "self_introduction", "intentions", "works", "projects",
               "educations", "skills", "language", "certifications"]

# 强制排除模块 + 原因
HARD_SKIP = {
    "personalSkills": "求职偏好问卷，无标定的保存端点",
}

# 求职状态（currentSituation）官网合法值：自官网简历编辑组件 allCurrentSition 实测提取
# （2026-08-31）。0 不是合法值——历史映射产出过 0，写入官网永远不生效却回执成功，
# 是「复核异常：求职状态不一致」久治不愈的根源。4/5/6 为学生态选项。
_LEGAL_CURRENT_SITUATION = {"1", "2", "3", "4", "5", "6"}
_CURRENT_SITUATION_LABELS = {
    "1": "离职-周内到岗", "2": "在职-月内到岗", "3": "在职-观望机会",
    "4": "周内到岗（学生）", "5": "月内到岗（学生）", "6": "观望机会（学生）",
}


def _resolve_current_situation(local_base: dict, off_base: dict):
    """解析本次回写的求职状态值，返回 (value, warning)。

    本地值非法（不在官网合法集，如历史映射产出的 0）时跳过写入、沿用官网当前值：
    非法值写入官网永远不生效但接口回执成功，复核永远标红（2026-08-31 案例）。
    注意用显式 None 判断而非 or 链——数字 0 是合法输入形态（falsy 但非空）。
    """
    lv_new = local_base.get("newCurrentSituation")
    lv_old = local_base.get("currentSituation")
    local_raw = _norm(lv_new if lv_new is not None and lv_new != "" else (lv_old if lv_old is not None and lv_old != "" else ""))
    if local_raw and local_raw not in _LEGAL_CURRENT_SITUATION:
        legal_desc = "、".join(f"{c}={_CURRENT_SITUATION_LABELS[c]}" for c in sorted(_LEGAL_CURRENT_SITUATION))
        warning = (f"本地求职状态值 '{local_raw}' 不是官网合法选项（{legal_desc}），"
                   f"本次跳过求职状态、保留官网原值；请修正主简历的求职状态，或到官网手动设置")
        return _norm(off_base.get("currentSituation")) or "5", warning
    return _norm(local_raw or off_base.get("currentSituation") or "5"), ""

# 列表模块：(resumeApi add/edit/del 方法名, 条目业务键 —— 用于 no-op 判定与复核)
LIST_MODULES = {
    "works":          {"add": "addWorkExpList", "edit": "editWorkExp",    "del": "delWorkExp",
                       "keys": ["companyName", "position", "workFunction", "workIndustry", "workDescription", "startTime", "endTime", "workType", "companySize", "companyType", "workVocationalSkills"]},
    "projects":       {"add": "getProjectAdd", "edit": "getProjectEdit", "del": "getProjectDel",
                       "keys": ["projectName", "describe", "companyName", "startTime", "endTime"]},
    "educations":     {"add": "addEducation",  "edit": "editEducation",  "del": "delEducation",
                       "keys": ["schoolName", "major", "degree", "describe", "startTime", "endTime"]},
    "skills":         {"add": "getSkillItAdd", "edit": "getSkillItEdit", "del": "getSkillItDel",
                       "keys": ["skillType", "skillName", "ability"]},
    "language":       {"add": "languageAdd",   "edit": "languageEdit",   "del": "languageDel",
                       "keys": ["skillType", "ability", "skillCertificationQueries"]},
    "certifications": {"add": "getCertificatedd", "edit": "getCertificateEdit", "del": "getCertificateDel",
                       "keys": ["cert"]},
    "intentions":     {"add": "addIntention",  "edit": "editIntention",  "del": "delIntention",
                       "keys": ["seekType", "expectArea", "expectIndustry", "expectFunction",
                                "salaryType", "minSalary", "maxSalary", "salaryMonth"]},
}

# add 时剔除的服务端生成字段（无 id 的新增条目）
_ADD_STRIP = {"id", "resumeId", "accountId", "createTime", "updateTime",
              "complete", "moduleId", "logoUrl", "diagnosis"}

# 官网项目描述长度上限（实测：2000 字通过、2500 字拒 100004；过短如 1 字也拒）
_PROJ_DESC_MAX = 2000


# ============================================================
# 数据加载（纯函数，可单测）
# ============================================================

def load_local():
    """优先读回写快照 51job_writeback.json，回退 51job_fields.json。
    返回 ({module: current_value}, 来源路径, freshness 新鲜度信息)"""
    from browser_common import load_writeback_source
    raw_fields, src, freshness = load_writeback_source("51job", SNAPSHOT_PATH, FIELDS_PATH)
    return {k: v.get("current_value") for k, v in raw_fields.items() if isinstance(v, dict)}, src, freshness


def _val(fields, module):
    v = fields.get(module)
    if isinstance(v, dict):
        return v.get("current_value", v)
    return v


def _norm_work_skills(skills):
    """将技能列表归一化为 51job 官方 workVocationalSkills 对象数组"""
    if not skills or not isinstance(skills, list):
        return []
    res = []
    for s in skills:
        if not s:
            continue
        if isinstance(s, str):
            name = s.strip()
            if name:
                res.append({
                    "skill": name,
                    "value": name,
                    "isCustomize": True,
                    "skillCode": "",
                    "direction": "",
                    "directionCode": "",
                })
        elif isinstance(s, dict):
            name = (s.get("skill") or s.get("value") or s.get("name") or "").strip()
            if name:
                res.append({
                    "skill": name,
                    "value": name,
                    "isCustomize": s.get("isCustomize", True),
                    "skillCode": s.get("skillCode", ""),
                    "direction": s.get("direction", ""),
                    "directionCode": s.get("directionCode", ""),
                })
    return res[:10]  # 51job 限制最多 10 个技能


def _norm_lang_certs(certs, cert_queries=None):
    """将语言证书列表归一化为 51job 官方 skillCertificationQueries 格式：
    [{cert: '0117', certString: '大学英语六级'}, ...]"""
    if cert_queries and isinstance(cert_queries, list):
        return cert_queries
    if not certs or not isinstance(certs, list):
        return []
    res = []
    for c in certs:
        if not c:
            continue
        if isinstance(c, str):
            res.append({"cert": c, "certString": ""})
        elif isinstance(c, dict):
            code = c.get("cert") or c.get("code") or ""
            name = c.get("certString") or c.get("value") or c.get("name") or ""
            if code:
                res.append({"cert": str(code), "certString": str(name)})
    return res
def _norm_cert_items(raw_items):
    """将资格证书列表归一化为标准的字典对象列表：
    输入可能是 ['0815', '0108'] 或 [{'cert': '0815', 'certName': 'C1驾照'}, ...]"""
    if not raw_items or not isinstance(raw_items, list):
        return []
    res = []
    seen = set()
    for it in raw_items:
        if isinstance(it, str) and it.strip():
            code = it.strip()
            if code not in seen:
                seen.add(code)
                res.append({"cert": code, "certName": "", "isEnglish": False, "startTime": ""})
        elif isinstance(it, dict):
            code = str(it.get("cert") or it.get("code") or "").strip()
            name = str(it.get("certName") or it.get("certString") or it.get("name") or "").strip()
            key = code or name.lower()
            if key and key not in seen:
                seen.add(key)
                item_dict = {
                    "cert": code,
                    "certName": name,
                    "isEnglish": it.get("isEnglish", False),
                    "startTime": it.get("startTime") or "",
                }
                if it.get("id"):
                    item_dict["id"] = it.get("id")
                res.append(item_dict)
    return res



def _strip_add_item(item):
    out = {}
    for k, v in item.items():
        if k in _ADD_STRIP:
            continue
        if v in ("True", "False"):  # 布尔字符串归一（映射值可能带字符串形态，服务端期望 bool）
            v = v == "True"
        out[k] = v
    # 51job 新增经历时 endTime 为 '至今' 必须清空为 None/""，否则 API 报 100004 日期格式错误
    if _norm(out.get("endTime")) == "至今":
        out["endTime"] = None
        out["endTimeString"] = "至今"
    # 技能字段归一化为官方 workVocationalSkills 格式
    if "workVocationalSkills" in out or "skills" in out:
        skills = out.get("workVocationalSkills") or out.get("skills") or []
        out["workVocationalSkills"] = _norm_work_skills(skills)
        out.pop("skills", None)
    # 语言能力字段归一化为官方期望格式（skillType, skillName, skillCertificationQueries, isEnglish: False）
    if "skillType" in out or "skill" in out:
        st = out.get("skillType") or out.get("skill")
        if st is not None:
            out["skillType"] = str(st)
            out.pop("skill", None)
    if "skillName" in out or "skillString" in out or "skillTypeString" in out:
        sn = out.get("skillName") or out.get("skillString") or out.get("skillTypeString")
        if sn is not None:
            out["skillName"] = str(sn)
            out.pop("skillString", None)
            out.pop("skillTypeString", None)
    if "certifications" in out or "skillCertificationQueries" in out:
        out["skillCertificationQueries"] = _norm_lang_certs(out.get("certifications"), out.get("skillCertificationQueries"))
        out.pop("certifications", None)
    # 资格证书字段归一化
    if "cert" in out or "certName" in out:
        out["cert"] = str(out.get("cert") or out.get("code") or "")
        out["certName"] = str(out.get("certName") or out.get("certString") or "")
        out["isEnglish"] = False
    # 专业技能 / 语言能力熟练度防空与防 100004 兜底
    if "ability" in out or "skillType" in out or "skillName" in out:
        ab = out.get("ability") or out.get("level") or "1"
        if str(ab) not in ("0", "1", "3", "2", "6", "5", "4"):
            ab = "1"
        out["ability"] = str(ab)
    # 工作类型与职位名称兜底（51job 官方对经历强校验 position 必填，缺失报 100004 请填写职位）
    if "workType" in out and out["workType"] is not None:
        out["workType"] = str(out["workType"])
    if ("companyName" in out or "workFunction" in out or "workDescription" in out) and not out.get("position"):
        out["position"] = out.get("workFunctionString") or out.get("jobTitle") or out.get("title") or "专业人员"
    # 工作经历所属行业与公司性质/规模
    if "workIndustry" in out or "industry" in out:
        ind = out.get("workIndustry") if out.get("workIndustry") is not None else out.get("industry")
        out["workIndustry"] = str(ind) if ind is not None else ""
        out["workIndustryNew"] = ""
    if "workIndustryString" in out or "industryName" in out:
        ind_name = out.get("workIndustryString") if out.get("workIndustryString") is not None else out.get("industryName")
        if ind_name is not None:
            out["workIndustryString"] = str(ind_name)
    if "companySize" in out and out["companySize"] is not None:
        out["companySize"] = str(out["companySize"])
    if "companyType" in out and out["companyType"] is not None:
        out["companyType"] = str(out["companyType"])
    # 项目所属公司（支持 company/companyName 别名，空/"无" 转 None）
    if "company" in out or "companyName" in out:
        comp = out.get("companyName") if out.get("companyName") is not None else out.get("company")
        out["companyName"] = None if comp in (None, "", "无") else str(comp).strip()
        out.pop("company", None)
    # 展示型派生字段缺失/为空时按时间生成（'YYYY-MM' → 'YYYY.MM'），缺失会被 100004 拒
    for tk, sk in (("startTime", "startTimeString"), ("endTime", "endTimeString")):
        tv = _norm(out.get(tk))
        if tv and not _norm(out.get(sk)):
            out[sk] = tv.replace("-", ".")
    if ("companyName" in out or "schoolName" in out) and out.get("endTime") is None and not out.get("endTimeString"):
        out["endTimeString"] = "至今"
    # 51job 官方对教育/经历/语言等布尔字段强校验（isEnglish 缺失会报 100004 参数校验错误）
    if "isEnglish" not in out or out["isEnglish"] is None:
        out["isEnglish"] = False
    if "isOverseas" in out:
        out["isOverseas"] = bool(out["isOverseas"]) if out["isOverseas"] not in (None, "") else False
    if "isMba" in out:
        out["isMba"] = bool(out["isMba"]) if out["isMba"] not in (None, "") else False
    if "isFullTime" in out:
        out["isFullTime"] = bool(out["isFullTime"]) if out["isFullTime"] not in (None, "") else True
    elif out.get("studyType"):
        out["isFullTime"] = (out.get("studyType") == "全日制")
    if "degree" in out and out["degree"] is not None:
        out["degree"] = str(out["degree"])
    if "majorName" in out and not out.get("majorString"):
        out["majorString"] = str(out["majorName"])
    return out


def _clip_proj_desc(payload):
    """项目描述超官网上限时截断（否则 100004 参数校验错误）；
    不在载荷内加标记字段（多余字段可能被 API 拒）"""
    d = payload.get("describe")
    if isinstance(d, str) and len(d) > _PROJ_DESC_MAX:
        payload["describe"] = d[:_PROJ_DESC_MAX]


# ============================================================
# 计划构建（纯函数，可单测）
# ============================================================

def _norm(v):
    """no-op 判定用的归一化：字符串去首尾空白，None -> ''"""
    if v is None:
        return ""
    return str(v).strip()


def _norm_time(v):
    """时间归一化：'至今'/None/'' 等价（官网「至今」存为 None，本地快照存为 '至今'）"""
    s = _norm(v)
    return "" if s in ("", "至今") else s


def _key_same(k, item, off_item):
    """单业务键对比：本地空值（未提供）视为与官网一致（edit 时官网打底不被覆盖）；
    官网纯数字码值 vs 本地文本视为一致（码值字段回写永远保留官网值，如 major=4000），
    否则每轮回写都会重复 edit（幂等性）。
    求职意向模块各字段为显式偏好配置，空值代表清空（如清除行业），需严格比对。"""
    if k == "expectIndustry":
        lv = _norm(item.get("expectIndustry") if item.get("expectIndustry") is not None else item.get("industry"))
        ov = _norm(off_item.get("expectIndustry") or off_item.get("industry"))
        return lv == ov
    if k == "expectArea":
        lv = _norm(item.get("expectArea") or item.get("expectAreaNames"))
        ov = _norm(off_item.get("expectArea") or off_item.get("expectAreaString"))
        return lv == ov
    if k == "expectFunction":
        lv = _norm(item.get("expectFunction") or item.get("expectFunctionName"))
        ov = _norm(off_item.get("expectFunction") or off_item.get("expectFunctionName"))
        return lv == ov
    if k in ("minSalary", "maxSalary", "salaryMonth", "seekType"):
        lv = _norm(item.get(k))
        ov = _norm(off_item.get(k))
        return lv == ov
    if k == "workVocationalSkills":
        l_skills = { (s if isinstance(s, str) else s.get("skill") or s.get("value") or "").strip()
                     for s in (item.get("workVocationalSkills") or item.get("skills") or []) if s }
        o_skills = { (s if isinstance(s, str) else s.get("skill") or s.get("value") or "").strip()
                     for s in (off_item.get("workVocationalSkills") or off_item.get("skills") or []) if s }
        return l_skills == o_skills or not l_skills
    if k in ("workIndustry", "industry"):
        lv = _norm(item.get("workIndustry") if item.get("workIndustry") is not None else item.get("industry"))
        ov = _norm(off_item.get("workIndustry") if off_item.get("workIndustry") is not None else off_item.get("industry"))
        if lv == "" and ov == "":
            return True
        return lv == ov or lv == ""
    if k in ("companySize", "companyType"):
        lv = _norm(item.get(k))
        ov = _norm(off_item.get(k))
        return lv == ov or lv == ""
    if k in ("workType", "seekType"):
        lv = _norm(item.get("seekType") if item.get("seekType") is not None else item.get("workType"))
        ov = _norm(off_item.get("seekType") if off_item.get("seekType") is not None else off_item.get("workType"))
        return lv == ov or lv == ""
    if k in ("companyName", "company"):
        lv = _norm(item.get("companyName") if item.get("companyName") is not None else item.get("company"))
        ov = _norm(off_item.get("companyName") if off_item.get("companyName") is not None else off_item.get("company"))
        if lv in ("", "无") and ov in ("", "无"):
            return True
        return lv == ov or lv == ""
    if k in ("skillType", "skill"):
        lv = _norm(item.get("skillType") or item.get("skill"))
        ov = _norm(off_item.get("skillType") or off_item.get("skill"))
        return lv == ov or lv == ""
    if k in ("skillName", "skillString", "skillTypeString"):
        lv = _norm(item.get("skillName") or item.get("skillString") or item.get("skillTypeString"))
        ov = _norm(off_item.get("skillName") or off_item.get("skillString") or off_item.get("skillTypeString"))
        return lv == ov or lv == "" or ov == ""
    if k == "ability":
        lv = _norm(item.get("ability"))
        ov = _norm(off_item.get("ability"))
        return lv == ov or lv == ""
    if k in ("cert", "code"):
        lv = _norm(item.get("cert") or item.get("code") if isinstance(item, dict) else item)
        ov = _norm(off_item.get("cert") or off_item.get("code") if isinstance(off_item, dict) else off_item)
        return lv == ov
    if k in ("skillCertificationQueries", "certifications"):
        l_certs = { (c if isinstance(c, str) else c.get("cert") or c.get("code") or "").strip()
                    for c in (item.get("certifications") or item.get("skillCertificationQueries") or []) if c }
        o_certs = { (c if isinstance(c, str) else c.get("cert") or c.get("code") or "").strip()
                    for c in (off_item.get("certifications") or off_item.get("skillCertificationQueries") or []) if c }
        return l_certs == o_certs

    lv = _norm_time(item.get(k)) if k == "endTime" else _norm(item.get(k))
    if lv == "":
        return True
    ov_raw = off_item.get(k)
    if isinstance(ov_raw, str) and ov_raw.isdigit() and not lv.isdigit():
        return True
    ov = _norm_time(ov_raw) if k == "endTime" else _norm(ov_raw)
    return lv == ov


def _build_intention_payload(item, official_item=None):
    """求职意向载荷构建：官网打底 + 本地覆盖，确保所有字段（seekType, expectArea, expectFunction, expectIndustry, minSalary, maxSalary, salaryMonth）规范入参"""
    off = official_item or {}

    # 行业：若本地有 expectIndustry 或 industry 键，以本地为准（空字符串代表清空为行业不限）；仅在本地完全未包含行业键时才回退官网
    if "expectIndustry" in item or "industry" in item:
        ind = _norm(item.get("expectIndustry") if item.get("expectIndustry") is not None else item.get("industry"))
    else:
        ind = _norm(off.get("expectIndustry") or off.get("industry"))

    area = _norm(item.get("expectArea") if item.get("expectArea") is not None else off.get("expectArea"))

    func = _norm(item.get("expectFunction") if item.get("expectFunction") is not None else off.get("expectFunction"))
    func_name = _norm(item.get("expectFunctionName") or item.get("expectFunctionString") or off.get("expectFunctionName") or off.get("expectFunctionString"))

    seek_type = _norm(item.get("seekType") if item.get("seekType") is not None else off.get("seekType") or "0")

    min_sal = item.get("minSalary") if item.get("minSalary") is not None else off.get("minSalary")
    max_sal = item.get("maxSalary") if item.get("maxSalary") is not None else off.get("maxSalary")

    sal_month = item.get("salaryMonth") if item.get("salaryMonth") is not None else off.get("salaryMonth")
    try:
        sal_month = int(sal_month) if sal_month is not None else 12
    except (ValueError, TypeError):
        sal_month = 12

    payload = {
        **{k: v for k, v in off.items() if k not in ("diagnosis",)},
        "salaryType": 1,
        "seekType": seek_type,
        "expectArea": area,
        "expectFunction": func if func else None,
        "expectFunctionName": func_name if func_name else None,
        "expectIndustry": ind if ind else None,
        "minSalary": min_sal,
        "maxSalary": max_sal,
        "salaryMonth": sal_month,
        "isEnglish": False,
        "intentionPreference": item.get("intentionPreference") or off.get("intentionPreference") or {}
    }
    if not official_item:
        for sk in _ADD_STRIP:
            payload.pop(sk, None)
    return payload


def _build_edit_payload(item, official_item=None):
    """edit 载荷：官网原条目打底 + 本地业务字段覆盖（借鉴 BOSS 回写经验：
    本地载荷缺 workFunction/workIndustry/licenseId 等官网必填码值字段会被 API 拒绝，
    必须以官网条目为底保留码值与 id）；endTime '至今'->None（官网语义存 None）。
    码值保护：官网纯数字码值字段（如 major=4000）不被本地文本覆盖，否则 100004 参数校验错误。
    派生字段剔除：*TimeString 由服务端据时间重算，残留旧值与时间不一致会报 100004"""
    payload = json.loads(json.dumps(official_item)) if official_item else json.loads(json.dumps(item))
    if official_item:
        for k, v in item.items():
            if k in ("id", "resumeId") or v in (None, ""):
                continue
            ov = official_item.get(k)
            if isinstance(ov, str) and ov.isdigit() and not str(v).isdigit():
                continue  # 官网是码值、本地是文本 → 保留官网码值
            payload[k] = v
        # 处理技能字段
        if "workVocationalSkills" in item or "skills" in item:
            skills = item.get("workVocationalSkills") or item.get("skills") or []
            payload["workVocationalSkills"] = _norm_work_skills(skills)
            payload.pop("skills", None)
        # 处理工作类型与职位名称
        if "workType" in item and item["workType"] is not None:
            payload["workType"] = str(item["workType"])
        if ("companyName" in payload or "workFunction" in payload or "workDescription" in payload) and not payload.get("position"):
            payload["position"] = payload.get("workFunctionString") or payload.get("jobTitle") or payload.get("title") or (official_item and official_item.get("position")) or "专业人员"
        # 处理工作经历所属行业与公司性质/规模
        if "workIndustry" in item or "industry" in item:
            ind = item.get("workIndustry") if item.get("workIndustry") is not None else item.get("industry")
            payload["workIndustry"] = str(ind) if ind is not None else ""
            payload["workIndustryNew"] = ""
        if "workIndustryString" in item or "industryName" in item:
            ind_name = item.get("workIndustryString") if item.get("workIndustryString") is not None else item.get("industryName")
            if ind_name is not None:
                payload["workIndustryString"] = str(ind_name)
        if "companySize" in item and item["companySize"] is not None:
            payload["companySize"] = str(item["companySize"])
        if "companyType" in item and item["companyType"] is not None:
            payload["companyType"] = str(item["companyType"])
        # 处理项目所属公司（支持 company/companyName 别名，空/"无" 转 None）
        if "company" in item or "companyName" in item:
            comp = item.get("companyName") if item.get("companyName") is not None else item.get("company")
            payload["companyName"] = None if comp in (None, "", "无") else str(comp).strip()
            payload.pop("company", None)
        # 处理语言能力字段
        if "skillType" in item or "skill" in item:
            st = item.get("skillType") or item.get("skill")
            if st is not None:
                payload["skillType"] = str(st)
                payload.pop("skill", None)
        if "skillName" in item or "skillString" in item or "skillTypeString" in item:
            sn = item.get("skillName") or item.get("skillString") or item.get("skillTypeString")
            if sn is not None:
                payload["skillName"] = str(sn)
                payload.pop("skillString", None)
                payload.pop("skillTypeString", None)
        if "certifications" in item or "skillCertificationQueries" in item:
            payload["skillCertificationQueries"] = _norm_lang_certs(item.get("certifications"), item.get("skillCertificationQueries"))
            payload.pop("certifications", None)
        # 处理资格证书
        if "cert" in item or "certName" in item:
            payload["cert"] = str(item.get("cert") or item.get("code") or payload.get("cert") or "")
            payload["certName"] = str(item.get("certName") or item.get("certString") or payload.get("certName") or "")
            payload["isEnglish"] = False
        if "ability" in item or "skillType" in item or "skillName" in item:
            ab = item.get("ability") or item.get("level") or payload.get("ability") or "1"
            if str(ab) not in ("0", "1", "3", "2", "6", "5", "4"):
                ab = "1"
            payload["ability"] = str(ab)
            payload["isEnglish"] = False
        # 时间变更时剔除展示型派生字段，由服务端重算，避免与时间字段不一致被拒
        for tk, sk in (("startTime", "startTimeString"), ("endTime", "endTimeString")):
            if _norm_time(item.get(tk)) and _norm_time(item.get(tk)) != _norm_time(official_item.get(tk)):
                payload.pop(sk, None)
    if _norm(payload.get("endTime")) == "至今":
        payload["endTime"] = None
    return payload


# 无 id 本地条目与官网条目的配对（借鉴 BOSS 回写经验：apply 映射后本地 id 丢失，
# 需按业务键重新配对并复用官网 id 走 edit，避免全删全增的破坏性回写）
# 加权评分：名称/公司权重最高（内容身份），时间次之；名称优先避免同时间条目互串
_MATCH_KEYS = {"works": [("companyName", 3), ("startTime", 1), ("endTime", 1)],
               "projects": [("projectName", 3), ("startTime", 1), ("endTime", 1)],
               "educations": [("schoolName", 3), ("degree", 2), ("startTime", 1), ("endTime", 1)],
               "language": [("skillType", 3), ("skill", 3), ("skillName", 3), ("skillString", 3), ("ability", 1)],
               "skills": [("skillType", 3), ("skill", 3), ("skillName", 3), ("skillTypeString", 3), ("ability", 1)],
               "intentions": [("expectFunction", 3), ("expectFunctionName", 3), ("expectArea", 1), ("expectIndustry", 1)]}


def _match_official(item, off_items, used_ids, mod):
    """为无 id 的本地条目配对官网条目，返回官网条目或 None。
    ① 语言能力与专业技能模块按码值/名称精准配对；
    ② 经历列表加权评分，且必须命中名称/公司键（权重>=3）才认可 —— 仅凭时间同分配对会把
    同起始时间的不同条目互串（真实事故：AI项目被写到全渠道条目上）；
    ③ 兜底：仅对非列表模块允许盲目配对"""
    if mod == "certifications":
        l_code = _norm(item.get("cert") or item.get("code") if isinstance(item, dict) else item)
        l_name = _norm(item.get("certName") or item.get("certString") or item.get("name") if isinstance(item, dict) else "").lower()
        for o in off_items:
            if str(o.get("id")) in used_ids:
                continue
            o_code = _norm(o.get("cert") or o.get("code"))
            o_name = _norm(o.get("certName") or o.get("certString") or o.get("name")).lower()
            if (l_code and o_code and l_code == o_code) or (l_name and o_name and l_name == o_name):
                return o
        return None

    if mod in ("language", "skills"):
        l_code = _norm(item.get("skillType") or item.get("skill"))
        l_name = _norm(item.get("skillName") or item.get("skillString") or item.get("skillTypeString")).lower()
        for o in off_items:
            if str(o.get("id")) in used_ids:
                continue
            o_code = _norm(o.get("skillType") or o.get("skill"))
            o_name = _norm(o.get("skillName") or o.get("skillString") or o.get("skillTypeString")).lower()
            if (l_code and o_code and l_code == o_code) or (l_name and o_name and l_name == o_name):
                return o
        return None

    keys = _MATCH_KEYS.get(mod, [])
    best, best_score = None, 0
    for o in off_items:
        if str(o.get("id")) in used_ids:
            continue
        score, named = 0, False
        for k, w in keys:
            if _norm(item.get(k)) and _norm_time(item.get(k)) == _norm_time(o.get(k)):
                score += w
                if w >= 3:
                    named = True
        if named and score > best_score:
            best, best_score = o, score
    if best is not None:
        return best
    if mod not in ("language", "skills", "works", "projects", "educations"):
        unused = [o for o in off_items if str(o.get("id")) not in used_ids]
        if len(unused) == 1:
            return unused[0]
    return None


def _add_already_landed(action, official):
    """add 动作失败后重试前的查重：按业务键判断该条目是否已在官网。

    add 接口无幂等保护——超时/CDP 中断型失败时请求可能已实际写入官网，
    盲目重发会造成同一段经历重复堆叠。查重偏宽松：宁可少写（漏写由复核兜底），
    绝不重复写。
    """
    mod = action.get("module")
    if mod not in LIST_MODULES:
        return False
    item = action.get("args", [None])[-1]
    if not isinstance(item, dict):
        return False
    return _match_official(item, official.get(mod) or [], set(), mod) is not None


def plan_writeback(local, official, selected_modules=None):
    """构建回写计划。返回 {actions, skipped}。
    local: {module: current_value}；official: 官网 resumeInfo 快照"""
    modules = selected_modules if selected_modules else ALL_MODULES
    actions, skipped = [], []

    # ---- 基本信息（单值模块：POST /open/resumes/{rid}/account-info） ----
    if "basic_info" in modules:
        local_base = _val(local, "basic_info") or {}
        off_base = official.get("basic_info") or {}

        # 51job 官方对实名信息（姓名、性别、出生年月）具有严格的只读防篡改保护，必须以官网实名数据为准，
        # 避免本地不同性别/姓名/生日值覆盖导致 API 报 100004 参数校验错误（“已实名账号暂不支持修改性别/姓名/出生年月”）
        c_name = _norm(off_base.get("cName") or local_base.get("cName"))
        sex = _norm(off_base.get("sex") or local_base.get("sex") or "1")
        birthday = _norm(off_base.get("birthday") or local_base.get("birthday"))

        wym = _norm(local_base.get("workYearMonth") or off_base.get("workYearMonth"))
        if "T" in wym:
            wym = wym.split("T")[0][:7]
        elif len(wym) > 7 and "-" in wym:
            wym = wym[:7]
        wy = wym[:4] if len(wym) >= 4 else _norm(local_base.get("workYear") or off_base.get("workYear") or "2016")

        area_val = local_base.get("area")
        area_id = area_val.get("id") if isinstance(area_val, dict) else _norm(area_val)
        if not area_id:
            off_area = off_base.get("area")
            area_id = off_area.get("id") if isinstance(off_area, dict) else _norm(off_area)

        household_val = local_base.get("household")
        household_id = household_val.get("id") if isinstance(household_val, dict) else _norm(household_val)
        if not household_id:
            off_hh = off_base.get("household")
            household_id = off_hh.get("id") if isinstance(off_hh, dict) else _norm(off_hh)

        person_as_label = _norm(local_base.get("personAsLabel") or off_base.get("personAsLabel") or "2")
        politics_status = _norm(local_base.get("politicsStatus") or off_base.get("politicsStatus") or "06")
        current_situation, situation_warning = _resolve_current_situation(local_base, off_base)
        if situation_warning:
            print(f"  [WARN] 前程无忧：{situation_warning}")
        wechat_id = _norm(local_base.get("wechatId") if local_base.get("wechatId") is not None else off_base.get("wechatId"))

        payload = {
            "cName": c_name,
            "sex": sex,
            "workYearMonth": wym,
            "isNoWorkExperience": not bool(wym),
            "workYear": wy,
            "birthday": birthday,
            "personAsLabel": person_as_label,
            "politicsStatus": politics_status,
            "area": area_id,
            "currentSituation": current_situation,
            "wechatId": wechat_id,
            "household": household_id,
        }

        # 检查可编辑字段是否发生变化
        diffs = []
        off_area_id = off_base.get("area") if not isinstance(off_base.get("area"), dict) else off_base.get("area", {}).get("id")
        if area_id and area_id != _norm(off_area_id):
            diffs.append("居住地")
        off_hh_id = off_base.get("household") if not isinstance(off_base.get("household"), dict) else off_base.get("household", {}).get("id")
        if household_id and household_id != _norm(off_hh_id):
            diffs.append("户口")
        if current_situation and current_situation != _norm(off_base.get("currentSituation")):
            diffs.append("求职状态")
        if wym and wym != _norm(off_base.get("workYearMonth")):
            diffs.append("工作时间")
        if person_as_label and person_as_label != _norm(off_base.get("personAsLabel")):
            diffs.append("身份")
        if politics_status and politics_status != _norm(off_base.get("politicsStatus")):
            diffs.append("政治面貌")
        if wechat_id != _norm(off_base.get("wechatId")):
            diffs.append("微信")

        if not diffs:
            skipped.append({"module": "basic_info", "reason": "与官网一致，无需回写"})
        else:
            actions.append({
                "module": "basic_info",
                "op": "edit",
                "method": "editBaseInfo",
                "args": [payload, "__RID__", {"loading": False}],
                "detail": f"基本信息 edit（变更: {','.join(diffs)}）"
            })

    # ---- 自我介绍（单值模块） ----
    if "self_introduction" in modules:
        local_si = _val(local, "self_introduction") or {}
        want = _norm(local_si.get("selfIntroduction", ""))
        cur = _norm(official.get("selfIntroduction", ""))
        if not want:
            skipped.append({"module": "self_introduction", "reason": "本地为空，跳过"})
        elif want == cur:
            skipped.append({"module": "self_introduction", "reason": "与官网一致，无需回写"})
        else:
            actions.append({"module": "self_introduction", "op": "edit", "method": "editSelfIntroduction",
                            "args": ["__RID__", {"selfIntroduction": want, "api_key": "51job"}],
                            "detail": f"自我介绍 edit（{len(want)}字）"})

    # ---- 列表模块（全量覆盖：按 id edit/add/del） ----
    for mod in ["intentions", "works", "projects", "educations", "skills",
                "language", "certifications"]:
        if mod not in modules:
            continue
        cfg = LIST_MODULES[mod]
        local_items = _val(local, mod) or []
        if mod == "certifications":
            local_items = _norm_cert_items(local_items)
        elif mod == "skills":
            invalid_pats = ["大模型与", "全栈开发与", "数据分析与", "设计与", "辅助与", "开发与架构"]
            raw_skills = [
                it for it in local_items
                if isinstance(it, dict) and (
                    it.get("skillType") or
                    (it.get("skillName") and not any(p in str(it.get("skillName", "")) for p in invalid_pats) and len(str(it.get("skillName", ""))) <= 20)
                ) and not (str(it.get("skillType") or "").startswith("22") or str(it.get("skillCategory") or "").strip() == "语言类")
            ]
            # 互斥去重保护：51job 官网同一技能不允许重复添加，按 skillType 或 skillName 去重（保留排在前面的或有 id 的）
            seen_skills = set()
            local_items = []
            for it in raw_skills:
                sk_key = (str(it.get("skillType") or "").strip() or str(it.get("skillName") or it.get("skillTypeString") or "").strip().lower())
                if sk_key and sk_key not in seen_skills:
                    seen_skills.add(sk_key)
                    local_items.append(it)
        off_items = official.get(mod) or []
        if not local_items:
            # 本地为空（未采集到/主简历未提供）时绝不删官网已有条目，避免误删用户数据
            if off_items:
                skipped.append({"module": mod, "reason": f"本地为空，保留官网现有 {len(off_items)} 条（不删）"})
            else:
                skipped.append({"module": mod, "reason": "本地与官网均为空，无需回写"})
            continue
        off_by_id = {str(o.get("id")): o for o in off_items if o.get("id") is not None}
        used_off_ids = set()

        edit_cnt = add_cnt = noop_cnt = 0
        module_edit_actions = []
        module_add_actions = []
        for li, item in enumerate(local_items):
            iid = str(item.get("id") or "")
            if iid in used_off_ids:
                iid = ""  # ID 已被前面的条目使用，清空以重新配对或走 add
            if not (iid and iid in off_by_id):
                # 本地无 id（apply 映射覆盖后 id 丢失 / 或重复 id）→ 按业务键配对官网条目，复用其 id 走 edit
                matched = _match_official(item, off_items, used_off_ids, mod)
                if matched:
                    iid = str(matched.get("id"))
                    off_by_id[iid] = matched
            if iid and iid in off_by_id and iid not in used_off_ids:
                # no-op 判定：业务键全部一致则跳过该条 edit（本地空值视为未提供）
                same = all(_key_same(k, item, off_by_id[iid]) for k in cfg["keys"])
                if same:
                    noop_cnt += 1
                    used_off_ids.add(iid)
                    continue
                act = {"module": mod, "op": "edit", "method": cfg["edit"],
                       "args": (["__RID__", iid, _build_edit_payload(item, off_by_id[iid])] if mod != "intentions"
                                else [iid, _build_intention_payload(item, off_by_id[iid])]),
                       "detail": f"{mod} edit id={iid}"}
                if mod == "projects":
                    _clip_proj_desc(act["args"][-1])
                module_edit_actions.append(act)
                edit_cnt += 1
                used_off_ids.add(iid)
            else:
                if cfg["add"] is None:
                    skipped.append({"module": mod, "reason": f"本地新增条目[{li}]无官网 id，该模块不支持 add"})
                    continue
                act = {"module": mod, "op": "add", "method": cfg["add"],
                       "args": (["__RID__", _strip_add_item(item)] if mod != "intentions"
                                else [_build_intention_payload(item)]),
                       "detail": f"{mod} add（本地新增，无 id）"}
                if mod == "projects":
                    _clip_proj_desc(act["args"][-1])
                module_add_actions.append(act)
                add_cnt += 1

        local_ids = {str(i.get("id")) for i in local_items if i.get("id")}
        dels = [o for o in off_items
                if str(o.get("id")) not in local_ids and str(o.get("id")) not in used_off_ids]
        module_del_actions = []
        for o in dels:
            oid = str(o.get("id"))
            module_del_actions.append({"module": mod, "op": "del", "method": cfg["del"],
                                       "args": (["__RID__", oid] if mod != "intentions" else [oid]),
                                       "detail": f"{mod} del id={oid}（官网多余）"})

        # 【核心保护】优先执行 del 清理多余项腾出配额，再执行 edit / add，防止触碰官网条目上限（如证书上限20条报错 201604）
        actions.extend(module_del_actions)
        actions.extend(module_edit_actions)
        actions.extend(module_add_actions)

        if not (edit_cnt or add_cnt or dels):
            skipped.append({"module": mod,
                            "reason": f"与官网一致（{noop_cnt} 条 no-op），无需回写"})

    return {"actions": actions, "skipped": skipped}


# ============================================================
# 浏览器交互
# ============================================================

JS_WAIT_READY = r"""
return (function(){
    var n = document.querySelector('#__nuxt');
    if (!n || !n.__vue__) return 'no';
    function f(c, nm, d){ if(d>10)return null; if((c.$options.name||'')===nm)return c;
      var ch=c.$children||[]; for(var i=0;i<ch.length;i++){var x=f(ch[i],nm,d+1); if(x)return x;} return null; }
    var pc = f(n.__vue__,'PCResume',0);
    return (pc && pc.$data.resumeInfo && pc.$data.resumeInfo.resumeId) ? 'yes' : 'no';
})();
"""

# 拉官网当前全量数据（resumeInfo + 自我介绍）
JS_READ_OFFICIAL = r"""
return (async function() {
  var nuxt = document.querySelector('#__nuxt') || document.querySelector('#app');
  if (!nuxt || !nuxt.__vue__) return JSON.stringify({error: 'no vue'});
  var vm = nuxt.__vue__;
  function findByName(c, n, d) {
    if (d > 10) return null;
    if ((c.$options.name || '') === n) return c;
    var ch = c.$children || [];
    for (var i = 0; i < ch.length; i++) { var f = findByName(ch[i], n, d + 1); if (f) return f; }
    return null;
  }
  var pc = findByName(vm, 'PCResume', 0);
  if (!pc) return JSON.stringify({error: 'PCResume not found'});
  var ri = JSON.parse(JSON.stringify(pc.$data.resumeInfo));
  var out = {resumeId: String(ri.resumeId)};
  ['intentions', 'works', 'projects', 'educations', 'skills', 'language', 'certifications']
    .forEach(function(k) { out[k] = ri[k] || []; });
  var ai = ri.accountInfo || {};
  out.basic_info = {
    cName: ai.cName || '',
    sex: ai.sex || '0',
    birthday: ai.birthday || '',
    workYearMonth: ai.workYearMonth || '',
    workYear: ai.workYear || '',
    personAsLabel: ai.personAsLabel || '2',
    politicsStatus: ai.politicsStatus || '06',
    area: typeof ai.area === 'object' ? (ai.area.id || '') : (ai.area || ''),
    areaString: typeof ai.area === 'object' ? (ai.area.label || '') : (ai.areaString || ''),
    household: typeof ai.household === 'object' ? (ai.household.id || '') : (ai.household || ''),
    currentSituation: (ai.newCurrentSituation !== undefined && ai.newCurrentSituation !== null && ai.newCurrentSituation !== '') ? String(ai.newCurrentSituation) : ((ai.currentSituation !== undefined && ai.currentSituation !== null && ai.currentSituation !== '') ? String(ai.currentSituation) : '5'),
    currentSituationString: ai.newCurrentSituationString || ai.currentSituationString || '',
    wechatId: ai.wechatId || '',
    mobile: ai.mobile || '',
    email: ai.email || ''
  };
  try {
    var ra = vm.$api.resumeApi;
    var r = await ra.getSelfIntroduction(out.resumeId, {api_key: '51job'});
    var nb = (r && r.resultbody !== undefined) ? r : (r && r.data);
    out.selfIntroduction = (nb && nb.resultbody && nb.resultbody.selfIntroduction) || '';
  } catch (e) { out.siErr = String(e); }
  if (out.language && out.language.length > 0 && vm.$api && vm.$api.resumeApi && vm.$api.resumeApi.getCertifications) {
    for (var li = 0; li < out.language.length; li++) {
      var langItem = out.language[li];
      try {
        var cRes = await vm.$api.resumeApi.getCertifications(out.resumeId, langItem.skillType, {isEnglish: false}, {loading: false});
        var cData = (cRes && cRes.resultbody && cRes.resultbody.data) || [];
        langItem.skillCertificationQueries = cData.map(function(c) { return { cert: c.cert, certString: c.certString || c.certName || '' }; });
        langItem.certifications = cData.map(function(c) { return c.cert; });
      } catch (e) {
        langItem.skillCertificationQueries = [];
        langItem.certifications = [];
      }
    }
  }
  return JSON.stringify(out);
})();
"""

# 执行单个回写动作（method/args 由 Python 逐个注入，占位符 __METHOD__ / __ARGS_JSON__）
# 逐动作独立 run_js（借鉴 BOSS 回写经验：批量串行 + 重试会撞 run_js 30s 超时）
JS_EXECUTE = r"""
return (async function() {
  var nuxt = document.querySelector('#__nuxt') || document.querySelector('#app');
  if (!nuxt || !nuxt.__vue__) return JSON.stringify({error: 'no vue'});
  var vm = nuxt.__vue__;
  function findByName(c, n, d) {
    if (d > 10) return null;
    if ((c.$options.name || '') === n) return c;
    var ch = c.$children || [];
    for (var i = 0; i < ch.length; i++) { var f = findByName(ch[i], n, d + 1); if (f) return f; }
    return null;
  }
  var pc = findByName(vm, 'PCResume', 0);
  if (!pc) return JSON.stringify({error: 'PCResume not found'});
  var rid = String(pc.$data.resumeInfo.resumeId);
  var ra = vm.$api.resumeApi;
  function norm(r) { return (r && r.resultbody !== undefined) ? r : (r && r.data); }
  var fn = ra['__METHOD__'];
  if (!fn) return JSON.stringify({resumeId: rid, ok: false, error: 'method missing: __METHOD__'});
  var args = __ARGS_JSON__.map(function(x) { return (x === '__RID__') ? rid : x; });
  var rec = {ok: false};
  try {
    var rawRes = await fn.apply(null, args);
    var r = norm(rawRes);
    rec.status = r && r.status;
    rec.message = r && r.message;
    rec.ok = String(r && r.status) === '1';
    rec.tips = (r && r.resultbody && r.resultbody.tips) || (r && r.tips) || (rawRes && rawRes.tips) || null;
    rec.resultbody = (r && r.resultbody) || (rawRes && rawRes.resultbody) || null;
    if (!rec.ok && r !== undefined && r !== null) rec.body = (JSON.stringify(r) || '').slice(0, 500);
  } catch (e) {
    rec.error = String(e).slice(0, 300);
  }
  rec.resumeId = rid;
  return JSON.stringify(rec);
})();
"""

def _diagnose_writeback_failure(action, resp):
    """根据官网接口错误响应（status, message, tips, resultbody）进行智能化诊断并生成行动建议。

    返回字典:
    {
        "field": 出错字段名 (如 "position", "sex", "describe" 等),
        "diagnosis": 错误简述 (如 "职位名称未填写"),
        "suggestion": 明确的调整方向建议,
        "tips_str": tips 原始序列化字符串,
        "tips": 原始 tips 对象
    }
    """
    mod = action.get("module", "")
    status = str(resp.get("status") or "")
    msg = resp.get("message") or resp.get("error") or ""

    # 提取 tips 字典或字符串
    tips = resp.get("tips")
    if not tips and isinstance(resp.get("resultbody"), dict):
        tips = resp.get("resultbody", {}).get("tips")
    if not tips and isinstance(resp.get("body"), str) and "tips" in resp.get("body"):
        try:
            body_json = json.loads(resp.get("body"))
            tips = body_json.get("tips") or (body_json.get("resultbody") or {}).get("tips")
        except Exception:
            pass

    field = None
    diag = None
    sugg = None
    tips_str = json.dumps(tips, ensure_ascii=False) if isinstance(tips, (dict, list)) else str(tips or "")

    if isinstance(tips, dict):
        if "position" in tips:
            field = "position"
            diag = "职位名称 (position) 缺失"
            sugg = "💡 建议调整方向：检测到职位名称未填写，请在「工作经历」编辑卡片中填写自定义职位或选取职位类目。"
        elif "sex" in tips:
            field = "sex"
            diag = "账号已实名，性别禁止修改"
            sugg = "💡 建议调整方向：当前账号已完成实名认证，性别为防篡改只读字段，请保持与官网实名数据一致。"
        elif "cName" in tips:
            field = "cName"
            diag = "账号已实名，姓名禁止修改"
            sugg = "💡 建议调整方向：当前账号已实名，姓名不可直接修改，如需变更请在 51job 官网发起实名更名认证。"
        elif "birthday" in tips:
            field = "birthday"
            diag = "账号已实名，出生年月禁止修改"
            sugg = "💡 建议调整方向：出生年月属于实名防篡改凭据，请通过官网实名核验调整。"
        elif "describe" in tips or "workDescription" in tips:
            field = "describe"
            diag = "描述内容字数超出官网限制（上限 2000 字）"
            sugg = "💡 建议调整方向：请将该条目内容精简至 10 ~ 2000 字以内后重试。"
        elif "isEnglish" in tips:
            field = "isEnglish"
            diag = "语言/经历缺少 isEnglish 标识"
            sugg = "💡 建议调整方向：请点击保存快照重新提取规范化布尔值后再次回写。"
        elif "skillType" in tips or "skillName" in tips or "ability" in tips:
            field = "skill"
            diag = "技能词条或熟练度不符合 51job 官方规范"
            sugg = "💡 建议调整方向：51job 官方仅支持 111 项标准 IT 技能白名单，请在技能选择器中挑选标准词并设置熟练度。"
        elif "companyName" in tips:
            field = "companyName"
            diag = "公司名称未填写或不合规"
            sugg = "💡 建议调整方向：请在对应经历卡片中补充公司名称。"
        elif "startTime" in tips or "endTime" in tips:
            field = "time"
            diag = "起止时间格式或范围不合法"
            sugg = "💡 建议调整方向：时间格式需为 YYYY-MM（如 2024-05），且开始时间不得晚于结束时间。"
        else:
            first_k = list(tips.keys())[0] if tips else "unknown"
            first_v = tips[first_k] if tips else ""
            field = str(first_k)
            diag = f"{first_k}: {first_v}"
            sugg = f"💡 建议调整方向：请检查「{first_k}」字段配置（官方提示：{first_v}）。"

    if not diag:
        if status == "201604" or "最多允许" in msg:
            field = "count_limit"
            diag = f"数量超出官网限制 ({msg or '最多允许20条'})"
            sugg = f"💡 建议调整方向：51job 官方对「{mod}」模块有数量上限限制（如证书最多20条），请精简数量后重试。"
        elif status == "100004":
            diag = "参数校验错误 (status=100004)"
            sugg = f"💡 建议调整方向：请检查「{mod}」模块各字段格式、必填项完整性与字数限制。"
        elif "method missing" in msg:
            diag = "官网端点未找到"
            sugg = "💡 建议调整方向：请确认当前页面已完全加载且处于在线简历编辑态。"
        else:
            diag = msg or f"回写执行异常 (status={status})"
            sugg = "💡 建议调整方向：请检查网络连接或稍后重试。"

    return {
        "field": field,
        "diagnosis": diag,
        "suggestion": sugg,
        "tips_str": tips_str if tips_str else None,
        "tips": tips,
    }



def _wait_ready(tab, tries=15):
    for _ in range(tries):
        if tab.run_js(JS_WAIT_READY) == "yes":
            return True
        time.sleep(1)
    return False


def _read_official(tab):
    tab.get(RESUME_URL)
    if not _wait_ready(tab):
        raise RuntimeError("PCResume/resumeInfo 加载失败（页面未就绪）")
    data = json.loads(tab.run_js(JS_READ_OFFICIAL))
    if data.get("error"):
        raise RuntimeError(f"读取官网数据失败: {data['error']}")
    return data


# ============================================================
# 复核（回写后重新读官网，逐模块比对）
# ============================================================

def verify_results(verify_off, local, plan):
    """复核：对比回写后官网数据与本地目标值。纯函数，可单测"""
    out = []
    touched = {a["module"] for a in plan["actions"]}
    for mod in ALL_MODULES:
        if mod not in touched:
            continue
        if mod == "basic_info":
            local_base = _val(local, "basic_info") or {}
            off_base = verify_off.get("basic_info") or {}
            bad = []
            for k, label in [("currentSituation", "求职状态"), ("area", "居住地"), ("household", "户口")]:
                lv = local_base.get(k)
                lv_id = lv.get("id") if isinstance(lv, dict) else _norm(lv)
                ov = off_base.get(k)
                ov_id = ov.get("id") if isinstance(ov, dict) else _norm(ov)
                if k == "currentSituation" and lv_id and lv_id not in _LEGAL_CURRENT_SITUATION:
                    # 非法值在规划阶段已跳过写入、官网保留原值，不进复核口径
                    continue
                if lv_id and ov_id and lv_id != ov_id:
                    bad.append(f"{label}不一致")
            out.append({"module": mod, "match": not bad, "note": "已生效" if not bad else "; ".join(bad)})
            continue
        if mod == "self_introduction":
            local_si = _val(local, "self_introduction") or {}
            want = _norm(local_si.get("selfIntroduction", ""))
            cur = _norm(verify_off.get("selfIntroduction", ""))
            match = (want == cur) or not want
            out.append({"module": mod, "match": match, "note": "已生效" if match else "官网值不一致"})
            continue
        if mod == "intentions":
            local_items = _val(local, "intentions") or []
            off_items = verify_off.get("intentions") or []
            off_by_id = {str(o.get("id")): o for o in off_items if o.get("id") is not None}
            bad = []
            for item in local_items:
                iid = str(item.get("id") or "")
                matched = off_by_id.get(iid) if iid in off_by_id else _match_official(item, off_items, set(), "intentions")
                if matched:
                    # 1. 期望行业
                    lv_ind = _norm(item.get("expectIndustry") if item.get("expectIndustry") is not None else item.get("industry"))
                    ov_ind = _norm(matched.get("expectIndustry") or matched.get("industry"))
                    if lv_ind != ov_ind:
                        bad.append(f"行业不一致(期望{lv_ind} vs 官网{ov_ind})")
                    # 2. 期望城市
                    lv_area = _norm(item.get("expectArea"))
                    ov_area = _norm(matched.get("expectArea"))
                    if lv_area and ov_area and lv_area != ov_area:
                        bad.append("城市不一致")
                    # 3. 期望职位
                    lv_func = _norm(item.get("expectFunction") or item.get("expectFunctionName"))
                    ov_func = _norm(matched.get("expectFunction") or matched.get("expectFunctionName"))
                    if lv_func and ov_func and lv_func != ov_func:
                        bad.append("职位不一致")
                    # 4. 最低薪资
                    if item.get("minSalary") and matched.get("minSalary") and str(item.get("minSalary")) != str(matched.get("minSalary")):
                        bad.append("最低薪资不一致")
                    # 5. 最高薪资
                    if item.get("maxSalary") and matched.get("maxSalary") and str(item.get("maxSalary")) != str(matched.get("maxSalary")):
                        bad.append("最高薪资不一致")
                    # 6. 工作类型
                    if item.get("seekType") is not None and matched.get("seekType") is not None and str(item.get("seekType")) != str(matched.get("seekType")):
                        bad.append("工作类型不一致")
                    # 7. 薪资月数
                    if item.get("salaryMonth") and matched.get("salaryMonth") and str(item.get("salaryMonth")) != str(matched.get("salaryMonth")):
                        bad.append("薪资月数不一致")
            if len(off_items) != len(local_items):
                bad.append(f"条数不一致 官网{len(off_items)} vs 本地{len(local_items)}")
            out.append({"module": mod, "match": not bad,
                        "note": "; ".join(bad) if bad else f"{len(local_items)} 条已生效"})
            continue
        cfg = LIST_MODULES[mod]
        local_items = _val(local, mod) or []
        if mod == "certifications":
            local_items = _norm_cert_items(local_items)
        off_items = verify_off.get(mod) or []
        off_by_id = {str(o.get("id")): o for o in off_items if o.get("id") is not None}
        bad = []
        for item in local_items:
            iid = str(item.get("id") or "")
            matched = off_by_id.get(iid) if (iid and iid in off_by_id) else _match_official(item, off_items, set(), mod)
            if matched:
                same = all(_key_same(k, item, matched) for k in cfg["keys"])
                if not same:
                    bad_keys = [k for k in cfg["keys"] if not _key_same(k, item, matched)]
                    bad.append(f"{mod}条目[{matched.get('id', '')}]不一致({','.join(bad_keys)})")
        if len(off_items) != len(local_items):
            bad.append(f"条数不一致 官网{len(off_items)} vs 本地{len(local_items)}")
        out.append({"module": mod, "match": not bad,
                    "note": "; ".join(bad) if bad else f"{len(local_items)} 条已生效"})
    return out


# ============================================================
# 主流程
# ============================================================

def run_write_back(dry_run=False, selected_paths=None):
    print("=" * 52)
    print("  51job - 本地数据回写官网在线简历")
    print("=" * 52)

    selected = None
    if selected_paths:
        selected = [m for m in selected_paths if m in ALL_MODULES]
        for p in selected_paths:
            if p in HARD_SKIP:
                print(f"  [HARD_SKIP] {p}: {HARD_SKIP[p]}")
            elif p not in ALL_MODULES:
                print(f"  [WARN] 未知模块: {p}")
        if not selected:
            print("  [ERROR] 勾选的模块全部不可回写")
            sys.exit(1)

    if not os.path.exists(SNAPSHOT_PATH) and not os.path.exists(FIELDS_PATH):
        print("  [ERROR] 本地数据不存在（51job_writeback.json / 51job_fields.json）")
        sys.exit(1)
    local, src, freshness = load_local()
    print(f"  数据源: {os.path.basename(src)}")
    # 回写全局空数据守卫：本地近乎为空时拒绝，防止把空内容推上官网
    from browser_common import ensure_writable_data
    ensure_writable_data("51job", local)
    if freshness.get("stale"):
        print(f"  [WARN] {freshness['warning']}")

    page = connect_page(PORT)
    print(f"  已连接浏览器 (端口 {PORT})")
    tab = page.latest_tab
    if "login" in tab.url.lower() or "passport" in tab.url.lower():
        print("  [ERROR] 未登录")
        sys.exit(1)

    official = _read_official(tab)
    print(f"  已读取官网当前数据 resumeId={official.get('resumeId')}")

    plan = plan_writeback(local, official, selected)

    print("\n  ── 回写计划 ──")
    for a in plan["actions"]:
        print(f"    [写] {a['module']:20} {a['detail']}")
    for s in plan["skipped"]:
        print(f"    [跳] {s['module']:20} {s['reason']}")

    if dry_run:
        print("\n  [DRY-RUN] 未执行实际回写")
        return {"plan": plan}

    if not plan["actions"]:
        print("\n  无需回写（全部与官网一致）")
        return {"plan": plan, "results": [], "verify": []}

    print("\n  ── 执行回写 ──")
    results = []
    for i, a in enumerate(plan["actions"]):
        js_exec = (JS_EXECUTE
                   .replace("__METHOD__", a["method"])
                   .replace("__ARGS_JSON__", json.dumps(a["args"], ensure_ascii=False)))
        r = {}
        for attempt in range(3):  # 单动作重试（接口偶发瞬时失败，成功即停）
            try:
                r = json.loads(tab.run_js(js_exec))
            except Exception as e:
                r = {"ok": False, "error": f"run_js 异常: {str(e)[:200]}"}
            if r.get("ok") or "method missing" in str(r.get("error", "")):
                break
            # add 无幂等：超时/中断型失败时请求可能已在官网生效，盲目重发会重复堆叠。
            # 重试前重读官网按业务键查重，已存在则视为成功，不再重发。
            if a.get("op") == "add" and attempt < 2:
                try:
                    if _add_already_landed(a, _read_official(tab)):
                        r = {"ok": True, "message": "接口报错但官网已存在该条目（业务键查重命中），跳过重试"}
                        break
                except Exception:
                    pass
            time.sleep(1)
        ok = bool(r.get("ok"))
        tag = "OK " if ok else "FAIL"
        diag_info = _diagnose_writeback_failure(a, r)
        print(f"    [{tag}] {a['module']:20} {a['detail']} "
              f"status={r.get('status')} {r.get('message') or r.get('error') or ''}")
        if not ok:
            if diag_info.get("tips_str"):
                print(f"           ├─ 官方报错详情: {diag_info['tips_str']}")
            if diag_info.get("diagnosis"):
                print(f"           ├─ 出错原因定位: {diag_info['diagnosis']}")
            if diag_info.get("suggestion"):
                print(f"           └─ {diag_info['suggestion']}")

        results.append({
            **a,
            "resp_status": r.get("status"),
            "resp_message": r.get("message") or r.get("error"),
            "tips": diag_info.get("tips"),
            "diagnosis": diag_info.get("diagnosis"),
            "suggestion": diag_info.get("suggestion"),
            "ok": ok,
        })
        time.sleep(0.8)

    # ---- 复核：重新拉官网数据对比 ----
    print("\n  ── 复核 ──")
    time.sleep(2)
    verify_off = _read_official(tab)
    verify = verify_results(verify_off, local, plan)
    for v in verify:
        tag = "✓" if v["match"] else "✗"
        print(f"    [{tag}] {v['module']:20} {v['note']}")

    succ = sum(1 for r in results if r["ok"])
    print(f"\n  回写完成：{succ}/{len(results)} 成功")
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
        if (a in ("--paths", "--modules")) and i + 1 < len(sys.argv):
            paths = [p.strip() for p in sys.argv[i + 1].split(",") if p.strip()]
    result = run_write_back(dry_run=dry, selected_paths=paths)
    if as_json:
        print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    if dry:
        sys.exit(0)
    ok_all = all(r.get("ok") for r in result.get("results", []))
    verify_bad = [v for v in result.get("verify", []) if not v.get("match")]
    sys.exit(0 if ok_all and not verify_bad else 2)
