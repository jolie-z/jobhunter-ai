"""Skill 简历改写共享流水线。

同步 `/skill_rewrite_and_save` 与异步 `/skill_rewrite_async` 共用本模块：
1. resolve_context：校验入参、读取岗位诊断、**只读一次**简历底稿并构造对账基线；
2. execute_rewrite：调用 engine_facade.process_resume_rewrite_detailed；
3. finalize：解析 JSON → 写回对账闸 → 原子归档 → 合并隐私 → 写回飞书。

岗位模式与简历库模式使用同一份结构化底稿作为“大模型输入 + 对账基线”，
避免两次读取之间底稿变化导致对账对象错位。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_agents.engine_facade import (
    RewriteResult,
    process_resume_rewrite_detailed,
)
from ai_agents.markdown_to_json import parse_markdown_to_json
from ai_agents.skills.skill_contract import get_skill_contract
from ai_agents.skills.skill_dirs import (
    extract_files_from_skill_output,
    save_skill_result,
)
from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.jobs.action_service import normalize_resume_json_field
from app.services.feishu_service import (
    extract_record_id,
    get_full_active_resume_from_feishu,
)
from app.strategy.config_service import _safe_extract_text
from app.strategy.skill_rewrite_guards import (
    _diagnosis_stage_message,
    _guard_parsed_resume,
    _load_job_diagnosis,
    _parse_result_has_error,
    _resolve_feishu_record_id_sync,
)

logger = logging.getLogger("strategy_skill_rewrite_service")
logger.setLevel(logging.INFO)

OnEvent = Callable[[str, dict], None] | None


class SkillRewriteError(Exception):
    """service 层异常；router 据 status_code 映射 HTTP 响应。"""

    status_code = 500

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class SkillRewriteValidationError(SkillRewriteError):
    status_code = 400


class SkillRewriteGuardError(SkillRewriteError):
    status_code = 422


class SkillRewriteEngineError(SkillRewriteError):
    status_code = 502


class SkillRewritePersistenceError(SkillRewriteError):
    status_code = 502


@dataclass
class SkillRewriteContext:
    job_id: str = ""
    resume_record_id: str = ""
    clean_id: str = ""
    clean_rid: str = ""
    diagnosis: dict = field(default_factory=dict)
    original_resume_override: str = ""
    src_struct: dict | None = None
    personal_info: dict = field(default_factory=dict)
    raw_structured: str = ""
    target_job_id: str = "default"
    target_skill_id: str = "default"
    jd_text: str = ""
    job_name: str = ""
    include_diagnosis: bool = True
    skill_id: str = ""
    resume_library_mode: bool = False
    contract: dict = field(default_factory=dict)
    result_kind: str = "resume"
    has_resume_output: bool = True


@dataclass
class SkillRewriteOutcome:
    markdown: str
    usage: dict
    parsed_json: dict
    artifacts: list
    partial: bool
    artifact_count: int
    expected_artifact_count: int
    engine: str
    result_kind: str = "resume"
    has_resume_output: bool = True
    final_artifact: str = ""
    archive_error: str = ""
    persisted: dict = field(default_factory=dict)


# 基础辅助（诊断读取 / record_id 归一 / 写回对账闸）已拆到
# app/strategy/skill_rewrite_guards.py；此处 import 即 re-export，
# router 与旧测试的 `from skill_rewrite_service import _guard_parsed_resume` 保持不变。

# =====================================================================
# 2. 三段式流水线
# =====================================================================

async def resolve_context(payload: Any) -> SkillRewriteContext:
    """校验入参并构造改写上下文。

    关键约束：岗位模式与简历库模式都只读取一次底稿结构化数据，
    同一份文本既传给大模型，也作为写回对账基线。
    """
    job_id = (payload.job_id or "").strip()
    resume_record_id = (payload.resume_record_id or "").strip()
    if not resume_record_id and not job_id:
        raise SkillRewriteValidationError(
            "需要提供 job_id（岗位模式）或 resume_record_id（简历库模式）",
            status_code=400,
        )

    context = SkillRewriteContext(
        job_id=job_id,
        resume_record_id=resume_record_id,
        jd_text=payload.jd_text or "",
        job_name=payload.job_name or "",
        include_diagnosis=bool(payload.include_diagnosis),
        skill_id=payload.skill_id or "",
        resume_library_mode=bool(resume_record_id),
    )

    try:
        context.contract = get_skill_contract(context.skill_id)
    except Exception as e:
        logger.warning(f"读取 Skill 输出契约失败，回退简历契约: {e}")
        context.contract = {}
    context.result_kind = str(context.contract.get("output_kind") or "resume")
    context.has_resume_output = bool(
        context.contract.get("has_resume_output", context.result_kind == "resume")
    )

    # ===== 1. 岗位诊断 =====
    if context.job_id:
        context.clean_id = _resolve_feishu_record_id_sync(extract_record_id(context.job_id))
        # 简历库模式不注入岗位诊断（与异步通道原有口径一致，也避免无谓的飞书读取）；
        # 岗位模式才读取诊断并校验岗位记录存在。
        if not context.resume_library_mode:
            diagnosis_error = False
            try:
                record, context.diagnosis = await _load_job_diagnosis(
                    context.clean_id,
                    parse_diagnosis=context.include_diagnosis,
                )
            except Exception as e:
                logger.warning(f"读取岗位诊断失败（继续改写）: {e}")
                record, context.diagnosis = None, {}
                diagnosis_error = True
            # 飞书读取异常不判 404（旧异步通道同样继续）；只有明确查无记录才 404
            if not record and not diagnosis_error:
                raise SkillRewriteValidationError("Job not found", status_code=404)

    # ===== 2. 底稿与隐私数据 =====
    if context.resume_library_mode:
        if not context.jd_text.strip():
            raise SkillRewriteValidationError(
                "简历库模式需要提供 jd_text（如 A级岗位画像）", status_code=400
            )
        context.clean_rid = _resolve_feishu_record_id_sync(
            extract_record_id(context.resume_record_id)
        )
        if not context.clean_rid.startswith("rec"):
            # 平台前缀（51job-recXXX / liepin-recXXX）允许，清洗后必须是纯 rec id；
            # temp_ 本地草稿与反查不到 raw_<rowid> 的简历在此明确拒绝。
            raise SkillRewriteValidationError(
                "该简历尚未同步到飞书（本地草稿），请先在简历库点击「保存并同步」后再改写",
                status_code=400,
            )
        try:
            resume_rec = await feishu_client.get_record(
                settings.FEISHU_TABLE_ID_RESUMES, context.clean_rid
            )
        except Exception as e:
            raise SkillRewriteEngineError(f"读取简历记录失败: {e}", status_code=502)
        if not resume_rec:
            raise SkillRewriteValidationError("简历记录不存在", status_code=404)

        raw_structured = _safe_extract_text(
            resume_rec.get("fields", {}).get("结构化数据", "")
        )
        if not raw_structured.strip():
            raise SkillRewriteValidationError(
                "该简历没有结构化数据，无法作为改写底稿", status_code=400
            )
        try:
            src_dict = json.loads(raw_structured)
        except Exception:
            raise SkillRewriteValidationError(
                "结构化数据不是合法 JSON，无法改写", status_code=500
            )
        if not isinstance(src_dict, dict):
            raise SkillRewriteValidationError(
                "结构化数据不是 JSON object，无法改写", status_code=500
            )

        personal_info = src_dict.pop("personalInfo", {}) or {}
        context.personal_info = personal_info if isinstance(personal_info, dict) else {}
        context.src_struct = src_dict
        context.raw_structured = raw_structured
        context.original_resume_override = json.dumps(src_dict, ensure_ascii=False)
    else:
        # 岗位模式：只读一次启用简历，同时作为大模型输入与对账基线
        raw_structured = ""
        try:
            raw_structured = await asyncio.to_thread(get_full_active_resume_from_feishu)
        except Exception as e:
            logger.warning(f"读取启用简历结构化数据失败: {e}")

        if raw_structured.strip():
            try:
                src_dict = json.loads(raw_structured)
            except Exception:
                src_dict = None
            if isinstance(src_dict, dict):
                personal_info = src_dict.pop("personalInfo", {}) or {}
                context.personal_info = personal_info if isinstance(personal_info, dict) else {}
                context.src_struct = src_dict
                context.raw_structured = raw_structured
                context.original_resume_override = json.dumps(src_dict, ensure_ascii=False)
            else:
                context.original_resume_override = raw_structured.strip()
        else:
            logger.warning(
                "岗位模式未读取到启用简历结构化数据，引擎将回退 load_resume()（无对账基线）"
            )

    context.target_job_id = context.clean_id or context.clean_rid or "default"
    context.target_skill_id = context.skill_id or "default"
    return context


async def execute_rewrite(
    context: SkillRewriteContext, on_event: OnEvent = None
) -> RewriteResult:
    """执行改写，返回 artifacts/partial/engine 等完整结果。"""
    if on_event:
        on_event("thinking", {
            "stage": "prepare",
            "message": _diagnosis_stage_message(
                context.resume_record_id or None,
                context.include_diagnosis,
                context.diagnosis,
            ),
        })

    result = await asyncio.to_thread(
        process_resume_rewrite_detailed,
        jd_text=context.jd_text,
        diagnosis_dict=context.diagnosis,
        job_name=context.job_name,
        rewrite_mode="skill",
        original_resume_override=context.original_resume_override,
        skill_id=context.skill_id,
        include_diagnosis=context.include_diagnosis,
        job_record_id=context.target_job_id,
        contract=context.contract,
        on_event=on_event,
    )

    if not result.markdown or result.markdown.lstrip().startswith("❌"):
        raise SkillRewriteEngineError(
            result.error_reason or result.markdown or "改写引擎返回空内容"
        )
    return result


async def _archive_artifacts(
    context: SkillRewriteContext, result: RewriteResult, on_event: OnEvent = None
) -> tuple[list, str]:
    """归档产物（对账之后调用）。返回 (artifact_files, archive_error)。"""
    raw_artifacts = result.artifacts or extract_files_from_skill_output(result.markdown)
    deduped: dict[str, dict] = {}
    for item in raw_artifacts:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        deduped[name] = {"name": name, "content": item.get("content", "")}
    artifact_files = list(deduped.values())

    archive_error = ""
    if not artifact_files:
        archive_error = "无可归档产物"
        logger.warning("[skill_pipeline] 无可归档产物，跳过本地归档")
    else:
        try:
            save_skill_result(
                job_record_id=context.target_job_id,
                skill_id=context.target_skill_id,
                files=artifact_files,
                token_usage=result.usage if isinstance(result.usage, dict) else {},
                output_type="multi_markdown",
                replace_existing=True,
                meta_extra={
                    "partial": result.partial,
                    "artifact_count": len(artifact_files),
                    "expected_artifact_count": result.expected_artifact_count,
                    "engine": result.engine,
                    "result_kind": result.result_kind,
                    "has_resume_output": result.has_resume_output,
                    "final_artifact": result.final_artifact or context.contract.get("final_artifact"),
                    "error_reason": result.error_reason if result.partial else "",
                },
            )
        except Exception as e:
            archive_error = str(e)
            logger.warning(f"[skill_pipeline] 保存 Skill 本地归档失败（不阻断交付）: {e}")

    if on_event:
        if archive_error:
            on_event("thinking", {
                "stage": "archive_error",
                "message": f"⚠️ 本地归档失败（已继续后续流程）: {archive_error}",
            })
        else:
            on_event("artifact_saved", {
                "stage": "archive",
                "result_kind": result.result_kind,
                "final_artifact": result.final_artifact or context.contract.get("final_artifact"),
                "partial": result.partial,
                "artifact_count": len(artifact_files),
                "expected_artifact_count": result.expected_artifact_count,
                "message": (
                    f"💾 全套产物已归档（{len(artifact_files)}/{result.expected_artifact_count} 份）"
                    if not result.partial and result.expected_artifact_count
                    else f"💾 产物已归档（{len(artifact_files)} 份）"
                ),
            })
    return artifact_files, archive_error


async def finalize(
    context: SkillRewriteContext, result: RewriteResult, on_event: OnEvent = None
) -> SkillRewriteOutcome:
    """解析（仅简历）→ 对账（仅简历）→ 原子归档 → 合并隐私/写回（仅简历）。"""
    parsed_json: dict = {}
    if result.result_kind == "resume":
        if on_event:
            on_event("thinking", {
                "stage": "parse",
                "message": "🧩 大模型定稿出炉，正在解析为结构化 JSON…（网关繁忙时此步可能需要数分钟，任务在后台不会中断）",
            })
        try:
            parsed_json = await asyncio.to_thread(parse_markdown_to_json, result.markdown)
        except Exception as e:
            raise SkillRewriteEngineError(f"解析 Markdown 为 JSON 失败: {e}", status_code=502)

        # 写回对账保底闸：解析失败标记与模块清零一律拒绝落盘
        try:
            _guard_parsed_resume(context.src_struct, parsed_json)
        except ValueError as guard_err:
            logger.error(f"[skill_pipeline] 写回前对账拦截: {guard_err}")
            raise SkillRewriteGuardError(str(guard_err))
        if _parse_result_has_error(parsed_json):
            detail = (
                str(parsed_json.get("error"))[:200]
                if isinstance(parsed_json, dict)
                else "解析器返回非 dict"
            )
            raise SkillRewriteGuardError(f"改写稿解析为结构化 JSON 失败，未写回飞书：{detail}")

    artifact_files, archive_error = await _archive_artifacts(context, result, on_event)

    # 非简历 skill：只归档并返回最终交付物，不碰简历 JSON / 飞书字段
    if result.result_kind != "resume":
        return SkillRewriteOutcome(
            markdown=result.markdown,
            usage=result.usage or {},
            parsed_json={},
            artifacts=artifact_files,
            partial=result.partial,
            artifact_count=len(artifact_files),
            expected_artifact_count=result.expected_artifact_count,
            engine=result.engine,
            result_kind=result.result_kind,
            has_resume_output=result.has_resume_output,
            final_artifact=result.final_artifact or str(context.contract.get("final_artifact") or ""),
            archive_error=archive_error,
            persisted={"ai_rewrite_json": False, "follow_status": None},
        )

    # 合并隐私数据
    if not context.personal_info:
        context.personal_info = {
            "name": "未填写",
            "phone": "未填写",
            "email": "未填写",
            "location": "未填写",
        }
    if not isinstance(parsed_json.get("personalInfo"), dict):
        parsed_json["personalInfo"] = context.personal_info
    else:
        parsed_json["personalInfo"].update(context.personal_info)

    # 改写前备份旧结构化数据（简历库模式）
    if context.resume_library_mode:
        try:
            from app.core.db_paths import writable_path

            backup_dir = writable_path(
                Path(__file__).resolve().parent.parent.parent.parent / "data" / "resume_backups",
                "resume_backups",
            )
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_name = f"{context.clean_rid}_{time.strftime('%Y%m%d_%H%M%S')}_before_rewrite.json"
            (backup_dir / backup_name).write_text(
                context.raw_structured or "{}", encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"改写前备份旧结构化数据失败: {e}")

    if on_event:
        on_event("tool_call", {
            "tool": "feishu_write",
            "message": "☁️ 正在写回飞书（AI改写JSON + 跟进状态）…",
        })

    ai_rewrite_json_str = normalize_resume_json_field(parsed_json)
    if context.resume_library_mode:
        saved = await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_RESUMES,
            record_id=context.clean_rid,
            fields={"结构化数据": ai_rewrite_json_str},
        )
        if not saved:
            raise SkillRewritePersistenceError(
                "改写已完成，但写回简历库失败。请稍后重试", status_code=502
            )
        follow_status = None
    else:
        saved = await feishu_client.update_record(
            table_id=settings.FEISHU_TABLE_ID_JOBS,
            record_id=context.clean_id,
            fields={
                "AI改写JSON": ai_rewrite_json_str,
                "跟进状态": "简历人工复核",
            },
        )
        if not saved:
            raise SkillRewritePersistenceError(
                "改写已完成，但写回岗位记录失败。请稍后重试", status_code=502
            )
        follow_status = "简历人工复核"

    return SkillRewriteOutcome(
        markdown=result.markdown,
        usage=result.usage or {},
        parsed_json=parsed_json,
        artifacts=artifact_files,
        partial=result.partial,
        artifact_count=len(artifact_files),
        expected_artifact_count=result.expected_artifact_count,
        engine=result.engine,
        result_kind="resume",
        has_resume_output=True,
        final_artifact=result.final_artifact or str(context.contract.get("final_artifact") or ""),
        archive_error=archive_error,
        persisted={
            "ai_rewrite_json": True,
            "follow_status": follow_status,
        },
    )


async def run_skill_rewrite_pipeline(payload: Any, on_event: OnEvent = None) -> SkillRewriteOutcome:
    """同步/异步接口共用的完整流水线。"""
    context = await resolve_context(payload)
    result = await execute_rewrite(context, on_event)
    return await finalize(context, result, on_event)
