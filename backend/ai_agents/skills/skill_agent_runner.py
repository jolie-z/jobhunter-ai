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

定稿语义（2026-10-25 工单）：
- 只认三种来源：闭合的 <FINAL_RESUME> 标签、精确文件名 06_targeted_resume.md、
  以及 06 上的 is_final_resume=True。`05_resume_polish.md` 等文件名含 resume 的
  阶段产物绝不自动升级为定稿。
- finish_reason=length 的轮次整轮作废（含 tool_calls，参数可能半截），追加续写指令；
  连续/累计截断超限才停。
- 06 有效但其余产物未跑完时返回 partial=True，由上层按“部分成功”写回；
  没有有效 06 才判失败。
- 本模块不再直接写磁盘；产物随返回值交给 router，在对账闸通过后原子归档。
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.llm_client import chat_create_no_thinking, get_openai_client

logger = logging.getLogger("skill_agent_runner")

EXPECTED_ARTIFACT_COUNT = 11
AGENT_MAX_TOKENS = 32768
MAX_CONSECUTIVE_TRUNCATIONS = 3
MAX_TOTAL_TRUNCATIONS = 5
MAX_CONTINUATION_ATTEMPTS = 2
FINAL_ARTIFACT_NAME = "06_targeted_resume.md"

_RESUME_MODULE_GROUPS = (
    ("工作经历", "work experience", "experience"),
    ("项目经历", "project experience", "projects"),
    ("教育", "education"),
    ("个人优势", "summary", "profile"),
    ("专业技能", "skills"),
    ("实习经历", "internship"),
    ("求职意向", "objective"),
    ("技能特长", "expertise"),
)

_TRUNCATION_CONTINUE_PROMPT = """上一轮输出因长度上限被截断，本轮的全部工具调用已丢弃（{discarded}）。
请不要拼接残缺内容；请重新完整调用 save_step_artifact(...)，每次只写 1 份产物，单份内容控制在约 6000 字以内，落盘后再继续下一份。"""

_NARRATION_CONTINUE_PROMPT = """你刚才只输出了过程性说明，还没有产出可用的最终交付物。
请继续执行 SOP：调用 save_step_artifact 逐份落盘产物；完成后用 <FINAL_RESUME> 或 <FINAL_OUTPUT> 包裹最终交付物，或将最终文件标记 is_final_resume=True。"""

_CONTINUATION_PLACEHOLDER = "（上一轮输出未产生可用内容）"


@dataclass
class ProgressiveAgentResult:
    """渐进式技能智能体的结构化结果。

    markdown 为空表示失败；partial=True 表示 06 主稿有效但其余产物/轮次未完成，
    上层应按“部分成功”处理（写回 + 标记 N/11）。
    """

    markdown: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    partial: bool = False
    artifact_count: int = 0
    expected_artifact_count: int = EXPECTED_ARTIFACT_COUNT
    engine: str = "agent"
    error_reason: str = ""
    result_kind: str = "resume"
    has_resume_output: bool = True
    final_artifact: str = ""


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
# 2. 定稿/内容判定辅助
# =====================================================================

def _looks_like_resume(text: str) -> bool:
    """内容侧二次校验（只用于挡过渡语/空稿/半截稿，不承担定稿身份判断）。

    身份判断由 _is_canonical_final_name（精确 06）或 <FINAL_RESUME> 标签负责——
    05_resume_polish 本身就像简历，单靠内容相似度无法区分。
    """
    if not text:
        return False
    cleaned = text.strip()
    if len(cleaned) < 300:
        return False
    lowered = cleaned.lower()
    module_hits = sum(
        1 for group in _RESUME_MODULE_GROUPS if any(kw in lowered for kw in group)
    )
    if module_hits < 2:
        return False
    if cleaned[-1] in "，,、：:；;—-_":
        return False
    if cleaned.count("```") % 2 != 0:
        return False
    return True


def _looks_like_complete_document(text: str) -> bool:
    """通用 Markdown/文本终稿校验：不要求简历模块，只挡空稿/过渡语/半截稿。"""
    if not text:
        return False
    cleaned = text.strip()
    if len(cleaned) < 200:
        return False
    if cleaned[-1] in "，,、：:；;—-_":
        return False
    if cleaned.count("```") % 2 != 0:
        return False
    lowered = cleaned.lower()
    if len(cleaned) < 400 and any(
        marker in lowered for marker in (
            "现在按 sop", "逐阶段落盘", "我将开始", "接下来我会", "已完成思考", "开始执行",
        )
    ):
        return False
    return True


