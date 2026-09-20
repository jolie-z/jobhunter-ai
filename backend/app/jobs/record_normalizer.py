import re
from datetime import datetime, timedelta, timezone
from typing import Any


def extract_url_from_markdown_link(text: str) -> str:
    """从 Markdown 形式的链接中提取裸 URL"""
    if not text or not isinstance(text, str):
        return ""
    text = text.strip()
    m = re.match(r'^\[(.*?)\]\((.*?)\)$', text)
    if m:
        return m.group(2)
    m = re.match(r'^\[.*?\]\s*:\s*(.*)$', text)
    if m:
        return m.group(1)
    if text.startswith(("http://", "https://")):
        return text
    return ""


def _compose_diagnosis_report(
    dream_picture: str = "",
    ats_ability_analysis: str = "",
    strong_fit_assessment: str = "",
    risk_red_flags: str = "",
    deep_action_plan: str = "",
) -> str:
    sections = [
        ("【理想画像与能力信号】", dream_picture),
        ("【核心能力词典】", ats_ability_analysis),
        ("【高杠杆匹配点】", strong_fit_assessment),
        ("【致命硬伤与毒点】", risk_red_flags),
        ("【破局行动计划】", deep_action_plan),
    ]
    parts = [f"{title}\n{content.strip()}" for title, content in sections if content and content.strip()]
    return "\n\n".join(parts)


def _safe_get_datetime_local(fields: dict[str, Any], key: str) -> str:
    val = fields.get(key)
    if not val:
        return ""
    try:
        ts = int(val)
        if ts > 10000000000:
            ts = ts / 1000.0
        tz_beijing = timezone(timedelta(hours=8))
        return datetime.fromtimestamp(ts, tz_beijing).strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return str(val)


def _safe_get_int(fields: dict[str, Any], key: str, default: int = 0) -> int:
    val = fields.get(key)
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _extract_paragraph_text(item: dict) -> str:
    elements = item.get("elements", [])
    para_texts = []
    for el in elements:
        if isinstance(el, dict):
            tr = el.get("text_run", {})
            if isinstance(tr, dict) and "content" in tr:
                para_texts.append(str(tr["content"]))
    return "".join(para_texts) + "\n" if para_texts else ""


def _extract_dict_text(item: dict) -> str | None:
    text = item.get("text") or item.get("name") or item.get("value")
    return str(text) if text is not None else None


def _extract_from_list(val: list) -> str:
    chunks: list[str] = []
    for item in val:
        if isinstance(item, str):
            chunks.append(item)
        elif isinstance(item, dict):
            if item.get("type") == "paragraph":
                chunks.append(_extract_paragraph_text(item))
            else:
                text = _extract_dict_text(item)
                if text is not None:
                    chunks.append(text)
        elif item is not None:
            chunks.append(str(item))
    return "".join([c for c in chunks if c])


def _safe_get_text(fields: dict[str, Any], key: str, default: str = "") -> str:
    val = fields.get(key)
    if val is None:
        return default
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return _extract_from_list(val) or default
    if isinstance(val, dict):
        text = _extract_dict_text(val)
        return text if text is not None else str(val)
    return str(val)


def _safe_get_link(fields: dict[str, Any], key: str) -> str:
    val = fields.get(key)
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        link = val.get("link") or val.get("text") or ""
        return str(link).strip()
    return ""


def _extract_list_items(val: list) -> list[str]:
    result: list[str] = []
    for item in val:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            text = item.get("text") or item.get("name") or item.get("value")
            if text:
                result.append(str(text).strip())
        elif item is not None:
            result.append(str(item).strip())
    return [x for x in result if x]


def _safe_get_list(fields: dict[str, Any], key: str) -> list[str]:
    val = fields.get(key)
    if val is None:
        return []
    if isinstance(val, list):
        return _extract_list_items(val)
    text = _safe_get_text(fields, key, "")
    if not text:
        return []
    return [part.strip() for part in str(text).replace("；", ",").replace("，", ",").split(",") if part.strip()]


# 列表瘦身：这些 key（大文本字段）不出现在 /api/jobs 列表响应里，
# 前端点开岗位详情时通过 /api/jobs/{id}/detail 按需获取。
_DETAIL_ONLY_KEYS = {
    "job_detail", "my_review", "interview_transcript", "ai_rewrite_json", "manual_refined_resume",
    "dream_picture", "ats_ability_analysis", "resume_audit", "strong_fit_assessment",
    "risk_red_flags", "deep_action_plan", "composite_diagnosis_report", "greeting_msg",
    "company_intel", "predicted_qa", "reverse_questions", "live_interview_record",
    "resume_qa", "interview_prep_report",
}

# 与上面 key 对应的飞书字段名：拉列表时从 search 的 field_names 中剔除，飞书侧就不传大文本
DETAIL_ONLY_FIELDS = {
    "岗位详情", "AI改写JSON", "AI改写简历", "我的复核", "面试记录",
    "现场面试记录", "简历专项QA", "理想画像与能力信号", "核心能力词典", "简历逐行审计",
    "高杠杆匹配点", "致命硬伤与毒点", "破局行动计划", "打招呼语", "公司业务情报",
    "专属面试预测", "反问环节建议", "面试辅导报告",
}


