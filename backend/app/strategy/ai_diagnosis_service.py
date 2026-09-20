import asyncio
import json
import logging
import re
import sys
import time
from typing import Any

from pydantic import ValidationError

import common.config as _ccfg
from app.core.resume_structurer import ResumeData, parse_resume_to_json
from app.strategy.config_service import get_active_resume_text_async
from app.strategy.schemas import (
    AtsAlignRequest,
    CompressWorkRequest,
    FilterProjectsRequest,
    GlobalDiagnosisRequest,
    InitialDraftRequest,
)
from common.config import get_openai_client

logger = logging.getLogger("strategy_ai_diagnosis")
logger.setLevel(logging.INFO)

ERR_AI_FORMAT = "AI 返回格式异常"


def _get_svc():
    return sys.modules.get("app.strategy.service")


def _get_client():
    svc = _get_svc()
    getter = getattr(svc, "get_openai_client", get_openai_client) if svc else get_openai_client
    return getter()


def _parse_json_safely(content) -> Any:
    if hasattr(content, "content"):
        content = content.content
    if not isinstance(content, str):
        content = str(content)
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    backticks = "`" * 3
    if content.startswith(f"{backticks}json"):
        content = content[len(f"{backticks}json") :].strip()
    elif content.startswith(backticks):
        content = content[len(backticks) :].strip()
    if content.endswith(backticks):
        content = content[: -len(backticks)].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        content = re.sub(r"//.*", "", content)
        content = re.sub(r"[\x00-\x1F\x7F]", "", content)
        try:
            return json.loads(content)
        except Exception:
            raise ValueError(f"Extracted json string is not valid JSON. Content: {content[:100]}...")


