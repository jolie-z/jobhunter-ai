import asyncio
import json
import re
from typing import Any

# 注意：这里请根据你实际的全局变量路径调整，通常是 common.config 或 app.core.config
import common.config as _ccfg
from app.copilot.schemas import CopilotChatRequest, VoiceCopilotChatRequest
from app.core.llm_client import get_openai_client


def compress_jd_text(jd_text: str, max_length: int = 800) -> str:
    if not jd_text or len(jd_text) <= max_length:
        return jd_text
    return jd_text[:max_length] + "\n\n...(后续内容已省略)"

def flatten_resume_json(resume_json_str: str) -> str:
    if not resume_json_str:
        return ""
    try:
        resume_data = json.loads(resume_json_str)
        flattened_parts = []

        if isinstance(resume_data, dict) and "header" in resume_data:
            header = resume_data["header"]
            if isinstance(header, dict):
                name = header.get("name", "")
                intention = header.get("intention", "")
                if name or intention:
                    flattened_parts.append(f"# {name} - {intention}")

        if isinstance(resume_data, dict) and "sections" in resume_data:
            sections = resume_data["sections"]
            if isinstance(sections, list):
                for section in sections:
                    if isinstance(section, dict):
                        title = section.get("title", "")
                        content = section.get("content", "")
                        if title and content:
                            flattened_parts.append(f"\n## {title}\n{content}")

        if not flattened_parts and isinstance(resume_data, dict):
            for key, value in resume_data.items():
                if isinstance(value, str) and len(value) > 20:
                    if key not in ["id", "record_id", "rewrite_rationale", "rationale"]:
                        flattened_parts.append(f"\n{value}")

        result = "\n".join(flattened_parts).strip()
        if len(result) > 3000:
            result = result[:3000] + "\n\n...(后续内容已省略)"
        return result

    except json.JSONDecodeError:
        if len(resume_json_str) > 3000:
            return resume_json_str[:3000] + "\n\n...(后续内容已省略)"
        return resume_json_str
    except Exception:
        return resume_json_str[:500] if resume_json_str else ""

