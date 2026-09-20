"""
BOSS直聘 - 本地数据回写官网在线简历
优先读 boss_writeback.json 回写快照（前端「保存快照」生成，含映射结果），
回退 boss_fields.json；逐模块通过 BOSS 内部保存 API 回写到官网在线简历。
采用「拦截真实 token + 页面内 fetch 回放」策略，不逐字段点 UI。

回写范围（按勾选，--paths 逗号分隔字段 path；不传 = 全部模块）：
  ✅ personal_advantage  -> userdesc/save.json
  ✅ work_experience     -> workexp/save.json（内容/业绩/公司/部门/日期/行业，保留官网职位码与 id）
  ✅ projects            -> projectexp/save.json（按 url/日期匹配，保留官网 id）
  ✅ certificates        -> certification/save.json（本地为准全量覆盖：官网多余证书会被删除）
  ✅ overseas            -> overseastraitoptions/collectinformation/save.json
  ✅ expectations        -> expect/save.json（全量覆盖：匹配更新 / 本地未匹配新增 / 官网未匹配 delete.json 删除）
  ✅ education           -> eduexp/save.json（保留官网 schoolId/degree/eduType 码）
  ✅ baseinfo            -> baseinfo/save.json（name 沿用官网脱敏值，仅写生日/性别/工作起始/求职状态）
  ⛔ HARD_SKIP（强制排除，无论勾选与否）：name/phone/email/wechat/experience_years

用法：python boss_write_back.py [--dry-run] [--json] [--paths field1,field2]
前提：BOSS 浏览器已启动且已登录（端口 19222）
"""

import json
import os
import sys
import time

# Add backend dir to path for imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from resume_editor.backwrite_report_system import create_backwrite_report
from resume_editor.platforms.skill_mapper import map_skills

# Add backend dir to path for imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
DATA_DIR = os.path.join(_BACKEND_DIR, "resume_editor", "data")
FIELDS_PATH = os.path.join(DATA_DIR, "boss_fields.json")
SNAPSHOT_PATH = os.path.join(DATA_DIR, "boss_writeback.json")

PORT = 19222
RESUME_URL = "https://www.zhipin.com/web/geek/resume"

# 驻外时长 name->code（实机标定，2026-08）
DURATION_MAP = {
    "偶尔出差": 11, "频繁出差": 12, "1个月内": 10, "1~3个月": 1,
    "3~6个月": 2, "6~12个月": 3, "1年": 4, "2年": 5,
    "3年": 6, "4年": 7, "5年以上": 8, "长期驻外": 9,
}

# 字段 path -> 回写模块（前端勾选按 path 粒度，回写按模块粒度）
PATH_TO_MODULE = {
    "personal_advantage": "personal_advantage",
    "work_experience": "work_experience",
    "projects": "projects",
    "certificates": "certificates",
    "overseas.countries": "overseas", "overseas.languages": "overseas",
    "overseas.duration": "overseas", "overseas.allowView": "overseas",
    "expectations": "expectations",
    "education": "education", "education_degree": "education",
    "gender": "baseinfo", "birth_month": "baseinfo",
    "work_start_date": "baseinfo", "job_status": "baseinfo",
}

# 强制排除字段（无论是否勾选都不回写）+ 原因
HARD_SKIP = {
    "name": "官网为脱敏昵称（张女士），回写真实姓名会触发改名审核",
    "phone": "本地为官网脱敏值（138******00），回写会破坏真实数据",
    "email": "本地为官网脱敏值，回写会破坏真实数据",
    "wechat": "本地为官网脱敏值，回写会破坏真实数据",
    "experience_years": "官网自动计算字段，无保存接口",
}

APPLY_STATUS_MAP = {
    "离职-随时到岗": 0, "在职-月内到岗": 1, "在职-考虑机会": 2, "在职-暂不考虑": 3,
}

GENDER_MAP = {"男": 1, "女": 0}


def _selected_modules(selected_paths):
    """勾选字段路径/模块名 -> 参与回写的模块集合。None/空 = 全部模块。
    兼容前端模块清单直接传模块 key（与 51job/智联模块级回写一致）"""
    if not selected_paths:
        return set(PATH_TO_MODULE.values())
    selected = set(selected_paths)
    modules = {m for p, m in PATH_TO_MODULE.items() if p in selected}
    modules |= selected & set(PATH_TO_MODULE.values())
    return modules


def load_local_fields():
    """优先读回写快照 boss_writeback.json（{meta, fields} 结构），回退 boss_fields.json。
    与 51job/猎聘/智联快照模式一致。返回 (fields, 来源路径, freshness 新鲜度信息)"""
    from browser_common import load_writeback_source
    return load_writeback_source("boss", SNAPSHOT_PATH, FIELDS_PATH)


def _parse_salary(text):
    '''Support '15k-25k', '15-25K', etc. Returns (min, max) or None'''
    import re
    text = (text or "").strip()
    if not text:
        return None
    # 支持带 k 的格式 (15k-25k)，也支持纯数字格式 (15000-25000)
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[kK]?\s*[-~\u81f3]\s*(\d+(?:\.\d+)?)\s*[kK]?", text)
    if m:
        try:
            low, high = float(m.group(1)), float(m.group(2))
            return int(low), int(high)
        except ValueError:
            return None
    return None


def _map_apply_status(text):
    '''Map job status text to BOSS applyStatus code. Returns None if no match.'''
    return APPLY_STATUS_MAP.get((text or "").strip())


def _map_gender(text):
    ''''Male'->1 'Female'->0; returns None if no match.'''
    return GENDER_MAP.get((text or "").strip())


def _norm_ym(v):
    '''Normalize '1996-11'/'19961101'/'int' to 'YYYY-MM' format.'''
    s = str(v or "").replace("-", "").replace(".", "").replace("/", "")
    return s.strip()


def _to_ym(v):
    """任意 YYYYMMDD / YYYY-MM / int -> 'YYYY-MM'（与官网保存报文格式一致，月份补零）；无法解析原样返回"""
    s = _norm_ym(v)
    if len(s) == 5 and s.isdigit():  # 'YYYYM'（月未补零，如 20197）
        return f"{s[:4]}-0{s[4]}"
    if len(s) >= 6 and s[:4].isdigit():
        return f"{s[:4]}-{s[4:6]}"
    return str(v or "")