async def ats_align_experience_service(payload: AtsAlignRequest) -> dict:
    """Agent 3 变体：ATS 靶向预诊与微创手术 (Global Context + Path Diff Mode)

    将原始经历根据 A级岗位画像进行专业术语对齐与改写。
    """
    start_time = time.time()
    client = _get_client()
    logger.info("[Func: ats_align_experience_service] 🎯 开始执行 ATS 靶向诊断预检")
    logger.info(f"   - 目标原段落长度: {len(payload.original_experience)} 字符")

    # 1. 自动获取并结构化解析全局主简历
    t_ctx = time.time()
    if payload.full_resume_context:
        logger.info(f"[Step 1] 优先使用前端传入的画布实时全量简历作为上下文 (长度: {len(payload.full_resume_context)})")
        resume_text = payload.full_resume_context
    else:
        logger.info("[Step 1] 拉取当前启用状态的 Master 简历底稿以构建全局上下文...")
        resume_text = await get_active_resume_text_async()
        if not resume_text:
            logger.warning("   - ⚠️ 未找到启用的简历底稿，全局上下文将为空。")
    logger.info(f"   - ⏱️ [计时] 上下文获取: {time.time() - t_ctx:.2f}秒 (底稿长度: {len(resume_text or '')} 字符)")

    t_parse_resume = time.time()
    resume_json: dict = {}
    if resume_text:
        try:
            # 底稿主路径已是结构化 JSON（存储与回读均为 JSON），本地直接解析，跳过
            # 曾占整链 53% 耗时的 parse_resume_to_json LLM 调用；产出与 LLM 路径同构
            # （同一 ResumeData 校验+dump）。仅当底稿真是 Markdown（或 JSON 结构意外
            # 损坏）时才回退 LLM。
            resume_json = ResumeData.model_validate(json.loads(resume_text)).model_dump()
            logger.info(
                f"[Step 2] ✅ JSON AST 本地直解析成功（跳过 LLM 调用#1），"
                f"检测到 {len(resume_json.get('workExperience', []))} 段工作经历和 {len(resume_json.get('personalProjects', []))} 段项目经历。"
            )
        except (json.JSONDecodeError, ValidationError):
            logger.info("[Step 2] 底稿非 JSON（Markdown/结构损坏），回退 LLM 解析 parse_resume_to_json...")
            resume_json = await parse_resume_to_json(resume_text)
            logger.info(
                f"   - ✅ JSON AST 构建成功（LLM 回退路径），"
                f"检测到 {len(resume_json.get('workExperience', []))} 段工作经历和 {len(resume_json.get('personalProjects', []))} 段项目经历。"
            )
    t_parse_resume_cost = time.time() - t_parse_resume
    logger.info(f"   - ⏱️ [计时] 简历→AST 总耗时: {t_parse_resume_cost:.2f}秒")

    system_prompt = (
        "你是一个顶级的 ATS（简历自动跟踪系统）优化专家。\n\n"
        "【你的任务】：\n"
        "阅读下方的【全局A级岗位核心能力画像】以及用户的【全局完整简历结构】，对比候选人被指定的【目标经历原始文本】。"
        "在**绝对不改变原文真实业务逻辑、不拔高职级、不虚构数据**的前提下，将画像中提取出的高级专业术语、行业黑话如微创手术般自然地替换或补充进目标经历中。\n\n"
        "【CRITICAL TRUTHFULNESS RULES - 严禁违反的真实性铁律】:\n"
        "1. 严禁增加简历中（含全局）没有真正掌握的技能、工具。\n"
        "2. 严禁虚构业务量化数据（如凭空写 '提升了 30%'）。\n"
        "3. 严禁增加原文没有的公司名、产品名。\n"
        "4. 严禁拔高职级（如 '助理' 改为 '资深'）。\n"
        "5. 你的修改必须只是“重塑原有的经历使其向目标能力靠拢”，而不是凭空捏造新经历。\n"
        "6. 严禁在输出中包含经历的头部标题行（例如公司名、职位、时间等，如 `[公司 · 职位 · 时间]`）。请直接从具体的业务描述正文开始输出。\n\n"
        "【约束规则】：\n"
        "1. 术语平替：如果原文有口语化的表达（如原文有『做了个数据报表』，画像中有『数据驱动洞察』），请直接将其替换为专业、高级的表达。\n"
        "2. 无痕缝合：修改必须极其自然，不能像生硬的拼凑。\n"
        "3. **输出格式要求**：请使用规范的简历排版格式输出重构后的文本，包含大 Bullet Point（如核心职责/成果维度）和小 Bullet Point（如具体执行细节）。不要整块输出宽泛的大段落，要像一份专业简历那样结构分明、有层级感。\n"
        "4. **区块化输出 (Blocks)**：将重构后的经历按原文逻辑划分为独立的区块（如按每个核心的大 Bullet Point 及其下方的小点拆分为一个 Block）。对每个 Block 输出 `original_content`（对应原始文本中的部分），如果进行了注入或修改，则 `is_modified` 设为 true 并提供 `new_content`；如果无需修改，则 `is_modified` 设为 false 且 `new_content` 保持与 `original_content` 一致。\n"
        "5. **全局视角查重**：如果你发现目标画像中的某个要求，候选人已经在全局简历的其他地方（如技能栏、其他经历）深度体现过了，就不必在这段目标经历里强行塞入，避免冗余。\n"
        "6. **排版法则**：请自行判断该经历是工作经历还是项目经历。如果判断为项目经历，请按照 CRD 法则（项目背景 Context、核心动作 Role/Action、项目成果 Deliverables/Results）进行改写排版；如果是工作经历，请保持按照 STAR 法则（情境 Situation、任务 Task、行动 Action、结果 Result）进行改写。\n\n"
        "【全局A级岗位核心能力画像】：\n"
        f"{payload.jd_report_context}\n\n"
        "【强制输出 JSON 格式，严格禁止外层包裹 markdown 代码块】：\n"
        "{\n"
        '  "is_modified": true,\n'
        '  "blocks": [\n'
        "    {\n"
        '      "id": 1,\n'
        '      "original_content": "原文中的某一块结构（如某个职责大点及下方细节）",\n'
        '      "new_content": "注入了关键词和高级表达后的新块文本",\n'
        '      "is_modified": true\n'
        "    }\n"
        "  ],\n"
        '  "injected_keywords": ["注入的高频词1", "专业术语2"],\n'
        '  "surgeon_rationale": "向用户解释你的缝合逻辑，例如你发现候选人在某处缺少该词，且全局没写，所以补在这里。"\n'
        "}"
    )

    resume_json_text = json.dumps(resume_json, ensure_ascii=False, indent=2)
    user_prompt = (
        f"【全局完整简历结构（仅供参考，帮助你了解候选人全貌与技能掌握情况）】：\n"
        f"{resume_json_text}\n\n"
        f"【请仅对以下目标经历原始文本进行靶向改写】：\n"
        f"{payload.original_experience}"
    )

    logger.info(
        f"[Step 3] 拼装 LLM Prompt 完成。⏱️ [计时] Prompt 体积: System={len(system_prompt)}字符"
        f"(含JD画像 {len(payload.jd_report_context)}字符), User={len(user_prompt)}字符"
        f"(简历AST {len(resume_json_text)}字符 + 目标经历 {len(payload.original_experience)}字符)"
    )

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    t_llm = time.time()
    response_text = await asyncio.to_thread(call_llm)
    t_llm_cost = time.time() - t_llm
    logger.info(
        f"[Step 4] ✅ LLM 靶向手术完成！⏱️ [计时] LLM调用#2(靶向改写): {t_llm_cost:.2f}秒，"
        f"返回结果长度: {len(response_text)} 字符，累计 {time.time() - start_time:.2f}秒。"
    )

    try:
        t_json = time.time()
        data = _parse_json_safely(response_text)
        is_mod = data.get("is_modified", False)
        logger.info(f"   - 解析成功 (⏱️ 本地JSON解析 {time.time() - t_json:.2f}秒)！诊断结论: {'需要修改 (is_modified=True)' if is_mod else '无需修改 (is_modified=False)'}")
        if is_mod:
            injected = data.get("injected_keywords", [])
            logger.info(f"   - 💡 成功注入 {len(injected)} 个关键词: {injected}")
            logger.info(f"   - 👨‍⚕️ 主刀医生诊断理由: {data.get('surgeon_rationale', '')}")
        return data
    except Exception as e:
        logger.exception(f"[Func: ats_align_experience_service] JSON解析失败: {e}\nResponse: {response_text}")
        raise ValueError(ERR_AI_FORMAT)


