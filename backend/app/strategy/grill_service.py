import asyncio
import json
import logging
import re
import sys
import time
from typing import Any

import common.config as _ccfg
from app.strategy.schemas import (
    FormatMarkdownRequest,
    GrillExperienceRequest,
    GrillSuggestionRequest,
    SyncBasicModuleRequest,
)
from common.config import get_openai_client

logger = logging.getLogger("strategy_grill_service")
logger.setLevel(logging.INFO)

MARKDOWN_JSON_PREFIX = "```json"
MARKDOWN_PREFIX = "```"


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


def _build_grill_context(payload: GrillExperienceRequest) -> str:
    ctx = ""
    if getattr(payload, "jd_report_context", None):
        ctx += (
            "\n【参考资料：全局A级岗位能力报告】\n"
            f"以下是市场顶级岗位的核心能力画像：\n{payload.jd_report_context}\n"
            "请在追问时有意识地对照这些高频能力要求进行靶向追问，挖掘候选人经历中可映射的细节。"
            "但注意：最终生成的 Bullet Point 中【绝对禁止】出现「岗位能力映射」等标签性文字，能力匹配应通过事实本身自然体现。\n"
        )
    if getattr(payload, "full_resume_context", None):
        ctx += (
            "\n【参考资料：当前画布全量简历】\n"
            f"以下是候选人的完整简历内容：\n{payload.full_resume_context}\n"
            "【全量视野约束】：在追问和改写时，请必须参考全量简历。严禁让你改写的这一小段经历，与全局中的其他内容发生逻辑冲突或能力复读机！\n"
        )
    return ctx


def _build_grill_messages(payload: GrillExperienceRequest, system_prompt: str) -> list:
    messages = [{"role": "system", "content": system_prompt}]
    if not payload.chat_history:
        messages.append({"role": "user", "content": f"这是我的原始经历：\n{payload.original_experience}\n\n请开始你的首次追问。"})
    else:
        messages.append({"role": "user", "content": f"这是我的原始经历：\n{payload.original_experience}"})
        for msg in payload.chat_history:
            messages.append({"role": msg.role, "content": msg.content})
    if payload.current_turn >= 4:
        messages.append({
            "role": "system",
            "content": "【最高优先级强制指令】：用户已明确要求结束拷问或达到最大轮次！\n你必须立即停止任何追问，直接进入【阶段二：区块化融合】。\n必须设置 `is_finished: true`，并将所有提炼出的细节缝合到 `blocks` 中输出！绝对不允许再输出任何新问题！",
        })
    return messages


