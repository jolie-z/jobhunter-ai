# app/services/search_service.py
import asyncio


async def research_company_serper(company_name: str) -> str:
    """
    公司外部背调入口：统一走 Google Serper 4路并发侦察主引擎，
    当 Serper 异常或未配置时自动平滑降级至 Tavily 备用引擎。
    异步包装，供 executor.py 协程调用。
    """
    if not company_name or "某" in company_name or company_name in ("未知公司", "保密", "匿名"):
        return "⚠️ 匿名或未知公司，跳过外部背调"

    def _fetch():
        from ai_agents.company_intel import fetch_company_intel
        return fetch_company_intel(company_name)

    return await asyncio.to_thread(_fetch)
