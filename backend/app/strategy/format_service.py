"""简历排版服务（自 grill_service.py 拆出，2026-09-23 七项修复#7 + 单文件≤500行治理）。

format_markdown：单模块 AI 精细排版，带进程内结果缓存——
同模块同内容（+同 prompt 版本+同模型）不重复付费重排（实测单模块约 60s）。
"""
import asyncio
import hashlib
import logging
import threading
import time

import common.config as _ccfg
from app.strategy.schemas import FormatMarkdownRequest
from common.config import get_openai_client

logger = logging.getLogger("strategy_format_service")
logger.setLevel(logging.INFO)

MARKDOWN_JSON_PREFIX = "```json"
MARKDOWN_PREFIX = "```"

# PROMPT_VERSION 必须与下方排版 system_prompt 同步维护——改 prompt 必须 bump，否则命中旧结果。
FORMAT_PROMPT_VERSION = "v1"
FORMAT_CACHE_TTL_SECONDS = 24 * 3600.0
_format_cache: dict[str, tuple[float, str]] = {}
_format_cache_lock = threading.Lock()
_FORMAT_CACHE_MAX = 200


def _get_client():
    from app.strategy import service as _svc_mod
    getter = getattr(_svc_mod, "get_openai_client", get_openai_client)
    # 交互类链路（grill/排版/联动）：max_retries=1，杜绝 429/5xx 时 3 次重试 × 180s 超时
    # 把单次失败放大到 12 分钟级挂死；后台批量链路（解析/投递）维持全局默认 3 次。
    try:
        return getter(caller="strategy_format", max_retries=1)
    except TypeError:
        return getter()


# 排版 system_prompt（与 FORMAT_PROMPT_VERSION 绑定）
FORMAT_SYSTEM_PROMPT = (
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


async def format_markdown_service(payload: FormatMarkdownRequest) -> dict:
    client = _get_client()
    system_prompt = FORMAT_SYSTEM_PROMPT
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

    # 结果缓存：同模块同内容（+同 prompt 版本+同模型）不重复付费重排（实测单模块 59s）。
    model_name = _ccfg.OPENAI_MODEL or "gpt-4o"
    cache_key = hashlib.sha256(
        f"{model_name}|{FORMAT_PROMPT_VERSION}|{payload.module_title}|{payload.current_content}".encode()
    ).hexdigest()
    now = time.time()
    with _format_cache_lock:
        hit = _format_cache.get(cache_key)
        if hit and now - hit[0] < FORMAT_CACHE_TTL_SECONDS:
            logger.info(f"[Func: format_markdown_service] ⚡ 模块「{payload.module_title}」命中排版缓存，0ms 返回。")
            return {"formatted_content": hit[1], "cached": True}
        # 顺手清理过期项，防无界增长
        expired = [k for k, (ts, _) in _format_cache.items() if now - ts >= FORMAT_CACHE_TTL_SECONDS]
        for k in expired:
            _format_cache.pop(k, None)

    start_time = time.time()
    formatted_content = (await asyncio.to_thread(call_llm)).strip()
    elapsed = time.time() - start_time
    logger.info(f"[Func: format_markdown_service] ✅ 模块「{payload.module_title}」排版完成，耗时 {elapsed:.2f}秒。")

    # 空结果不入缓存：避免一次异常空返回让后续 24h 内的重试恒得空
    if formatted_content:
        now = time.time()  # TTL 起点以写入时刻为准（避免被 LLM 调用时长吃掉一段寿命）
        with _format_cache_lock:
            if len(_format_cache) >= _FORMAT_CACHE_MAX:
                _format_cache.pop(next(iter(_format_cache)), None)
            _format_cache[cache_key] = (now, formatted_content)

    return {"formatted_content": formatted_content, "cached": False}