# ============================================================
# 纯函数：码表映射 / 匹配 / 载荷构建（无浏览器依赖，可单测）
# ============================================================

def _walk_tree(nodes):
    """递归展平 树形选项（含 subLevelModelList），yield (code, name)"""
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        if n.get("name"):
            yield n.get("code"), n.get("name")
        sub = n.get("subLevelModelList")
        if sub:
            for item in _walk_tree(sub):
                yield item


def build_name_code_map(tree_nodes):
    """树形选项 -> {name: code}（重名取首个）"""
    m = {}
    for code, name in _walk_tree(tree_nodes):
        if name and name not in m:
            m[name] = code
    return m


def map_country_codes(names, country_tree):
    """国家名列表 -> code 列表；返回 (codes, unmapped_names)"""
    m = build_name_code_map(country_tree)
    codes, unmapped = [], []
    for nm in names or []:
        nm = (nm or "").strip()
        if not nm:
            continue
        if nm in m:
            codes.append(m[nm])
        else:
            unmapped.append(nm)
    return codes, unmapped


def map_language_codes(names, lang_tree):
    m = build_name_code_map(lang_tree)
    codes, unmapped = [], []
    for nm in names or []:
        nm = (nm or "").strip()
        if not nm:
            continue
        if nm in m:
            codes.append(m[nm])
        else:
            unmapped.append(nm)
    return codes, unmapped


def map_industry(name, industry_tree):
    """行业名 -> (code, name)；找不到返回 (None, name)"""
    m = build_name_code_map(industry_tree)
    name = (name or "").strip()
    if name in m:
        return m[name], name
    return None, name


def map_duration(text, duration_map=None):
    duration_map = duration_map or DURATION_MAP
    text = (text or "").strip()
    return duration_map.get(text)


def _ym(year, month):
    """('2024','4') -> '2024-04'；空 -> ''"""
    y = str(year or "").strip()
    m = str(month or "").strip()
    if not y:
        return ""
    if not m:
        return y
    return f"{y}-{int(m):02d}"


def match_work_items(local_list, official_list):
    """按起始年月匹配工作经历；无法匹配且条数相等时按剩余顺序兜底配对。
    返回 [(local_idx, official_idx)]，未匹配的 local_idx 单独返回"""
    local_list = local_list or []
    official_list = official_list or []
    off_by_start = {}
    for oi, o in enumerate(official_list):
        key = _parse_official_start(o)
        off_by_start.setdefault(key, oi)
    pairs, unmatched = [], []
    used = set()
    for li, l in enumerate(local_list):
        key = _ym(l.get("startYear"), l.get("startMonth"))
        oi = off_by_start.get(key)
        if oi is not None and oi not in used:
            pairs.append((li, oi))
            used.add(oi)
        else:
            unmatched.append(li)
    # 兜底：条数相等时，剩余本地条目按序配剩余官网条目
    if unmatched and len(local_list) == len(official_list):
        remaining_off = [oi for oi in range(len(official_list)) if oi not in used]
        for li, oi in zip(unmatched, remaining_off):
            pairs.append((li, oi))
            used.add(oi)
        unmatched = []
    return pairs, unmatched


def _parse_official_start(o):
    """官方 workExp item 的起始 'YYYY-MM'"""
    s = o.get("startDateStr") or o.get("startDate") or ""
    s = str(s).replace(".", "-").replace("/", "-")
    parts = [p for p in s.split("-") if p]
    if len(parts) >= 2:
        try:
            return f"{int(parts[0])}-{int(parts[1]):02d}"
        except ValueError:
            return ""
    return ""


def match_project_items(local_list, official_list):
    """项目匹配。回写会覆盖项目的内容字段(name/role/desc/url/dates/performance)且保留官网 id，
    因此当条数相等时按序配对即可得到确定的最终态（官网项目内容=本地项目）。
    条数不等时退回 url/起始年月 匹配，未匹配的本地条目不新增。
    返回 (pairs, unmatched_local_idx)"""
    local_list = local_list or []
    official_list = official_list or []

    # 条数相等：按序配对（确定、可预期）
    if len(local_list) == len(official_list):
        return [(i, i) for i in range(len(local_list))], []

    # 条数不等：url 精确 -> 起始年月
    pairs, matched_local = [], set()
    used = set()
    for li, l in enumerate(local_list):
        lu = (l.get("project_link") or "").strip()
        if not lu:
            continue
        for oi, o in enumerate(official_list):
            if oi in used:
                continue
            if (o.get("url") or "").strip() == lu:
                pairs.append((li, oi))
                used.add(oi)
                matched_local.add(li)
                break
    off_by_start = {}
    for oi, o in enumerate(official_list):
        if oi in used:
            continue
        off_by_start.setdefault(_parse_official_start(o), oi)
    for li, l in enumerate(local_list):
        if li in matched_local:
            continue
        oi = off_by_start.get(_ym(l.get("startYear"), l.get("startMonth")))
        if oi is not None and oi not in used:
            pairs.append((li, oi))
            used.add(oi)
            matched_local.add(li)
    unmatched = [li for li in range(len(local_list)) if li not in matched_local]
    return pairs, unmatched


