# app/services/model_pricing_service.py
"""
模型计价与成本核算服务层。
集中收敛多模型配置解析、官方定价字典以及自定义计价的保存与目标历史精准重算。
"""
import logging

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.model_pricing import (
    MIMO_PRICING,
    delete_custom_pricing,
    get_custom_pricing,
    is_mimo_model,
    save_custom_pricing,
)
from app.services.token_service import recalculate_historical_costs
from common.config import CLEANER_LLM_MODEL, CLEANER_VISION_MODEL, VISION_MODEL

logger = logging.getLogger(__name__)

# 官方国内定价基准表（对齐 MiMo 官网最新定价）
MIMO_OFFICIAL_LIST = [
    {
        "series": "MiMo-V2.5 系列",
        "model_name": "mimo-v2.5-pro",
        "cached_prompt_rate": 0.025,
        "prompt_rate": 3.00,
        "completion_rate": 6.00,
    },
    {
        "series": "MiMo-V2.5 系列",
        "model_name": "mimo-v2.5",
        "cached_prompt_rate": 0.02,
        "prompt_rate": 1.00,
        "completion_rate": 2.00,
    },
]


class PricingConfigPayload(BaseModel):
    model_name: str = Field(..., description="模型名称")
    prompt_rate: float = Field(..., ge=0, description="输入未命中单价 (元 / 1M tokens)")
    cached_prompt_rate: float = Field(default=0.0, ge=0, description="输入命中缓存单价 (元 / 1M tokens)")
    completion_rate: float = Field(..., ge=0, description="输出单价 (元 / 1M tokens)")
    reset: bool = Field(default=False, description="是否重置为默认")
    recalculate_history: bool = Field(default=False, description="是否触发目标模型历史成本重算")


def get_model_pricing_config_data(model: str | None = None) -> dict:
    """
    获取指定模型（或当前系统活跃模型）的计价配置详情，并汇总系统配置的全部模型与官方基准表。
    """
    active_model = model or settings.OPENAI_MODEL or "mimo-v2.5-pro"
    is_mimo = is_mimo_model(active_model)
    custom = get_custom_pricing(active_model)

    # 汇总系统配置的 4 个关键角色模型
    roles_def = [
        ("主评估推理", "main_model", settings.OPENAI_MODEL or "mimo-v2.5-pro"),
        ("数据清洗专用", "cleaner_model", CLEANER_LLM_MODEL or ""),
        ("主视觉模型", "vision_model", VISION_MODEL or ""),
        ("清洗视觉模型", "cleaner_vision_model", CLEANER_VISION_MODEL or ""),
    ]
    configured_models = []
    for role, key, m_name in roles_def:
        if not m_name:
            continue
        m_name = m_name.strip()
        is_m = is_mimo_model(m_name)
        c = get_custom_pricing(m_name)
        configured_models.append({
            "role": role,
            "key": key,
            "model_name": m_name,
            "is_mimo": is_m,
            "has_custom_pricing": c is not None,
            "pricing": {
                "prompt_rate": c["raw_prompt_1m"],
                "cached_prompt_rate": c["raw_cached_1m"],
                "completion_rate": c["raw_completion_1m"],
            } if c else (
                {
                    "prompt_rate": MIMO_PRICING[m_name]["prompt"] * 1000.0,
                    "cached_prompt_rate": MIMO_PRICING[m_name]["cached_prompt"] * 1000.0,
                    "completion_rate": MIMO_PRICING[m_name]["completion"] * 1000.0,
                } if is_m and m_name in MIMO_PRICING else None
            )
        })

    return {
        "active_model": active_model,
        "is_mimo": is_mimo,
        "has_custom_pricing": custom is not None,
        "custom_pricing": {
            "prompt_rate": custom["raw_prompt_1m"] if custom else None,
            "cached_prompt_rate": custom["raw_cached_1m"] if custom else None,
            "completion_rate": custom["raw_completion_1m"] if custom else None,
        } if custom else None,
        "mimo_defaults": {
            "prompt_rate": MIMO_PRICING.get("mimo-v2.5-pro", {}).get("prompt", 0.003) * 1000.0,
            "cached_prompt_rate": MIMO_PRICING.get("mimo-v2.5-pro", {}).get("cached_prompt", 0.000025) * 1000.0,
            "completion_rate": MIMO_PRICING.get("mimo-v2.5-pro", {}).get("completion", 0.006) * 1000.0,
        },
        "mimo_official_list": MIMO_OFFICIAL_LIST,
        "configured_models": configured_models,
    }


def save_model_pricing_config_data(payload: PricingConfigPayload) -> tuple[int, str, dict | None]:
    """
    保存或重置用户自定义模型计价配置，并根据用户授权严格按 target_model 范围执行历史重算。
    返回: (code, message, result_data)
    """
    model_name = (payload.model_name or "").strip()
    if not model_name:
        return 1, "模型名称不能为空", None

    if is_mimo_model(model_name):
        return 1, f"模型 [{model_name}] 属于 MiMo 官方系列，系统已内置基准资费，无需重复配置", None

    logger.info(
        f"[model_pricing_service] 接收计价配置请求: model={model_name}, reset={payload.reset}, "
        f"recalculate_history={payload.recalculate_history}, prompt={payload.prompt_rate}"
    )

    if payload.reset:
        delete_custom_pricing(model_name)
        msg = f"已重置模型 [{model_name}] 的自定义计价"
    else:
        try:
            save_custom_pricing(
                model_name=model_name,
                prompt_per_1m=payload.prompt_rate,
                cached_prompt_per_1m=payload.cached_prompt_rate,
                completion_per_1m=payload.completion_rate,
            )
            msg = f"已成功保存模型 [{model_name}] 的自定义单价"
        except ValueError as e:
            return 1, str(e), None

    recalc_result = None
    if payload.recalculate_history:
        try:
            # 严格限定 target_model，支持前缀兼容，绝不污染其他模型
            recalc_result = recalculate_historical_costs(target_model=model_name)
            updated_count = recalc_result.get("updated_count", 0)
            msg += f"，并已同步重算该模型 {updated_count} 条历史账单"
            logger.info(f"[model_pricing_service] 历史账单重算完成: model={model_name}, count={updated_count}")
        except Exception as e:
            logger.error(f"[model_pricing_service] 重算历史成本异常: model={model_name}, err={e}", exc_info=True)
            msg += f"（注意：历史账单重算未完成: {str(e)}）"

    return 0, msg, {
        "model_name": model_name,
        "recalculated": recalc_result,
    }
