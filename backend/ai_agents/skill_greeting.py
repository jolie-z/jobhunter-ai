import os
import time
import json
from typing import Tuple, Dict
from app.core.config import settings
from app.core.llm_client import get_openai_client



def run_skill_based_greeting(jd_text: str, diagnosis_dict: dict, resume_text: str, job_name: str = "") -> Tuple[str, Dict]:
    print(f"🚀 [Skill Executor] 启动打招呼语生成引擎，岗位: {job_name}")
    
    from app.automation.db import get_autopilot_config
    cfg = get_autopilot_config()
    prompt_mode = cfg.get("greeting_prompt_mode", "official")
    custom_prompt = (cfg.get("custom_greeting_prompt") or "").strip()
    
    if prompt_mode == "custom" and custom_prompt:
        print(f"🎨 [Skill Executor] 使用用户自定义打招呼语 System Prompt (字数: {len(custom_prompt)})")
        system_prompt = custom_prompt
    else:
        skill_file_path = os.path.join(os.path.dirname(__file__), "skills", "greeting_writer.md")
        try:
            with open(skill_file_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            return f"❌ 找不到打招呼语重构策略文件: {skill_file_path}", {}

    # 🌟 极速剪枝优化：告别 6000 字母本全量堆砌与整表诊断 JSON，仅提炼核心亮点
    clean_resume = (resume_text or "").strip()
    resume_summary = clean_resume[:1200].strip()
    if len(clean_resume) > 1200:
        resume_summary += "\n... (略去细化项目细节)"

    strong_fit = ""
    if diagnosis_dict and isinstance(diagnosis_dict, dict):
        strong_fit = str(diagnosis_dict.get("strong_fit_assessment") or "").strip()
        if not strong_fit:
            strong_fit = str(diagnosis_dict.get("dream_picture") or "").strip()

    clean_jd = (jd_text or "").strip()
    if len(clean_jd) > 1500:
        clean_jd = clean_jd[:1500].strip() + "\n... (JD 过长已截取核心诉求)"

    blocks = [
        f"【候选人背景精要】\n{resume_summary}",
        f"【目标岗位 JD】\n{clean_jd}",
    ]
    if strong_fit:
        blocks.append(f"【针对该岗位的核心高杠杆匹配亮点（打招呼核心素材）】\n{strong_fit}")

    blocks.append(
        "请严格按照 System 规则撰写打招呼语。\n"
        "1. 开头与结尾必须一字不差使用指定原文；\n"
        "2. 中间用数字序号罗列 2-3 个最核心匹配理由（硬核项目经验、技术栈与量化业绩）；\n"
        "3. 总字数严格控制在 150-250 字以内，务必包裹在 <GREETING>...</GREETING> 标签内（可在 <THINKING> 记录简要思考）。"
    )
    user_prompt = "\n\n".join(blocks)

    client = get_openai_client()
    if not client:
        return "❌ AI 服务未配置 (api_key)", {}

    _empty_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        start_time = time.time()
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL or "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=4096
        )
        
        final_text = (response.choices[0].message.content or "").strip()
        
        import logging
        logger = logging.getLogger(__name__)
        
        # 提取 <THINKING> 标签（用于白盒化展示在 Python 终端）
        import re
        thinking_match = re.search(r"<THINKING>\s*(.*?)\s*</THINKING>", final_text, re.DOTALL | re.IGNORECASE)
        if thinking_match:
            thinking_content = thinking_match.group(1).strip()
            logger.info("\n" + "="*60 + "\n🧠 [Greeting Agent 深度思考白盒日志]\n" + thinking_content + "\n" + "="*60 + "\n")
        else:
            logger.info("\n" + "="*60 + "\n🧠 [Greeting Agent 原始返回日志 (未匹配到思考标签)]\n" + final_text + "\n" + "="*60 + "\n")
            
        # 提取 <GREETING> 标签内部的文本作为返回内容
        match = re.search(r"<GREETING>\s*(.*?)(?:</GREETING>|$)", final_text, re.DOTALL | re.IGNORECASE)
        if match:
            final_greeting = match.group(1).strip()
        else:
            final_greeting = final_text.strip()
            
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
        } if usage else _empty_usage
        
        elapsed = time.time() - start_time
        cached_hint = f" (🔥命中缓存: {cached})" if cached > 0 else ""
        print(f"✅ [Greeting Executor] 打招呼语生成完成！耗时: {elapsed:.2f}s, 消耗 Token: 提示 {usage_dict.get('prompt_tokens')}{cached_hint} / 补全 {usage_dict.get('completion_tokens')}")
        return final_greeting, usage_dict
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"您好，我对该岗位非常感兴趣，我的过往经验与岗位需求匹配度较高。在线简历即完整简历，您方便的话可以详细了解下，若看完有意向的话我们做进一步沟通？", _empty_usage