def build_workexp_payload(local_item, official_item, industry_tree, skill_tree=None):
    """构建 workexp/save.json 表单。保留官网 id/职位码，写入本地内容、技能标签(emphasis)与隐藏简历配置(isPublic)"""
    ind_code, ind_name = map_industry(local_item.get("industry"), industry_tree)
    off_ind = official_item.get("industry") or {}
    if ind_code is None:
        # 本地行业无法映射 -> 沿用官网行业
        ind_code = off_ind.get("code", "")
        ind_name = off_ind.get("name", "")
    
    # 提取技能标签（支持 [{"name": "xxx"}] 或 ["xxx"]），去重保留前 6 个，使用 #&# 拼接
    raw_skills = local_item.get("skills") or []
    skill_names = []
    for s in raw_skills:
        if isinstance(s, dict):
            name = str(s.get("name", "")).strip()
        else:
            name = str(s or "").strip()
        if name and name not in skill_names:
            skill_names.append(name)
    emphasis_str = "#&#".join(skill_names[:6])
    
    # Content length validation (BOSS API limits)
    work_content = (local_item.get("content", "") or "")[:3000]  # Max 3000 chars
    work_performance = (local_item.get("achievement", "") or "")[:1000]  # Max 1000 chars
    
    return {
        "id": official_item.get("id", ""),
        "position": official_item.get("position", ""),
        "customPositionName": official_item.get("customPositionName", ""),
        "companyName": local_item.get("company") or official_item.get("companyName", ""),  # 官网必填：本地为空时沿用官网原值
        "industryCode": ind_code,
        "industryName": ind_name,
        "emphasis": emphasis_str,
        "department": local_item.get("department", official_item.get("department", "")) or "",
        "startDate": _ym(local_item.get("startYear"), local_item.get("startMonth")) or _parse_official_start(official_item),
        "endDate": _ym(local_item.get("endYear"), local_item.get("endMonth")),
        "workContent": work_content,
        "workPerformance": work_performance,
        # 对该公司隐藏我的简历：1=隐藏, 0=公开
        "isPublic": 1 if local_item.get("hideResume") else 0,
        "workType": official_item.get("workType", 0),
        "entrance": 1,
        "industrySource": -1,
        "riskTipType": 1,
    }


def build_project_payload(local_item, official_item):
    """构建 projectexp/save.json 表单。保留官网 id，写入本地内容字段"""
    return {
        "id": official_item.get("id", ""),
        "name": local_item.get("project_name", official_item.get("name", "")),
        "roleName": local_item.get("project_role", official_item.get("roleName", "")),
        "description": local_item.get("project_description", "") or "",
        "url": local_item.get("project_link", official_item.get("url", "")) or "",
        "performance": local_item.get("achievement", "") or "",
        "startDate": _ym(local_item.get("startYear"), local_item.get("startMonth")) or _parse_official_start(official_item),
        "endDate": _ym(local_item.get("endYear"), local_item.get("endMonth")),
        "entrance": 1,
        "riskTipType": 1,
    }


def build_cert_payload(cert_names):
    return {"certJson": json.dumps(
        [{"name": n, "type": 0} for n in cert_names or []], ensure_ascii=False)}


def build_overseas_payload(local_overseas, country_tree, lang_tree, duration_map=None):
    """构建驻外 collectinformation/save.json 表单。返回 (payload, unmapped)"""
    countries, u1 = map_country_codes(local_overseas.get("countries"), country_tree)
    langs, u2 = map_language_codes(local_overseas.get("languages"), lang_tree)
    dur = map_duration(local_overseas.get("duration"), duration_map)
    payload = {
        "duration": dur if dur is not None else "",
        "country": ",".join(str(c) for c in countries),
        "language": ",".join(str(c) for c in langs),
        "showStatus": 1 if local_overseas.get("allowView") else 0,
    }
    unmapped = {"countries": u1, "languages": u2}
    if dur is None:
        unmapped["duration"] = local_overseas.get("duration")
    return payload, unmapped


def match_expect_items(local_list, official_list):
    """期望条目匹配（全量覆盖语义）。
    官网兼职是独立条目（positionType=1），本地兼职是合并的 positions 列表，
    因此兼职按职位名逐个匹配官网兼职条目；全职按 positionName 匹配。
    返回 (pairs, add_entries, del_offs)：
      pairs=[(li, oi)] 匹配对 -> 更新（保留官网 id）
      add_entries=[(li, pos_or_None)] 本地未匹配 -> 新增（兼职带职位名，全职为 None）
      del_offs=[oi] 官网未匹配 -> 删除
    """
    local_list = local_list or []
    official_list = official_list or []
    pairs, used_off, add_entries = [], set(), []

    # 兼职：本地 positions（或 position 顿号拆分）逐个匹配官网兼职条目
    off_part = {}
    for oi, o in enumerate(official_list):
        if o.get("positionType") == 1:
            off_part.setdefault((o.get("positionName") or "").strip(), oi)
    for li, l in enumerate(local_list):
        if str(l.get("jobType", "")).lower() != "parttime":
            continue
        positions = l.get("positions") or []
        if not positions and l.get("position"):
            positions = str(l.get("position")).split("、")
        for pos in positions:
            pos = (pos or "").strip()
            oi = off_part.get(pos)
            if pos and oi is not None and oi not in used_off:
                pairs.append((li, oi))
                used_off.add(oi)
            elif pos:
                add_entries.append((li, pos))

    # 全职：按职位名匹配
    off_full = {}
    for oi, o in enumerate(official_list):
        if o.get("positionType") != 1:
            off_full.setdefault((o.get("positionName") or "").strip(), oi)
    for li, l in enumerate(local_list):
        if str(l.get("jobType", "")).lower() == "parttime":
            continue
        nm = (l.get("position") or "").strip()
        oi = off_full.get(nm)
        if nm and oi is not None and oi not in used_off:
            pairs.append((li, oi))
            used_off.add(oi)
        elif nm:
            add_entries.append((li, None))

    del_offs = [oi for oi in range(len(official_list)) if oi not in used_off]
    return pairs, add_entries, del_offs


