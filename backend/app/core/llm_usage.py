"""LLM usage 观测的共享工具：网关前缀缓存命中量（cached_tokens）白盒日志。

多轮（grill）与多条目（ATS 对齐）链路共用。「稳定前缀优先」的消息排布是否真的
命中缓存，只能靠网关回传的 prompt_tokens_details.cached_tokens 验证——观测与
排布约束必须成对出现。

usage 形态因 SDK/网关而异（pydantic 对象或 dict，嵌套的 prompt_tokens_details
也可能是 dict），全部按缺省容错，绝不因观测抛错阻断主流程。
"""
import logging
from typing import Any

logger = logging.getLogger("llm_usage")
logger.setLevel(logging.INFO)


def extract_prompt_cache_usage(usage: Any) -> tuple[int | None, int]:
    """从 OpenAI 兼容 usage（对象或 dict）提取 (prompt_tokens, cached_tokens)，缺失按 0。"""
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        details = usage.get("prompt_tokens_details")
    else:
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        details = getattr(usage, "prompt_tokens_details", None)
    if isinstance(details, dict):
        cached = details.get("cached_tokens")
    else:
        cached = getattr(details, "cached_tokens", None) if details is not None else None
    try:
        prompt_tokens = int(prompt_tokens) if prompt_tokens is not None else None
    except (TypeError, ValueError):
        prompt_tokens = None
    try:
        cached = int(cached) if cached is not None else 0
    except (TypeError, ValueError):
        cached = 0
    return prompt_tokens, cached


def log_prompt_cache_hit(func_name: str, usage: Any, turn: int | None = None) -> None:
    """记录网关前缀缓存命中量；usage 为空（部分网关不回传）时静默跳过。"""
    if not usage:
        return
    prompt_tokens, cached = extract_prompt_cache_usage(usage)
    turn_part = f"第 {turn} 轮 " if turn is not None else ""
    logger.info(f"[Func: {func_name}] {turn_part}prompt_tokens={prompt_tokens} cached_tokens={cached}")
