import os
import re
import time
import json
import logging
from typing import Tuple, Dict, List, Optional
from app.core.config import settings
from app.core.llm_client import get_openai_client

logger = logging.getLogger("skill_rewrite")


def truth_boundary_check(text: str) -> Tuple[str, List[Dict]]:
    """
    Truth Boundary 安全阀：扫描改写输出中的高危词并自动降级。
    方法论参考 LLMInternSkill (MIT, github.com/wanyichen06/LLMInternSkill)
    
    Returns:
        (降级后文本, 降级日志列表)
    """
    config_path = os.path.join(os.path.dirname(__file__), "skills", "truth_boundary.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return text, []

    rules = config.get("downgrade_rules", [])
    downgrades = []

    for rule in rules:
        pattern = rule.get("pattern", "")
        safe = rule.get("safe", "")
        if not pattern or not safe:
            continue
        matches = list(re.finditer(pattern, text))
        if matches:
            for m in matches:
                downgrades.append({
                    "original": m.group(),
                    "replaced": safe,
                    "reason": rule.get("reason", ""),
                    "severity": rule.get("severity", "low"),
                })
            text = re.sub(pattern, safe, text)

    if downgrades:
        logger.info(f"[Truth Boundary] 安全阀触发 {len(downgrades)} 处降级: "
                    + "; ".join(f"'{d['original']}'→'{d['replaced']}'" for d in downgrades[:5]))

    return text, downgrades


def format_diagnosis_context(diagnosis_dict: dict) -> str:
    """将诊断字典格式化为对大模型极具可读性的避坑与高杠杆指导文档"""
    if not diagnosis_dict or not any(bool(v) for v in diagnosis_dict.values()):
        return ""
    
    sections = []
    
    # 1. 理想画像
    dream = diagnosis_dict.get("dream_picture")
    if dream and str(dream).strip():
        sections.append(f"- 🎯 理想画像与能力信号：\n{str(dream).strip()}")
        
    # 2. 核心能力词典 (ATS)
    ats = diagnosis_dict.get("ats_ability_analysis")
    if ats and str(ats).strip():
        sections.append(f"- 🏷️ 核心能力词典 (ATS 必备关键词)：\n{str(ats).strip()}")
        
    # 3. 致命硬伤与毒点
    red_flags = diagnosis_dict.get("risk_red_flags")
    if red_flags and str(red_flags).strip():
        sections.append(f"- 🚩 致命硬伤与毒点预警 (改写时严禁踩雷)：\n{str(red_flags).strip()}")
        
    # 4. 高杠杆匹配点
    strong_fit = diagnosis_dict.get("strong_fit_assessment")
    if strong_fit and str(strong_fit).strip():
        sections.append(f"- ⚡ 高杠杆匹配点 (改写时应重点突出强化)：\n{str(strong_fit).strip()}")
        
    # 5. 破局行动计划
    action_plan = diagnosis_dict.get("deep_action_plan")
    if action_plan and str(action_plan).strip():
        sections.append(f"- 🛠️ 破局行动计划与改写指导：\n{str(action_plan).strip()}")

    # 兜底：如果上述标准键不存在，直接转格式化 JSON
    if not sections and diagnosis_dict:
        sections.append(json.dumps(diagnosis_dict, ensure_ascii=False, indent=2))

    return "\n\n".join(sections)


def assemble_adaptive_prompt(
    system_prompt: str,
    original_resume: str,
    jd_text: str,
    diagnosis_dict: dict,
    include_diagnosis: bool = True
) -> Tuple[str, str]:
    """
    自适应装配 System Prompt 与 User Prompt:
    1. 检查 System Prompt 是否包含变量占位符 ({{resume}}, {{jd}}, {{diagnosis}}, $RESUME, $JD, $DIAGNOSIS)
    2. 若包含变量则直接插值
    3. 若无变量则按标准结构化分块拼装
    4. 根据 include_diagnosis 决定是否附带诊断报告
    """
    diagnosis_formatted = format_diagnosis_context(diagnosis_dict) if (include_diagnosis and diagnosis_dict) else ""

    has_resume_var = any(ph in system_prompt for ph in ["{{resume}}", "$RESUME", "{{RESUME}}", "{{ resume }}"])
    has_jd_var = any(ph in system_prompt for ph in ["{{jd}}", "$JD", "{{JD}}", "{{ jd }}"])
    has_diag_var = any(ph in system_prompt for ph in ["{{diagnosis}}", "$DIAGNOSIS", "{{DIAGNOSIS}}", "{{ diagnosis }}"])

    if has_resume_var or has_jd_var:
        # 🌟 占位符插值模式
        interpolated_system = system_prompt
        for ph in ["{{resume}}", "$RESUME", "{{RESUME}}", "{{ resume }}"]:
            interpolated_system = interpolated_system.replace(ph, original_resume.strip())
        for ph in ["{{jd}}", "$JD", "{{JD}}", "{{ jd }}"]:
            interpolated_system = interpolated_system.replace(ph, jd_text.strip())
        for ph in ["{{diagnosis}}", "$DIAGNOSIS", "{{DIAGNOSIS}}", "{{ diagnosis }}"]:
            interpolated_system = interpolated_system.replace(ph, diagnosis_formatted)
        
        user_prompt = "请严格按照上述 System 规则执行简历改写，并直接输出重塑后的简历内容。"
        return interpolated_system, user_prompt

    # 🌟 标准三段式 / 黄金融合分块模式 (无变量占位符的 99% 通用 Skill)
    user_blocks = []

    # 1. 候选人原始简历（不可变静态基石前缀，对齐大模型 KV Cache）
    user_blocks.append(f"【候选人原始简历】\n{original_resume.strip()}")

    # 2. 目标岗位 JD（动态）
    user_blocks.append(f"【目标岗位 JD】\n{jd_text.strip() or '（未提供具体 JD 文本）'}")

    # 3. 针对该岗位的 AI 专家深度解构与避坑指南 (如果开启且有数据)
    if include_diagnosis and diagnosis_formatted:
        user_blocks.append(f"【💡 针对该岗位的 AI 专家深度解构与避坑指南 (AI Job Insights & Risk Red Flags)】\n{diagnosis_formatted}")

    # 4. 执行指令
    user_blocks.append("请严格按照 System Prompt 中的专业改写规则与输出契约，结合上述岗位要求与避坑指导，开始执行简历重塑。")

    user_prompt = "\n\n".join(user_blocks)
    return system_prompt, user_prompt


def run_skill_based_rewrite(
    original_resume: str,
    jd_text: str,
    diagnosis_dict: dict,
    job_name: str = "",
    skill_id: str = "",
    include_diagnosis: bool = True
) -> Tuple[str, Dict]:
    print(f"🚀 [Skill Executor] 启动基于 Skill 的简历重构引擎，岗位: {job_name} | Skill ID: {skill_id or 'default'} | 带入诊断: {include_diagnosis}")
    
    system_prompt = ""
    if skill_id:
        try:
            from .skills.skill_loader import get_skill_manager
            manager = get_skill_manager()
            system_prompt = manager.get_skill_content(skill_id) or ""
            if system_prompt:
                print(f"📜 [Skill Executor] 成功加载动态技能: {skill_id}")
        except Exception as e:
            logger.warning(f"⚠️ 加载动态技能 {skill_id} 失败，将回退默认技能: {e}")

    if not system_prompt:
        skill_file_path = os.path.join(os.path.dirname(__file__), "skills", "resume_rewrite.md")
        try:
            with open(skill_file_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            return f"❌ 找不到简历重构策略文件: {skill_file_path}", {}

    final_system_prompt, user_prompt = assemble_adaptive_prompt(
        system_prompt=system_prompt,
        original_resume=original_resume,
        jd_text=jd_text,
        diagnosis_dict=diagnosis_dict,
        include_diagnosis=include_diagnosis
    )

    logger.info(f"🧩 [白盒化追踪] System Prompt 组装完成 (长度: {len(final_system_prompt)} 字符), User Prompt (长度: {len(user_prompt)} 字符)")
    print(f"\n🧩 [白盒化追踪] 装配完成: System Prompt ({len(final_system_prompt)} chars) + User Context ({len(user_prompt)} chars)")

    client = get_openai_client()
    if not client:
        return "❌ AI 服务未配置 (api_key)", {}

    _empty_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        model_name = settings.OPENAI_MODEL or "gpt-4o"
        logger.info(f"⏳ [白盒化追踪] 正在向大模型 ({model_name}) 发起简历定制请求...")
        print(f"⏳ [白盒化追踪] 正在向大模型 ({model_name}) 发起简历定制请求，请稍候...")
        start_time = time.time()
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=8192
        )
        elapsed = time.time() - start_time
        
        choice_msg = response.choices[0].message
        raw_content = (getattr(choice_msg, "content", "") or "").strip()
        reasoning_content = (getattr(choice_msg, "reasoning_content", "") or "").strip()
        
        # 兼容 reasoning 模型将内容输出在 reasoning_content 的情况
        final_md = raw_content
        if not final_md and reasoning_content:
            logger.info("⚠️ [Skill Executor] 大模型将正文直接输出在 reasoning_content，已自动兜底捕获！")
            final_md = reasoning_content

        logger.info(f"✅ [白盒化追踪] 大模型响应完成，耗时: {elapsed:.2f}s，生成内容长度: {len(final_md)} 字符")
        print(f"✅ [白盒化追踪] 大模型响应完成，耗时: {elapsed:.2f}s，生成内容长度: {len(final_md)} 字符")

        if not final_md:
            logger.error("❌ [Skill Executor] 大模型返回空内容！")
            return "❌ 简历定制失败：大模型响应为空（可能因参考资料过长或网络超时），请再次重试。", _empty_usage
        
        # 提取 <THINKING> 标签（用于白盒化展示在 Python 终端）
        thinking_match = re.search(r"<THINKING>\s*(.*?)\s*</THINKING>", final_md, re.DOTALL | re.IGNORECASE)
        if thinking_match:
            thinking_content = thinking_match.group(1).strip()
            print("\n\033[96m" + "="*60 + "\033[0m")
            print("\033[96m🧠 [Agent 深度思考白盒日志]\033[0m")
            print("\033[90m" + thinking_content + "\033[0m")
            print("\033[96m" + "="*60 + "\033[0m\n")
            
        # 提取 <FINAL_RESUME> 标签内部的文本作为返回内容
        match = re.search(r"<FINAL_RESUME>\s*(.*?)\s*</FINAL_RESUME>", final_md, re.DOTALL | re.IGNORECASE)
        if match:
            final_md = match.group(1).strip()
        else:
            if final_md.startswith("```markdown"):
                final_md = final_md[11:]
            elif final_md.startswith("```"):
                final_md = final_md[3:]
            if final_md.endswith("```"):
                final_md = final_md[:-3]
            final_md = final_md.strip()

        # ── Truth Boundary 安全阀：后处理降级 ──
        final_md, downgrades = truth_boundary_check(final_md)
        if downgrades:
            print(f"\033[93m🛡️ [Truth Boundary] 安全阀触发 {len(downgrades)} 处降级\033[0m")
            for d in downgrades:
                print(f"\033[90m   '{d['original']}' → '{d['replaced']}' ({d['reason']})\033[0m")

        # ── 证据强度标签清理（确保输出简历无 [稳] [需补证] 尾缀） ──
        final_md = re.sub(r'\s*\[(?:稳|需补证|补证后可用)\]', '', final_md)
        confidence_summary = {"stable": 0, "need_evidence": 0, "after_evidence": 0}

        usage = response.usage
        cached = 0
        if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
        elif isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
        usage_dict = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
            "cached_tokens": cached,
            "bullet_confidence": confidence_summary,
        } if usage else _empty_usage
        
        pt = usage_dict.get("prompt_tokens", 0)
        ct = usage_dict.get("completion_tokens", 0)
        tot = usage_dict.get("total_tokens", 0)
        cached_hint = f" (🔥命中缓存: {cached})" if cached > 0 else " (未命中缓存)"
        print(f"✅ [Skill Executor] 重构完成！耗时: {elapsed:.2f}s, 消耗 Token: 提示 {pt}{cached_hint} / 补全 {ct} / 总计 {tot}")
        return final_md, usage_dict
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"❌ [Skill Executor] 运行时出错: {str(e)}", _empty_usage