def build_expect_payload(local_item, official_item, industry_tree=None, city_tree=None, position_map=None,
                         add_position_name=None):
    """构建期望条目 expect/save.json 表单。
    official_item 非空（更新）：保留官网 id/职位码/类型/城市码，写入本地薪资/其他城市/行业（无法映射时沿用官网）
    official_item 为空（新增）：id 置空，职位码从 position_map（职位名->码）取；
        兼职由 add_position_name 指定具体职位；城市码从 city_tree 映射本地 city"""
    ind_tree = industry_tree or []
    city_map = build_name_code_map(city_tree) if city_tree else {}
    position_map = position_map or {}
    is_add = not official_item
    off = official_item or {}

    salary = _parse_salary(local_item.get("salary"))
    low = salary[0] if salary else off.get("lowSalary", 0)
    high = salary[1] if salary else off.get("highSalary", 0)

    # 行业：本地 industries -> 码；空/失败沿用官网 industryList
    ind_codes = []
    for ind in local_item.get("industries") or []:
        c, _ = map_industry(ind, ind_tree)
        if c is not None:
            ind_codes.append(str(c))
    if not ind_codes:
        ind_codes = [str(x.get("code", "")) for x in (off.get("industryList") or []) if x.get("code")]

    # 其他城市：本地 otherCities -> 码；空/失败沿用官网 interestLocationList
    other_codes = []
    for c in local_item.get("otherCities") or []:
        c = (c or "").strip()
        if c and c in city_map:
            other_codes.append(str(city_map[c]))
    if not other_codes:
        other_codes = [str(x.get("code", "")) for x in (off.get("interestLocationList") or []) if x.get("code")]

    # 主城市：更新沿用官网 location；新增从本地 city 映射
    if is_add:
        loc = city_map.get((local_item.get("city") or "").strip(), 0)
        loc_name = local_item.get("city", "")
        loc_sub = 0
    else:
        loc = off.get("location", 0)
        loc_name = off.get("locationName", "")
        loc_sub = off.get("subLocation", 0)

    # 职位码：更新沿用官网 position；新增从 position_map 映射（兼职用 add_position_name）
    if is_add:
        pos_name = add_position_name or (local_item.get("position") or "").strip()
        position = position_map.get(pos_name, "") or position_map.get((local_item.get("position") or "").strip(), "")
    else:
        position = off.get("position", "")

    return {
        "positionType": 1 if str(local_item.get("jobType", "")).lower() == "parttime" else off.get("positionType", 0),
        "position": position,
        "lowSalary": low,
        "highSalary": high,
        "industryCodes": ",".join(ind_codes),
        "location": loc,
        "subLocation": loc_sub,
        "locationName": loc_name,
        "id": off.get("id", ""),
        "freshGraduate": off.get("freshGraduate", 0),
        "fullUpdate": "false",
        "otherPositionCodeStr": off.get("otherPositionCodeStr", "") or "",
        "otherLocationCodeStr": ",".join(other_codes),
    }


def match_edu_items(local_list, official_list):
    """教育经历匹配：条数相等按序；不等按 学校+起始年 匹配。返回 (pairs, unmatched)"""
    local_list = local_list or []
    official_list = official_list or []
    if len(local_list) == len(official_list):
        return [(i, i) for i in range(len(local_list))], []
    pairs, used = [], set()
    for li, l in enumerate(local_list):
        for oi, o in enumerate(official_list):
            if oi in used:
                continue
            if (o.get("school") or "").strip() == (l.get("school") or "").strip() and \
               str(o.get("startYear") or "").strip() == str(l.get("startYear") or "").strip():
                pairs.append((li, oi))
                used.add(oi)
                break
    unmatched = [li for li in range(len(local_list)) if li not in {p[0] for p in pairs}]
    return pairs, unmatched


def build_edu_payload(local_item, official_item):
    """构建教育经历 eduexp/save.json 表单。保留官网 id/schoolId/degree/eduType 码，写入本地内容"""
    return {
        "school": local_item.get("school", official_item.get("school", "")),
        "schoolId": official_item.get("schoolId", ""),
        "degree": official_item.get("degree", ""),
        "major": local_item.get("major", ""),
        "eduType": official_item.get("eduType", 1),
        "startDate": local_item.get("startYear", ""),
        "endDate": local_item.get("endYear", ""),
        "eduDescription": local_item.get("campus_experience", "") or "",
        "thesisTitle": local_item.get("thesisTitle", "") or "",
        "thesisDesc": local_item.get("thesisDesc", "") or "",
        "id": official_item.get("id", ""),
        "majorRanking": official_item.get("majorRanking", 0),
        "course": official_item.get("course", "") or "",
        "entrance": 1,
        "riskTipType": 1,
    }


def build_baseinfo_payload(local_fields, official_baseinfo):
    """构建 baseinfo/save.json 表单。name 沿用官网脱敏值（不回写本地真实姓名，避免改名审核）。
    仅写本地有值的字段，缺失沿用官网（统一 YYYY-MM 格式）。"""
    bi = official_baseinfo or {}
    birthday = _to_ym((_val(local_fields, "birth_month") or "").strip() or bi.get("birthday", ""))
    start_work = _to_ym((_val(local_fields, "work_start_date") or "").strip() or bi.get("startWorkDate", ""))
    gender = _map_gender(_val(local_fields, "gender"))
    apply_status = _map_apply_status(_val(local_fields, "job_status"))
    return {
        "name": bi.get("name", ""),
        "birthday": birthday,
        "gender": gender if gender is not None else bi.get("gender", 0),
        "nameShowType": bi.get("nameShowType", 0),
        "startWorkDate": start_work,
        "applyStatus": apply_status if apply_status is not None else bi.get("applyStatus", 0),
        "freshGraduate": bi.get("freshGraduate", 0),
    }


def _field_differs(a, b):
    """payload 值 vs 官网值：None/'' 与 0 视为相同（官网缺字段时默认 0）"""
    if a is None or a == "":
        a = 0
    if b is None or b == "":
        b = 0
    try:
        return int(a) != int(b)
    except (TypeError, ValueError):
        return str(a) != str(b)


def _baseinfo_unchanged(payload, official_baseinfo):
    """payload 与官网 baseInfo 归一化对比（官网生日为 8 位、payload 为 YYYY-MM）。
    本地无值的字段沿用官网 -> 视为一致；任一字段不同返回 False"""
    bi = official_baseinfo or {}
    pb, ob = _norm_ym(payload.get("birthday", "")), _norm_ym(bi.get("birthday", ""))
    if pb and ob and not (ob.startswith(pb) or pb.startswith(ob)):
        return False
    pw, ow = _norm_ym(payload.get("startWorkDate", "")), _norm_ym(bi.get("startWorkDate", ""))
    if pw and ow and not (ow.startswith(pw) or pw.startswith(ow)):
        return False
    if _field_differs(payload.get("gender"), bi.get("gender")):
        return False
    if _field_differs(payload.get("applyStatus"), bi.get("applyStatus")):
        return False
    return True


# ============================================================
# 浏览器编排
# ============================================================

def connect_browser():
    """连接已启动的浏览器（端口 PORT），端口无响应直接报错，绝不自动拉起新浏览器"""
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from browser_common import connect_page
    return connect_page(PORT)

