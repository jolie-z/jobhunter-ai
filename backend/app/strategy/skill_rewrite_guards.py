"""Skill 改写共享辅助：诊断读取、record_id 归一、写回对账闸。

从 router/service 抽出，保持单文件 <500 行；router 仍可从 skill_rewrite_service
导入这些名字（service 做了 re-export），旧测试导入面不变。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ai_agents.skill_rewrite import diagnosis_has_content
from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.strategy.config_service import _safe_extract_text

logger = logging.getLogger("strategy_skill_rewrite_guards")

_REWRITE_GUARD_MODULES = {
    "workExperience": "工作经历",
    "personalProjects": "项目经历",
    "education": "教育背景",
}


def _parse_result_has_error(parsed: Any) -> bool:
    """解析器失败形态判定：{"error":...} 或非 dict（markdown_to_json 的失败约定）。"""
    return not isinstance(parsed, dict) or "error" in parsed


def _diagnosis_stage_message(
    resume_record_id: str | None, include_diagnosis: bool, diagnosis_dict: dict | None
) -> str:
    """异步通道「诊断阶段」的 SSE 文案，四态与诊断是否真进了 Prompt 严格对应。"""
    if resume_record_id:
        return "📄 简历库模式：无岗位诊断上下文，以传入的目标画像作为改写输入"
    if not include_diagnosis:
        return "🧪 纯净模式：已跳过岗位深度诊断注入"
    if diagnosis_has_content(diagnosis_dict):
        return "🩺 岗位深度诊断上下文就绪（已注入改写 Prompt）"
    return "⚠️ 未读到岗位深度诊断（字段为空或读取失败），将以无诊断上下文继续改写"


def _resolve_feishu_record_id_sync(candidate: str, raw_db_path: str | None = None) -> str:
    """岗位标识归一：rec 开头原样返回；raw_<rowid>/纯数字 查本地台账回填飞书 record_id。"""
    candidate = (candidate or "").strip()
    if not candidate or candidate.startswith("rec"):
        return candidate
    rowid_digits = candidate[4:] if candidate.lower().startswith("raw_") else candidate
    if not rowid_digits.isdigit():
        return ""
    import sqlite3
    if not raw_db_path:
        from app.automation.scrape_runner import _get_raw_db_path
        raw_db_path = _get_raw_db_path()
    db = raw_db_path
    try:
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT feishu_record_id FROM raw_jobs WHERE rowid = ? AND feishu_record_id != ''",
                (int(rowid_digits),),
            ).fetchone()
            return (row[0] or "").strip() if row else ""
    except Exception as e:
        logger.warning(f"反查 raw_jobs.feishu_record_id 失败 (rowid={rowid_digits}): {e}")
        return ""


async def _load_job_diagnosis(
    clean_id: str, parse_diagnosis: bool = True
) -> tuple[dict | None, dict]:
    """读取岗位记录与深度诊断（合成报告优先，缺失时退回 6 个分字段）。

    parse_diagnosis=False 时只做记录存在性校验，不解析 6 个诊断字段
    （纯净模式 include_diagnosis=False 用）。
    """
    if not clean_id:
        return None, {}
    record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, clean_id)
    if not record:
        return None, {}
    if not parse_diagnosis:
        return record, {}
    fields = record.get("fields", {})
    diagnosis_dict: dict = {}
    analysis_report = _safe_extract_text(fields.get("深度分析诊断报告(AI)"))
    if analysis_report:
        try:
            loaded = json.loads(analysis_report)
            if isinstance(loaded, dict):
                diagnosis_dict = loaded
        except json.JSONDecodeError:
            pass
    if not diagnosis_dict:
        diagnosis_dict = {
            "dream_picture": _safe_extract_text(fields.get("理想画像与能力信号")),
            "ats_ability_analysis": _safe_extract_text(fields.get("核心能力词典")),
            "resume_audit": _safe_extract_text(fields.get("简历逐行审计")),
            "strong_fit_assessment": _safe_extract_text(fields.get("高杠杆匹配点")),
            "risk_red_flags": _safe_extract_text(fields.get("致命硬伤与毒点")),
            "deep_action_plan": _safe_extract_text(fields.get("破局行动计划")),
        }
    return record, diagnosis_dict


def _guard_parsed_resume(src_structured, parsed_json) -> None:
    """写回飞书前置闸，两类脏数据一律拒绝落盘：

    1. 解析器失败标记：markdown_to_json 失败时返回 {"error": ...}；
    2. 模块清零：原结构化数据非空的模块在改写结果中条数归零。
       剧本允许按岗位相关性合理裁剪（4→2 放行），但 4→0 是输出截断/解析残缺
       的特征，宁可拒绝也不清空用户数据。
    """
    if isinstance(parsed_json, dict) and parsed_json.get("error"):
        raise ValueError(
            f"改写产物 Markdown→JSON 解析失败，已保留原简历数据：{str(parsed_json['error'])[:200]}"
        )
    if isinstance(src_structured, str):
        try:
            src_structured = json.loads(src_structured)
        except Exception:
            src_structured = None
    if not isinstance(src_structured, dict) or not isinstance(parsed_json, dict):
        return
    wiped = []
    for key, cn in _REWRITE_GUARD_MODULES.items():
        old, new = src_structured.get(key), parsed_json.get(key)
        old_n = len(old) if isinstance(old, list) else 0
        new_n = len(new) if isinstance(new, list) else 0
        if old_n > 0 and new_n == 0:
            wiped.append(cn)
    if wiped:
        raise ValueError(
            f"改写结果丢失了原有模块（{'、'.join(wiped)}：原非空、改写后被清空，疑似输出截断或解析残缺），"
            f"已拒绝写回并保留原简历数据，请重试改写"
        )
