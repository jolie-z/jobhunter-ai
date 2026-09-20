# app/api/routes/analytics_dashboard.py
"""
数据分析聚合路由 v2 - 为前端数据分析大盘和外部调用提供统一接口。
内部业务计算已严格解耦下沉至:
  1. app.services.analytics_pipeline_service: 飞书多维表格与招聘管道指标聚合
  2. app.services.analytics_stats_service: 大模型 Token 算力与成本审计统计
  3. app.services.model_pricing_service: 模型计价与多角色资费配置
"""
import logging

from fastapi import APIRouter, Query

from app.services.analytics_pipeline_service import (
    calculate_funnel_stats,
    calculate_overview_stats,
    calculate_platform_stats,
    calculate_trend_stats,
    get_feishu_pipeline_stats,
    get_feishu_stats_sync,
)
from app.services.analytics_stats_service import calculate_token_stats
from app.services.feishu_jobs_fetcher import invalidate_feishu_cache
from app.services.model_pricing_service import (
    PricingConfigPayload,
    get_model_pricing_config_data,
    save_model_pricing_config_data,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 导出同步包装函数，确保 report_service / goal_service / chatops 等外部调用兼容
__all__ = ["router", "get_feishu_stats_sync", "get_feishu_pipeline_stats"]


@router.get("/overview")
async def get_overview():
    """核心指标总览。"""
    try:
        data = await calculate_overview_stats()
        return {"code": 0, "data": data}
    except Exception as e:
        logger.error(f"[analytics_dashboard] overview 查询失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"查询失败: {str(e)}", "data": None}


@router.get("/funnel")
async def get_funnel():
    """求职漏斗 - 顶部总抓取量(本地) + 飞书跟进状态动态分布。"""
    try:
        data = await calculate_funnel_stats()
        return {"code": 0, "data": data}
    except Exception as e:
        logger.error(f"[analytics_dashboard] funnel 查询失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"查询失败: {str(e)}", "data": None}


@router.get("/platform")
async def get_platform_stats():
    """平台转化效率 - 动态读取招聘平台字段并经智能归一化聚合。"""
    try:
        data = await calculate_platform_stats()
        return {"code": 0, "data": data}
    except Exception as e:
        logger.error(f"[analytics_dashboard] platform 查询失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"查询失败: {str(e)}", "data": None}


@router.get("/trend")
async def get_trend(
    time_range: str = Query(default="daily", alias="range", pattern="^(daily|weekly|monthly)$"),
):
    """抓取/投递/面试趋势（按抓取时间分桶）。"""
    try:
        data = await calculate_trend_stats(time_range=time_range)
        return {"code": 0, "data": data}
    except Exception as e:
        logger.error(f"[analytics_dashboard] trend 查询失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"查询失败: {str(e)}", "data": None}


@router.get("/tokens")
async def get_token_stats(
    time_range: str | None = Query(default="all", alias="range", pattern="^(today|month|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
):
    """Token 用量统计与调用审计明细。"""
    try:
        data = calculate_token_stats(
            time_range=time_range or "all",
            page=page,
            page_size=page_size,
        )
        return {"code": 0, "data": data}
    except Exception as e:
        logger.error(f"[analytics_dashboard] tokens 统计失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"聚合分析异常: {str(e)}", "data": None}


@router.get("/model-pricing-config")
async def get_v2_model_pricing_config(model: str | None = None):
    """V2 接口：获取模型计价配置详情，并返回多模型清单与官方定价表。"""
    data = get_model_pricing_config_data(model=model)
    return {"code": 0, "data": data}


@router.post("/model-pricing-config")
async def save_v2_model_pricing_config(payload: PricingConfigPayload):
    """V2 接口：保存或重置用户自定义模型计价配置，支持精准定向历史重算。"""
    code, msg, data = save_model_pricing_config_data(payload)
    return {"code": code, "msg": msg, "data": data}


@router.post("/cache/clear")
async def clear_cache():
    """清除飞书数据缓存，并打脏磁盘 JobCache 快照，确保下轮拉取强制绕过本地缓存。"""
    invalidate_feishu_cache()
    try:
        from app.core.cache import JobCache
        JobCache.mark_dirty()
    except Exception as e:
        logger.warning(f"[analytics_dashboard] JobCache.mark_dirty 失败: {e}")
    return {"code": 0, "msg": "缓存已清除"}