async def process_copilot_chat(payload: CopilotChatRequest) -> dict[str, Any]:
    client = get_openai_client()
    if client is None:
        raise ValueError("AI 服务未配置（缺少 LLM_API_KEY），请检查环境变量后重试。")

    # 1. 提取与压缩变量
    jd_text_raw = payload.context.get("jd_text", "")
    evaluation_report = payload.context.get("evaluation_report", "")
    ai_resume_json = payload.context.get("ai_resume_json", "")
    human_refined_resume = payload.context.get("human_refined_resume", "")

    jd_text = compress_jd_text(jd_text_raw, max_length=800)
    current_resume_raw = human_refined_resume if human_refined_resume else ai_resume_json
    current_resume = flatten_resume_json(current_resume_raw)
    title = payload.section_title or "全局问答"

    # 2. 计算轮次
    round_count = len([m for m in payload.history if m.get("role") == "user"])

    # 3. 动态 Prompt 路由
    if "技能" in title:
        system_prompt = f"""你是一名顶尖的技术猎头，现在的任务是精修候选人的【{title}】模块。

【参考弹药库】
- 原始文本：{current_resume}
- 岗位 JD：{jd_text}
- 深度评估报告（核心能力词典等）：{evaluation_report}

【你的工作准则】
1. 禁止追问数据结果：在技能模块，只看候选人“会什么”以及“写得专业吗”。
2. 分类审视：建议候选人将技能梳理为硬技能（如工具/语言/框架）、行业业务技能、软技能/方法论三大类。
3. 主动找茬（Gap Analysis）：仔细对比评估报告中的核心能力词典。如果 JD 强烈要求某项技能（如 Docker），但简历没写，主动追问候选人是否有相关经验，或者寻找可替代的平替技能。
4. 如果你觉得当前描述已经很好地覆盖了核心词，直接回复认可，并询问是否有隐藏技能补充；若无，生成草稿。
5. 每次最多只问 1 个最核心的问题。如果信息已充足，立即生成包含在 <DRAFT>（改写内容）</DRAFT> 标签内的完整段落。

当前已追问轮次：{round_count}"""

    elif "总结" in title or "评价" in title:
        system_prompt = f"""你是一名拥有 15 年经验的资深猎头，擅长撰写价值百万的【{title}】。

【参考弹药库】
- 原始文本：{current_resume}
- 岗位 JD：{jd_text}
- 深度评估报告（理想画像与能力信号）：{evaluation_report}

【你的工作准则】
1. 镜像策略：紧扣“理想画像”，HR 想要什么人，我们就呈现什么人。重点突出候选人作为“全栈 AI 开发”和“独立开发者”的破局能力（结合实际匹配度）。
2. 字数控制：目标生成的草稿字数控制在 200-300 字左右，字字珠玑，直击痛点。
3. 主动触达：你要主动告诉候选人：“我读取了理想画像，HR 想要的是 xxx，我觉得您的 xxx 经历是最佳切入点，关于这点您还有什么隐藏亮点吗？”
4. 黄金开场：第一句话就要定胜负，呈现出 HR 梦寐以求的候选人模样。
5. 每次最多只问 1 个最核心的问题。如果信息已充足，立即生成包含在 <DRAFT>（改写内容）</DRAFT> 标签内的完整段落。

当前已追问轮次：{round_count}"""

    elif "全局" in title:
        system_prompt = f"""你是一名顶尖的大厂资深猎头与专属求职 Copilot。

【参考弹药库】
- 当前简历摘要：{current_resume}
- 岗位 JD：{jd_text}
- 深度评估报告：{evaluation_report}

【你的工作准则】
1. 综合解答：候选人会通过浮窗问你关于 JD 重点、面试防守策略、或者简历整体匹配度等各种问题。
2. 结合数据：请务必结合提供的【深度评估报告】（特别是高杠杆匹配点和致命硬伤）给出极其专业、一针见血的指导建议。
3. 毒舌精准：语言要极度干练，不要讲废话，直接给出可落地的 Action。

当前对话轮次：{round_count}"""

    else:
        system_prompt = f"""你是一位拥有 15 年经验的资深猎头顾问，当前正在精修候选人的【{title}】模块。

【参考弹药库】
- 原始文本：{current_resume}
- 岗位 JD：{jd_text}
- 深度评估报告（高匹配点、不匹配点、破局计划）：{evaluation_report}

【你的工作准则】
1. 全局排布战略：如果原始文本有多段经历，不要盲目只要数据。先结合“高匹配点”，向候选人提出排版建议（例如：哪段该重点展开，哪段该缩减）。
2. STAR 原则深挖：不要干巴巴地要数据，而是结合 JD 的痛点追问。最终如果有数据支撑最好，没有的话，产出关键机制或规范也可以。
3. 每次最多只问 1 个最核心的问题。如果信息已充足，立即生成包含在 <DRAFT>（改写内容）</DRAFT> 标签内的完整段落。

当前已追问轮次：{round_count}"""

    # 4. 组装消息
    messages = [{"role": "system", "content": system_prompt}]
    for msg in payload.history:
        if msg.get("role") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": payload.user_question})

    # 5. 🚀 使用 asyncio.to_thread 进行纯异步网络 IO
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=_ccfg.LLM_MODEL,
        messages=messages,
        temperature=0.7,
        timeout=60.0,
    )

    ai_reply = (response.choices[0].message.content or "").strip()
    if not ai_reply:
        raise ValueError("AI 返回为空，请稍后重试")

    return {"status": "success", "reply": ai_reply}

