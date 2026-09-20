#!/usr/bin/env python3
"""
Tool-Use Progressive Skill Agent Runner
========================================
类似 Claude Code / Antigravity 的智能体执行引擎：
1. 初始仅注入精简的 SKILL.md 目录与 SOP 流程；
2. 赋予 Agent 工具调用能力（Tool Use）：
   - `read_reference`: 按需查阅 references/ 目录下的具体规范文档（零删减、零压缩）
   - `list_references`: 列出可用参考资料清单
   - `save_step_artifact`: 实时落盘阶段作战产物（如 01_jd_analysis.md, 02_truth_boundary.md ...）
3. 驱动大模型多轮渐进式推演，直到生成 <FINAL_RESUME> 最终简历。
"""

import os
import re
import json
import time
import logging
from typing import Dict, List, Tuple, Optional, Any, Callable
from pathlib import Path

from app.core.config import settings
from app.core.llm_client import get_openai_client
from .skill_dirs import save_skill_result, get_skill_run_dir

logger = logging.getLogger("skill_agent_runner")

# =====================================================================
# 1. 工具定义 (OpenAI Function Calling Schema)
# =====================================================================

SKILL_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_references",
            "description": "列出当前技能包 (Skill Package) 中所有可供查阅的参考资料、行业标准与边界文档清单。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_reference",
            "description": "按需读取指定参考资料文件 (reference file) 的完整内容。在执行具体步骤前查阅对应规则以保证专业性。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "需要查阅的参考资料文件名或相对路径，例如 'references/01_jd_analysis.md' 或 '02_truth_boundary.md'"
                    }
                },
                "required": ["file_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_step_artifact",
            "description": "将当前步骤生成的 Markdown 产物实时保存到工作区（例如保存 01_岗位诊断分析.md、02_真实性边界表.md 或最终定制简历）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "产物规范文件名，如 '01_jd_analysis.md'、'02_truth_boundary.md'、'06_targeted_resume.md'"
                    },
                    "title": {
                        "type": "string",
                        "description": "产物清晰的中文标题，如 '01. 岗位深度诊断与Fit判定'"
                    },
                    "markdown_content": {
                        "type": "string",
                        "description": "该阶段生成的完整 Markdown 文本内容"
                    },
                    "is_final_resume": {
                        "type": "boolean",
                        "description": "此产物是否为最终定稿的求职简历主稿（默认为 false）"
                    }
                },
                "required": ["filename", "title", "markdown_content"]
            }
        }
    }
]


# =====================================================================
# 2. 智能体主运行器 (Runner)
# =====================================================================

