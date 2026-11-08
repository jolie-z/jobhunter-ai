
from pydantic import BaseModel, Field


class SettingsPayload(BaseModel):
    """系统配置保存载荷 — 按分组覆盖所有可配置字段。"""

    # 🌟 待清除的配置键（页面「清除」按钮）：从 settings.json 删除并回落 .env / 未配置。
    # alias 供前端传 "__delete__"；exclude 保证它不会混进 model_dump 的保存值里
    delete_keys: list[str] | None = Field(default=None, alias="__delete__", exclude=True)

    # A. LLM 大模型（主力）
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str | None = None

    # A1. 视觉（图片识别）通道：模型名是硬前提；Key/Base URL 留空则复用主通道
    VISION_MODEL: str | None = None
    VISION_API_KEY: str | None = None
    VISION_BASE_URL: str | None = None

    # A2. 数据清洗专用 LLM
    CLEANER_LLM_API_KEY: str | None = None
    CLEANER_LLM_BASE_URL: str | None = None
    CLEANER_LLM_MODEL: str | None = None
    CLEANER_VISION_MODEL: str | None = None


    # B. 飞书
    FEISHU_APP_ID: str | None = None
    FEISHU_APP_SECRET: str | None = None
    FEISHU_APP_TOKEN: str | None = None
    FEISHU_ALERT_RECEIVE_ID: str | None = None
    FEISHU_TABLE_ID_JOBS: str | None = None
    FEISHU_TABLE_ID_RESUMES: str | None = None
    FEISHU_TABLE_ID_INTERVIEW_REPORTS: str | None = None
    FEISHU_TABLE_ID_INTERVIEW_SUMMARY: str | None = None
    FEISHU_TABLE_ID_INTERVIEW_REAL: str | None = None
    FEISHU_APPROVER_OPEN_IDS: str | None = None

    # C. 搜索/情报（博查国内直连主引擎，Serper / Tavily 境外网络备用）
    BOCHA_API_KEY: str | None = None
    SERPER_API_KEY: str | None = None
    TAVILY_API_KEY: str | None = None

    # D. 语音识别（火山引擎）
    VOLC_ASR_APPID: str | None = None
    VOLC_ASR_TOKEN: str | None = None
    VOLC_ASR_RESOURCE_ID: str | None = None

    # F. 地图（高德）
    AMAP_API_KEY: str | None = None
    AMAP_BASE_URL: str | None = None