def normalize_job_record(record: dict[str, Any], default_platform: str = "未知", slim: bool = False) -> dict[str, Any] | None:
    fields = record.get("fields", {})

    job = {
        "record_id": record.get("record_id"),
        "job_name": _safe_get_text(fields, "岗位名称", "未知岗位"),
        "company_name": _safe_get_text(fields, "公司名称", "未知公司"),
        "city": _safe_get_text(fields, "城市", "未知城市"),
        "salary": _safe_get_text(fields, "薪资", "面议"),
        "follow_status": _safe_get_text(fields, "跟进状态", "新线索"),
        "scale": _safe_get_text(fields, "公司规模", "规模不详"),
        "industry": _safe_get_text(fields, "所属行业", "未知行业"),
        "education": _safe_get_text(fields, "学历要求", "学历不限"),
        "experience": _safe_get_text(fields, "经验要求", "经验不限"),
        "job_detail": _safe_get_text(fields, "岗位详情", "暂无详情"),
        "hr_skills": _safe_get_list(fields, "HR技能标签"),
        "benefits": _safe_get_list(fields, "福利标签"),
        "hr_active": _safe_get_text(fields, "HR活跃度", ""),
        "delivery_date": _safe_get_text(fields, "投递日期", ""),
        "fetch_time": _safe_get_text(fields, "抓取时间", ""),
        "work_address": _safe_get_text(fields, "工作地址", ""),
        "my_review": _safe_get_text(fields, "我的复核", ""),
        "interview_transcript": _safe_get_text(fields, "面试记录", ""),
        "ai_rewrite_json": _safe_get_text(fields, "AI改写JSON", "") or _safe_get_text(fields, "AI改写简历", ""),
        "manual_refined_resume": _safe_get_text(fields, "AI改写JSON", ""),
        "dream_picture": _safe_get_text(fields, "理想画像与能力信号", ""),
        "ats_ability_analysis": _safe_get_text(fields, "核心能力词典", ""),
        "resume_audit": _safe_get_text(fields, "简历逐行审计", ""),
        "strong_fit_assessment": _safe_get_text(fields, "高杠杆匹配点", ""),
        "risk_red_flags": _safe_get_text(fields, "致命硬伤与毒点", ""),
        "deep_action_plan": _safe_get_text(fields, "破局行动计划", ""),
        "composite_diagnosis_report": _compose_diagnosis_report(
            dream_picture=_safe_get_text(fields, "理想画像与能力信号", ""),
            ats_ability_analysis=_safe_get_text(fields, "核心能力词典", ""),
            strong_fit_assessment=_safe_get_text(fields, "高杠杆匹配点", ""),
            risk_red_flags=_safe_get_text(fields, "致命硬伤与毒点", ""),
            deep_action_plan=_safe_get_text(fields, "破局行动计划", ""),
        ),
        "greeting_msg": _safe_get_text(fields, "打招呼语", ""),
        "platform": _safe_get_text(fields, "招聘平台", "") or _safe_get_text(fields, "数据来源", "") or default_platform,
        "role": _safe_get_text(fields, "角色", "") or _safe_get_text(fields, "发布人角色", "") or "未知",
        "publish_date": _safe_get_text(fields, "发布日期", ""),
        "grade": _safe_get_text(fields, "综合评级 (A-F)", "") or _safe_get_text(fields, "综合评级", ""),
        "ai_evaluation_detail": _safe_get_text(fields, "AI评估详情", ""),
        "role_match": _safe_get_int(fields, "核心-角色匹配", 0),
        "skills_align": _safe_get_int(fields, "核心-技能重合", 0),
        "seniority": _safe_get_int(fields, "高权-职级资历", 0),
        "compensation": _safe_get_int(fields, "高权-薪资契合", 0),
        "interview_prob": _safe_get_int(fields, "高权-面试概率", 0),
        "company_stage": _safe_get_int(fields, "中权-公司阶段", 0),
        "market_fit": _safe_get_int(fields, "中权-赛道前景", 0),
        "growth": _safe_get_int(fields, "中权-成长空间", 0),
        "job_link": _safe_get_link(fields, "岗位链接"),
        "company_intel": _safe_get_text(fields, "公司业务情报", ""),
        "predicted_qa": _safe_get_text(fields, "专属面试预测", ""),
        "reverse_questions": _safe_get_text(fields, "反问环节建议", ""),
        "live_interview_record": _safe_get_text(fields, "现场面试记录", ""),
        "resume_qa": _safe_get_text(fields, "简历专项QA", ""),
        "interview_time": _safe_get_datetime_local(fields, "面试时间"),
        "interview_location": _safe_get_text(fields, "面试地点", "") or _safe_get_text(fields, "工作地址", ""),
        "amap_link": _safe_get_link(fields, "高德导航直达") or extract_url_from_markdown_link(_safe_get_text(fields, "高德导航直达", "")),
        "interview_prep_report": _safe_get_text(fields, "面试辅导报告", ""),
    }

    if slim:
        for key in _DETAIL_ONLY_KEYS:
            job.pop(key, None)
    return job