def warmup_rewrite_cache(original_resume: str, skill_id: str = "") -> dict:
    """
    为批量定制改写执行 1-token 轻量点火预热，将 System Prompt + 候选人母本简历前缀写入 GPU Prefix Cache (用于 N>=3 大批量)
    """
    system_prompt = ""
    if skill_id:
        try:
            from .skills.skill_loader import get_skill_manager
            manager = get_skill_manager()
            system_prompt = manager.get_skill_content(skill_id) or ""
        except Exception:
            pass

    if not system_prompt:
        skill_file_path = os.path.join(os.path.dirname(__file__), "skills", "resume_rewrite.md")
        try:
            with open(skill_file_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            return {"success": False, "error": "未找到简历重构策略文件"}

    final_system_prompt, user_prompt = assemble_adaptive_prompt(
        system_prompt=system_prompt,
        original_resume=original_resume,
        jd_text="预热点火占位",
        diagnosis_dict={},
        include_diagnosis=False
    )

    client = get_openai_client()
    if not client:
        return {"success": False, "error": "AI 服务未配置 (api_key)"}

    try:
        model_name = settings.OPENAI_MODEL or "gpt-4o"
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            max_tokens=1
        )
        usage = response.usage
        cached = 0
        if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
        elif isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0

        pt = getattr(usage, "prompt_tokens", 0) if usage else 0
        logger.info(f"🔥 [warmup_rewrite_cache] 定制改写母本点火完成: Prompt {pt}, Cached {cached}")
        return {
            "success": True,
            "prompt": pt,
            "cached": cached,
        }
    except Exception as e:
        logger.warning(f"⚠️ [warmup_rewrite_cache] 定制改写点火预热异常 (不影响主流程继续): {e}")
        return {"success": False, "error": str(e)}