async def process_voice_copilot_chat(payload: VoiceCopilotChatRequest) -> dict[str, Any]:
    client = get_openai_client()
    if client is None:
        raise ValueError("LLM 客户端未初始化，请检查 API Key 配置")

    round_count = len([m for m in payload.history if m.get("role") == "user"])
    title = payload.section_title or ""

    if "技能" in title:
        system_prompt = f"""你是一名顶尖的技术猎头，现在的任务是精修候选人的【{title}】模块。
【参考弹药库】
- 原始文本：{payload.original_text}
- 岗位 JD：{payload.job_description}
- 深度评估报告：{payload.evaluation_report}
【你的工作准则】
1. 禁止追问数据结果：只看候选人“会什么”以及“写得专业吗”。
2. 主动找茬（Gap Analysis）：对比 JD，若有缺失主动追问。
3. 每次最多只问 1 个最核心的问题。如果信息已充足，立即生成包含在 <DRAFT>（改写内容）</DRAFT> 标签内的完整段落。
当前已追问轮次：{round_count}"""
    elif "总结" in title or "评价" in title:
        system_prompt = f"""你是一名拥有 15 年经验的资深猎头，擅长撰写价值百万的【{title}】。
【参考弹药库】
- 原始文本：{payload.original_text}
- 岗位 JD：{payload.job_description}
- 深度评估报告：{payload.evaluation_report}
【你的工作准则】
1. 镜像策略：紧扣“理想画像”，重点突出破局能力。
2. 每次最多只问 1 个最核心的问题。如果信息已充足，立即生成包含在 <DRAFT>（改写内容）</DRAFT> 标签内的完整段落。
当前已追问轮次：{round_count}"""
    else:
        system_prompt = f"""你是一位拥有 15 年经验的资深猎头顾问，当前正在精修候选人的【{title}】模块。
【参考弹药库】
- 原始文本：{payload.original_text}
- 岗位 JD：{payload.job_description}
- 深度评估报告：{payload.evaluation_report}
【你的工作准则】
1. 全局排布战略：结合高匹配点，向候选人提出排版建议。
2. STAR 原则深挖：结合 JD 痛点追问。
3. 每次最多只问 1 个最核心的问题。如果信息已充足，立即生成包含在 <DRAFT>（改写内容）</DRAFT> 标签内的完整段落。
当前已追问轮次：{round_count}"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in payload.history:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    response = await asyncio.to_thread(
        client.chat.completions.create,
        model=_ccfg.LLM_MODEL,
        messages=messages,
        temperature=0.72,
    )
    full_reply: str = response.choices[0].message.content or ""

    draft_match = re.search(r"<DRAFT>([\s\S]*?)</DRAFT>", full_reply, re.IGNORECASE)
    draft_text = draft_match.group(1).strip() if draft_match else None

    reply = re.sub(r"<DRAFT>[\s\S]*?</DRAFT>", "", full_reply, flags=re.IGNORECASE).strip()
    if not reply and draft_text:
        reply = "✅ 改写稿已生成，请查看右侧草稿区域并确认应用。"

    return {"reply": reply, "draft_text": draft_text}

# ==================== 🎙️ 面试训练营 (Interview Camp) Actions ====================
import inspect  # noqa: E402
import logging  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.copilot.schemas import CheckIntelRequest, InterviewRequest  # noqa: E402
from app.core.feishu_client import feishu_client  # noqa: E402
from app.core.feishu_utils import feishu_field_to_plain_str  # noqa: E402
from app.interview.service import get_core_job_keywords  # noqa: E402

# 飞书凭证/表 ID 统一走 _ccfg 动态属性访问（模块级 from-import 会在 import 时冻结快照，
# 配置页保存的新值读不到）；_ccfg.<ATTR> 在 common.config reload 后拿到最新值
from app.services.feishu_service import (  # noqa: E402
    extract_record_id,
    update_feishu_record,
)

logger = logging.getLogger(__name__)

# 面经 RAG 已收编进本仓库（原依赖外部项目 interview_scraper 的 ai_interview_rag，
# 2026-09-04 迁入 app/interview/interview_rag.py，配置走 _cfg）
# 公司情报走 backend 原生 Serper 引擎（外部 company_searcher 与本项目 common 包撞名，
# 在 backend 进程内 import 必然失败，故不再从那里导入）
from ai_agents.company_intel import search_company_ai_news  # noqa: E402
from app.interview.interview_rag import (  # noqa: E402
    ask_for_interview_summary,
    fetch_single_reports_by_tags,
    get_feishu_token,
)


async def check_intel_update_action(req: CheckIntelRequest):
    """极轻量级探测雷达：仅查询飞书中的面经数量，判断是否有更新"""
    try:
        token = await asyncio.to_thread(get_feishu_token)
        # 只拉取数据记录查数量，绝不唤醒大模型
        single_records = await asyncio.to_thread(fetch_single_reports_by_tags, token, req.job_group, req.business_track)
        new_count = len(single_records)

        has_update = new_count > req.current_count
        return {
            "status": "success",
            "has_update": has_update,
            "new_count": new_count
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

async def init_interviewer_action(req: InterviewRequest):
    print(f"\n====== 🎙️ 收到面试初始化请求：挑战【{req.company}】【{req.job_group}】(强制刷新: {req.force_refresh}) ======")
    updates_for_feishu = {}

    try:
        # ==========================================
        # 1. 公司情报：如果要求强刷，或者无缓存，则重新搜索
        should_refresh_company = (req.refresh_target == 'company') or (req.refresh_target == 'all' and (req.force_refresh or not req.cached_intel or len(req.cached_intel) <= 10))

        if not should_refresh_company and req.cached_intel:
            print("  [⚡ 命中缓存/跳过] 公司情报保留原数据。")
            company_intel = req.cached_intel
        else:
            print("  [🏢 靶向刷新] 正在搜索公司业务情报...")
            if inspect.iscoroutinefunction(search_company_ai_news):
                company_intel = await search_company_ai_news(req.company)
            else:
                company_intel = await asyncio.to_thread(search_company_ai_news, req.company)
            updates_for_feishu["公司业务情报"] = company_intel

        # ==========================================
        # 2. 🌟 面经题库：引入智能洗词器与全域降级搜索！
        job_keywords = await get_core_job_keywords(req.job_group)

        async def fetch_summary_with_fallback_for_ui(keywords):
            for keyword in keywords:
                print(f"  [🔍] 正在尝试使用关键词 [{keyword}] 全域检索面经...")
                try:
                    # 强制行业为 None，打破赛道壁垒进行全域模糊搜索
                    if inspect.iscoroutinefunction(ask_for_interview_summary):
                        res = await ask_for_interview_summary(keyword, None, req.force_refresh)
                    else:
                        res = await asyncio.to_thread(ask_for_interview_summary, keyword, None, req.force_refresh)

                    if res and res[0]:
                        text = res[0]
                        if isinstance(text, list):
                            text = "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in text])

                        if "库里暂时没有该方向的面经" not in text and "0 篇相关" not in text:
                            print(f"  [✅] 成功命中面经！最终匹配使用关键词: [{keyword}]")
                            return text, res[1]
                        else:
                            print(f"  [📭] 关键词 [{keyword}] 无结果，准备尝试更宽泛的词...")
                except Exception as e:
                    print(f"  [⚠️] 关键词 [{keyword}] 检索异常: {e}")
            return "", []

        summary_text, raw_records = await fetch_summary_with_fallback_for_ui(job_keywords)

        if not summary_text:
            # 🌟 明确指出缺失的是哪个岗位的面经，并给出精准的行动指令
            summary_text = f"### 📭 题库空空如也\n系统情报库中经过 AI 智能降级检索（{job_keywords}），依然没有找到与【{req.job_group}】相匹配的面经。\n💡 **破局行动：请立刻前往小红书或 Boss 直聘，搜索“{req.job_group} 面试”或“{job_keywords[0] if job_keywords else req.job_group} 面经”，并将真实面经流水账喂给左侧的【面经粉碎机】入库。**"
            links = []
        else:
            if isinstance(summary_text, list):
                summary_text = "".join([str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in summary_text])
            elif not isinstance(summary_text, str):
                summary_text = str(summary_text)

            links = [rec.get("fields", {}).get("原文链接", {}).get("link", "") if isinstance(rec.get("fields", {}).get("原文链接", {}), dict) else rec.get("fields", {}).get("原文链接", "") for rec in raw_records[:3]]
            links = [link for link in links if link]

        # ==========================================
        # 3. 专属预测：强刷或无缓存时触发
        predicted_qa = ""
        reverse_questions = ""
        should_refresh_qa = (req.refresh_target == 'qa') or (req.refresh_target == 'all' and (req.force_refresh or not req.cached_qa or len(req.cached_qa) <= 20))

        if not should_refresh_qa and req.cached_qa and req.cached_rq:
            print("  [⚡ 命中缓存/跳过] 专属预测题与反问环节保留原数据。")
            predicted_qa = req.cached_qa
            reverse_questions = req.cached_rq
        elif req.jd_text and not summary_text.startswith("### 📭"):
            print("  [🔮] 正在并发呼叫大模型：生成深度预测面试题 + 黄金反问环节...")
            prediction_prompt = f"""你是一个极其严苛且专业的资深大厂面试官。你的任务不是出"通用面试题"，而是**追踪候选人简历中的每一条具体主张**，设计会暴露弱点的追问链。

