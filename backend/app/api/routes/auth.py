"""
平台授权路由 — 统一唤起 Edge 浏览器完成登录。

端口 / profile 目录 / 授权 URL 全部定义在 app/session/registry.py（全项目唯一配置区），
本文件不允许出现任何硬编码端口；拉起逻辑复用 app/session/browser.py 的唯一实现。
"""
import logging

from fastapi import APIRouter, HTTPException

from app.session.browser import launch_edge
from app.session.registry import PLATFORM_CONFIGS, resolve_platform

logger = logging.getLogger(__name__)
router = APIRouter()

COMMON_RESPONSES = {
    400: {"description": "未找到 Edge 浏览器或启动失败"},
    404: {"description": "不支持的平台"},
}


@router.get("/platforms")
async def list_auth_platforms():
    """返回各平台授权配置表（端口来自全项目唯一配置区 registry，供前端展示，禁止前端另存副本）"""
    return {
        "status": "success",
        "platforms": [
            {"key": cfg.name, "display_name": cfg.display_name, "port": cfg.port}
            for cfg in PLATFORM_CONFIGS.values()
        ],
    }


@router.post("/{platform}/edge", responses=COMMON_RESPONSES)
async def launch_platform_edge(platform: str):
    """唤起指定平台的专用 Edge 浏览器（支持别名，如 /xhs/edge → xiaohongshu）"""
    config = resolve_platform(platform)
    if not config:
        raise HTTPException(status_code=404, detail=f"不支持的平台: {platform}")
    try:
        return launch_edge(config)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