async def filter_projects_service(payload: FilterProjectsRequest):
    """AI 项目经历智能删减服务

    给每个项目打分(0-100)，并给出去留建议和简短理由。
    """
    client = _get_client()
    projects_json = [{"id": p.id, "title": p.title, "content": p.content} for p in payload.projects]

    system_prompt = (
        "你是一个资深的招聘总监兼面试官。你的任务是根据求职者投递的【岗位要求 JD】和【简历诊断报告】，"
        "对求职者的多段【项目经历】进行极其严苛的筛选和打分。\n"
        "你的目标是：找出那些和当前岗位核心要求完全不沾边、凑字数、甚至会减分的冗余项目，建议把它们“毙掉 (kill)”。\n"
        "对于有价值、能体现核心能力、和JD高匹配的项目，建议“保留 (keep)”。\n"
        "【保底约束】（优先级最高）：除非你判断所有项目都与岗位要求完全无关——仅此时允许全部 kill——否则至少保留相关度最高的 1-2 个项目；若所有项目得分均偏低但并非全部无关，保留得分最高的一个，并在其 reason 中注明'保底保留'。\n\n"
        "【输出格式要求】：\n"
        "请务必输出合法的 JSON 数组，每个元素包含以下字段：\n"
        "- id: 项目的唯一ID（原样返回）\n"
        "- score: 0 到 100 的整数得分\n"
        "- decision: \"keep\" 或 \"kill\"\n"
        "- reason: 充分且详尽的裁切或保留理由，直击痛点（例如：'该项目涉及高并发处理与微服务架构，完美契合当前JD中对于后端专家应对千万级QPS的核心要求' 或 '该项目主要职责是简单的UI组件重构，不仅技术含量较低，且与当前JD要求的底层性能调优毫无关联，建议彻底裁掉以节省简历版面'）\n\n"
        "【JSON示例】：\n"
        "[\n"
        "  {\n"
        '    "id": "section-123",\n'
        '    "score": 85,\n'
        '    "decision": "keep",\n'
        '    "reason": "分布式系统经验，完美契合JD要求"\n'
        "  }\n"
        "]\n"
    )

    user_prompt = (
        f"【岗位要求 JD】：\n{payload.jd_text}\n\n"
        f"【简历诊断报告】：\n{payload.diagnosis_report}\n\n"
        f"【候选人项目经历列表】：\n{json.dumps(projects_json, ensure_ascii=False, indent=2)}\n"
    )

    logger.info("========== [Project Pruner: 白盒化追踪开始] ==========")
    logger.info(f"[Step 1] 接收到待评估的项目总数: {len(payload.projects)}")

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    start_time = time.time()
    response_text = await asyncio.to_thread(call_llm)
    elapsed = time.time() - start_time
    logger.info(f"[Step 3] ✅ LLM 评估完成！耗时 {elapsed:.2f} 秒。")

    try:
        data = _parse_json_safely(response_text)
        if not isinstance(data, list):
            if isinstance(data, dict) and "projects" in data:
                data = data["projects"]
            else:
                data = [data]

        for item in data:
            logger.info(f"   => 项目 {item.get('id')}: 得分 {item.get('score')}, 判定 {item.get('decision')}")
        logger.info("========== [Project Pruner: 白盒化追踪结束] ==========")
        return data
    except Exception as e:
        logger.exception(f"[Func: filter_projects_service] JSON解析失败: {e}\nResponse: {response_text}")
        raise ValueError(ERR_AI_FORMAT)


