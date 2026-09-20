import os
import sys
import json
from typing import Tuple, Dict, Optional, Callable, Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from .skill_rewrite import run_skill_based_rewrite

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
    """
    统一的简历改写网关 (Facade)
    
    入参:
        - jd_text (str): 目标岗位JD原文
        - diagnosis_dict (dict): 深度诊断报告（由 deep_evaluate_resume 生成）
        - job_name (str): 岗位名称（主要用于单Agent的记忆检索）
        - rewrite_mode (str): 改写模式，当前固定为 "skill" (基于SOP脚本)
        - original_resume_override (str): 可选，调用方指定的底稿简历文本；
          为空时维持原行为（拉取飞书【启用】状态的基础简历）
        - skill_id (str): 可选，指定动态 Skill 技能 ID（默认为空即官方技能）
        - include_diagnosis (bool): 是否将 AI 岗位诊断报告（毒点与高杠杆点）作为上下文注入改写 Prompt
        - job_record_id (str): 目标岗位记录 ID，供多产物落盘
        - on_event (Callable): 可选，SSE 实时流事件分发回调
        
    返回:
        - Tuple[str, Dict]: (最终定制好的Markdown简历, Token消耗统计)
    """
    print(f"\n🚪 [Engine Facade] 收到简历定制请求 | 模式: {rewrite_mode.upper()} | 岗位: {job_name} | Skill: {skill_id or 'default'} | 带入诊断: {include_diagnosis}")
    
    # --- 统一动作：拉取底料简历（调用方可通过 override 指定底稿）---
    if original_resume_override:
        print("☁️ [Engine Facade] 使用调用方指定的简历底稿（跳过拉取启用简历）")
        original_resume = original_resume_override
    else:
        print("☁️ [Engine Facade] 正在拉取飞书【启用】状态的基础简历...")
        from .ai_evaluator import load_resume
        original_resume = load_resume()
    if not original_resume:
        return "❌ 简历定制失败：未能从飞书拉取到【启用】状态的基础简历，请前往配置表检查。", {}
        
    # --- 路由分支 1：基于 Skill 的重构模式 ---
    if rewrite_mode == "skill":
        # 🌟 智能判断：如果是包含附属规范的多文件技能包，优先路由至 Tool-Use 渐进式 Agent
        if skill_id:
            try:
                from .skills.skill_loader import get_skill_manager
                manager = get_skill_manager()
                if skill_id in manager.skills:
                    meta = manager.skills[skill_id]
                    if meta.is_package and meta.references_count > 0:
                        print("🤖 [Engine Facade] 路由至 -> Tool-Use 渐进式智能体执行引擎 (Progressive Skill Agent)")
                        from .skills.skill_agent_runner import run_progressive_skill_agent
                        main_content = manager.loaded_contents.get(skill_id, "")
                        ref_map = manager.reference_maps.get(skill_id, {})
                        agent_final_md, agent_usage, _ = run_progressive_skill_agent(
                            skill_id=skill_id,
                            main_skill_content=main_content,
                            reference_map=ref_map,
                            original_resume=original_resume,
                            jd_text=jd_text,
                            diagnosis_dict=diagnosis_dict if include_diagnosis else None,
                            job_name=job_name,
                            job_record_id=job_record_id,
                            on_event=on_event
                        )
                        return agent_final_md, agent_usage
            except Exception as e:
                print(f"⚠️ [Engine Facade] 尝试启动 Tool-Use 智能体失败，将回退标准 SOP: {e}")

        print("💡 [Engine Facade] 路由至 -> 基于 Skill 的标准 Prompt 重构引擎")
        return run_skill_based_rewrite(
            original_resume=original_resume,
            jd_text=jd_text,
            diagnosis_dict=diagnosis_dict,
            job_name=job_name,
            skill_id=skill_id,
            include_diagnosis=include_diagnosis
        )
        
    else:
        return f"❌ 未知的改写模式: {rewrite_mode}", {}

def process_greeting_generation(jd_text: str, diagnosis_dict: dict, resume_text: str, job_name: str = "") -> Tuple[str, Dict]:
    """
    统一的打招呼语生成网关 (Facade)
    
    入参:
        - jd_text (str): 目标岗位JD原文
        - diagnosis_dict (dict): 深度诊断报告（由 deep_evaluate_resume 生成）
        - resume_text (str): 候选人原始简历
        - job_name (str): 岗位名称
        
    返回:
        - Tuple[str, Dict]: (最终生成的打招呼语纯文本, Token消耗统计)
    """
    from .skill_greeting import run_skill_based_greeting
    return run_skill_based_greeting(jd_text, diagnosis_dict, resume_text, job_name)