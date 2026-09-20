import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    HttpUrl,
    computed_field,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# ==========================================
# 🌐 网络与环境变量配置
# ==========================================
# 飞书直连白名单：防止代理劫持 SSL 握手失败
os.environ.setdefault("NO_PROXY", "open.feishu.cn,feishu.cn")
os.environ.setdefault("no_proxy", "open.feishu.cn,feishu.cn")

# ==========================================
# 📂 全局路径常量配置
# ==========================================
# 假设 config.py 位于 new_jobhunter/backend/app/core/
# 则 PROJECT_ROOT 指向 new_jobhunter/backend/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BASE_DIR = PROJECT_ROOT

# 数据与数据库路径
SETTINGS_DATA_PATH = BASE_DIR / "data" / "settings.json"
DB_PATH = BASE_DIR.parent / "data" / "job_hunter.db"

def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore"
    )
    API_V1_STR: str = "/api/v1"
    FRONTEND_HOST: str = "http://localhost:5173"
    FRONTEND_BASE_URL: str = "http://localhost:3000"  # Next.js dev server URL for Playwright PDF rendering
    BACKEND_BASE_URL: str = "http://127.0.0.1:8000"  # 后端对外地址（简历照片代理等回传前端的 URL 拼接用）
    # 公网直达域名：面试锦囊 / 简历 PDF 直达链接回写飞书时拼接用（需公网可达，如内网穿透域名）
    TUNNEL_DOMAIN: str = ""
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str = "JobHunter"
    SENTRY_DSN: HttpUrl | None = None

    # Feishu Configuration
    FEISHU_APP_ID: str | None = None
    FEISHU_APP_SECRET: str | None = None
    FEISHU_APP_TOKEN: str | None = None
    # 会话过期预警接收人（飞书 open_id，战报/预警兜底接收人；页面「飞书」分组可配）
    FEISHU_ALERT_RECEIVE_ID: str | None = None
    # ChatOps 审批门禁白名单（open_id 逗号分隔；空=全员可审批，单人自用向后兼容，Q-M9-4）
    FEISHU_APPROVER_OPEN_IDS: str | None = None
    FEISHU_TABLE_ID_JOBS: str | None = None

    FEISHU_TABLE_ID_RESUMES: str | None = None
    FEISHU_TABLE_ID_INTERVIEW_REPORTS: str | None = None
    FEISHU_TABLE_ID_INTERVIEW_SUMMARY: str | None = None
    FEISHU_TABLE_ID_INTERVIEW_REAL: str | None = None

    # === LLM 大模型通用配置 (OpenAI / 小米 Mimo) ===
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_MODEL: str | None = None
    VISION_MODEL: str | None = None
    # 视觉（图片识别）独立通道：主网关不支持图片输入时，可单独指到支持 VL 的供应商
    VISION_API_KEY: str | None = None
    VISION_BASE_URL: str | None = None

    CLEANER_LLM_API_KEY: str | None = None
    CLEANER_LLM_BASE_URL: str | None = None
    CLEANER_LLM_MODEL: str | None = None
    CLEANER_VISION_MODEL: str | None = None

    # === 其他第三方服务 ===
    TAVILY_API_KEY: str | None = None

    # === 高德地图 Configuration (used by map_service 地理编码/导航直达) ===
    AMAP_API_KEY: str | None = None
    AMAP_BASE_URL: str | None = None

    # === Volc Engine STT Configuration ===
    VOLC_ASR_APPID: str | None = None
    VOLC_ASR_TOKEN: str | None = None
    VOLC_ASR_RESOURCE_ID: str | None = None


settings = Settings()
