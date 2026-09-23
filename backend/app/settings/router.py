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


@router.get("/readiness")
async def get_readiness() -> dict[str, Any]:
    """功能就绪度速查：主 LLM / 视觉 / 飞书最小字段是否配置齐全（零网络调用）。"""
    try:
        return await service.get_readiness()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/setup-status")
async def get_setup_status() -> dict[str, Any]:
    """新手引导配置体检：最小启动字段 + 简历库 + 指挥中心 9 模块聚合一次返回。"""
    try:
        from app.settings.setup_status import get_setup_status as _status
        return await _status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/diagnose/llm")
async def diagnose_llm() -> dict[str, Any]:
    """LLM 链路自检：推理通道配置 + 真实探活 + 视觉通道探活（视觉为选填项）。

    仅提供 POST：本端点会触发真实（极小）计费调用，不设 GET 以防浏览器预取误触。
    """
    try:
        from app.settings.diagnostics import diagnose_llm as _diagnose
        return await _diagnose()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/restart/preflight")
async def restart_preflight() -> dict[str, Any]:
    """重启前占用检测：批量任务 / 全链路流水线 / 平台爬虫是否有正在执行的。"""
    try:
        return await service.get_restart_blockers()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart")
async def restart_backend() -> dict[str, Any]:
    """一键重启后端：占用复检 → 通过则优雅退出（SIGTERM），由 PM2 守护自动拉起。

    有占用时返回 409 与阻塞项列表，前端提示用户等任务结束。
    响应先落盘再退出（3 秒延迟），保证前端能收到确认。
    """
    try:
        blockers = await service.get_restart_blockers()
        if not blockers.get("ok"):
            raise HTTPException(status_code=409, detail={
                "message": "当前有任务正在执行，暂不能重启",
                "blockers": blockers.get("blockers", []),
            })
        # 注意：request_graceful_exit 内部延迟 3 秒才发信号，本响应会正常返回；
        # 防重入：已有重启在途时仅确认，不再叠加退出线程
        service.request_graceful_exit()
        return {"ok": True, "message": "重启指令已接受，后端即将退出并由进程守护自动拉起（约 10~20 秒）"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