async def compress_work_experience_service(payload: CompressWorkRequest):
    """AI 工作经历战略折叠服务

    给每段工作经历打分(0-100)，给出'focus'(着重写) 或 'compress'(略写) 的建议，
    若判定为略写，则根据分数的动态梯度决定 compressed_content。
    """
    client = _get_client()
    works_json = [{"id": w.id, "title": w.title, "content": w.content} for w in payload.work_experiences]

    system_prompt = (
        "你现在是一位拥有 10 年经验的资深 HR 兼核心业务线负责人 (Hiring Manager)，同时也是一位顶级的简历精修导师，深谙 ATS 的抓取逻辑。\n"
        "你的任务是根据求职者投递的【岗位要求 JD】和【简历诊断报告】，对求职者的多段【工作经历原文】进行战略价值评估。\n"
        "你的目标是：判断哪些工作经历是核心拿分项（应着重写，建议 'focus'），哪些是边缘经历（应略写以节省版面，建议 'compress'）。\n\n"
        "【核心重构原则（提纯密度策略）】\n"
        "在为建议 'compress'（略写）的经历生成精简版时，绝不能写成干瘪的流水账，也尽量不要生硬地砍掉重要细节，而是通过【提纯密度】的方式重写：\n"
        "1. 动作合并与提纯：不要简单丢弃动作细节，而是将多个零散的动作合并为一个高度专业化的长句，保留核心数字指标和技术栈。\n"
        "2. 动态对症下药 (Targeted Remediation)：在重写时，必须将缺失的 JD 关键词自然融入，并通过话术的升维来对冲弱信号。\n"
        "3. 动态适配 JD 偏好：若 JD 偏技术，突出“工程化落地、边界异常处理”；若 JD 偏业务，突出“痛点驱动架构、ROI 优化、商业闭环”。\n"
        "4. 真实性铁律：禁止虚构不存在的技术栈、虚构量化指标。\n\n"
        "【输出格式要求】：\n"
        "请务必输出合法的 JSON 数组，每个元素包含以下字段：\n"
        "- id: 工作经历的唯一ID（原样返回）\n"
        "- score: 0 到 100 的整数得分\n"
        "- decision: \"focus\" 或 \"compress\"\n"
        "- reason: 简明扼要的裁决理由（例如：'核心业务架构与JD匹配度极高，建议着重写' 或 '业务场景边缘且技术栈老旧，建议压缩折叠'）\n"
        "- compressed_content: 精炼后的经历正文文本（采用 Markdown 列表呈现，保留高光技术与量化结果）。注意：如果 decision 为 'focus'，此字段可返回空字符串 \"\" 或原文。\n"
    )

    user_prompt = (
        f"【岗位要求 JD】：\n{payload.jd_text}\n\n"
        f"【简历诊断报告】：\n{payload.diagnosis_report}\n\n"
        f"【候选人工作经历列表】：\n{json.dumps(works_json, ensure_ascii=False, indent=2)}\n"
    )

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    start_time = time.time()
    response_text = await asyncio.to_thread(call_llm)
    elapsed = time.time() - start_time
    logger.info(f"[Func: compress_work_experience_service] ✅ LLM 评估完成！耗时 {elapsed:.2f} 秒。")

    try:
        data = _parse_json_safely(response_text)
        if not isinstance(data, list):
            if isinstance(data, dict) and "work_experiences" in data:
                data = data["work_experiences"]
            else:
                data = [data]
        return data
    except Exception as e:
        logger.exception(f"[Func: compress_work_experience_service] JSON解析失败: {e}\nResponse: {response_text}")
        raise ValueError(ERR_AI_FORMAT)


