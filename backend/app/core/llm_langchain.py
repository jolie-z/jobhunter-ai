"""
LangChain 站点的闸门接入 (app/core/llm_langchain.py)

规范 Phase 2：LangChain 不走 llm_tracker，闸门为显式式。本模块提供 GovernedChatOpenAI——
在模型层包住每次真实 HTTP 发送（_generate/_agenerate/_stream/_astream），确保：
1. 每次 LLM 调用前过闸（冷却窗 -> RPM 令牌 -> 并发槽），槽位仅在单次调用在飞期间持有；
2. ReAct 循环（create_agent）中的一轮多次模型调用逐次过闸，而非整轮占槽（跨工具执行占槽
   违反"仅 HTTP 在飞期间持有"约束，且 RPM 计数会漏记）；
3. 上游 429 经 classify_llm_error 同样开启全局冷却窗。

注意事项：
- 本模块必须惰性导入（M2 首启硬化：langchain_openai 在模块顶层 import 于无 .env 环境
  会因凭据校验崩溃，与 agent_router 的惰性构造约定一致）；
- governed_llm_passage 自带重入护栏，LangChain 内部 invoke -> _stream 等嵌套路径不会二次占槽。
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.llm_governed import async_governed_llm_passage, governed_llm_passage


class GovernedChatOpenAI(ChatOpenAI):
    """过闸版 ChatOpenAI：构造参数与原生一致，额外接受 gate_caller 标识调用来源。"""

    gate_caller: str = ""

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: Any = None, **kwargs: Any):
        with governed_llm_passage(caller=self.gate_caller):
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                         run_manager: Any = None, **kwargs: Any):
        async with async_governed_llm_passage(caller=self.gate_caller):
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(self, *args: Any, **kwargs: Any):
        with governed_llm_passage(caller=self.gate_caller):
            yield from super()._stream(*args, **kwargs)

    async def _astream(self, *args: Any, **kwargs: Any):
        async with async_governed_llm_passage(caller=self.gate_caller):
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
