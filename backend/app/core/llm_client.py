# 📂 app/core/llm_client.py

from openai import OpenAI

# 🌟 临时从旧配置库借用底层获取函数，等我们未来重构 config 时再彻底解绑
from common.config import _cfg, get_safe_httpx_client


def get_openai_client() -> OpenAI | None:
    """返回使用最新配置的 OpenAI 客户端（动态读取，感知 settings.json 变更）。
    自动包装 token 追踪代理，所有调用方的 LLM 消耗均会被记录。
    """
    from app.core.llm_tracker import make_tracked_client

    key = _cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY")
    url = _cfg("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url", json_key="OPENAI_BASE_URL")

    if not key:
        return None

    raw_client = OpenAI(
        api_key=key,
        base_url=url,
        http_client=get_safe_httpx_client(),
        max_retries=3
    )
    return make_tracked_client(raw_client, caller="llm_client")
