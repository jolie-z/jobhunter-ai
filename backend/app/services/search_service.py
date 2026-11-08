# app/services/search_service.py
import asyncio


async def research_company_serper(company_name: str) -> str:
    """
    公司外部背调入口：统一走博查（国内直连）4 路并发侦察主引擎，
    未配置或异常时依次降级 Serper、Tavily（两者需要境外网络）。
    异步包装，供 executor.py 协程调用。
    """
    if not company_name or "某" in company_name or company_name in ("未知公司", "保密", "匿名"):
        return "⚠️ 匿名或未知公司，跳过外部背调"

    def _fetch():
        from ai_agents.company_intel import fetch_company_intel
        return fetch_company_intel(company_name)

    return await asyncio.to_thread(_fetch)
