"""
BOSS 平台确定性规则映射引擎 (backend/resume_editor/rule_map_boss.py)

核心职责：
1. 作为 LLM 映射不可用（429 限流/余额不足/超时/网络故障/无 Key）时的保底降级引擎。
2. 文本与日期字段安全覆盖：
   - personal_advantage ← master.summary
   - 基本信息基础文本字段同步
   - 工作经历、项目经历、教育经历运行时动态键投影与起止年月覆盖
3. 动态键投影与脏数据防御（GLM-P1-4 / GLM2-P2-2 / GLM2-P2-3）：
   - 严格沿用 fields_data 中现有条目的 key 进行投影，不编造 schema 外键
   - 遇到空数组（current_value: []）绝不捏造条目，转入 unfilled 并说明理由
   - 遇到脏数据（非 dict 条目等）安全降级转入 unfilled，绝不抛未捕获异常
   - 主简历经历多于模板条目时，按模板条数截断投影，未匹配项记录 warnings
4. 选项类字段（expectations / overseas / certificates / job_status 等）安全转入 unfilled。
5. 结果强制通过 validate_mapping_result 校验与 selected_modules 过滤。
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any, Callable

from .agent_mapper import (
    _attach_changed_flags,
    _attach_field_options,
    _attach_translations,
    _clean_md,
    _ensure_unfilled_fields,
    _field_path_to_module,
    _parse_years,
    validate_mapping_result,
)

logger = logging.getLogger("rule_map_boss")


def _extract_master_dates(master_item: dict) -> tuple[str | None, str | None]:
    """从主简历条目中提取 (start_ym, end_ym)，如 ('2021-06', '2023-08') 或 ('2021-06', '至今')"""
    if not isinstance(master_item, dict):
        return None, None
    years = master_item.get("years")
    if years:
        st, en = _parse_years(years)
        if st:
            return st, en
    st = str(master_item.get("start") or master_item.get("start_date") or "").strip().replace(".", "-").replace("/", "-")
    en = str(master_item.get("end") or master_item.get("end_date") or "").strip().replace(".", "-").replace("/", "-")
    m_st = re.search(r"(\d{4})[-/](\d{1,2})", st)
    st_val = f"{m_st.group(1)}-{int(m_st.group(2)):02d}" if m_st else (st if st else None)
    if not en or any(kw in en for kw in ("至今", "now", "目前", "Present", "present")):
        en_val = "至今"
    else:
        m_en = re.search(r"(\d{4})[-/](\d{1,2})", en)
        en_val = f"{m_en.group(1)}-{int(m_en.group(2)):02d}" if m_en else en
    return st_val, en_val


def _split_ym(ym: str | None) -> tuple[str, str]:
    """'2021-06' -> ('2021', '6'); '至今' 或 None -> ('', '')"""
    if not ym or ym in ("至今", "now", "目前", "Present", "present"):
        return "", ""
    m = re.match(r"^(\d{4})[-/](\d{1,2})", ym)
    if m:
        return m.group(1), str(int(m.group(2)))
    return "", ""


def _apply_date_keys(plat_item: dict, master_item: dict) -> None:
    """按模板中存在的 key 投影起止日期字段（支持 startYear/Month 或 start_date 等）。"""
    st, en = _extract_master_dates(master_item)
    sy, sm = _split_ym(st)
    ey, em = _split_ym(en)
    if "startYear" in plat_item and sy:
        plat_item["startYear"] = sy
    if "startMonth" in plat_item and sm:
        plat_item["startMonth"] = sm
    if "endYear" in plat_item:
        plat_item["endYear"] = ey
    if "endMonth" in plat_item:
        plat_item["endMonth"] = em
    if "start_date" in plat_item and st:
        plat_item["start_date"] = st
    if "end_date" in plat_item:
        plat_item["end_date"] = en or "至今"


def _match_entries(master_items: list[dict], plat_items: list[dict], match_keys: list[str]) -> list[tuple[int, int]]:
    """配对主简历条目与平台模板条目：优先按名称，次选按时间，兜底按剩余顺序。"""
    pairs: list[tuple[int, int]] = []
    used_plat, used_master = set(), set()

    for mi, master_item in enumerate(master_items):
        if not isinstance(master_item, dict):
            continue
        m_names = {_clean_md(str(master_item.get(k) or "")).strip() for k in match_keys} - {""}
        if not m_names:
            continue
        for pi, plat_item in enumerate(plat_items):
            if pi in used_plat or not isinstance(plat_item, dict):
                continue
            p_names = {_clean_md(str(plat_item.get(k) or "")).strip() for k in match_keys} - {""}
            if m_names & p_names:
                pairs.append((mi, pi))
                used_plat.add(pi)
                used_master.add(mi)
                break

    for mi, master_item in enumerate(master_items):
        if mi in used_master or not isinstance(master_item, dict):
            continue
        m_st, _ = _extract_master_dates(master_item)
        if not m_st:
            continue
        for pi, plat_item in enumerate(plat_items):
            if pi in used_plat or not isinstance(plat_item, dict):
                continue
            p_st = plat_item.get("start_date") or (
                f"{plat_item.get('startYear')}-{int(plat_item.get('startMonth')):02d}"
                if plat_item.get("startYear") and str(plat_item.get("startMonth", "")).isdigit()
                else None
            )
            if p_st and p_st == m_st:
                pairs.append((mi, pi))
                used_plat.add(pi)
                used_master.add(mi)
                break

    for pi, plat_item in enumerate(plat_items):
        if pi in used_plat or not isinstance(plat_item, dict):
            continue
        for mi, master_item in enumerate(master_items):
            if mi in used_master or not isinstance(master_item, dict):
                continue
            pairs.append((mi, pi))
            used_plat.add(pi)
            used_master.add(mi)
            break

    return pairs


def _project_array_items(
    node: Any,
    master_items: list[dict],
    path: str,
    label: str,
    match_keys: list[str],
    update_fn: Callable[[dict, dict], None],
    fields: list[dict[str, Any]],
    unfilled: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    """通用数组投影执行器：统一承载空数组防御、脏数据防御与条目数量不对等提示。"""
    plat_items = node.get("current_value") if isinstance(node, dict) else None
    # 【GLM-P1-4】空数组边界防御
    if not isinstance(plat_items, list) or len(plat_items) == 0:
        unfilled.append({
            "path": path,
            "label": label,
            "reason": "需人工在官网首次添加至少一条记录以生成字段模板",
            "type": "array",
        })
        return
    # 【GLM2-P2-3】脏数据防御
    if not isinstance(plat_items[0], dict):
        unfilled.append({
            "path": path,
            "label": label,
            "reason": "字段模板数据格式非对象字典，无法安全投影",
            "type": "array",
        })
        return
    if not master_items:
        unfilled.append({
            "path": path,
            "label": label,
            "reason": f"主简历未提供{label}内容",
            "type": "array",
        })
        return

    new_items = copy.deepcopy(plat_items)
    pairs = _match_entries(master_items, new_items, match_keys)
    for mi, pi in pairs:
        master_item, plat_item = master_items[mi], new_items[pi]
        if isinstance(plat_item, dict):
            update_fn(master_item, plat_item)

    # 【GLM2-P2-2】经历数量不对等提示
    if len(master_items) > len(new_items):
        warnings.append(
            f"{label}：主简历包含 {len(master_items)} 段经历，官网模板仅 {len(new_items)} 段，已匹配投影 {len(pairs)} 段，未匹配经历请人工在官网补充"
        )
    fields.append({
        "path": path,
        "value": new_items,
        "confidence": "high",
        "source": f"master.{path}",
        "note": "规则映射",
        "type": "array",
    })


def _update_work_item(master_item: dict, plat_item: dict) -> None:
    if "company" in plat_item:
        plat_item["company"] = _clean_md(master_item.get("company")) or plat_item["company"]
    if "position" in plat_item:
        plat_item["position"] = _clean_md(master_item.get("position") or master_item.get("role") or master_item.get("title")) or plat_item["position"]
    content_val = _clean_md(master_item.get("content") or master_item.get("desc") or master_item.get("description") or master_item.get("responsibilities"))
    if "content" in plat_item:
        plat_item["content"] = content_val or plat_item["content"]
    elif "description" in plat_item:
        plat_item["description"] = content_val or plat_item["description"]
    _apply_date_keys(plat_item, master_item)


def _update_project_item(master_item: dict, plat_item: dict) -> None:
    pname = _clean_md(master_item.get("name") or master_item.get("project_name") or master_item.get("projectName"))
    for k in ("project_name", "projectName", "name"):
        if k in plat_item:
            plat_item[k] = pname or plat_item[k]
            break
    prole = _clean_md(master_item.get("role") or master_item.get("project_role"))
    for k in ("project_role", "role"):
        if k in plat_item:
            plat_item[k] = prole or plat_item[k]
            break
    pdesc = _clean_md(master_item.get("desc") or master_item.get("description") or master_item.get("content") or master_item.get("project_description") or master_item.get("describe"))
    for k in ("project_description", "describe", "description", "content"):
        if k in plat_item:
            plat_item[k] = pdesc or plat_item[k]
            break
    _apply_date_keys(plat_item, master_item)


def _update_education_item(master_item: dict, plat_item: dict) -> None:
    school = _clean_md(master_item.get("school") or master_item.get("institution"))
    if "school" in plat_item:
        plat_item["school"] = school or plat_item["school"]
    major = _clean_md(master_item.get("major"))
    if "major" in plat_item:
        plat_item["major"] = major or plat_item["major"]

    deg = _clean_md(master_item.get("degree"))
    if deg:
        # 【P1-1 修复】尊重官网原有学制性质（全日制 vs 非全日制），绝不凭空篡改或强加全日制标签
        edu_type = str(plat_item.get("eduType") or "")
        degree_name_cur = str(plat_item.get("degreeName") or "")
        degree_cur = str(plat_item.get("degree") or "")

        is_non_fulltime = "非全日制" in edu_type or "非全日制" in degree_name_cur or "非全日制" in degree_cur
        is_fulltime = "全日制" in edu_type or "全日制" in degree_name_cur or "全日制" in degree_cur
        suffix = "非全日制" if is_non_fulltime else ("全日制" if is_fulltime else "")

        if "degree" in plat_item:
            if " / " in degree_cur:
                parts = degree_cur.split(" / ", 1)
                plat_item["degree"] = f"{deg} / {parts[1]}"
            elif suffix:
                plat_item["degree"] = f"{deg} / {suffix}"
            else:
                plat_item["degree"] = deg

        if "degreeName" in plat_item:
            if is_non_fulltime:
                plat_item["degreeName"] = f"非全日制{deg}"
            elif is_fulltime:
                plat_item["degreeName"] = f"全日制{deg}"
            else:
                plat_item["degreeName"] = deg

    _apply_date_keys(plat_item, master_item)


def rule_map_boss(
    fields_data: dict,
    master: dict,
    llm_error: str = "",
    selected_modules: list[str] | None = None,
) -> dict:
    """BOSS 平台确定性规则映射入口。"""
    data = master.get("data") if isinstance(master.get("data"), dict) else master
    fields: list[dict[str, Any]] = []
    unfilled: list[dict[str, Any]] = []
    warnings: list[str] = [
        "⚠️ 已降级为确定性规则映射（LLM 不可用：%s），仅覆盖文本/日期字段，请重点核对"
        % (llm_error or "未配置")
    ]
    logger.warning("[映射降级] BOSS 规则映射触发，原因: %s", llm_error or "未配置 LLM API Key")

    # 1. 优势亮点 ← summary
    summary = _clean_md(data.get("summary") or master.get("summary"))
    if summary and "personal_advantage" in fields_data:
        fields.append({
            "path": "personal_advantage",
            "value": summary,
            "confidence": "high",
            "source": "master.summary",
            "note": "规则映射",
            "type": "textarea",
        })

    # 2. 基本信息基础字段
    pi = data.get("personalInfo") if isinstance(data.get("personalInfo"), dict) else data
    if not isinstance(pi, dict):
        pi = master
    for key in ("name", "phone", "email", "wechat"):
        if key in fields_data:
            val = _clean_md(pi.get(key) or master.get(key))
            if val:
                fields.append({
                    "path": key,
                    "value": val,
                    "confidence": "high",
                    "source": "master.basic_info",
                    "note": "规则映射",
                    "type": "text",
                })

    # 3. 工作经历 (work_experience)
    we_master = data.get("workExperience") or data.get("work_experience") or data.get("experiences") or master.get("experiences") or []
    if "work_experience" in fields_data:
        _project_array_items(
            fields_data["work_experience"], we_master, "work_experience", "工作经历",
            ["company", "company_name"], _update_work_item, fields, unfilled, warnings
        )

    # 4. 项目经历 (projects)
    pj_master = data.get("personalProjects") or data.get("projects") or master.get("projects") or []
    if "projects" in fields_data:
        _project_array_items(
            fields_data["projects"], pj_master, "projects", "项目经历",
            ["project_name", "projectName", "name"], _update_project_item, fields, unfilled, warnings
        )

    # 5. 教育经历 (education)
    edu_master = data.get("education") or master.get("education") or []
    if "education" in fields_data:
        _project_array_items(
            fields_data["education"], edu_master, "education", "教育经历",
            ["school", "institution"], _update_education_item, fields, unfilled, warnings
        )

    # 6. 选项类及其他字段统一归入 unfilled
    mapped_paths = {f["path"] for f in fields} | {u["path"] for u in unfilled}
    for key, node in fields_data.items():
        if key in mapped_paths or key.endswith("Translation"):
            continue
        label = str(node.get("label") or key) if isinstance(node, dict) else str(key)
        node_type = str(node.get("type") or "text") if isinstance(node, dict) else "text"
        unfilled.append({
            "path": key,
            "label": label,
            "reason": "选项类/复合配置字段需人工在官网核对选择",
            "type": node_type,
        })

    # 7. 组装、校验与后处理
    raw_report = {
        "success": True,
        "platform": "boss",
        "fields": fields,
        "unfilled": unfilled,
        "warnings": warnings,
    }
    report = validate_mapping_result(raw_report, fields_data)
    report = _attach_changed_flags(report, fields_data)
    report = _attach_translations(report, fields_data)
    report = _ensure_unfilled_fields(report, fields_data, selected_modules=selected_modules)
    report = _attach_field_options(report, "boss")
    report["success"] = True
    report["platform"] = "boss"

    # 8. selected_modules 过滤与 message 生成（过滤后精确统计）
    if selected_modules and len(selected_modules) > 0:
        sel_set = set(selected_modules)
        report["fields"] = [f for f in report.get("fields", []) if _field_path_to_module(f.get("path", "")) in sel_set]
        report["unfilled"] = [u for u in report.get("unfilled", []) if _field_path_to_module(u.get("path", "")) in sel_set]
        report["selected_modules"] = selected_modules

    report["message"] = f"规则映射完成：{len(report.get('fields', []))} 项填入，{len(report.get('unfilled', []))} 项待人工"

    return report
