import asyncio
import importlib
import json
import os
from typing import Any

import common.config as _config_module
from app.settings.schemas import SettingsPayload
from common.config import MINIMAL_REQUIRED_KEYS
from common.config import SETTINGS_JSON_PATH as SETTINGS_DATA_PATH

# 字段级「最小启动必填」集合（LLM 3 键 + 飞书 5 键，与 common.config 同源）
_MINIMAL_REQUIRED = {key for keys in MINIMAL_REQUIRED_KEYS.values() for key in keys}

# 敏感字段集合 — 这些字段返回时做遮罩处理
_SENSITIVE_KEYS = {
    "OPENAI_API_KEY", "CLEANER_LLM_API_KEY", "VISION_API_KEY",
    "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
    "SERPER_API_KEY", "TAVILY_API_KEY",
    "VOLC_ASR_APPID", "VOLC_ASR_TOKEN",
    "AMAP_API_KEY",
}


def _mask_key(val: str | None) -> str:
    """对敏感 Key 进行遮罩处理，仅显示前 4 位和后 4 位。"""
    if not val:
        return ""
    if len(val) <= 8:
        return "****"
    return val[:4] + "****" + val[-4:]


# 分组定义：(分组标题, [(字段key, 显示名, 是否敏感)])
CONFIG_GROUPS = [
    ("LLM 大模型", [
        ("OPENAI_API_KEY", "API Key", True),
        ("OPENAI_BASE_URL", "Base URL", False),
        ("OPENAI_MODEL", "推理模型", False),
        ("VISION_MODEL", "视觉模型", False),
    ]),
    ("视觉通道 (可选)", [
        ("VISION_API_KEY", "API Key", True),
        ("VISION_BASE_URL", "Base URL", False),
    ]),
    ("数据清洗 LLM", [
        ("CLEANER_LLM_API_KEY", "API Key", True),
        ("CLEANER_LLM_BASE_URL", "Base URL", False),
        ("CLEANER_LLM_MODEL", "清洗模型", False),
        ("CLEANER_VISION_MODEL", "清洗视觉模型", False),
    ]),
    ("飞书", [
        ("FEISHU_APP_ID", "App ID", True),
        ("FEISHU_APP_SECRET", "App Secret", True),
        ("FEISHU_APP_TOKEN", "App Token", True),
        ("FEISHU_TABLE_ID_JOBS", "岗位总表", False),
        ("FEISHU_TABLE_ID_RESUMES", "简历库", False),
        ("FEISHU_TABLE_ID_INTERVIEW_REPORTS", "面试报告", False),
        ("FEISHU_TABLE_ID_INTERVIEW_SUMMARY", "面试汇总", False),
        ("FEISHU_TABLE_ID_INTERVIEW_REAL", "真题库", False),
        ("FEISHU_ALERT_RECEIVE_ID", "预警接收人 ID (ou_ 或 oc_)", False),
        ("FEISHU_APPROVER_OPEN_IDS", "审批人白名单 (open_id 逗号分隔，空=全员可审批)", False),
    ]),
    ("搜索/情报", [
        ("SERPER_API_KEY", "Serper API Key（主引擎）", True),
        ("TAVILY_API_KEY", "Tavily API Key（降级备用）", True),
    ]),
    ("语音识别 (火山引擎)", [
        ("VOLC_ASR_APPID", "App ID", True),
        ("VOLC_ASR_TOKEN", "Token", True),
        ("VOLC_ASR_RESOURCE_ID", "Resource ID", False),
    ]),
    ("地图 (高德)", [
        ("AMAP_API_KEY", "API Key", True),
        ("AMAP_BASE_URL", "Base URL", False),
    ]),
]


async def get_system_settings() -> dict[str, Any]:
    """返回当前系统配置，按分组组织，敏感字段已遮罩。"""
    cfg = _config_module._cfg

    groups = []
    for group_name, fields in CONFIG_GROUPS:
        items = []
        for key, label, sensitive in fields:
            raw = cfg(key, json_key=key)
            value = _mask_key(raw) if sensitive else (raw or "")
            items.append({
                "key": key,
                "label": label,
                "value": value,
                "sensitive": sensitive,
                "required": key in _MINIMAL_REQUIRED,
            })
        groups.append({"group": group_name, "fields": items})

    return {"groups": groups}


async def get_readiness() -> dict[str, Any]:
    """功能就绪度速查（纯本地配置读取，零网络调用）。

    供前端在各功能入口做前置拦截：主 LLM 未就绪时简历上传不可用、
    视觉未就绪时截图识别类功能不可用、飞书最小字段未齐时同步链路不可用。
    """
    from common.config import (
        get_missing_feishu_min_keys,
        get_missing_llm_keys,
        get_missing_vision_keys,
    )

    llm_missing = get_missing_llm_keys()
    vision_missing = get_missing_vision_keys()
    feishu_missing = get_missing_feishu_min_keys()

    return {
        "code": 0,
        "data": {
            "main_llm_ready": not llm_missing,
            "vision_ready": not vision_missing,
            "feishu_min_ready": not feishu_missing,
            "missing": {"llm": llm_missing, "vision": vision_missing, "feishu": feishu_missing},
        },
    }


