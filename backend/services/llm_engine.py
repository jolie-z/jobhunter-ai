# services/llm_engine.py
import asyncio
from openai import AsyncOpenAI
import common.config as _ccfg
# 🌟 统一 Token 埋点拦截层
from app.core.llm_tracker import make_tracked_client

class LLMEngine:
    def __init__(self):
        # 注意这里我们改用 AsyncOpenAI，为了支持异步的高并发
        # 🌟 经 make_tracked_client 包装后，所有 create() 自动记录 token 消耗
        # 配置走动态属性访问（感知配置页保存）；interview 路由按请求实例化，天然拿到最新值
        raw = AsyncOpenAI(api_key=_ccfg.LLM_API_KEY, base_url=_ccfg.LLM_BASE_URL)
        self.client = make_tracked_client(raw, model_default=_ccfg.LLM_MODEL, caller="llm_engine")
        self.model = _ccfg.LLM_MODEL

    async def async_stream_generate(self, messages):
        """流式生成器：一段一段地吐出文字"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,  # 🌟 推理模型（如 mimo-v2.5-pro）会先消耗 token 做内部思考，max_tokens 过小会导致 content 为空
                stream=True # 🌟 核心：开启流式输出
            )
            async for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            print(f"❌ LLM 流式生成异常: {e}")