请结合以下材料，按 5 轮结构输出 15-20 个面试拷问问题：

【第1轮：真实性边界】追踪简历中的 ownership 和量化主张，追问"你具体做了什么？"
【第2轮：技术深度】针对简历提到的每个技术栈，追问 input/output、数据规模、模型选型、系统瓶颈、评估指标
【第3轮：JD专项深挖】对照JD的核心要求，找出简历中"看似匹配但实际证据不足"的点，设计追问
【第4轮：场景压力题】设计失败、延迟、质量下降、数据漂移、权限不足等异常场景，看候选人如何应对
【第5轮：风险总评】对每个问题标注风险等级：✅可答 / ⚠️需补证据 / ❌高风险(简历写了但答不上来)

每个问题必须包含：
- 问题本身（必须追踪简历原文，禁止泛问如"请介绍RAG"）
- 为什么会问这个（面试官意图）
- 什么证据能回答它（代码/日志/指标/截图）
- 高分参考答案思路

【岗位JD】：
{req.jd_text}

【通用领域面经】：
{summary_text}

【候选人真实简历】：
{req.resume_text or '未提供'}

【深度简历评估报告】：
{req.evaluation_report or '未提供'}

请使用结构化 Markdown 格式输出，按轮次分大标题，每个问题用编号列出。
"""
            rq_prompt = f"""你现在是一名顶级面试教练。请结合【公司情报】、【岗位JD】和【候选人简历】，为候选人生成 5 个高含金量的面试反问问题（即面试结尾候选人问面试官的问题）。