async def global_diagnosis_service(payload: GlobalDiagnosisRequest) -> list:
    client = _get_client()
    system_prompt = (
        "你是一个拥有 10 年经验的大厂资深招聘专家和简历指导教练。\n"
        "你的任务是通读求职者的【全量简历】和【目标岗位 JD】，进行全局交叉对比诊断，挑出最关键、最需要优化的经历段落，并给出行动建议。\n\n"
        "【诊断维度】：\n"
        "1. 匹配度低/内容薄弱的经历 -> 建议深度拷问挖掘 (grill)\n"
        "2. 关键词缺失/表达不专业的经历 -> 建议 ATS 靶向对齐 (ats_align)\n"
        "3. 与岗位完全不相关/减分项的项目 -> 建议智能删减 (prune)\n"
        "4. 偏边缘/年限久远但有一定参考价值的工作经历 -> 建议战略折叠压缩 (compress)\n\n"
        "【输出格式要求（最高优先级）】\n"
        "必须严格输出一个 JSON 数组，每个元素包含：\n"
        "- section_title: 该段经历在简历中的原标题（如 'xx项目', 'xx公司'），必须是原文真实存在的二级标题的内容，不能随意编造。\n"
        "- action: 具体的动作标识（必须是 'grill', 'ats_align', 'prune', 'compress' 之一）。\n"
        "- reason: 给用户的建议理由（例如 '这段经历写得很宽泛，建议使用深度拷问挖掘量化数据'）。\n\n"
        "请只返回问题最严重、最值得优化的 3-5 条建议。不要包裹 ```json"
    )
    user_prompt = (
        f"【岗位要求 JD】：\n{payload.jd_text}\n\n"
        f"【全量简历】：\n{payload.full_resume_context}\n"
    )

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or "[]"

    response_text = await asyncio.to_thread(call_llm)

    try:
        data = _parse_json_safely(response_text)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.exception(f"Global diagnosis parse error: {e}")
        return []


