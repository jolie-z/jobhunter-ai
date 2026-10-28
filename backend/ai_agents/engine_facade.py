import os
import sys
from dataclasses import dataclass, field
from typing import Tuple, Dict, Optional, Callable, Any, List

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from .skill_rewrite import run_skill_based_rewrite

EXPECTED_ARTIFACT_COUNT = 11


@dataclass
class RewriteResult:
    """统一改写结果（detailed 通道）。

    `process_resume_rewrite`（5 处批量调用）仍返回 2 元组；需要产物/部分成功
    语义的 router 与测试端点使用 detailed，避免破坏既有链路。
    """

    markdown: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    partial: bool = False
    artifact_count: int = 0
    expected_artifact_count: int = EXPECTED_ARTIFACT_COUNT
    engine: str = "official"
    error_reason: str = ""
    result_kind: str = "resume"
    has_resume_output: bool = True
    final_artifact: str = ""


def resolve_rewrite_engine(skill_id: str = "") -> str:
    """技能 ID → 执行引擎（official / agent）。

    口径：官方 resume_rewrite 固定 official；其余技能读取 skill_contract 的
    engine 字段——多文件包、以及非简历类的单文件通用 skill 走 agent；
    单文件简历类 skill 仍走 official。facade 路由与 router 的 init 事件共用本函数。
    """
    if not skill_id or skill_id in ("resume_rewrite", "default"):
        return "official"
    try:
        from .skills.skill_contract import get_skill_contract

        contract_engine = str(get_skill_contract(skill_id).get("engine") or "official")
        return contract_engine
    except Exception:
        pass
    try:
        from .skills.skill_loader import get_skill_manager

        manager = get_skill_manager()
        meta = manager.skills.get(skill_id)
        if (
            meta
            and getattr(meta, "is_package", False)
            and getattr(meta, "references_count", 0) > 0
        ):
            return "agent"
    except Exception:
        pass
    return "official"


def _load_original_resume(original_resume_override: str) -> str:
    if original_resume_override:
        print("☁️ [Engine Facade] 使用调用方指定的简历底稿（跳过拉取启用简历）")
        return original_resume_override
    print("☁️ [Engine Facade] 正在拉取飞书【启用】状态的基础简历...")
    from .ai_evaluator import load_resume

    return load_resume()


