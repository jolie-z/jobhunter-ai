"""新手引导 · 配置体检聚合端点（GET /api/settings/setup-status）。

把散落各处的必配项收拢为一次调用，供前端「新手引导」三步卡消费：
  base     —— 最小启动必填的 8 个字段（LLM 3 + 飞书 5）逐一判定（common.config 同源）
  resume   —— 简历库是否有「已生效」简历（与指挥中心 rewriting 同口径：当前状态=启用；
              不再对本地 resumes/*.md 兜底——第二步必须确认用户设置了生效简历）
  pipeline —— 全链路指挥中心 9 模块（直接复用 config_status 判定，全是本地 sqlite/缓存读取）

complete = base 全齐 && resume 有生效简历（pipeline 属第三步「完整自动化体验」，不算硬阻塞）。
"""
import logging
import time
from typing import Any

from common.config import (
    MINIMAL_REQUIRED_KEYS,
    get_configured_value,
    get_missing_vision_keys,
)

# 自愈节流：新手指引弹窗开着时本接口每 8s 被轮询一次，自愈至少间隔 60s，避免空转打飞书
_LAST_HEAL_TS = {"ts": 0.0}
_HEAL_MIN_INTERVAL = 60.0

logger = logging.getLogger("setup_status")

# 最小字段的展示归属（分组名与配置页 CONFIG_GROUPS 对齐）
_FIELD_LABELS = {
    "OPENAI_API_KEY": ("LLM 大模型", "API Key"),
    "OPENAI_BASE_URL": ("LLM 大模型", "Base URL"),
    "OPENAI_MODEL": ("LLM 大模型", "推理模型"),
    "FEISHU_APP_ID": ("飞书", "App ID"),
    "FEISHU_APP_SECRET": ("飞书", "App Secret"),
    "FEISHU_APP_TOKEN": ("飞书", "App Token"),
    "FEISHU_TABLE_ID_JOBS": ("飞书", "岗位总表"),
    "FEISHU_TABLE_ID_RESUMES": ("飞书", "简历库"),
}


def _resume_exists() -> bool:
    """简历库是否有「已生效」简历：复用指挥中心 rewriting 的既有判定（当前状态=启用，60s 缓存），口径唯一。

    新手指引第二步要求用户明确设置生效中的简历；库里仅一份简历时 config 读取/保存
    链路会自动生效（config_service._ensure_single_resume_active），因此这里不再对
    resumes/*.md 本地文件兜底——本地文件存在不等于简历已接入改写/投递链路。
    """
    try:
        from app.pipeline.routes.feishu_status_router import (
            _get_active_resume_meta_cached,
        )
        meta = _get_active_resume_meta_cached()
        if meta and (meta.get("id") or meta.get("title")):
            return True
    except Exception as e:
        logger.debug(f"[setup-status] 活跃简历判定异常（按未生效处理）: {e}")
    return False


async def _heal_single_resume_if_needed() -> None:
    """第二步判定失败时的兜底自愈：库里仅一份简历且未生效则自动启用。

    覆盖「用户只在飞书表里维护简历 / 只打开引导弹窗未进简历库页」的窗口期；
    自愈内部全 try/except 且有 60s 节流，绝不阻塞体检接口本身。
    无论自愈是否实际启用（含「已有生效简历、仅缓存过期」的情形），都失效一次
    活跃简历缓存，保证随后的重判读到真实状态而不是同一份 stale 缓存。
    """
    if not get_configured_value("FEISHU_TABLE_ID_RESUMES"):
        return
    now = time.time()
    if now - _LAST_HEAL_TS["ts"] < _HEAL_MIN_INTERVAL:
        return
    try:
        from app.strategy.config_service import _ensure_single_resume_active
        await _ensure_single_resume_active()
        _LAST_HEAL_TS["ts"] = time.time()
    except Exception as e:
        logger.debug(f"[setup-status] 单份简历自愈尝试失败（下次轮询重试）: {e}")
        return
    try:
        from app.pipeline.routes.feishu_status_router import (
            invalidate_active_resume_meta_cache,
        )
        invalidate_active_resume_meta_cache()
    except Exception as e:
        logger.debug(f"[setup-status] 自愈后失效活跃简历缓存失败: {e}")


async def get_setup_status() -> dict[str, Any]:
    # 1. base：最小启动字段逐一判定
    fields: list[dict[str, Any]] = []
    base_done = True
    for channel, keys in MINIMAL_REQUIRED_KEYS.items():
        for key in keys:
            group, label = _FIELD_LABELS.get(key, (channel, key))
            filled = bool(get_configured_value(key))
            if not filled:
                base_done = False
            fields.append({"key": key, "group": group, "label": label, "filled": filled})

    # 2. 简历库：先判「已生效」，未生效时兜底自愈（单份自动启用）后重判
    resume_done = _resume_exists()
    if not resume_done:
        await _heal_single_resume_if_needed()
        resume_done = _resume_exists()

    # 3. 指挥中心 9 模块（config_status 内部已逐项 try/except fail-open）
    pipeline_modules: dict = {}
    pipeline_all = False
    try:
        from app.pipeline.routes.feishu_status_router import config_status
        data = config_status().get("data", {})
        pipeline_modules = data.get("modules", {})
        pipeline_all = bool(data.get("all_configured"))
    except Exception:
        pass

    vision_missing = get_missing_vision_keys()

    return {
        "code": 0,
        "data": {
            "base": {"done": base_done, "fields": fields},
            "resume": {"done": resume_done},
            "pipeline": {"done": pipeline_all, "modules": pipeline_modules},
            "vision_ready": not vision_missing,
            "complete": base_done and resume_done,
        },
    }
