# 📂 app/core/llm_client.py
"""
统一 LLM Client 对外访问门面：
委托 common.config.get_openai_client，收敛双入口并自动挂载治理与埋点代理。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("llm_client")


def get_openai_client(caller: str = "", max_retries: int | None = None, timeout: float | None = None) -> Any | None:
    """返回使用最新配置的 OpenAI 客户端（动态感知 settings.json 变更与统一重试治理）。

    caller/max_retries/timeout 原样透传给 common.config.get_openai_client：
    调用方靠 caller 进入对应批量通道与埋点，门面不得吞参改写。
    """
    from common.config import get_openai_client as _get_client
    return _get_client(caller=caller or "llm_client", max_retries=max_retries, timeout=timeout)


def chat_create_no_thinking(client: Any, **kwargs: Any) -> Any:
    """确定性/结构化 LLM 调用统一入口：关闭推理模型思考并做网关兼容降级。

    背景（2026-10-22 画像空内容 / 2026-10-23 改写截断清空项目经历，同根两起）：
    推理模型的思考计入 completion 输出预算，聚合/提取类任务的思考先烧尽预算、
    正文被拦腰截断。顶层 {"thinking":{"type":"disabled"}} 本机网关实测生效
    （enable_thinking:false 与 reasoning.enabled:false 实测无效，勿改）；
    其他网关不认该参数时（异常文本含 thinking）降级去掉后重发一次。

    注意：本函数不检查 finish_reason——截断显式失败属调用方业务语义
    （各链路失败形态不同），调用方必须自行判读 response.choices[0].finish_reason。
    """
    kwargs = dict(kwargs)
    kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as e:
        if "thinking" in str(e).lower():
            logger.warning(f"[llm_client] 网关不接受 thinking 参数，降级不携带重发: {e}")
            kwargs.pop("extra_body", None)
            return client.chat.completions.create(**kwargs)
        raise
