from typing import Any

from fastapi import APIRouter, HTTPException

from app.settings import service
from app.settings.schemas import SettingsPayload

router = APIRouter()

@router.get("")
@router.get("/")
async def get_settings() -> dict[str, Any]:
    """返回当前系统配置（按分组，敏感 Key 已遮罩）。"""
    try:
        return await service.get_system_settings()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
@router.post("/")
async def save_settings(payload: SettingsPayload) -> dict[str, Any]:
    """保存配置到 settings.json，并热重载 config 模块及全局客户端。"""
    try:
        return await service.save_system_settings(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/diagnose/feishu")
@router.get("/diagnose/feishu")
async def diagnose_feishu() -> dict[str, Any]:
    """飞书配置连通性自检：凭证 → token → 多维表格 → 数据表 → 群列表 → 长连接。"""
    try:
        from app.settings.diagnostics import diagnose_feishu as _diagnose
        return await _diagnose()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