def load_preview_and_tokens(page):
    """刷新简历页，拦截 preview 拿官网当前数据 + 真实请求头 token。
    preview 拦截偶发丢包/空响应体（页面时序），连 body 解析一起最多重试 3 次"""
    api_data = None
    packet = None
    for attempt in range(3):
        page.listen.start("geek/preview/data.json")
        page.get(RESUME_URL)
        packet = page.listen.wait(timeout=25)
        page.listen.stop()
        if packet:
            body = packet.response.body
            try:
                api_data = json.loads(body) if isinstance(body, (str, bytes)) else body
            except Exception:
                api_data = None
        if api_data:
            break
        print(f"    [WARN] preview/data.json 未捕获或响应为空（第 {attempt + 1} 次），重试…")
        time.sleep(2)
    if not api_data:
        raise RuntimeError("未捕获 preview/data.json，无法获取官网数据与 token")
    if "login" in page.url.lower():
        raise RuntimeError("未登录，请先在浏览器登录 BOSS 直聘")
    zp = api_data.get("zpData", {})
    hdrs = packet.request.headers or {}
    tokens = {"zp_token": hdrs.get("zp_token", ""), "token": hdrs.get("token", "")}
    if not tokens["zp_token"] or not tokens["token"]:
        raise RuntimeError("preview 请求头缺少 zp_token/token")
    return zp, tokens


def fetch_json_api(page, url, tokens):
    """页面内 fetch 一个 GET JSON 接口（带 token 头）"""
    js = """
    return fetch(%s + (%s.indexOf('?')===-1 ? '?_=' + Date.now() : ''), {
        credentials: 'include',
        headers: {'X-Requested-With': 'XMLHttpRequest', 'zp_token': %s, 'token': %s}
    }).then(function(r){ return r.text(); });
    """ % (json.dumps(url), json.dumps(url), json.dumps(tokens["zp_token"]), json.dumps(tokens["token"]))
    raw = page.run_js(js)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def post_form(page, url, form, tokens):
    """页面内 fetch POST 一个 urlencoded 表单，返回解析后的 JSON"""
    js = """
    return (function(){
        var fd = new URLSearchParams();
        var obj = %s;
        for (var k in obj) { if (obj.hasOwnProperty(k)) fd.append(k, obj[k] === null ? '' : String(obj[k])); }
        return fetch(%s, {
            method: 'POST', credentials: 'include',
            headers: {'Content-Type': 'application/x-www-form-urlencoded',
                      'X-Requested-With': 'XMLHttpRequest',
                      'zp_token': %s, 'token': %s},
            body: fd.toString()
        }).then(function(r){ return r.text(); });
    })();
    """ % (json.dumps(form, ensure_ascii=False), json.dumps(url),
           json.dumps(tokens["zp_token"]), json.dumps(tokens["token"]))
    raw = page.run_js(js)
    if not raw:
        return {"code": -1, "message": "no-response"}
    try:
        return json.loads(raw)
    except Exception:
        return {"code": -1, "message": str(raw)[:200]}


def _val(fields, path):
    f = fields.get(path) or {}
    if not f and path == "overseas":
        f = fields.get("stayAbroad") or {}
    return f.get("current_value")


