
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
    VISION_MODEL: str | None = None

    # A1. 视觉（图片识别）独立通道：主网关不支持图片输入时指向支持 VL 的供应商
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

    # C. 搜索/情报（Serper 主引擎，Tavily 降级备用）
    SERPER_API_KEY: str | None = None
    TAVILY_API_KEY: str | None = None

    # D. 语音识别（火山引擎）
    VOLC_ASR_APPID: str | None = None
    VOLC_ASR_TOKEN: str | None = None
    VOLC_ASR_RESOURCE_ID: str | None = None

    # F. 地图（高德）
    AMAP_API_KEY: str | None = None
    AMAP_BASE_URL: str | None = None
