"""新手引导 · 配置体检聚合端点（GET /api/settings/setup-status）。

把散落各处的必配项收拢为一次调用，供前端「新手引导」三步卡消费：
  base     —— 最小启动必填的 8 个字段（LLM 3 + 飞书 5）逐一判定（common.config 同源）
  resume   —— 简历库是否有可用简历（与指挥中心 rewriting 同口径：活跃简历 meta 优先，resumes/*.md 兜底）
  pipeline —— 全链路指挥中心 9 模块（直接复用 config_status 判定，全是本地 sqlite/缓存读取）

complete = base 全齐 && resume 有简历（pipeline 属第三步「完整自动化体验」，不算硬阻塞）。
"""
import glob
import os
from typing import Any

from common.config import (
    MINIMAL_REQUIRED_KEYS,
    get_configured_value,
    get_missing_vision_keys,
)

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

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
    """简历库是否有可用简历：复用指挥中心 rewriting 的既有判定（含 60s 缓存），口径唯一。

    注：_get_active_resume_meta_cached 与 config_status 均为 pipeline 路由模块的既有符号
    （前者带下划线但属同仓共享判定逻辑的单点真源，60s 缓存随宿主模块唯一）；两者皆为
    同步函数（def），已由真机冒烟证实（配置齐全环境下 pipeline.done=True）。
    """
    try:
        from app.pipeline.routes.feishu_status_router import (
            _get_active_resume_meta_cached,
        )
        meta = _get_active_resume_meta_cached()
        if meta and (meta.get("id") or meta.get("title")):
            return True
    except Exception:
        pass
    try:
        resumes = glob.glob(os.path.join(_PROJECT_ROOT, "resumes", "*.md")) + glob.glob(
            os.path.join(_PROJECT_ROOT, "backend", "resumes", "*.md")
        )
        return len(resumes) > 0
    except Exception:
        return False


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

    # 2. 简历库
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