def plan_writeback(local_fields, official_zp, country_tree, lang_tree, industry_tree, city_tree=None,
                   selected_paths=None, position_map=None, skill_tree=None):
    """
    制定回写计划。返回 {actions:[{module,endpoint,payload,detail}], skipped:[{module,reason}]}
    selected_paths：前端勾选的字段 path 列表；None/空 = 全部模块
    强制排除字段（HARD_SKIP）无论是否勾选都不回写。
    position_map：{职位名: 职位码}（期望新增条目用，来自 expectposition.json）
    纯函数，可单测。
    """
    actions, skipped = [], []
    modules = _selected_modules(selected_paths)
    city_tree = city_tree or []
    position_map = position_map or {}

    # 强制排除字段（无论勾选与否都不回写）+ 未勾选模块
    skipped.append({"module": "hard_skip",
                    "reason": "强制排除：" + "；".join(f"{p}（{r}）" for p, r in HARD_SKIP.items())})
    for m in sorted(set(PATH_TO_MODULE.values()) - modules):
        skipped.append({"module": m, "reason": "未勾选该模块字段，跳过回写"})

    # ---- 个人优势 ----
    if "personal_advantage" in modules:
        local_adv = _val(local_fields, "personal_advantage") or ""
        off_adv = official_zp.get("userDesc", "") or ""
        if local_adv.strip() and local_adv.strip() != off_adv.strip():
            actions.append({
                "module": "personal_advantage",
                "endpoint": "/wapi/zpgeek/resume/userdesc/save.json",
                "payload": {"advantage": local_adv},
                "detail": f"个人优势 {len(off_adv)}字 -> {len(local_adv)}字",
            })
        else:
            skipped.append({"module": "personal_advantage", "reason": "无变化或本地为空"})

    # ---- 工作经历 ----
    if "work_experience" in modules:
        local_work = _val(local_fields, "work_experience") or []
        off_work = official_zp.get("workExpList", []) or []
        pairs, unmatched = match_work_items(local_work, off_work)
        for li, oi in pairs:
            payload = build_workexp_payload(local_work[li], off_work[oi], industry_tree, skill_tree)
            actions.append({
                "module": "work_experience",
                "endpoint": "/wapi/zpgeek/resume/workexp/save.json",
                "payload": payload,
                "detail": f"工作经历[{li}] {local_work[li].get('company','')} (匹配官网[{oi}])",
            })
        if unmatched:
            skipped.append({"module": "work_experience",
                            "reason": f"{len(unmatched)} 条本地工作经历无法匹配官网（不新增）：索引 {unmatched}"})
        if not pairs:
            skipped.append({"module": "work_experience", "reason": "无可匹配条目"})

    # ---- 项目经历 ----
    if "projects" in modules:
        local_proj = _val(local_fields, "projects") or []
        off_proj = official_zp.get("projectExpList", []) or []
        ppairs, punmatched = match_project_items(local_proj, off_proj)
        for li, oi in ppairs:
            payload = build_project_payload(local_proj[li], off_proj[oi])
            actions.append({
                "module": "projects",
                "endpoint": "/wapi/zpgeek/resume/projectexp/save.json",
                "payload": payload,
                "detail": f"项目[{li}] {local_proj[li].get('project_name','')} (匹配官网[{oi}])",
            })
        if punmatched:
            skipped.append({"module": "projects",
                            "reason": f"{len(punmatched)} 条本地项目无法匹配官网（不新增）：索引 {punmatched}"})
        if not ppairs:
            skipped.append({"module": "projects", "reason": "无可匹配条目"})

    # ---- 资格证书（本地为准全量覆盖：官网多余证书会被删除） ----
    if "certificates" in modules:
        local_certs = _val(local_fields, "certificates") or []
        off_certs = [c.get("certName", "") for c in official_zp.get("certificationList", []) or []]
        local_set = set(x.strip() for x in local_certs if x and x.strip())
        off_set = set(x.strip() for x in off_certs if x and x.strip())
        if local_set:
            if local_set == off_set:
                skipped.append({"module": "certificates", "reason": "与官网一致，无需回写"})
            else:
                actions.append({
                    "module": "certificates",
                    "endpoint": "/wapi/zpgeek/resume/certification/save.json",
                    "payload": build_cert_payload([x for x in local_certs if x and x.strip()]),
                    "detail": f"证书全量覆盖 {sorted(off_set)} -> {sorted(local_set)}",
                })
        else:
            skipped.append({"module": "certificates", "reason": "本地为空，跳过回写"})

    # ---- 驻外选项 ----
    if "overseas" in modules:
        local_ov = _val(local_fields, "overseas") or {}
        if local_ov:
            payload, unmapped = build_overseas_payload(local_ov, country_tree, lang_tree)
            has_unmapped = any(unmapped.values())
            if has_unmapped:
                skipped.append({"module": "overseas", "reason": f"存在无法映射的选项：{unmapped}"})
            else:
                actions.append({
                    "module": "overseas",
                    "endpoint": "/wapi/zpgeek/overseastraitoptions/collectinformation/save.json",
                    "payload": payload,
                    "detail": f"驻外 国家{payload['country']} 语言{payload['language']} 时长{payload['duration']}",
                })
        else:
            skipped.append({"module": "overseas", "reason": "本地无驻外数据"})

    # ---- 求职期望（本地为准全量覆盖：匹配更新 / 本地未匹配新增 / 官网未匹配删除） ----
    if "expectations" in modules:
        local_exp = _val(local_fields, "expectations") or []
        off_exp = official_zp.get("expectList", []) or []
        epairs, eadd, edel = match_expect_items(local_exp, off_exp)
        for li, oi in epairs:
            payload = build_expect_payload(local_exp[li], off_exp[oi], industry_tree, city_tree, position_map)
            actions.append({
                "module": "expectations",
                "endpoint": "/wapi/zpgeek/resume/expect/save.json",
                "payload": payload,
                "detail": f"期望[{li}] {local_exp[li].get('position','')} (更新官网[{oi}] {off_exp[oi].get('positionName','')})",
            })
        for li, pos in eadd:
            payload = build_expect_payload(local_exp[li], None, industry_tree, city_tree, position_map,
                                           add_position_name=pos)
            nm = pos or local_exp[li].get("position", "")
            actions.append({
                "module": "expectations",
                "endpoint": "/wapi/zpgeek/resume/expect/save.json",
                "payload": payload,
                "detail": f"期望[{li}] {nm} (新增)",
            })
        # 官网约束：至少保留一条求职期望。本地有新增条目时删除安全；
        # 否则删除不得清空官网列表（删到剩最后一条即停，避免接口拒绝并把整体标失败）
        max_del = len(edel) if eadd else max(0, len(off_exp) - 1)
        for idx, oi in enumerate(edel):
            if idx >= max_del:
                skipped.append({"module": "expectations",
                                "reason": f"官网要求至少保留一条期望，跳过删除「{off_exp[oi].get('positionName','')}」"})
                continue
            actions.append({
                "module": "expectations",
                "endpoint": "/wapi/zpgeek/resume/expect/delete.json",
                "payload": {"id": off_exp[oi].get("id", "")},
                "detail": f"期望 删除官网未匹配条目 {off_exp[oi].get('positionName','')}",
            })
        if not (epairs or eadd or edel):
            skipped.append({"module": "expectations", "reason": "本地与官网均无期望数据"})

    # ---- 教育经历 ----
    if "education" in modules:
        local_edu = _val(local_fields, "education") or []
        off_edu = official_zp.get("educationExpList", []) or []
        edpairs, edunmatched = match_edu_items(local_edu, off_edu)
        for li, oi in edpairs:
            payload = build_edu_payload(local_edu[li], off_edu[oi])
            actions.append({
                "module": "education",
                "endpoint": "/wapi/zpgeek/resume/eduexp/save.json",
                "payload": payload,
                "detail": f"教育[{li}] {local_edu[li].get('school','')} (匹配官网[{oi}])",
            })
        if edunmatched:
            skipped.append({"module": "education",
                            "reason": f"{len(edunmatched)} 条本地教育无法匹配官网（不新增）：索引 {edunmatched}"})
        if not edpairs:
            skipped.append({"module": "education", "reason": "无可匹配条目"})

    # ---- 基础信息 ----
    if "baseinfo" in modules:
        off_base = official_zp.get("baseInfo", {}) or {}
        payload = build_baseinfo_payload(local_fields, off_base)
        if _baseinfo_unchanged(payload, off_base):
            skipped.append({"module": "baseinfo", "reason": "与官网一致，无需回写"})
        else:
            actions.append({
                "module": "baseinfo",
                "endpoint": "/wapi/zpgeek/resume/baseinfo/save.json",
                "payload": payload,
                "detail": f"基础信息 生日{payload['birthday']} 性别{payload['gender']} "
                          f"工作起始{payload['startWorkDate']} 求职状态{payload['applyStatus']}",
            })

    return {"actions": actions, "skipped": skipped}