# 保存后钩子的分组归属：键 → 变更后需要触发的动作
_FEISHU_WS_KEYS = {"FEISHU_APP_ID", "FEISHU_APP_SECRET"}
_CHAT_AGENT_KEYS = {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"}

# 允许清除的键白名单：只认配置分组里声明过的键，防止误删任意环境变量
_KNOWN_CONFIG_KEYS = {key for _, fields in CONFIG_GROUPS for key, _, _ in fields}


async def save_system_settings(payload: SettingsPayload) -> dict[str, Any]:
    """保存配置到 settings.json，并热注入运行时（os.environ + pydantic 单例原地更新）。

    支持清除语义：payload.__delete__ 指定的键从 settings.json 移除，注入的环境变量
    一并 pop，再由 load_dotenv 从 .env 重新填充、pydantic 单例回落 —— 即「清除后
    回落 .env（无则未配置）」。
    """

    def _save() -> tuple[dict[str, str], list[str]]:
        SETTINGS_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

        existing: dict = {}
        if SETTINGS_DATA_PATH.exists():
            try:
                existing = json.loads(SETTINGS_DATA_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        updates = {k: v for k, v in payload.model_dump(exclude_none=True).items() if v and str(v).strip()}
        delete_keys = [k for k in (payload.delete_keys or []) if k in _KNOWN_CONFIG_KEYS]
        existing.update(updates)
        for k in delete_keys:
            existing.pop(k, None)
        SETTINGS_DATA_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

        # 重载 common.config：模块级常量按新配置重算；模块尾部的 sync_settings_to_runtime()
        # 会把新值注入 os.environ 并原地更新 app.core.config.settings 单例（全模块即时生效）
        importlib.reload(_config_module)
        _config_module.sync_settings_to_runtime()

        # 🌟 清除回落：pop 掉此前注入的环境变量，再从 .env 重新填充（load_dotenv 只补空缺、
        # 不覆盖已有值，天然保持 settings.json > .env 优先级），最后让 pydantic 单例同步回落
        if delete_keys:
            for k in delete_keys:
                os.environ.pop(k, None)
            try:
                from dotenv import load_dotenv
                # settings.json 位于 backend/common/data/，向上三级即 backend/（.env 所在根）
                load_dotenv(dotenv_path=SETTINGS_DATA_PATH.parents[2] / ".env", override=False)
            except Exception:
                pass
            _config_module.sync_settings_to_runtime(reset_keys=delete_keys)

        return updates, delete_keys

    updates, delete_keys = await asyncio.to_thread(_save)
    updated_keys = set(updates.keys())
    deleted_keys = set(delete_keys)

    # 🌟 保存后钩子 1：飞书凭证变更（含清除）→ 用最新配置热重启 WebSocket 长连接
    ws_restarted: bool | None = None
    if (updated_keys | deleted_keys) & _FEISHU_WS_KEYS:
        try:
            from app.core.feishu_ws import restart_feishu_ws
            ws_restarted = restart_feishu_ws(asyncio.get_running_loop())
        except Exception:
            ws_restarted = False

    # 🌟 保存后钩子 2：LLM 配置变更（含清除）→ 重建 ChatAgent（未配置 Key 时自动跳过）
    agent_rebuilt = False
    if (updated_keys | deleted_keys) & _CHAT_AGENT_KEYS:
        try:
            from app.services.chat_agent import agent as chat_agent
            agent_rebuilt = await chat_agent.reinit_chat_agent()
        except Exception:
            agent_rebuilt = False

    # 诚实汇报热生效范围：仍有少量模块级常量（如火山 ASR 的 interview/router）需重启后读取
    msg_parts: list[str] = []
    if updated_keys:
        msg_parts.append(f"已保存 {len(updated_keys)} 个配置项，已即时生效")
    if deleted_keys:
        msg_parts.append(f"已清除 {len(deleted_keys)} 个配置项（回落 .env / 未配置）")
    if not msg_parts:
        return {"status": "ok", "message": "没有需要变更的配置项", "updated": [], "deleted": []}
    if (updated_keys | deleted_keys) & _FEISHU_WS_KEYS:
        msg_parts.append("飞书长连接已用最新配置重连" if ws_restarted else "⚠️ 飞书长连接未能自动重连，请重启后端")
    if (updated_keys | deleted_keys) & _CHAT_AGENT_KEYS:
        msg_parts.append("ChatAgent 已按最新配置重建" if agent_rebuilt else "ChatAgent 将在下次消息时按最新配置工作")
    if updated_keys & {"VOLC_ASR_APPID", "VOLC_ASR_TOKEN", "VOLC_ASR_RESOURCE_ID"}:
        msg_parts.append("语音识别配置需重启后端后生效")

    return {
        "status": "ok",
        "message": "；".join(msg_parts),
        "updated": sorted(updated_keys),
        "deleted": sorted(deleted_keys),
    }
