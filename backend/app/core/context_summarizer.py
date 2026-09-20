"""
上下文摘要压缩器

职责：
- 当 session 内的消息轮数超过窗口阈值时，将旧消息压缩为一段摘要
- 摘要作为 system message 前缀注入，保留关键决策和参数
- 摘要持久化到 session_manager，不重复计算

策略：
- 保留最近 CONTEXT_WINDOW_SIZE 轮消息原文
- 超出部分由 LLM 压缩为 200-300 字摘要
- 摘要累积更新（新摘要 = 旧摘要 + 新溢出消息 的压缩结果）
"""

import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger("context_summarizer")

# ==========================================
# 配置
# ==========================================
CONTEXT_WINDOW_SIZE = 20  # 保留最近 N 轮消息原文（可通过 settings 覆盖）

SUMMARY_PROMPT = """你是一个对话摘要助手。请将以下对话历史压缩为一段简洁的摘要（200-300字），重点保留：
1. 用户下达的关键指令和参数（如城市、关键词、薪资范围、平台选择）
2. 已完成的操作及其结果（如爬取了多少条、评估了几个岗位）
3. 未完成的待办事项或用户表达的偏好
4. 重要的决策和结论

不要保留寒暄、重复确认、进度汇报等低信息量内容。
用中文输出，直接给出摘要内容，不要加前缀。"""


def get_window_size() -> int:
    """获取上下文窗口大小（支持配置覆盖）。"""
    try:
        from app.core.config import settings
        return getattr(settings, "CONTEXT_WINDOW_SIZE", CONTEXT_WINDOW_SIZE)
    except Exception:
        return CONTEXT_WINDOW_SIZE


def should_summarize(messages: list[BaseMessage], _existing_summary: str = "") -> bool:
    """
    判断是否需要触发摘要压缩。

    条件：非 system 消息数量超过窗口大小的 1.5 倍时触发。
    （1.5 倍是为了避免每多一条就触发，留一个缓冲区间）
    """
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]
    threshold = int(get_window_size() * 1.5)
    return len(non_system) > threshold


def summarize_messages(
    messages: list[BaseMessage],
    existing_summary: str = "",
) -> tuple[str, list[BaseMessage]]:
    """
    对消息列表进行摘要压缩。

    Args:
        messages: 完整的消息历史（含 system messages）
        existing_summary: 之前已有的摘要（累积模式）

    Returns:
        (new_summary, trimmed_messages)
        - new_summary: 更新后的摘要文本
        - trimmed_messages: 裁剪后的消息列表（摘要 + 最近 N 轮原文）
    """
    window_size = get_window_size()

    # 分离 system messages 和对话消息
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    conversation = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(conversation) <= window_size:
        # 不需要裁剪
        return existing_summary, messages

    # 需要压缩的部分（超出窗口的旧消息）
    overflow = conversation[:-window_size]
    recent = conversation[-window_size:]

    # 构建待压缩文本
    overflow_text = _messages_to_text(overflow)

    # 调用 LLM 生成摘要
    new_summary = _call_llm_summarize(overflow_text, existing_summary)

    if not new_summary:
        # LLM 调用失败，回退：直接截断，不压缩
        logger.warning("[Summarizer] LLM 摘要失败，回退为直接截断")
        new_summary = existing_summary

    # 组装裁剪后的消息列表
    trimmed = []

    # 1. 原始 system messages（如 agent 的 system prompt）
    trimmed.extend(system_msgs)

    # 2. 摘要作为额外的 system message 注入
    if new_summary:
        summary_msg = SystemMessage(content=f"[对话历史摘要]\n{new_summary}")
        trimmed.append(summary_msg)

    # 3. 最近 N 轮原文
    trimmed.extend(recent)

    logger.info(
        f"[Summarizer] 压缩完成: {len(conversation)} 条 → 摘要({len(new_summary)}字) + {len(recent)} 条原文"
    )
    return new_summary, trimmed


def _messages_to_text(messages: list[BaseMessage]) -> str:
    """将消息列表转为纯文本（供 LLM 摘要用）。"""
    lines = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "用户"
        elif isinstance(msg, AIMessage):
            role = "助手"
        else:
            role = "系统"

        content = msg.content or ""
        # 截断过长的单条消息（如工具返回的大段 JSON）
        if len(content) > 500:
            content = content[:500] + "...(截断)"

        # 跳过工具调用的中间消息（tool_calls）
        if hasattr(msg, "tool_calls") and msg.tool_calls and not content:
            tool_names = [tc.get("name", "?") for tc in msg.tool_calls]
            content = f"[调用工具: {', '.join(tool_names)}]"

        lines.append(f"{role}: {content}")

    return "\n".join(lines)


def _call_llm_summarize(overflow_text: str, existing_summary: str) -> str | None:
    """调用 LLM 生成摘要。"""
    try:
        from app.core.config import settings
        from app.core.llm_client import get_openai_client
        client = get_openai_client()
        if not client:
            logger.warning("[Summarizer] OpenAI client 不可用")
            return None

        user_content = ""
        if existing_summary:
            user_content += f"[之前的摘要]\n{existing_summary}\n\n"
        user_content += f"[需要压缩的新对话]\n{overflow_text}"

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,  # 🌟 使用配置的模型，避免硬编码 gpt-4o-mini 在当前通道不存在
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=1500,  # 🌟 推理模型会先消耗 token 做内部思考，适当调大
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.exception(f"[Summarizer] LLM 调用异常: {e}")
        return None