要求按以下5个战略维度分布：
1. 业务深度/痛点型：结合公司近期新闻或JD痛点。
2. 团队协作/文化型：了解真实工作环境。
3. 个人成长/挑战型：结合简历中的优势。
4. 公司远景/战略型：展现宏观视野。
5. 反馈/闭环型：询问面试官评价或后续流程。
请用结构化的 Markdown 格式输出，每一条附带提问的具体话术和背后的意图说明。
【公司情报】：\n{company_intel}\n\n【岗位JD】：\n{req.jd_text}\n\n【候选人简历】：\n{req.resume_text or '未提供'}"""

            try:
                llm_client = get_openai_client()

                # 封装并发任务
                async def _gen_qa():
                    resp = await asyncio.to_thread(llm_client.chat.completions.create, model=_ccfg.LLM_MODEL, messages=[{"role": "user", "content": prediction_prompt}], temperature=0.4, max_tokens=4000)
                    return resp.choices[0].message.content

                async def _gen_rq():
                    resp = await asyncio.to_thread(llm_client.chat.completions.create, model=_ccfg.LLM_MODEL, messages=[{"role": "user", "content": rq_prompt}], temperature=0.4, max_tokens=2000)
                    return resp.choices[0].message.content

                # 双管齐下，等待两份报告同时完成！
                predicted_qa, reverse_questions = await asyncio.gather(_gen_qa(), _gen_rq())

                predicted_qa = (predicted_qa or "").strip() or "> ⚠️ AI 本轮没有返回预测题内容，请点击右上角 🔄 重新生成。"
                reverse_questions = (reverse_questions or "").strip() or "> ⚠️ AI 本轮没有返回反问内容，请点击右上角 🔄 重新生成。"

                updates_for_feishu["专属面试预测"] = predicted_qa
                updates_for_feishu["反问环节建议"] = reverse_questions
                print(f"  [✅] 专属预测问题与反问环节双线程生成完毕！(QA长度={len(predicted_qa)}, RQ长度={len(reverse_questions)})")
            except Exception as e:
                predicted_qa = f"> ⚠️ 预测面试题失败: {e}"
                reverse_questions = f"> ⚠️ 反问环节生成失败: {e}"

        # 🌟 全局兜底：覆盖"if/elif 都跳过"导致 predicted_qa/reverse_questions 仍为空的边界情况，
        # 防止前端的 `{intelData.xxx && ...}` falsy 短路把卡片整张吞掉。
        if not (predicted_qa and str(predicted_qa).strip()):
            predicted_qa = "> ⚠️ 当前无可用预测题（可能是面经库未命中或缓存为空），请点击右上角 🔄 重新生成。"
        if not (reverse_questions and str(reverse_questions).strip()):
            reverse_questions = "> ⚠️ 当前无可用反问内容（可能是面经库未命中或缓存为空），请点击右上角 🔄 重新生成。"

        # ==========================================
        # 4. 核心同步：写回飞书
        if updates_for_feishu:
            print(f"  [💾] 准备将新生成的资料持久化至飞书 (ID: {req.job_id})...")
            try:
                pure_record_id = extract_record_id(req.job_id)
                # 使用全局 update_feishu_record 并用 asyncio.to_thread 隔离
                await asyncio.to_thread(update_feishu_record, pure_record_id, updates_for_feishu, _ccfg.FEISHU_TABLE_ID_JOBS)
                print("  [✅] 飞书存档更新成功！")
            except Exception as cache_err:
                print(f"  [⚠️] 飞书回写失败: {cache_err}")

        system_prompt = f"你现在是{req.company}的面试官。公司动态：{company_intel}\n考点参考：{summary_text}"

        # ==========================================
        # 5. 暗杀任务注入（使用异步 feishu_client，绝不调用同步阻塞接口）
        try:
            import random as _rand
            qbank_records = await feishu_client.fetch_bitable_records(_ccfg.FEISHU_TABLE_ID_INTERVIEW_REAL)
            weak_pool = []
            for r in qbank_records or []:
                f = r.get("fields", {}) or {}
                status = feishu_field_to_plain_str(f.get("掌握状态", ""))
                if any(tag in status for tag in ["🔴", "🟡", "未掌握", "练习中"]):
                    q_text = feishu_field_to_plain_str(f.get("题目 / 核心拷问", ""))
                    a_text = feishu_field_to_plain_str(f.get("我的黄金答案", ""))
                    if q_text:
                        weak_pool.append({"question": q_text, "answer": a_text})

            if weak_pool:
                pick_n = min(len(weak_pool), _rand.randint(1, 2))
                hits = _rand.sample(weak_pool, pick_n)
                hits_md = "\n".join([f"  {i+1}. 【突击题】{h['question']}\n     【参考】{h['answer']}" for i, h in enumerate(hits)])
                system_prompt += f"\n\n【专属特训暗杀任务】：中途突击考察薄弱题：\n{hits_md}\n打断并指出错误。"
                print(f"  [🎯 暗杀任务] 已注入 {pick_n} 道薄弱题")
        except Exception as e:
            print(f"  [⚠️ 暗杀任务注入失败]: {e}")

        return {
            "status": "success",
            "system_prompt": system_prompt,
            "company_intel": company_intel,
            "summary_text": summary_text,
            "predicted_qa": predicted_qa,
            "reverse_questions": reverse_questions,
            "reference_links": links
        }
    except Exception as e:
        print(f"❌ 初始化面试官失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