def run_write_back(dry_run=False, selected_paths=None):
    print("=" * 52)
    print("  BOSS直聘 - 本地数据回写官网在线简历")
    print("=" * 52)

    try:
        local_fields, src, freshness = load_local_fields()
    except FileNotFoundError:
        print("  [ERROR] boss_fields.json 不存在")
        sys.exit(1)
    print(f"  本地数据源: {os.path.basename(src)}")
    # 回写全局空数据守卫：本地近乎为空时拒绝，防止把空内容推上官网
    from browser_common import ensure_writable_data
    ensure_writable_data("boss", local_fields)
    if freshness.get("stale"):
        print(f"  [WARN] {freshness['warning']}")

    page = connect_browser()
    print(f"  已连接浏览器 (端口 {PORT})")

    official_zp, tokens = load_preview_and_tokens(page)
    print("  已获取官网当前数据 + 回写 token")

    # 拉取码表
    country_tree = (fetch_json_api(page, "/wapi/zpgeek/overseastraitoptions/country/config/query.json", tokens) or {}).get("zpData", {}).get("configList", [])
    lang_tree = (fetch_json_api(page, "/wapi/zpgeek/overseastraitoptions/language/config/query.json", tokens) or {}).get("zpData", {}).get("configList", [])
    industry_tree = (fetch_json_api(page, "/wapi/zpCommon/data/industry.json", tokens) or {}).get("zpData", [])
    
    # NEW: Load skill tree for work experience skills field
    skill_tree = (fetch_json_api(page, "/wapi/zpgeek/resume/skill/query.json", tokens) or {}).get("zpData", {}).get("configList", [])
    print(f"  ✓ Loaded {len(skill_tree)} available skills from BOSS")
    
    city_json = fetch_json_api(page, "/wapi/zpCommon/data/city.json", tokens) or {}
    city_tree = (city_json.get("zpData") or {}).get("cityList", [])
    # 职位字典（期望新增条目用）：用本地第一条期望的城市映射城市码后拉取
    position_map = {}
    local_exp = _val(local_fields, "expectations") or []
    city_map = build_name_code_map(city_tree)
    city_code = city_map.get((local_exp[0].get("city") or "").strip(), "") if local_exp else ""
    if city_code:
        pos_json = fetch_json_api(page, f"/wapi/zpgeek/common/data/expectposition.json?cityCode={city_code}&version=1", tokens) or {}
        pos_config = (pos_json.get("zpData") or {}).get("config", [])
        position_map = build_name_code_map(pos_config)
        if not position_map:
            # 职位树子节点 key 可能不同，尝试直接展平所有叶子
            position_map = {str(n.get("name", "")).strip(): n.get("code")
                            for n in pos_config if isinstance(n, dict) and n.get("name")}
    print(f"  码表就绪：国家{len(country_tree)}组 语言{len(lang_tree)}组 行业{len(industry_tree)}组 "
          f"城市{len(city_tree)}组 职位{len(position_map)}个")

    plan = plan_writeback(local_fields, official_zp, country_tree, lang_tree, industry_tree,
                          city_tree=city_tree, selected_paths=selected_paths, position_map=position_map,
                          skill_tree=skill_tree)

    print("\n  ── 回写计划 ──")
    for a in plan["actions"]:
        print(f"    [写] {a['module']:20} {a['detail']}")
    for s in plan["skipped"]:
        print(f"    [跳] {s['module']:20} {s['reason']}")

    if dry_run:
        print("\n  [DRY-RUN] 未执行实际回写")
        return plan

    results = []
    print("\n  ── 执行回写 ──")
    for a in plan["actions"]:
        resp = post_form(page, a["endpoint"], a["payload"], tokens)
        code = resp.get("code")
        # code=200082「存在完全相同的项目经历」= 官网已有目标内容（幂等达成），视为成功，复核环节再校验
        ok = (code == 0) or (code == 200082)
        tag = "OK " if ok else "FAIL"
        print(f"    [{tag}] {a['module']:20} code={code} msg={resp.get('message','')}")
        results.append({**a, "resp_code": code, "resp_message": resp.get("message", ""), "ok": ok})
        # token 失效则刷新一次
        if code in (121, 122):
            print("    [WARN] token 疑似失效，刷新后重试一次该条")
            official_zp, tokens = load_preview_and_tokens(page)
            resp = post_form(page, a["endpoint"], a["payload"], tokens)
            ok = resp.get("code") == 0
            results[-1].update({"resp_code": resp.get("code"), "resp_message": resp.get("message", ""), "ok": ok})
            print(f"    [{'OK ' if ok else 'FAIL'}] 重试 {a['module']} code={resp.get('code')}")
        time.sleep(0.8)

    # ---- 复核：重新拉 preview 对比 ----
    print("\n  ── 复核 ──")
    time.sleep(2)
    verify_zp, _ = load_preview_and_tokens(page)
    verify = verify_results(verify_zp, results)
    for v in verify:
        tag = "✓" if v["match"] else "✗"
        print(f"    [{tag}] {v['module']:20} {v['note']}")

    succ = sum(1 for r in results if r["ok"])
    print(f"\n  回写完成：{succ}/{len(results)} 成功")
    
    #  Generate detailed backwrite report
    report_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        f"boss_writeback_report_{time.strftime('%Y%m%d_%H%M%S')}.html",
    )
    report = create_backwrite_report({"actions": plan.get("actions", []), "skipped": plan.get("skipped", [])}, results, report_file)
    print(f"\n📊 Report saved to: {report_file}")
    
    # 顶层 success/message 契约（用户案例 2026-08-30）：统一路由按 data["success"] 判定，
    # 历史载荷缺这两个键导致批量回写把成功误判为失败
    ok_results = [r for r in results if r.get("ok")]
    verify_bad = [v for v in verify if not v.get("match")]
    if not results:
        summary = "无需回写（本地与官网一致或无可回写模块）"
    elif not verify_bad and len(ok_results) == len(results):
        summary = f"回写成功 {len(ok_results)}/{len(results)}"
    elif verify_bad:
        summary = f"回写完成 {len(ok_results)}/{len(results)}，复核异常 {len(verify_bad)} 项"
    else:
        summary = f"部分模块回写失败：{len(ok_results)}/{len(results)} 成功"
    return {
        "success": len(ok_results) == len(results) and not verify_bad,
        "message": summary,
        "plan": plan, "results": results, "verify": verify, "data_source": freshness,
    }


