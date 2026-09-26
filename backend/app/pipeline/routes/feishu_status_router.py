import sqlite3
from contextlib import closing

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# 9 模块判定体已下沉 config_status_service（CLI 体检脚本与 Router 统一消费，避免 CLI 反依赖 FastAPI）。
# 本模块保留同名薄壳与 re-export：setup_status.py / pipeline/router.py / 测试 monkeypatch 的
# 既有 import 路径全部不变。
from app.pipeline.config_status_service import (  # noqa: F401
    _ACTIVE_RESUME_META_CACHE,
    _PROJECT_ROOT,
    AUTOPILOT_DB,
    DB_PATH,
    _get_active_resume_meta_cached,
    compute_config_status,
    invalidate_active_resume_meta_cache,
)

router = APIRouter()


class FeishuConfigBody(BaseModel):
    batch_limit: int | None = None
    enable_report: bool | None = None
    enable_alert: bool | None = None


@router.get("/config-status")
def config_status():
    """自动判定全链路 9 大模块的配置状态（判定体在 config_status_service，此为薄壳）"""
    return compute_config_status()


@router.get("/feishu-status")
async def get_feishu_status_endpoint():
    """获取飞书多维表格连通状态、凭证与线索池元数据"""
    from app.automation.db import get_autopilot_config
    from app.core.cache import JobCache
    from app.core.config import settings

    app_id = settings.FEISHU_APP_ID or ""
    app_secret = settings.FEISHU_APP_SECRET or ""
    app_token = settings.FEISHU_APP_TOKEN or ""
    table_id = settings.FEISHU_TABLE_ID_JOBS or ""

    is_configured = bool(app_id and app_secret and app_token and table_id)
    app_id_masked = f"{app_id[:4]}****{app_id[-4:]}" if len(app_id) > 8 else (app_id or "未配置")

    cached = JobCache.get()
    if isinstance(cached, list):
        total_records = len(cached)
    else:
        try:
            with closing(sqlite3.connect(DB_PATH)) as conn:
                row = conn.execute("SELECT COUNT(*) FROM raw_jobs WHERE is_synced = 1 OR status = 'synced'").fetchone()
            total_records = row[0] if row else 0
        except Exception:
            total_records = 0

    bitable_url = f"https://feishu.cn/base/{app_token}?table={table_id}" if app_token and table_id else ""
    autopilot_cfg = get_autopilot_config()
    batch_limit = autopilot_cfg.get("batch_limit", 50)
    app_token_masked = (
        f"{app_token[:6]}****{app_token[-4:]}" if len(app_token) > 12 else (app_token or "未配置")
    )

    return {
        "code": 0,
        "data": {
            "is_configured": is_configured,
            "app_id_masked": app_id_masked,
            "app_token": app_token_masked,
            "table_id": table_id,
            "total_records": total_records,
            "bitable_url": bitable_url,
            "batch_limit": batch_limit,
            "enable_report": bool(autopilot_cfg.get("feishu_enable_report", True)),
            "enable_alert": bool(autopilot_cfg.get("feishu_enable_alert", True)),
        },
    }


@router.post("/feishu-test")
async def test_feishu_connection_endpoint():
    """发起飞书 API 实时连通性探测"""
    from app.core.feishu_client import feishu_client

    try:
        token = await feishu_client.get_tenant_access_token()
        if not token:
            raise HTTPException(status_code=502, detail="获取 Tenant Access Token 为空")
        return {
            "code": 0,
            "msg": "✓ 飞书多维表格凭证鉴权成功，连接状态健康！",
            "data": {"token_preview": f"{token[:8]}..."},
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"飞书鉴权失败: {str(e)}")


@router.post("/feishu-config")
async def save_feishu_config_endpoint(body: FeishuConfigBody):
    """保存飞书推送与通知参数——严格 PATCH，只写本面板字段"""
    from app.automation.db import update_autopilot_config

    if not update_autopilot_config(
        batch_limit=max(1, body.batch_limit or 50) if body.batch_limit is not None else None,
        feishu_enable_report=body.enable_report,
        feishu_enable_alert=body.enable_alert,
    ):
        raise HTTPException(status_code=500, detail="保存配置失败：数据库写入异常，请重试")
    return {"code": 0, "msg": "飞书推送与风控配置已保存"}
