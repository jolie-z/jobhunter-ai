"""执行前预检：读取上下文（不调用 LLM），返回产物契约、加载说明与 token 预估。

独立于 skill_rewrite_service，避免主流水线文件超过 500 行红线；
router 的 /skill_rewrite_preflight 直接调用本模块。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ai_agents.skills.skill_contract import estimate_skill_run
from app.strategy.skill_rewrite_service import resolve_context

logger = logging.getLogger("strategy_skill_preflight")


async def preflight_skill_rewrite(payload: Any) -> dict:
    """执行前预检：读取上下文（不调 LLM），返回产物契约、加载说明与 token 预估。"""
    context = await resolve_context(payload)

    main_content = ""
    reference_map: dict = {}
    skill_name = context.skill_id or "resume_rewrite"
    try:
        from ai_agents.skills.skill_loader import get_skill_manager

        manager = get_skill_manager()
        main_content = manager.loaded_contents.get(context.skill_id, "")
        reference_map = manager.reference_maps.get(context.skill_id, {})
        meta = manager.skills.get(context.skill_id)
        if meta:
            skill_name = meta.name
    except Exception as e:
        logger.warning(f"预检读取技能包内容失败: {e}")

    diagnosis_chars = (
        len(json.dumps(context.diagnosis, ensure_ascii=False)) if context.diagnosis else 0
    )
    estimate = estimate_skill_run(
        skill_id=context.skill_id or "resume_rewrite",
        contract=context.contract,
        main_content=main_content,
        reference_map=reference_map,
        jd_chars=len(context.jd_text),
        resume_chars=len(context.original_resume_override),
        diagnosis_chars=diagnosis_chars,
    )

    warnings = list(dict.fromkeys(context.contract.get("warnings") or []))
    if estimate.get("source") == "heuristic":
        warnings.append("Token 预估为启发式（无同技能历史样本），实际消耗可能差异较大。")
    if not context.has_resume_output and not any("未检测到简历" in w for w in warnings):
        warnings.append("未检测到简历改写产物：执行结果只归档到产物库，不会写回简历库。")

    return {
        "skill_id": context.skill_id or "resume_rewrite",
        "name": skill_name,
        "engine": context.contract.get("engine", "official"),
        "result_kind": context.result_kind,
        "has_resume_output": context.has_resume_output,
        "expected_artifact_count": context.contract.get("expected_artifact_count", 0),
        "final_artifact": context.contract.get("final_artifact"),
        "final_source": context.contract.get("final_source", "unknown"),
        "outputs": context.contract.get("outputs", []),
        "output_count_source": context.contract.get("output_count_source", "unknown"),
        "warnings": warnings,
        "will_load": {
            "skill_md": True,
            "skill_chars": len(main_content),
            "references_count": len(reference_map),
            "jd_chars": len(context.jd_text),
            "resume_chars": len(context.original_resume_override),
            "diagnosis_injected": bool(context.diagnosis) and not context.resume_library_mode,
            "resume_library_mode": context.resume_library_mode,
        },
        "estimated_tokens": estimate,
        "estimate_scope": "skill_and_inputs",
    }