def _validate_final_content(text: str, output_kind: str) -> bool:
    if output_kind == "resume":
        return _looks_like_resume(text)
    if output_kind == "json":
        try:
            import json as _json
            return isinstance(_json.loads(text), (dict, list))
        except Exception:
            return False
    return _looks_like_complete_document(text)


def _is_canonical_final_name(filename: str, final_name: str = FINAL_ARTIFACT_NAME) -> bool:
    return (filename or "").strip().lower() == (final_name or "").strip().lower()


def _extract_final_tag(content: str) -> Tuple[str, bool]:
    """提取 <FINAL_RESUME> 标签内容。

    Returns:
        (内容, 是否闭合)。只有开标签没有闭标签时返回 ("", False)，
        由调用方按“定稿没写完”处理，绝不把半截全文当正文。
    """
    if not content:
        return "", False
    match = re.search(
        r"<(FINAL_RESUME|FINAL_OUTPUT)>\s*(.*?)\s*</\1>",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(2).strip(), True
    if re.search(r"<(FINAL_RESUME|FINAL_OUTPUT)>", content, re.IGNORECASE):
        return "", False
    return "", False


def _discarded_tool_label(tc: Any) -> str:
    """截断轮的可读工具标识，用于续写提示。"""
    try:
        args = json.loads(getattr(tc.function, "arguments", "") or "{}")
    except Exception:
        args = {}
    name = getattr(tc.function, "name", "unknown")
    target = args.get("filename") or args.get("file_name") or ""
    return f"{name}({target})" if target else f"{name}()"


def _normalize_filename(raw: str, fallback: str) -> str:
    filename = (raw or fallback).strip() or fallback
    if not filename.lower().endswith(
        (".md", ".markdown", ".json", ".txt", ".csv", ".yaml", ".yml")
    ):
        filename = f"{filename}.md"
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


# =====================================================================
# 3. 智能体主运行器 (Runner)
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
    contract: Optional[Dict[str, Any]] = None,
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None
) -> ProgressiveAgentResult:
    """运行 Tool-Use 智能体流水线。

    contract 由 skill_contract 扫描生成：outputs/final_artifact/output_kind/
    expected_artifact_count 决定提示词、定稿识别、内容校验与 partial 计数。
    contract 为 None 时保留旧的 11 份简历 SOP 行为（直接调用/旧测试兼容）。
    本函数只做推演与产物收集，不写磁盘；归档由 router 在对账通过后执行。
    """
    logger.info(
        f"🤖 [Skill Agent] 启动 Tool-Use 渐进式智能体 | 技能: {skill_id} | "
        f"参考资料总数: {len(reference_map)} | job_record_id={job_record_id}"
    )
    print("\n" + "=" * 65)
    print("🤖 \033[1;36m[Skill Agent Runner]\033[0m 启动 Tool-Use 渐进式智能体")
    print(f"   技能: {skill_id} | 参考资料库: {len(reference_map)} 篇文档")
    print(f"   岗位: {job_name} | 模式: Progressive Tool Calling")
    print("=" * 65)

    if on_event:
        on_event("agent_start", {
            "engine": "agent",
            "skill_id": skill_id,
            "total_references": len(reference_map),
            "job_name": job_name,
            "message": f"🤖 智能体启动：载入技能《{skill_id}》，挂载 {len(reference_map)} 篇参考资料与工具箱"
        })

    client = get_openai_client()
    if not client:
        err_msg = "❌ AI 服务未配置 (api_key)"
        logger.error(err_msg)
        if on_event:
            on_event("agent_error", {"error": err_msg, "message": err_msg})
        return ProgressiveAgentResult(error_reason=err_msg, engine="agent")

    # 1. 组装初始 System Prompt 与可用参考资料清单
    ref_list_summary = []
    for r_name, r_content in sorted(reference_map.items()):
        first_line = r_content.strip().split("\n")[0].replace("#", "").strip() if r_content else ""
        ref_list_summary.append(f"- `{r_name}`: {first_line[:40]}")

    ref_catalog_str = "\n".join(ref_list_summary) if ref_list_summary else "（暂无额外参考资料文件）"

    # ---- 输出契约（skill_contract 扫描结果）----
    contract_provided = contract is not None
    contract = contract or {}
    output_specs = contract.get("outputs") or []
    final_artifact_name = str(contract.get("final_artifact") or "").strip()
    output_kind = str(contract.get("output_kind") or "resume")
    has_resume_output = bool(contract.get("has_resume_output", output_kind == "resume"))
    expected_count = int(contract.get("expected_artifact_count") or 0)
    if not contract_provided:
        # 兼容旧直接调用：11 份简历 SOP
        output_kind = "resume"
        has_resume_output = True
        expected_count = EXPECTED_ARTIFACT_COUNT
        final_artifact_name = FINAL_ARTIFACT_NAME

    required_specs = [s for s in output_specs if s.get("required", True)]
    if output_specs:
        artifact_lines = []
        for spec in output_specs:
            filename = str(spec.get("filename") or "").strip()
            if not filename:
                continue
            title = str(spec.get("title") or "").strip()
            label = f" ({title})" if title and title != filename else ""
            final_hint = "（最终交付物，设置 is_final_resume=True）" if spec.get("is_final") else ""
            artifact_lines.append(f"   - `{filename}`{label}{final_hint}")
        artifact_instructions = (
            f"请严格按照 SKILL.md 规划的 {len(required_specs) or len(output_specs)} 份产物结构，"
            "逐一调用 `save_step_artifact(filename, title, markdown_content)` 进行落盘：\n"
            + "\n".join(artifact_lines)
        )
    elif contract_provided:
        artifact_instructions = (
            "请严格按照 SKILL.md 的产物结构，逐一调用 `save_step_artifact(filename, title, markdown_content)` 落盘；"
            "文件名以 SKILL.md 为准。\n"
            "   如果 SKILL.md 没有明确最终文件，请在全部产物完成后，用 `<FINAL_OUTPUT>...</FINAL_OUTPUT>` "
            "包裹最终交付物，或将最终文件标记 `is_final_resume=True`。"
        )
    else:
        artifact_instructions = """请严格按照 SKILL.md 规划的 11 份产物结构，逐一调用 `save_step_artifact(filename, title, markdown_content)` 进行落盘：
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
   - `11_final_pack.md` (全套作战交付总览)"""

    if output_kind == "resume":
        final_tag_hint = "请在最终回复中用 `<FINAL_RESUME>...</FINAL_RESUME>` 标签包裹最终简历。"
    else:
        final_tag_hint = (
            "请在最终回复中用 `<FINAL_OUTPUT>...</FINAL_OUTPUT>` 标签包裹最终交付物，"
            "或将最终文件标记 `is_final_resume=True`。"
        )
    persona = (
        "你是一名世界顶级的求职改写与职业规划专家 Agent（架构对齐 Claude Code / Antigravity）。"
        if has_resume_output else
        "你是一名严格按照技能剧本交付产物的专家 Agent（架构对齐 Claude Code / Antigravity）。"
    )
    skill_noun = "求职改写技能剧本" if has_resume_output else "技能剧本"

    system_prompt = f"""{persona}
你正在执行{skill_noun}《{skill_id}》。

### 📖 技能 SOP 核心剧本：
```markdown
{main_skill_content.strip()}
```

### 📚 当前技能包拥有的参考资料库 (References Catalog)：
{ref_catalog_str}

### 🛠️ 你的工具箱与执行准则 (Tool-Use Directives)：
1. **渐进式查阅 (Progressive Lookup)**：严禁凭空猜测规范。在推进到具体步骤前，请主动调用 `read_reference(file_name)` 查阅对应的标准和边界。
2. **全套阶段性落盘 (Full Artifacts Delivery)**：
   {artifact_instructions}
3. **真实性第一 (Truth Boundary)**：严格遵守真实性底线，不夸大、不捏造。
4. **最终定稿**：{final_tag_hint}
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

    # 文件名 → 产物（同文件重复保存时保留最新有效版本）
    artifacts_by_name: Dict[str, Dict[str, Any]] = {}
    final_resume_md = ""
    final_source = ""
    final_actual_name = ""
    total_prompt_tokens = 0
    total_cached_tokens = 0
    total_completion_tokens = 0
    model_name = settings.OPENAI_MODEL or "gpt-4o"

    turn_count = 0
    truncation_count = 0
    consecutive_truncations = 0
    continuation_attempts = 0
    run_error = ""
    partial_reason = ""

    while turn_count < max_turns:
        turn_count += 1
        logger.info(f"🔄 [Skill Agent] 执行第 {turn_count}/{max_turns} 轮推演...")
        print(f"\n🔄 \033[94m[Agent Step {turn_count}/{max_turns}]\033[0m 正在向大模型发起推演 (已落盘 {len(artifacts_by_name)} 篇)...")

        if on_event:
            on_event("step_start", {
                "engine": "agent",
                "result_kind": output_kind,
                "step": turn_count,
                "max_turns": max_turns,
                "artifacts_count": len(artifacts_by_name),
                "message": f"🔄 正在执行第 {turn_count}/{max_turns} 阶段推演（已归档 {len(artifacts_by_name)} 份产物）..."
            })

        try:
            start_t = time.time()
            # 2026-10-25 工单：与 10-23 官方引擎同款防护——推理模型思考计入 completion
            # 预算，8192 会被思考烧穿；提额到 32768 并默认关思考（网关拒参自动降级重发）。
            response = chat_create_no_thinking(
                client,
                model=model_name,
                messages=messages,
                tools=SKILL_AGENT_TOOLS,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=AGENT_MAX_TOKENS,
            )
            elapsed = time.time() - start_t
        except Exception as e:
            logger.error(f"❌ [Skill Agent] LLM 调用失败: {e}")
            print(f"❌ [Skill Agent] LLM 调用失败: {e}")
            run_error = f"大模型调用异常: {e}"
            break

        choice = response.choices[0] if getattr(response, "choices", None) else None
        if choice is None or getattr(choice, "message", None) is None:
            run_error = "大模型返回空 choices/message"
            logger.error(f"❌ [Skill Agent] {run_error}")
            break

        msg = choice.message
        finish_reason = (getattr(choice, "finish_reason", "") or "").strip()
        if response.usage:
            total_prompt_tokens += getattr(response.usage, "prompt_tokens", 0)
            total_completion_tokens += getattr(response.usage, "completion_tokens", 0)
            total_cached_tokens += getattr(getattr(response.usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            if on_event:
                on_event("usage", {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens,
                    "cached_tokens": total_cached_tokens,
                    "message": f"🪙 Token 累计 {total_prompt_tokens + total_completion_tokens}",
                })

        tool_calls = getattr(msg, "tool_calls", None) or []
        raw_content = (msg.content or "").strip()
        reasoning_content = (getattr(msg, "reasoning_content", "") or "").strip()

        # 观测缺口补齐：每轮把实际模型/结束原因/输出预算打出来，复盘不再靠网关日志反推
        logger.info(
            "🤖 [Skill Agent] turn=%s model=%s finish_reason=%s completion=%s tool_calls=%s",
            turn_count,
            model_name,
            finish_reason or "<empty>",
            getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
            len(tool_calls),
        )

        if reasoning_content:
            print(f"🧠 \033[90m[Agent 深度思考] {reasoning_content[:150]}...\033[0m")
            if on_event:
                on_event("thinking", {
                    "step": turn_count,
                    "reasoning": reasoning_content[:300],
                    "message": f"🧠 深度思考: {reasoning_content[:120]}..."
                })

        # ── 截断轮：整轮作废（tool_calls 参数可能是半截 JSON），续写重来 ──
        if finish_reason in ("length", "max_tokens"):
            truncation_count += 1
            consecutive_truncations += 1
            discarded = "、".join(_discarded_tool_label(tc) for tc in tool_calls) or "无工具调用"
            logger.warning(
                "⚠️ [Skill Agent] 第 %s 轮输出触顶（finish_reason=%s），丢弃本轮 %s 个工具调用: %s",
                turn_count, finish_reason, len(tool_calls), discarded,
            )
            if on_event:
                on_event("thinking", {
                    "stage": "truncation",
                    "step": turn_count,
                    "message": f"⚠️ 第 {turn_count} 轮输出触顶被截断，已丢弃本轮工具调用，正在要求智能体分步续写…",
                })
            # 不把 tool_calls 放进历史：OpenAI 协议要求每个 tool_call 都有 tool 响应，
            # 半截调用无法可靠执行；用占位文本保留上下文即可。
            messages.append({
                "role": "assistant",
                "content": raw_content or _CONTINUATION_PLACEHOLDER,
            })
            messages.append({
                "role": "user",
                "content": _TRUNCATION_CONTINUE_PROMPT.format(discarded=discarded),
            })
            if consecutive_truncations >= MAX_CONSECUTIVE_TRUNCATIONS or truncation_count >= MAX_TOTAL_TRUNCATIONS:
                run_error = f"输出连续被截断（累计 {truncation_count} 次），模型未能完成本轮任务"
                break
            continue

        consecutive_truncations = 0
        if tool_calls:
            # 连续“只说话”计数：只要进入正常工具轮就清零，避免早期两次追问额度
            # 永久占用、后续工具轮也无法恢复（2026-10-25 审阅发现）。
            continuation_attempts = 0

        # 将 Assistant 消息加入历史（正常轮才带 tool_calls）
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

        # 检查是否已包含闭合的最终交付标签（FINAL_RESUME / FINAL_OUTPUT）
        tag_content, tag_closed = _extract_final_tag(raw_content)
        has_final_tag = bool(re.search(r"<(FINAL_RESUME|FINAL_OUTPUT)>", raw_content, re.IGNORECASE))
        unclosed_final_tag = bool(has_final_tag and not tag_closed)
        if tag_content:
            if _validate_final_content(tag_content, output_kind):
                final_resume_md = tag_content
                final_source = "tag"
                print(f"🎉 \033[92m[Agent 定稿] 成功生成最终交付标签 (长度: {len(tag_content)} 字符)\033[0m")
            else:
                logger.warning("⚠️ [Skill Agent] 最终交付标签内容未通过 %s 校验（过短/缺结构/非法 JSON），已忽略", output_kind)
        elif unclosed_final_tag:
            logger.error("❌ [Skill Agent] 最终交付标签未闭合（疑似输出被截断），拒绝使用")

        # 没有工具调用：只有已拿到有效定稿才结束，否则追问继续
        if not tool_calls:
            if final_resume_md:
                print(f"✅ \033[92m[Agent 推演完成] 耗时: {elapsed:.2f}s | 共完成 {turn_count} 轮交互\033[0m")
                break

            # 只要回复里出现 <FINAL_RESUME>/<FINAL_OUTPUT> 标签（无论闭合与否），
            # 就不允许再走纯文本兜底：标签本身就是“这是定稿”的声明，内容不合格就该重写。
            if not has_final_tag and raw_content and _validate_final_content(raw_content, output_kind):
                final_resume_md = raw_content
                final_source = "plain"
                print(f"🎉 \033[92m[Agent 定稿] 纯文本回复通过终稿校验 (长度: {len(raw_content)} 字符)\033[0m")
                break

            # 只输出过程性文字 / 标签未闭合：追问续跑，超过上限判失败
            continuation_attempts += 1
            logger.warning(
                "⚠️ [Skill Agent] 第 %s 轮无工具调用且无有效定稿，追问续跑 (%s/%s)",
                turn_count, continuation_attempts, MAX_CONTINUATION_ATTEMPTS,
            )
            if on_event:
                on_event("thinking", {
                    "stage": "continuation",
                    "step": turn_count,
                    "message": f"⚠️ 第 {turn_count} 轮未产出有效简历，正在要求智能体继续执行 SOP…",
                })
            messages.append({
                "role": "assistant",
                "content": raw_content or _CONTINUATION_PLACEHOLDER,
            })
            messages.append({"role": "user", "content": _NARRATION_CONTINUE_PROMPT})
            if continuation_attempts >= MAX_CONTINUATION_ATTEMPTS:
                run_error = "模型连续只输出过程性文字，未产出有效简历主稿"
                break
            continue

        # 处理所有 Tool Calls
        for tc in tool_calls:
            func_name = getattr(tc.function, "name", "")
            call_id = tc.id
            tool_output_str = ""

            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("参数必须是 JSON object")
            except Exception as e:
                # 绝不用 {} 静默执行：让模型看到明确错误并重新完整调用
                tool_output_str = f"❌ 工具参数不是合法 JSON（{e}），本次调用未执行。请重新完整调用 {func_name}。"
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_output_str,
                })
                continue

            if func_name == "list_references":
                print("  🔧 \033[93m[Tool Call]\033[0m list_references()")
                tool_output_str = json.dumps(list(reference_map.keys()), ensure_ascii=False)
                if on_event:
                    on_event("tool_call", {
                        "engine": "agent",
                        "tool": "list_references",
                        "message": "🔧 调用工具: list_references() 列出参考资料库"
                    })

            elif func_name == "read_reference":
                target_file = str(args.get("file_name", "")).strip()
                print(f"  🔧 \033[93m[Tool Call]\033[0m read_reference('{target_file}')")

                matched_content = None
                for r_path, r_text in reference_map.items():
                    if (
                        r_path == target_file
                        or r_path.endswith(target_file)
                        or target_file.endswith(r_path)
                        or Path(r_path).name == Path(target_file).name
                    ):
                        matched_content = r_text
                        break

                if matched_content is not None:
                    tool_output_str = f"# {target_file}\n\n{matched_content}"
                    print(f"     ↳ ✅ 成功读取参考资料，返回 {len(matched_content)} 字符")
                    if on_event:
                        on_event("tool_call", {
                            "engine": "agent",
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
                            "engine": "agent",
                            "tool": "read_reference",
                            "file": target_file,
                            "error": "not_found",
                            "message": f"⚠️ 文件未找到: {target_file}"
                        })

            elif func_name == "save_step_artifact":
                filename = _normalize_filename(
                    str(args.get("filename", "")),
                    f"step_{len(artifacts_by_name) + 1}.md",
                )
                title = str(args.get("title") or filename).strip()
                md_content = str(args.get("markdown_content", "")).strip()
                is_final_flag = bool(args.get("is_final_resume", False))
                canonical_final = bool(
                    final_artifact_name
                    and _is_canonical_final_name(filename, final_artifact_name)
                )
                # 通用技能允许任意文件用 is_final_resume=True 声明最终交付物；
                # 简历模式仍只认契约 final_artifact（默认 06），避免 05 被误升级。
                # 契约未声明 final_artifact 时，允许模型用 is_final_resume=True
                # 指定最终交付物：通用 skill 任意文件可标记；简历类仍走 resume 内容校验。
                final_flag_allowed = bool(is_final_flag) and not final_artifact_name
                is_final_artifact = canonical_final or final_flag_allowed

                if not md_content:
                    tool_output_str = f"❌ 产物 {filename} 内容为空，已拒绝保存。请重新生成完整内容后再调用。"
                    print(f"  ⚠️ \033[93m[Artifact Rejected]\033[0m {filename}: 空内容")
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_output_str})
                    continue

                if is_final_artifact:
                    if not _validate_final_content(md_content, output_kind):
                        tool_output_str = (
                            f"❌ {filename} 内容未通过 {output_kind} 终稿校验（过短/缺结构/非法 JSON），"
                            "已拒绝保存。请重新生成完整交付物后再调用。"
                        )
                        print(f"  ⚠️ \033[93m[Artifact Rejected]\033[0m {filename}: 内容未通过终稿校验")
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": tool_output_str})
                        continue
                    final_resume_md = md_content
                    final_source = "artifact"
                    final_actual_name = filename
                elif is_final_flag:
                    logger.warning(
                        "⚠️ [Skill Agent] %s 标记 is_final_resume=True，但契约最终文件是 %s，已忽略该标记",
                        filename, final_artifact_name or "SKILL.md 声明",
                    )

                artifacts_by_name[filename] = {
                    "name": filename,
                    "title": title,
                    "content": md_content,
                    "is_final_resume": is_final_artifact,
                }

                print(f"  💾 \033[92m[Artifact Saved]\033[0m {filename} ({title}, {len(md_content)} bytes)")
                tool_output_str = f"✅ 产物 {filename} 已成功落盘保存。"

                if on_event:
                    on_event("artifact_saved", {
                        "engine": "agent",
                        "stage": "agent_artifact",
                        "filename": filename,
                        "title": title,
                        "size": len(md_content),
                        "is_final_resume": is_final_artifact,
                        "result_kind": output_kind,
                        "total_artifacts": len(artifacts_by_name),
                        "message": f"💾 阶段产物已落盘: {filename} · {title} ({(len(md_content)/1024):.1f} KB)"
                    })

            else:
                tool_output_str = f"❌ 未知工具: {func_name}"

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": tool_output_str,
            })

    # ── 收尾：按契约确定最终交付物 ──
    final_name = final_artifact_name or (
        FINAL_ARTIFACT_NAME if output_kind == "resume" else "final_output.md"
    )
    if final_source == "artifact" and final_actual_name:
        final_name = final_actual_name

    existing_final = artifacts_by_name.get(final_name)
    if (
        not final_resume_md
        and existing_final
        and _validate_final_content(existing_final.get("content", ""), output_kind)
    ):
        final_resume_md = existing_final["content"]
        final_source = "artifact"
        final_actual_name = final_name

    if not final_resume_md and output_kind != "resume" and not final_artifact_name:
        # 通用 skill 没有显式 final 时：优先 is_final_resume=True，其次最后一份通过校验的产物
        for art in reversed(list(artifacts_by_name.values())):
            if art.get("is_final_resume") or _validate_final_content(art.get("content", ""), output_kind):
                final_resume_md = art["content"]
                final_source = "artifact"
                final_actual_name = art["name"]
                final_name = art["name"]
                break

    if final_resume_md:
        existing_final = artifacts_by_name.get(final_name)
        if final_source in ("tag", "plain"):
            if existing_final and _validate_final_content(existing_final.get("content", ""), output_kind):
                if existing_final.get("content", "").strip() != final_resume_md.strip():
                    logger.warning("⚠️ [Skill Agent] 最终标签与 %s 内容不一致，优先采用产物文件", final_name)
                final_resume_md = existing_final["content"]
                final_source = "artifact"
            else:
                artifacts_by_name[final_name] = {
                    "name": final_name,
                    "title": "最终交付物",
                    "content": final_resume_md,
                    "is_final_resume": True,
                }
        elif existing_final:
            final_resume_md = existing_final["content"]
        artifacts_by_name[final_name]["is_final_resume"] = True

    total_tokens = total_prompt_tokens + total_completion_tokens
    usage_dict = {
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": total_cached_tokens,
    }
    artifacts = list(artifacts_by_name.values())

    if not final_resume_md:
        target = final_artifact_name or (
            FINAL_ARTIFACT_NAME if output_kind == "resume" else "最终交付物"
        )
        run_error = run_error or f"未产出有效的 {target}"
        logger.error(f"❌ [Skill Agent] 推演失败: {run_error}")
        if on_event:
            on_event("agent_error", {
                "engine": "agent",
                "result_kind": output_kind,
                "error": run_error,
                "message": f"❌ 技能智能体未产出有效交付物：{run_error}",
            })
        return ProgressiveAgentResult(
            markdown="",
            usage=usage_dict,
            artifacts=artifacts,
            partial=False,
            artifact_count=len(artifacts),
            expected_artifact_count=expected_count,
            engine="agent",
            result_kind=output_kind,
            has_resume_output=has_resume_output,
            final_artifact="",
            error_reason=run_error,
        )

    missing_count = max(0, expected_count - len(artifacts)) if expected_count > 0 else 0
    # 部分成功口径：只按契约声明的产物数判断；通用 skill 未声明数量时不虚报缺失。
    partial = missing_count > 0
    if run_error and not partial:
        logger.warning("⚠️ [Skill Agent] 推演尾声出现异常，但最终交付物已有效，按成功返回: %s", run_error)
    if partial:
        count_msg = f"已生成 {len(artifacts)}/{expected_count} 份产物，缺少 {missing_count} 份"
        partial_reason = f"{run_error}；{count_msg}" if run_error else count_msg
    else:
        partial_reason = ""

    if on_event:
        on_event("agent_done", {
            "engine": "agent",
            "result_kind": output_kind,
            "has_resume_output": has_resume_output,
            "status": "partial" if partial else "success",
            "partial": partial,
            "total_artifacts": len(artifacts),
            "expected_artifacts": expected_count,
            "total_tokens": total_tokens,
            "error_reason": partial_reason,
            "message": (
                f"⚠️ 部分完成：已生成 {len(artifacts)}/{expected_count} 份产物，最终交付物有效。"
                if partial else
                (
                    "🎉 全套作战产物推演完毕！共生成 "
                    f"{len(artifacts)} 份独立作战文档。"
                    if output_kind == "resume" else
                    f"🎉 技能执行完成，共生成 {len(artifacts)} 份产物。"
                )
            ),
        })

    return ProgressiveAgentResult(
        markdown=final_resume_md,
        usage=usage_dict,
        artifacts=artifacts,
        partial=partial,
        artifact_count=len(artifacts),
        expected_artifact_count=expected_count,
        engine="agent",
        result_kind=output_kind,
        has_resume_output=has_resume_output,
        final_artifact=final_name,
        error_reason=partial_reason,
    )