def run_progressive_skill_agent(
    skill_id: str,
    main_skill_content: str,
    reference_map: Dict[str, str],
    original_resume: str,
    jd_text: str,
    diagnosis_dict: Optional[Dict] = None,
    job_name: str = "",
    job_record_id: str = "default_job",
    max_turns: int = 16,
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None
) -> Tuple[str, Dict, List[Dict]]:
    """
    运行 Tool-Use 智能体改写流水线
    
    Returns:
        (final_resume_markdown, usage_dict, saved_artifacts_list)
    """
    logger.info(f"🤖 [Skill Agent] 启动 Tool-Use 渐进式智能体 | 技能: {skill_id} | 参考资料总数: {len(reference_map)}")
    print(f"\n" + "="*65)
    print(f"🤖 \033[1;36m[Skill Agent Runner]\033[0m 启动 Tool-Use 渐进式智能体")
    print(f"   技能: {skill_id} | 参考资料库: {len(reference_map)} 篇文档")
    print(f"   岗位: {job_name} | 模式: Progressive Tool Calling")
    print("="*65)

    if on_event:
        on_event("agent_start", {
            "skill_id": skill_id,
            "total_references": len(reference_map),
            "job_name": job_name,
            "message": f"🤖 智能体启动：载入技能《{skill_id}》，挂载 {len(reference_map)} 篇参考资料与工具箱"
        })

    client = get_openai_client()
    if not client:
        err_msg = "❌ AI 服务未配置 (api_key)"
        if on_event:
            on_event("agent_error", {"error": err_msg, "message": err_msg})
        return err_msg, {}, []

    # 1. 组装初始 System Prompt 与可用参考资料清单
    ref_list_summary = []
    for r_name, r_content in sorted(reference_map.items()):
        first_line = r_content.strip().split("\n")[0].replace("#", "").strip() if r_content else ""
        ref_list_summary.append(f"- `{r_name}`: {first_line[:40]}")
    
    ref_catalog_str = "\n".join(ref_list_summary) if ref_list_summary else "（暂无额外参考资料文件）"

    system_prompt = f"""你是一名世界顶级的求职改写与职业规划专家 Agent（架构对齐 Claude Code / Antigravity）。
你正在执行求职改写技能剧本《{skill_id}》。

### 📖 技能 SOP 核心剧本：
```markdown
{main_skill_content.strip()}
```

### 📚 当前技能包拥有的参考资料库 (References Catalog)：
{ref_catalog_str}

### 🛠️ 你的工具箱与执行准则 (Tool-Use Directives)：
1. **渐进式查阅 (Progressive Lookup)**：严禁凭空猜测规范。在推进到具体步骤前，请主动调用 `read_reference(file_name)` 查阅对应的标准和边界。
2. **全套阶段性落盘 (Full Artifacts Delivery)**：
   请严格按照 SKILL.md 规划的 11 份产物结构，逐一调用 `save_step_artifact(filename, title, markdown_content)` 进行落盘：
   - `01_jd_analysis.md` (JD 深度解构与 Fit 判定)
   - `02_materials_audit.md` (材料证据与缺口审计)
   - `03_truth_boundary.md` (真实性边界判定表)
   - `04_evidence_contract.md` (核心主张证据契约)
   - `05_resume_polish.md` (单行精修与要点润色)
   - `06_targeted_resume.md` (定制版简历完整主稿，设置 is_final_resume=True)
   - `07_interview_grilling.md` (面试官深度追问卡)
   - `08_answer_cards.md` (高频考点三段式应答卡)
   - `09_upgrade_plan.md` (0.5天/1天/3天证据提升计划)
   - `10_project_scout.md` (开源项目深度借鉴与复现建议)
   - `11_final_pack.md` (全套作战交付总览)
3. **真实性第一 (Truth Boundary)**：严格遵守真实性底线，不夸大、不捏造。
4. **最终定稿**：当完成全部 11 份产物推演并生成最终定制简历时，请在最终回复中用 `<FINAL_RESUME>...</FINAL_RESUME>` 标签包裹最终简历。
"""

    user_context_parts = [
        "## 🎯 目标岗位 JD 原文：",
        f"```text\n{jd_text.strip()}\n```",
        "## 👤 候选人基础简历底稿：",
        f"```text\n{original_resume.strip()}\n```"
    ]
    if diagnosis_dict:
        diag_str = json.dumps(diagnosis_dict, ensure_ascii=False, indent=2)
        user_context_parts.extend([
            "## 🛡️ 岗位诊断避坑情报（毒点与高杠杆点）：",
            f"```json\n{diag_str}\n```"
        ])
    user_context_parts.append("\n请按照 SKILL.md 规划，调用工具查阅规范并逐步产出各阶段备战文档与最终定制简历。")
    user_prompt = "\n\n".join(user_context_parts)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    saved_artifacts: List[Dict[str, Any]] = []
    final_resume_md = ""
    total_prompt_tokens = 0
    total_completion_tokens = 0
    model_name = settings.OPENAI_MODEL or "gpt-4o"

    turn_count = 0
    while turn_count < max_turns:
        turn_count += 1
        logger.info(f"🔄 [Skill Agent] 执行第 {turn_count}/{max_turns} 轮推演...")
        print(f"\n🔄 \033[94m[Agent Step {turn_count}/{max_turns}]\033[0m 正在向大模型发起推演 (已落盘 {len(saved_artifacts)} 篇)...")

        if on_event:
            on_event("step_start", {
                "step": turn_count,
                "max_turns": max_turns,
                "artifacts_count": len(saved_artifacts),
                "message": f"🔄 正在执行第 {turn_count}/{max_turns} 阶段推演（已归档 {len(saved_artifacts)} 份产物）..."
            })

        try:
            start_t = time.time()
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=SKILL_AGENT_TOOLS,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=8192
            )
            elapsed = time.time() - start_t
        except Exception as e:
            logger.error(f"❌ [Skill Agent] LLM 调用失败: {e}")
            print(f"❌ [Skill Agent] LLM 调用失败: {e}")
            if on_event:
                on_event("agent_error", {"error": str(e), "message": f"❌ 大模型调用异常: {e}"})
            break

        msg = response.choices[0].message
        if response.usage:
            total_prompt_tokens += getattr(response.usage, "prompt_tokens", 0)
            total_completion_tokens += getattr(response.usage, "completion_tokens", 0)

        # 检查是否有 Tool Calls
        tool_calls = getattr(msg, "tool_calls", None) or []
        raw_content = (msg.content or "").strip()
        reasoning_content = (getattr(msg, "reasoning_content", "") or "").strip()

        if reasoning_content:
            print(f"🧠 \033[90m[Agent 深度思考] {reasoning_content[:150]}...\033[0m")
            if on_event:
                on_event("thinking", {
                    "step": turn_count,
                    "reasoning": reasoning_content[:300],
                    "message": f"🧠 深度思考: {reasoning_content[:120]}..."
                })

        # 将 Assistant 消息加入历史
        assistant_msg_dict: Dict[str, Any] = {
            "role": "assistant",
            "content": raw_content or None
        }
        if tool_calls:
            assistant_msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg_dict)

        # 检查是否已包含最终简历
        if raw_content:
            final_match = re.search(r"<FINAL_RESUME>\s*(.*?)\s*</FINAL_RESUME>", raw_content, re.DOTALL | re.IGNORECASE)
            if final_match:
                final_resume_md = final_match.group(1).strip()
                print(f"🎉 \033[92m[Agent 定稿] 成功生成 <FINAL_RESUME> (长度: {len(final_resume_md)} 字符)\033[0m")

        # 如果没有工具调用且大模型给出了回复，结束推演
        if not tool_calls:
            if not final_resume_md and raw_content:
                final_resume_md = raw_content
            print(f"✅ \033[92m[Agent 推演完成] 耗时: {elapsed:.2f}s | 共完成 {turn_count} 轮交互\033[0m")
            break

        # 处理所有 Tool Calls
        for tc in tool_calls:
            func_name = tc.function.name
            call_id = tc.id
            tool_output_str = ""

            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}

            if func_name == "list_references":
                print(f"  🔧 \033[93m[Tool Call]\033[0m list_references()")
                tool_output_str = json.dumps(list(reference_map.keys()), ensure_ascii=False)
                if on_event:
                    on_event("tool_call", {
                        "tool": "list_references",
                        "message": f"🔧 调用工具: list_references() 列出参考资料库"
                    })

            elif func_name == "read_reference":
                target_file = args.get("file_name", "").strip()
                print(f"  🔧 \033[93m[Tool Call]\033[0m read_reference('{target_file}')")
                
                # 模糊匹配 reference_map 中的文件
                matched_content = None
                for r_path, r_text in reference_map.items():
                    if r_path == target_file or r_path.endswith(target_file) or target_file.endswith(r_path) or Path(r_path).name == Path(target_file).name:
                        matched_content = r_text
                        break
                
                if matched_content is not None:
                    tool_output_str = f"# {target_file}\n\n{matched_content}"
                    print(f"     ↳ ✅ 成功读取参考资料，返回 {len(matched_content)} 字符")
                    if on_event:
                        on_event("tool_call", {
                            "tool": "read_reference",
                            "file": target_file,
                            "chars": len(matched_content),
                            "message": f"🔍 查阅规范: {target_file} ({len(matched_content)} 字符)"
                        })
                else:
                    tool_output_str = f"❌ 未找到文件: {target_file}。可用文件列表: {list(reference_map.keys())[:10]}"
                    print(f"     ↳ ⚠️ 文件未找到: {target_file}")
                    if on_event:
                        on_event("tool_call", {
                            "tool": "read_reference",
                            "file": target_file,
                            "error": "not_found",
                            "message": f"⚠️ 文件未找到: {target_file}"
                        })

            elif func_name == "save_step_artifact":
                filename = args.get("filename", f"step_{len(saved_artifacts)+1}.md").strip()
                title = args.get("title", filename).strip()
                md_content = args.get("markdown_content", "").strip()
                is_final = bool(args.get("is_final_resume", False))

                # 规范化文件名
                if not filename.endswith(".md"):
                    filename = f"{filename}.md"
                filename = re.sub(r'[\\/*?:"<>|]', '_', filename)

                artifact_entry = {
                    "name": filename,
                    "title": title,
                    "content": md_content,
                    "is_final_resume": is_final
                }
                saved_artifacts.append(artifact_entry)

                if is_final or "06" in filename or "resume" in filename.lower() or "定制简历" in title:
                    final_resume_md = md_content

                print(f"  💾 \033[92m[Artifact Saved]\033[0m {filename} ({title}, {len(md_content)} bytes)")
                tool_output_str = f"✅ 产物 {filename} 已成功落盘保存。"

                if on_event:
                    on_event("artifact_saved", {
                        "filename": filename,
                        "title": title,
                        "size": len(md_content),
                        "is_final_resume": is_final,
                        "total_artifacts": len(saved_artifacts),
                        "message": f"💾 阶段产物已落盘: {filename} · {title} ({(len(md_content)/1024):.1f} KB)"
                    })

            else:
                tool_output_str = f"❌ 未知工具: {func_name}"

            # 将工具结果反馈给 LLM
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_output_str
            })

    # 如果有产物但没有单独特定的 final_resume_md，取最后一个简历候选或第一篇综合报告
    if not final_resume_md and saved_artifacts:
        for art in reversed(saved_artifacts):
            if art.get("is_final_resume") or "resume" in art["name"].lower() or "06" in art["name"]:
                final_resume_md = art["content"]
                break
        if not final_resume_md:
            final_resume_md = saved_artifacts[-1]["content"]

    # 兜底：如果一次 save_step_artifact 都没有调用，自动提取生成的内容为 06_targeted_resume.md
    if not saved_artifacts and final_resume_md:
        saved_artifacts.append({
            "name": "06_targeted_resume.md",
            "title": "定制简历主稿",
            "content": final_resume_md,
            "is_final_resume": True
        })

    # 本地安全落盘
    total_tokens = total_prompt_tokens + total_completion_tokens
    usage_dict = {
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens
    }

    try:
        files_for_storage = [{"name": a["name"], "content": a["content"]} for a in saved_artifacts]
        save_skill_result(
            job_record_id=job_record_id,
            skill_id=skill_id,
            files=files_for_storage,
            token_usage=usage_dict,
            output_type="multi_markdown"
        )
        print(f"📂 \033[1;32m[Skill Artifacts Persisted]\033[0m 已成功落地 {len(files_for_storage)} 份独立作战产物！")
    except Exception as e:
        logger.warning(f"落盘 Skill 运行产物失败: {e}")

    if on_event:
        on_event("agent_done", {
            "status": "success",
            "total_artifacts": len(saved_artifacts),
            "total_tokens": total_tokens,
            "message": f"🎉 全套作战产物推演完毕！共生成 {len(saved_artifacts)} 份独立作战文档。"
        })

    return final_resume_md, usage_dict, saved_artifacts

