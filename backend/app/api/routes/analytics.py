# app/api/routes/analytics.py
"""
Token 用量分析接口 v1 - 提供聚合查询供前端大盘展示。
底层业务计算与多模型配置统一收敛至:
  1. app.services.analytics_stats_service: Token 算力与成本审计统计
  2. app.services.model_pricing_service: 模型计价与多角色资费配置
"""
import logging

from fastapi import APIRouter, Query

from app.services.analytics_stats_service import calculate_token_stats
from app.services.model_pricing_service import (
    PricingConfigPayload,
    get_model_pricing_config_data,
    save_model_pricing_config_data,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/tokens")
async def get_token_stats(
    time_range: str | None = Query(default="all", alias="range", pattern="^(today|month|all)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
):
    """
    Token 用量聚合接口（v1 兼容）。
    统一委托 analytics_stats_service 执行高内聚计算，确保与 v2 结果完全同构。
    backfill_missing_cost=True 沿用 v1 历史口径：对 cost_cny=0 的存量行按计价表实时补算。
    """
    try:
        data = calculate_token_stats(
            time_range=time_range or "all",
            page=page,
            page_size=page_size,
            backfill_missing_cost=True,
        )
        return {"code": 0, "data": data}
    except Exception as e:
        logger.error(f"[analytics] tokens 查询失败: {e}", exc_info=True)
        return {"code": 1, "msg": f"查询失败: {str(e)}", "data": None}


@router.get("/model-pricing-config")
async def get_model_pricing_config(model: str | None = None):
    """
    获取指定模型（或当前系统活跃模型）的计价配置详情，并返回多模型清单与官方基准表。
    """
    data = get_model_pricing_config_data(model=model)
    return {"code": 0, "data": data}


@router.post("/model-pricing-config")
async def save_model_pricing_config(payload: PricingConfigPayload):
    """
    保存或重置用户自定义模型计价配置（单位：元 / 1M tokens）。
    保存后可由用户选择是否重算该模型的历史记录。
    """
    code, msg, data = save_model_pricing_config_data(payload)
    return {"code": code, "msg": msg, "data": data}