async def grill_experience_service(payload: GrillExperienceRequest) -> dict:
    """处理简历经历的 Grill 追问逻辑"""
    client = _get_client()
    context_instruction = _build_grill_context(payload)

    system_prompt = (
        "你是一位拥有10年经验的顶级简历精修师兼面试教练。\n"
        "你的任务分两个阶段：\n"
        "  阶段一（系统化追问）：通过犀利的追问，从用户干瘪的项目/工作经历中挖掘出饱满的事实细节。\n"
        "  阶段二（区块化融合）：当挖掘结束时，将所有隐藏细节原位融合进原始经历中，并以“区块（Blocks）”的颗粒度输出 Diff 对比，供用户局部采纳。\n\n"
        "===== 阶段一：追问规则（全局 -> 局部策略） =====\n"
        "1. 你的追问必须**有条理、分步骤**：\n"
        "   - 首个问题必须从【全局视角】切入：关注整段经历的业务背景、核心痛点、最终量化价值或整体技术架构。\n"
        "   - 后续问题必须转入【局部深挖】：逐个锁定用户原文里的大 Bullet Point，追问里面隐藏的技术选型、过程难点、或者是模糊的动作。\n"
        "2. 每次仅抛出 1 个最犀利的问题，聚焦核心。\n"
        "3. 必须为问题提供 2-3 个符合业务/技术常理的「预设答案选项」，降低用户输入负担。\n"
        "4. 追问阶段 is_finished 必须为 false，且 blocks 必须为空数组 []。\n\n"
        "===== 阶段二：区块化缝合输出规则（仅当 is_finished=true 时执行） =====\n"
        "当你收到用户的明确结束指令时，将 is_finished 设为 true，并在 blocks 中输出重构后的差异块。\n"
        "【区块（Block）切分逻辑】\n"
        "你需要将原文切分成若干个逻辑独立的块（通常每一条大的 Bullet Point 或每一个独立段落算作一个 Block）。\n"
        "对于每个 Block，你必须对比用户的补充细节，决定是否需要修改该 Block。\n"
        "如果需要修改（原位润色、或在其下方新增小 Bullet Point 追加细节），将该 Block 的 is_modified 设为 true，并提供 new_content。\n"
        "如果该 Block 无需修改，is_modified 设为 false，new_content 与 original_content 保持完全一致。\n\n"
        "【缝合排版铁律】\n"
        "1. 不要破坏原文的大结构。新增细节应自然融入原句，或以二级列表（如缩进的 `- ` 或 `* `）追加在大点下方。\n"
        "2. 严禁出现空洞的感悟（如“这是核心跃迁”），一切基于事实。\n"
        "3. 保持干练有力的简历语言（强动词开头，包含背景与量化结果）。\n\n"
        f"{context_instruction}"
        "【严格要求】请直接且仅输出合法的 JSON 格式，不要包裹在 markdown 代码块中，结构如下：\n"
        "{\n"
        '  "question": "你的追问文本（is_finished=false 时填写）",\n'
        '  "suggested_options": ["选项A", "选项B", "选项C"],\n'
        '  "is_finished": false,\n'
        '  "blocks": [\n'
        "    {\n"
        '      "id": 1,\n'
        '      "original_content": "原文中的某段或某个 Bullet Point（必须100%忠于原文对应部分）",\n'
        '      "new_content": "修改后或追加了细节的文本（仅当 is_modified=true 时有意义）",\n'
        '      "is_modified": true\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    messages = _build_grill_messages(payload, system_prompt)
    logger.info(f"[Func: grill_experience_service] 🚀 开始第 {payload.current_turn} 轮 Grill。")

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=messages,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or "{}"

    start_time = time.time()
    try:
        llm_reply_str = await asyncio.to_thread(call_llm)
        elapsed = time.time() - start_time
        logger.info(f"[Func: grill_experience_service] ✅ 大模型 Grill 响应成功，耗时 {elapsed:.2f}秒。")

        llm_reply_str = llm_reply_str.strip()
        if llm_reply_str.startswith(MARKDOWN_JSON_PREFIX):
            llm_reply_str = llm_reply_str[7:]
        if llm_reply_str.startswith(MARKDOWN_PREFIX):
            llm_reply_str = llm_reply_str[3:]
        if llm_reply_str.endswith(MARKDOWN_PREFIX):
            llm_reply_str = llm_reply_str[:-3]

        parsed_data = json.loads(llm_reply_str.strip())
        is_finished = parsed_data.get("is_finished", False)
        blocks = parsed_data.get("blocks", [])

        if is_finished:
            logger.info("[Func: grill_experience_service] 触发终止条件，开始返回细节提取结果")

        return {
            "question": parsed_data.get("question", "系统无法解析问题"),
            "suggested_options": parsed_data.get("suggested_options", []),
            "is_finished": is_finished,
            "blocks": blocks if is_finished else [],
        }
    except Exception as e:
        logger.exception(f"[Func: grill_experience_service] 解析 LLM Grill 结果失败: {e}")
        return {
            "question": "不好意思，我的大脑短路了。你能换个方式描述一下吗？",
            "suggested_options": [],
            "is_finished": False,
            "blocks": [],
        }


async def grill_suggestion_service(payload: GrillSuggestionRequest) -> list:
    """Step 3 入口：分析全量简历 + JD，输出「哪些经历值得深度拷问」的建议列表。

    返回格式：[{ section_title, signal, direction, priority }]
    """
    client = _get_client()

    system_prompt = (
        "你是一位拥有 10 年经验的顶级简历精修师兼面试教练。\n"
        "你的任务是：根据候选人的【全量简历】和目标岗位的【JD】，精准识别出哪些经历段落值得进行「深度拷问」。\n\n"
        "【深度拷问的价值】：\n"
        "候选人简历上的经历往往写得干瘪、缺乏细节。通过犀利的追问，可以挖掘出隐藏的技术深度、业务价值和量化成果，"
        "让经历从「做了什么」升级为「做到了什么、怎么做到的、带来了什么影响」。\n\n"
        "【筛选标准】：\n"
        "1. 优先选择与 JD 高度相关、但描述过于笼统的经历（有潜力但未充分展现）\n"
        "2. 优先选择有量化空间的经历（如提效 X%、节省 Y 万、覆盖 Z 个场景）\n"
        "3. 优先选择技术栈与 JD 匹配、但缺少深度细节的经历\n"
        "4. 跳过已经写得非常饱满、细节充分的经历\n"
        "5. 跳过与 JD 完全无关的经历\n\n"
        "【输出格式要求】：\n"
        "请务必输出合法的 JSON 数组，每个元素包含以下字段：\n"
        "- section_title: 经历的标题（必须与简历中的标题完全一致）\n"
        "- signal: 一句话说明为什么这段经历值得深挖（如「JD 要求微服务经验，但该经历未展开架构细节」）\n"
        "- direction: 建议的深挖方向（如「追问服务拆分策略、链路治理方案、性能优化手段」）\n"
        '- priority: 优先级，仅允许 "high" 或 "medium"\n\n'
        "【注意事项】：\n"
        "- 建议数量控制在 3-5 条，宁缺毋滥\n"
        "- 如果简历整体质量已经很高，可以只返回 1-2 条甚至空数组\n"
        "- section_title 必须与简历原文完全匹配，不要改写标题\n"
    )

    user_prompt = (
        f"【岗位要求 JD】：\n{payload.jd_text}\n\n"
        f"【候选人全量简历】：\n{payload.full_resume_context}"
    )

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL or "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or "[]"

    start_time = time.time()
    try:
        llm_reply_str = await asyncio.to_thread(call_llm)
        elapsed = time.time() - start_time
        logger.info(f"[Func: grill_suggestion_service] ✅ Grill 建议响应成功，耗时 {elapsed:.2f}秒。")

        parsed = _parse_json_safely(llm_reply_str)
        if not isinstance(parsed, list):
            logger.warning(f"[Func: grill_suggestion_service] LLM 返回非数组格式: {type(parsed)}")
            return []

        valid_suggestions = []
        for item in parsed:
            if isinstance(item, dict) and all(k in item for k in ("section_title", "signal", "direction", "priority")):
                valid_suggestions.append({
                    "section_title": str(item["section_title"]),
                    "signal": str(item["signal"]),
                    "direction": str(item["direction"]),
                    "priority": item["priority"] if item["priority"] in ("high", "medium") else "medium",
                })

        logger.info(f"[Func: grill_suggestion_service] 返回 {len(valid_suggestions)} 条有效建议")
        return valid_suggestions

    except Exception as e:
        logger.exception(f"[Func: grill_suggestion_service] 解析 Grill 建议失败: {e}")
        return []


async def sync_basic_module_service(payload: SyncBasicModuleRequest) -> dict:
    client = _get_client()
    system_prompt = (
        "你是一位顶级资深猎头与简历精修师。你的任务是根据求职者最新的【经历原文】，帮他们同步更新简历的基础模块（如专业技能、个人总结）。\n"
        "规则：\n"
        "1. 对比用户的【当前模块内容】与【经历原文】，提炼出经历中出现的新技术栈、新亮点、新数据。\n"
        "2. 将这些新提炼的亮点，以恰当的结构润色并融合到当前的模块内容中，如果原来没有，则补充进去。\n"
        "3. 你还需要给出一个简短的【更新理由】，解释你为什么做这些修改（例如：在经历中发现了你使用了React，已补充到技能栏）。\n"
        "4. **区块化输出 (Blocks)**：请将模块内容按逻辑（如具体的技能点或总结段落）拆解为多个独立区块。对每个区块输出 `original_content`（即当前模块的旧内容），如果进行了补充或修改，将 `is_modified` 设为 true 并给出 `new_content`。如果你是为了某个全新技能新增的条目，`original_content` 可以为空。如果无需修改，`is_modified` 设为 false 且 `new_content` 保持一致。\n"
        "【严格要求】请直接且仅输出合法的 JSON 格式，不要包裹在 markdown 代码块中，结构如下：\n"
        "{\n"
        '  "reason": "整体更新理由",\n'
        '  "is_modified": true,\n'
        '  "blocks": [\n'
        "    {\n"
        '      "id": 1,\n'
        '      "original_content": "原内容中的某一条记录（如无则留空）",\n'
        '      "new_content": "补充或修改后的记录",\n'
        '      "is_modified": true\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    user_prompt = (
        f"【当前基础模块名称】：{payload.module_title}\n\n"
        f"【当前基础模块内容】：\n{payload.current_content}\n\n"
        f"【完整的经历原文】：\n{payload.experiences_context}\n\n"
        "请根据上述经历补充/更新当前基础模块的内容。"
    )

    logger.info(f"[Func: sync_basic_module_service] 🚀 开始为模块 {payload.module_title} 进行 AI 联动更新")

    def call_llm():
        response = client.chat.completions.create(
            model=_ccfg.OPENAI_MODEL if _ccfg.OPENAI_MODEL else "gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or "{}"

    start_time = time.time()
    try:
        llm_reply_str = await asyncio.to_thread(call_llm)
        elapsed = time.time() - start_time
        logger.info(f"[Func: sync_basic_module_service] ✅ 大模型响应成功，耗时 {elapsed:.2f}秒。")

        llm_reply_str = llm_reply_str.strip()
        if llm_reply_str.startswith(MARKDOWN_JSON_PREFIX):
            llm_reply_str = llm_reply_str[7:]
        if llm_reply_str.startswith(MARKDOWN_PREFIX):
            llm_reply_str = llm_reply_str[3:]
        if llm_reply_str.endswith(MARKDOWN_PREFIX):
            llm_reply_str = llm_reply_str[:-3]

        parsed_data = json.loads(llm_reply_str.strip())
        return {
            "reason": parsed_data.get("reason", "根据最新经历进行了润色更新"),
            "is_modified": parsed_data.get("is_modified", True),
            "blocks": parsed_data.get("blocks", []),
        }
    except Exception as e:
        logger.exception(f"[Func: sync_basic_module_service] 解析失败: {e}")
        raise ValueError(f"AI 更新失败: {str(e)}")


async def format_markdown_service(payload: FormatMarkdownRequest) -> dict:
    client = _get_client()
    system_prompt = (
        "你是一个资深的简历排版与精修专家。你的任务是将用户提供的粗糙、未排版的简历内容（例如个人总结或专业技能），进行结构化和美观的 Markdown 格式排版。\n"
        "【核心排版规则】\n"
        "1. 层级排版规则：如果内容存在大分类（即原先的大 bullet point）和小要点（小 bullet point），**绝对不要给大分类加上任何 bullet point（- 或 *）**，请直接将大分类当作小标题**加粗并独占一行**。只有大分类下方的具体要点，才使用 '-' 进行缩进排列。【极为重要】：在每一个加粗的小标题（大分类）的**上方和下方，必须各空一行（即使用两次换行）**！否则渲染器会把新的小标题错当成上一个列表项的延续内容。\n"
        "2. 对每条亮点的关键词（如具体技能、数据、核心成果）使用加粗（**关键词**），提高扫描效率。\n"
        "3. 绝对不要随意篡改用户的核心意思、不要无中生有、不要增删技能。只做**排版美化**和**同义精简**。\n"
        "4. 每个 bullet point（列表项）的结尾**绝对不要使用句号（。）**，请直接去掉句号，保持干净利落。\n"
        "5. 特殊字段排版规则：当识别到描述“技术栈”、“核心技术栈”等包含众多并列短语或名词的内容时，**绝对不要使用垂直的 bullet point 列表，也不要对每个技术栈名词单独加粗**。请将其处理为同一行内的普通文本，各项之间使用中文顿号（、）分隔，例如：`核心技术栈：Python、RPA (GUI 自动化)、LLM API(通义千问)、Prompt Engineering、飞书 Open API`。\n"
        "6. 严禁在输出中重复“【当前模块】”等提示信息，严禁自行脑补并添加任何主模块标题。你只需要输出经过排版的【待排版内容】本身！\n"
        "7. 链接展示规则：如果遇到包含网址链接的内容（如 GitHub源码：https://github.com/... 等），请保持纯文本形式，**绝对不要对其加粗，不要使用 `[]()` 等 Markdown 超链接语法，也不要将其变成 bullet point**。直接平铺显示即可。\n"
        "8. 输出必须是一段纯 Markdown 文本，不要有 ```markdown 等任何代码块包裹，不要有任何多余的开头问候语。\n"
    )
    user_prompt = f"【当前模块】：{payload.module_title}\n【待排版内容】：\n{payload.current_content}"

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

    formatted_content = await asyncio.to_thread(call_llm)
    return {"formatted_content": formatted_content.strip()}


async def predict_keyword_desc_service(keyword: str) -> str:
    """调用大模型为关键字自动生成详尽的AI解释语"""
    client = _get_client()
    prompt = f"用户在求职过滤系统中输入了初筛关键字: '{keyword}'，请你帮他写一段'AI解释语'（提供给另一个LLM作为判断标准）。这段解释语需要明确定义这个关键字在招聘JD中通常代表的具体条件，包括相关的近义词/表述，以及哪些情况是不符合的伪表述。要求语言简练客观，直接输出解释语，不要包含多余寒暄，100字以内。"

    try:
        def call_llm():
            return client.chat.completions.create(
                model=_ccfg.OPENAI_MODEL or "gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )

        response = await asyncio.to_thread(call_llm)
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.exception(f"[predict_keyword_desc_service] LLM prediction failed: {e}")
        raise ValueError(f"AI 生成失败: {str(e)}")