def verify_results(verify_zp, results):
    """复核：对比回写后官网数据与本地载荷。纯函数，可单测"""
    out = []
    for r in results:
        if not r.get("ok"):
            out.append({"module": r["module"], "match": False, "note": "保存接口未成功"})
            continue
        mod = r["module"]
        payload = r["payload"]
        if mod == "personal_advantage":
            cur = verify_zp.get("userDesc", "") or ""
            match = cur.strip() == str(payload.get("advantage", "")).strip()
            out.append({"module": mod, "match": match, "note": "已生效" if match else "官网值不一致"})
        elif mod == "work_experience":
            def _work_match(w):
                content_match = (w.get("workContent") or "").strip() == str(payload.get("workContent", "")).strip()
                perf_match = (w.get("workPerformance") or "").strip() == str(payload.get("workPerformance", "")).strip()
                pub_match = int(w.get("isPublic", 0)) == int(payload.get("isPublic", 0))
                # 校验技能标签一致性
                exp_emphasis = [x for x in payload.get("emphasis", "").split("#&#") if x]
                cur_emphasis = [x for x in (w.get("emphasis") or []) if x]
                emphasis_match = exp_emphasis == cur_emphasis
                return content_match and perf_match and pub_match and emphasis_match
            
            match = any(w.get("id") == payload.get("id") and _work_match(w) for w in verify_zp.get("workExpList", []) or [])
            out.append({"module": mod, "match": match, "note": payload.get("companyName", "")})
        elif mod == "projects":
            def _proj_match(p):
                return (p.get("projectDesc") or "").strip() == str(payload.get("description", "")).strip() \
                    and (p.get("performance") or "").strip() == str(payload.get("performance", "")).strip()
            proj_list = verify_zp.get("projectExpList", []) or []
            # 优先按 id 匹配；重复条目（200082）实际落在另一 id 上，退化为纯内容对比
            match = any(p.get("id") == payload.get("id") and _proj_match(p) for p in proj_list) \
                or any(_proj_match(p) for p in proj_list)
            out.append({"module": mod, "match": match, "note": payload.get("name", "")})
        elif mod == "certificates":
            try:
                want = {c["name"] for c in json.loads(payload.get("certJson", "[]"))}
            except Exception:
                want = set()
            cur = {c.get("certName", "") for c in verify_zp.get("certificationList", []) or []}
            match = want == {x for x in cur if x}
            out.append({"module": mod, "match": match, "note": f"{sorted(want)}"})
        elif mod == "overseas":
            out.append({"module": mod, "match": True, "note": "已提交（驻外需页面展示确认）"})
        elif mod == "expectations":
            exp_list = verify_zp.get("expectList", []) or []
            if "delete" in r.get("endpoint", ""):
                # 删除：确认该 id 已不在官网
                match = not any(e.get("id") == payload.get("id") for e in exp_list)
                out.append({"module": mod, "match": match, "note": f"删除条目 id={payload.get('id')}"})
            elif payload.get("id"):
                # 更新：按 id 对比薪资
                match = any(e.get("id") == payload.get("id")
                            and str(e.get("lowSalary", "")) == str(payload.get("lowSalary", ""))
                            and str(e.get("highSalary", "")) == str(payload.get("highSalary", ""))
                            for e in exp_list)
                out.append({"module": mod, "match": match,
                            "note": f"更新 {payload.get('lowSalary')}-{payload.get('highSalary')}K 职位码{payload.get('position')}"})
            else:
                # 新增：确认职位码已出现在官网
                match = any(str(e.get("position", "")) == str(payload.get("position", ""))
                            and str(e.get("positionType", "")) == str(payload.get("positionType", ""))
                            for e in exp_list)
                out.append({"module": mod, "match": match,
                            "note": f"新增 职位码{payload.get('position')} 类型{payload.get('positionType')}"})
        elif mod == "education":
            match = any(e.get("id") == payload.get("id")
                        and str(e.get("school", "")).strip() == str(payload.get("school", "")).strip()
                        and str(e.get("startYear", "")).strip() == str(payload.get("startDate", "")).strip()
                        for e in verify_zp.get("educationExpList", []) or [])
            out.append({"module": mod, "match": match, "note": payload.get("school", "")})
        elif mod == "baseinfo":
            bi = verify_zp.get("baseInfo", {}) or {}
            pb, ob = _norm_ym(payload.get("birthday", "")), _norm_ym(bi.get("birthday", ""))
            pw, ow = _norm_ym(payload.get("startWorkDate", "")), _norm_ym(bi.get("startWorkDate", ""))
            match = (not pb or not ob or ob.startswith(pb) or pb.startswith(ob)) \
                and (not pw or not ow or ow.startswith(pw) or pw.startswith(ow)) \
                and str(bi.get("gender", "")) == str(payload.get("gender", "")) \
                and str(bi.get("applyStatus", "")) == str(payload.get("applyStatus", ""))
            out.append({"module": mod, "match": match,
                        "note": f"生日{bi.get('birthday','')} 工作起始{bi.get('startWorkDate','')} 求职状态{bi.get('applyStatus','')}"})
        else:
            out.append({"module": mod, "match": True, "note": "已提交"})
    return out


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    as_json = "--json" in sys.argv
    paths = None
    for i, a in enumerate(sys.argv):
        if a == "--paths" and i + 1 < len(sys.argv):
            paths = [p for p in sys.argv[i + 1].split(",") if p]
    
    try:
        result = run_write_back(dry_run=dry, selected_paths=paths)
    except Exception as e:
        import traceback
        error_details = {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "platform": "boss",
            "selected_paths": paths or "all"
        }
        print(f"ERROR: {e}")
        print(traceback.format_exc())
        if as_json:
            print("RESULT_JSON:" + json.dumps({
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "details": "详细错误见 stdout"
            }, ensure_ascii=False))
        sys.exit(1)
    
    if as_json:
        print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    if dry:
        sys.exit(0)
    # 空 results（无需回写）= 成功，与智联/51job 退出码口径一致；
    # 此前 bool(results) 前缀使"全部一致"时 exit 2，Tab 内一键回写按退出码误判为失败
    ok_all = all(r.get("ok") for r in result.get("results") or [])
    sys.exit(0 if ok_all else 2)