def process_resume_rewrite_detailed(
    jd_text: str,
    diagnosis_dict: dict,
    job_name: str = "",
    rewrite_mode: str = "skill",
    original_resume_override: str = "",
    skill_id: str = "",
    include_diagnosis: bool = True,
    job_record_id: str = "default_job",
    contract: Optional[dict] = None,
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> RewriteResult:
    """执行改写并返回完整结果（markdown/usage/artifacts/partial/engine）。

    与 `process_resume_rewrite` 的差异仅在于返回结构化结果；技能包 runner 一旦
    启动，异常就是显式失败，不再静默回退官方引擎（避免一次失败的智能体运行被
    另一个引擎的结果悄悄覆盖）。

    `contract`：调用方已解析的技能契约快照（skill_rewrite_service 传入）。传入后
    引擎与调用方的对账/部分进度共用同一份契约，不再按 skill_id 重复解析——
    两次独立解析可能在扫描窗口期拿到不同结果，导致对账口径与执行口径漂移。
    """
    print(
        f"\n🚪 [Engine Facade] 收到简历定制请求 | 模式: {rewrite_mode.upper()} | "
        f"岗位: {job_name} | Skill: {skill_id or 'default'} | 带入诊断: {include_diagnosis}"
    )

    engine = resolve_rewrite_engine(skill_id) if rewrite_mode == "skill" else "official"
    if contract is None:
        # 旧调用方不传契约：按 skill_id 现场解析（get_skill_contract 自带持久化缓存）
        contract = {}
        if rewrite_mode == "skill":
            try:
                from .skills.skill_contract import get_skill_contract

                contract = get_skill_contract(skill_id)
            except Exception:
                contract = {}

    # --- 统一动作：拉取底料简历（调用方可通过 override 指定底稿）---
    original_resume = _load_original_resume(original_resume_override)
    if not original_resume:
        return RewriteResult(
            markdown="❌ 简历定制失败：未能从飞书拉取到【启用】状态的基础简历，请前往配置表检查。",
            engine=engine,
            error_reason="未能拉取到【启用】状态的基础简历",
            expected_artifact_count=int(contract.get("expected_artifact_count") or 0),
            result_kind=str(contract.get("output_kind") or "resume"),
            has_resume_output=bool(contract.get("has_resume_output", True)),
        )

    # --- 路由分支 1：基于 Skill 的重构模式 ---
    if rewrite_mode == "skill":
        if engine == "agent":
            print("🤖 [Engine Facade] 路由至 -> Tool-Use 渐进式智能体执行引擎 (Progressive Skill Agent)")
            try:
                from .skills.skill_agent_runner import run_progressive_skill_agent
                from .skills.skill_loader import get_skill_manager

                manager = get_skill_manager()
                main_content = manager.loaded_contents.get(skill_id, "")
                ref_map = manager.reference_maps.get(skill_id, {})
                agent_result = run_progressive_skill_agent(
                    skill_id=skill_id,
                    main_skill_content=main_content,
                    reference_map=ref_map,
                    original_resume=original_resume,
                    jd_text=jd_text,
                    diagnosis_dict=diagnosis_dict if include_diagnosis else None,
                    job_name=job_name,
                    job_record_id=job_record_id,
                    contract=contract,
                    on_event=on_event,
                )
            except Exception as e:
                # 显式失败：不再回退标准 SOP（2026-10-25 工单）
                print(f"❌ [Engine Facade] Tool-Use 智能体执行失败: {e}")
                return RewriteResult(
                    markdown=f"❌ 技能包智能体执行失败: {e}",
                    engine="agent",
                    error_reason=str(e),
                    expected_artifact_count=int(contract.get("expected_artifact_count") or 0),
                    result_kind=str(contract.get("output_kind") or "resume"),
                    has_resume_output=bool(contract.get("has_resume_output", True)),
                )

            return RewriteResult(
                markdown=agent_result.markdown,
                usage=agent_result.usage,
                artifacts=agent_result.artifacts,
                partial=agent_result.partial,
                artifact_count=agent_result.artifact_count,
                expected_artifact_count=agent_result.expected_artifact_count,
                engine="agent",
                error_reason=agent_result.error_reason,
                result_kind=agent_result.result_kind,
                has_resume_output=agent_result.has_resume_output,
                final_artifact=agent_result.final_artifact,
            )

        print("💡 [Engine Facade] 路由至 -> 基于 Skill 的标准 Prompt 重构引擎")
        markdown, usage = run_skill_based_rewrite(
            original_resume=original_resume,
            jd_text=jd_text,
            diagnosis_dict=diagnosis_dict,
            job_name=job_name,
            skill_id=skill_id,
            include_diagnosis=include_diagnosis,
            on_event=on_event,
        )
        error_reason = ""
        if not markdown or markdown.lstrip().startswith("❌"):
            error_reason = (markdown or "改写引擎返回空内容")[:300]
        return RewriteResult(
            markdown=markdown,
            usage=usage or {},
            engine="official",
            error_reason=error_reason,
            expected_artifact_count=int(contract.get("expected_artifact_count") or 0),
            result_kind="resume",
            has_resume_output=True,
            final_artifact=str(contract.get("final_artifact") or ""),
        )

    return RewriteResult(
        markdown=f"❌ 未知的改写模式: {rewrite_mode}",
        engine="official",
        error_reason=f"未知的改写模式: {rewrite_mode}",
    )


def process_resume_rewrite(
    jd_text: str,
    diagnosis_dict: dict,
    job_name: str = "",
    rewrite_mode: str = "skill",
    original_resume_override: str = "",
    skill_id: str = "",
    include_diagnosis: bool = True,
    job_record_id: str = "default_job",
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None
) -> Tuple[str, Dict]:
    """统一的简历改写网关 (Facade) —— 2 元组兼容入口。

    当前仅 5 处批量调用继续使用本函数：
      ai_evaluator.py:608、ai_evaluator.py:792、executor.py:190、
      wave_pipeline.py:375、workflow.py:301。
    这 5 处均不传 skill_id，走官方引擎，不会产生 agent artifacts。
    /test_skill_rewrite 与 router 同步/异步路径已改用
    process_resume_rewrite_detailed（测试端点返回 artifacts 但不落盘）。
    需要 artifacts/partial 的调用方一律使用 detailed。
    """
    result = process_resume_rewrite_detailed(
        jd_text=jd_text,
        diagnosis_dict=diagnosis_dict,
        job_name=job_name,
        rewrite_mode=rewrite_mode,
        original_resume_override=original_resume_override,
        skill_id=skill_id,
        include_diagnosis=include_diagnosis,
        job_record_id=job_record_id,
        on_event=on_event,
    )
    return result.markdown, result.usage


def process_greeting_generation(jd_text: str, diagnosis_dict: dict, resume_text: str, job_name: str = "") -> Tuple[str, Dict]:
    """统一的打招呼语生成网关 (Facade)

    入参:
        - jd_text (str): 目标岗位JD原文
        - diagnosis_dict (dict): 深度诊断报告
        - resume_text (str): 候选人原始简历
        - job_name (str): 岗位名称

    返回:
        - Tuple[str, Dict]: (最终生成的打招呼语纯文本, Token消耗统计)
    """
    from .skill_greeting import run_skill_based_greeting
    return run_skill_based_greeting(jd_text, diagnosis_dict, resume_text, job_name)
