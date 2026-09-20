import logging

from fastapi import APIRouter, HTTPException

from app.strategy import service
from app.strategy.schemas import (
    ActivateResumeRequest,
    ActiveStrategyResponse,
    DeleteStrategyRequest,
    PredictDescRequest,
    PreferenceUpsertRequest,
    SaveConfigRequest,
    UpdateStrategyRequest,
    WeightsUpdateRequest,
)

logger = logging.getLogger("strategy_rules_router")
logger.setLevel(logging.INFO)

router = APIRouter()


@router.get("/weights")
async def get_weights():
    """获取动态评估权重"""
    weights = await service.get_weights_service()
    return {"status": "success", "data": weights}


@router.post("/weights")
async def update_weights(payload: WeightsUpdateRequest):
    """保存用户自定义评估权重"""
    await service.update_weights_service(payload.weights)
    return {"status": "success", "message": "权重保存成功"}


@router.get("/active", response_model=ActiveStrategyResponse)
async def read_active_strategy():
    """获取当前的岗位初筛策略 (SQLite)"""
    return await service.get_active_strategy()


@router.post("/active", responses={500: {"description": "Error 500"}})
async def update_active_strategy_api(payload: UpdateStrategyRequest):
    """更新当前的岗位初筛策略到 SQLite"""
    try:
        await service.update_active_strategy_in_db(payload)
        return {"status": "success", "message": "策略更新成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"策略更新失败: {str(e)}")


@router.get("/config", responses={500: {"description": "Error 500"}})
async def get_strategy_config():
    """获取所有简历和Prompt配置列表，供大盘渲染"""
    try:
        data = await service.get_all_strategy_configs()
        return {"status": "success", **data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取策略配置失败: {str(e)}")


@router.post("/activate_resume", responses={500: {"description": "Error 500"}})
def activate_resume(payload: ActivateResumeRequest):
    """唯一启用排斥：切换生效简历底稿"""
    try:
        service.activate_target_resume(payload.record_id)
        return {"status": "success", "message": "已切换生效底稿"}
    except Exception as e:
        logger.exception(f"[activate_resume] 报错: {e}")
        raise HTTPException(status_code=500, detail=f"切换简历状态失败: {str(e)}")


@router.post("/save", responses={500: {"description": "Error 500"}})
async def save_strategy_config(payload: SaveConfigRequest):
    """保存或更新配置到飞书多维表格"""
    try:
        record_id = await service.save_strategy_config_service(payload)
        return {"status": "success", "record_id": record_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理保存请求时出错: {str(e)}")


@router.post("/delete", responses={500: {"description": "Error 500"}})
async def delete_strategy(payload: DeleteStrategyRequest):
    """从飞书中永久删除一条配置记录"""
    try:
        await service.delete_strategy_service(payload)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/preferences")
async def get_preferences():
    """实时拉取飞书多维表格中的求职偏好数据"""
    try:
        data = await service.get_preferences_service()
        return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/preferences")
async def upsert_preference(payload: PreferenceUpsertRequest):
    """新增或修改飞书多维表格中的求职偏好"""
    try:
        msg = await service.upsert_preference_service(payload)
        return {"status": "success", "message": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/preferences/{record_id}")
async def delete_preference(record_id: str):
    """删除飞书多维表格中的偏好规则"""
    try:
        msg = await service.delete_preference_service(record_id)
        return {"status": "success", "message": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/predict_desc", responses={500: {"description": "Error 500"}})
async def predict_desc_api(payload: PredictDescRequest):
    """大模型辅助生成 AI 初筛解释语"""
    try:
        desc = await service.predict_keyword_desc_service(payload.keyword)
        return {"status": "success", "data": desc}
    except Exception as e:
        logger.exception(f"predict_desc error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