async def generate_initial_draft_service(payload: InitialDraftRequest):
    """Step 2 初版改写 (Align the bones)

    目标：对幸存经历进行基于 JD 侧重点的宏观结构重组与初改，不强塞黑话。
    """
    client = _get_client()
    experiences_json = [
        {"id": w.id, "title": w.title, "content": w.content, "category": w.category or "未知"}
        for w in payload.experiences
    ]

    system_prompt = (
        "你现在是一位拥有 10 年经验的资深简历精修导师与 HRBP。\n"
        "你的任务是根据【岗位要求 JD】和【简历诊断报告】，对求职者投递的多段【幸存工作/项目经历】进行第一轮「基底对齐 (Initial Draft Rewrite)」。\n\n"
        "【极度重要：如何判断使用哪种格式】\n"
        "每条经历都带有一个 category 字段，它的值明确标识了该经历属于「工作经历」还是「项目经历」。\n"
        "- 当 category == '工作经历' 时 → 必须使用 STAR 法则（见下方规则 1）。\n"
        "- 当 category == '项目经历' 时 → 必须使用 CRD 法则（见下方规则 2）。\n"
        "【绝对不允许】对工作经历使用 CRD 格式，也不允许对项目经历使用 STAR 格式。\n\n"
        "【核心重构原则】\n"
        "1. 工作经历结构 (STAR per Bullet)：工作经历的每一个 Bullet Point 都应独立遵循 STAR 法则（情境/任务+行动+结果）。"
        "但【绝对不要】出现\"情境:\"、\"行动:\"、\"结果:\"、\"S:\"、\"T:\"、\"A:\"、\"R:\" 等任何标签词，"
        "必须融合成通顺专业的一句话。请将经历拆分为多个独立的 Bullet Point，不要把所有内容堆叠成一个超长句。每个 Bullet Point 控制在 1~2 句话以内。\n"
        "2. 项目经历结构 (CRD)：项目经历整体必须严格遵循 CRD 法则，并在文本中**明确标出**以下三个段落标签（只用中文，不要加英文括号）：\n"
        "   - **项目背景**：1句话交代业务痛点或项目目标。\n"
        "   - **核心动作**：【拆分多个 Bullet Point】不要揉成一段长难句，分多点清晰列出你的职责与技术/业务动作。每个 Bullet Point 控制在 1~2 句话以内。\n"
        "   - **项目成果**：【拆分多个 Bullet Point】如果有多个维度的成果（如性能提升、业务转化），也请分点列出。\n"
        "3. 侧重点偏移 (Align the bones)：根据 JD 的偏好调整原文描述的侧重点。如果 JD 偏业务，请放大原经历中解决业务痛点、商业闭环的部分；如果 JD 偏技术，请放大工程化落地、异常处理的部分。\n"
        "4. 绝对真实底线：严禁无中生有，严禁捏造数字。只能基于候选人提供的原文进行结构调整和表达优化。\n"
        "5. 拒绝生硬塞词：在这个阶段，【绝对不要】强行塞入 JD 里的生僻专业术语或 ATS 黑话，让逻辑通顺、重点突出即可。\n"
        "6. 语气要求：自信、专业、干练，避免过度口语化的表述。\n"
        "7. 【绝对禁止改写标题】：你只改写经历的正文内容(content)，绝对不要修改或重写经历的标题(title)。标题原样保留，不要在 initial_draft_content 中包含任何标题行（如 ### 开头的行）。\n\n"
        "【输出格式要求】：\n"
        "请务必输出合法的 JSON 数组，每个元素包含以下字段：\n"
        "- id: 经历的唯一ID（原样返回）\n"
        "- initial_draft_content: 改写后的经历正文文本（采用 Markdown 语法，使用 '-' 列表呈现多个要点，分段清晰，排版美观）。注意：不要包含标题行。\n"
    )

    if getattr(payload, "full_resume_context", None):
        global_context_instruction = (
            "\n【参考资料：当前画布全量简历】\n"
            f"以下是候选人的完整简历内容：\n{payload.full_resume_context}\n\n"
            "【全量视野约束（最高优先级）】：\n"
            "1. 在改写任何一段经历时，必须参考全量简历。严禁让你改写的这段经历，与全局中的其他内容发生逻辑冲突或能力复读机！\n"
            "2. 全局视角查重：如果你发现这段经历中的某个能力或成果，候选人已经在全局简历的其他地方（如技能栏、其他工作/项目经历）深度体现过了，就不必在这段改写里强行重复强调，避免冗余。\n"
            "3. 侧重点偏移时，优先放大当前经历的「独特价值」——即这段经历中独有的业务场景、技术栈或量化成果，而非简历中已有的通用能力。\n"
        )
        system_prompt += global_context_instruction

    user_prompt = (
        f"【岗位要求 JD】：\n{payload.jd_text}\n\n"
        f"【简历诊断报告】：\n{payload.diagnosis_report}\n\n"
        f"【候选人经历列表（注意每条的 category 字段）】：\n{json.dumps(experiences_json, ensure_ascii=False, indent=2)}\n"
    )

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
        return response.choices[0].message.content or "[]"

    response_text = await asyncio.to_thread(call_llm)

    try:
        data = _parse_json_safely(response_text)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.exception(f"[Func: generate_initial_draft_service] JSON解析失败: {e}\nResponse: {response_text}")
        return []
