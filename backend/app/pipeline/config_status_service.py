"""全链路 9 模块配置状态判定(纯函数层)
====================================

自 feishu_status_router.py 下沉:供 HTTP Router(dashboard-sync / config-status
端点)与 CLI 运维脚本(newmachine_check.py)统一消费,避免 CLI 反向依赖
FastAPI Router。判定逻辑与返回结构与搬移前逐字节一致。

无 FastAPI/HTTP 依赖,可在任意上下文同步调用。
"""
import os
import sqlite3
import time
from contextlib import closing

from app.pipeline import get_scrape_config

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "job_hunter.db",
)
AUTOPILOT_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "autopilot.db",
)
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

_ACTIVE_RESUME_META_CACHE: dict = {"ts": 0.0, "value": None}


def _get_active_resume_meta_cached(ttl: float = 60.0):
    from app.services.feishu_service import get_active_resume_meta

    now = time.time()
    if now - _ACTIVE_RESUME_META_CACHE["ts"] < ttl:
        return _ACTIVE_RESUME_META_CACHE["value"]
    try:
        value = get_active_resume_meta()
    except Exception:
        value = None
    _ACTIVE_RESUME_META_CACHE["ts"] = now
    _ACTIVE_RESUME_META_CACHE["value"] = value
    return value


def invalidate_active_resume_meta_cache() -> None:
    """主动失效活跃简历 60s 缓存。

    简历生效状态被切换/自动生效后调用，让 setup-status（新手指引第二步）、
    config_status（改写模块判定）等消费方下一次读取立刻看到新的生效简历，
    而不是等最多 60s TTL 自然过期。
    """
    _ACTIVE_RESUME_META_CACHE["ts"] = 0.0


def compute_config_status() -> dict:
    """自动判定全链路 9 大模块的配置状态"""
    status = {
        "scraping": False,
        "cleaning": False,
        "feishu_sync": False,
        "evaluating": False,
        "deep_eval": True,
        "rewriting": False,
        "greeting": False,
        "review": False,
        "delivering": False,
    }

    # 1. 平台抓取
    try:
        cfg = get_scrape_config()
        has_keywords = len(cfg.get("keywords", [])) > 0
        has_platforms = (
            any(p.get("enabled", False) for p in cfg.get("platforms", {}).values())
            if isinstance(cfg.get("platforms"), dict)
            else False
        )
        status["scraping"] = has_keywords and has_platforms
    except Exception:
        pass
    if not status["scraping"]:
        try:
            from app.automation.db import get_autopilot_config

            autopilot = get_autopilot_config()
            plat_cfg = autopilot.get("platform_configs", {}) or {}
            for v in plat_cfg.values():
                limit = v.get("limit", 0) if isinstance(v, dict) else (v if isinstance(v, (int, float)) else 0)
                if int(limit or 0) > 0:
                    status["scraping"] = True
                    break
        except Exception:
            pass

    # 2. 规则清洗
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM job_strategies WHERE is_active = 1").fetchone()
        status["cleaning"] = row[0] > 0 if row else False
    except Exception:
        pass

    # 3. 飞书推送
    try:
        from app.core.config import settings

        app_id = (getattr(settings, "FEISHU_APP_ID", "") or "").strip()
        app_secret = (getattr(settings, "FEISHU_APP_SECRET", "") or "").strip()
        app_token = (getattr(settings, "FEISHU_APP_TOKEN", "") or "").strip()
        table_id = (
            getattr(settings, "FEISHU_TABLE_ID_JOBS", "") or getattr(settings, "FEISHU_TABLE_ID", "") or ""
        ).strip()
        status["feishu_sync"] = bool(app_id and app_secret and (app_token or table_id))
    except Exception:
        pass

    # 4. AI初评
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM evaluation_weights").fetchone()
        status["evaluating"] = row[0] > 0 if row else False
    except Exception:
        pass

    # 5. 深度评估
    status["deep_eval"] = True

    # 6. 简历改写
    meta = _get_active_resume_meta_cached()
    if meta and (meta.get("id") or meta.get("title")):
        status["rewriting"] = True
    if not status["rewriting"]:
        try:
            import glob

            resumes = glob.glob(os.path.join(_PROJECT_ROOT, "resumes", "*.md")) + glob.glob(
                os.path.join(_PROJECT_ROOT, "backend", "resumes", "*.md")
            )
            status["rewriting"] = len(resumes) > 0
        except Exception:
            status["rewriting"] = False

    # 7. 打招呼语
    try:
        from app.automation.db import get_autopilot_config

        cfg = get_autopilot_config()
        mag = (cfg.get("mass_apply_greeting") or "").strip()
        gp = cfg.get("greeting_platforms") or {}
        has_gp = any(bool(v) for v in gp.values()) if isinstance(gp, dict) else True
        status["greeting"] = bool(len(mag) > 0 and has_gp)
    except Exception:
        pass

    # 8. 待审批
    try:
        from app.automation.db import get_autopilot_config

        cfg = get_autopilot_config()
        headcount = int(cfg.get("mass_apply_max_headcount", 0) or 0)
        status["review"] = headcount > 0
    except Exception:
        pass

    # 9. 自动投递
    try:
        if os.path.exists(AUTOPILOT_DB):
            with closing(sqlite3.connect(AUTOPILOT_DB)) as conn:
                row = conn.execute("SELECT auto_deliver_platforms FROM automation_configs WHERE id = 1").fetchone()
            if row and row[0]:
                import json

                platforms = json.loads(row[0])
                status["delivering"] = len(platforms) > 0
    except Exception:
        pass

    required_keys = [
        "scraping",
        "cleaning",
        "feishu_sync",
        "evaluating",
        "rewriting",
        "greeting",
        "review",
        "delivering",
    ]
    all_configured = all(status[k] for k in required_keys)
    return {
        "code": 0,
        "data": {
            "modules": status,
            "all_configured": all_configured,
            "required_keys": required_keys,
        },
    }
