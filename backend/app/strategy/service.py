"""Strategy Service Facade.

聚合底层的配置管理、Grill 追问、JD 能力报告、AI 靶向诊断服务。
保持 100% 向后兼容性，所有外部导入与测试 monkeypatch 均无感透传。
"""

import logging

import httpx
import requests

from app.core.config import settings
from app.core.feishu_client import feishu_client
from app.core.feishu_utils import get_tenant_access_token
from common.config import get_openai_client

# 核心常量与日志
logger = logging.getLogger("strategy_service")
logger.setLevel(logging.INFO)

CONTENT_TYPE_JSON = "application/json"
MARKDOWN_JSON_PREFIX = "```json"
MARKDOWN_PREFIX = "```"
ERR_AI_FORMAT = "AI 返回格式异常"

# 1. 配置管理与 SQLite / 飞书底稿同步
# 4. ATS 靶向诊断、微创手术、项目删减与经历折叠
from app.strategy.ai_diagnosis_service import (  # noqa: E402
    _parse_json_safely,
    ats_align_experience_service,
    compress_work_experience_service,
    filter_projects_service,
    generate_initial_draft_service,
    global_diagnosis_service,
)
from app.strategy.config_service import (  # noqa: E402
    RESUME_SAVE_FIELD_WHITELIST,
    _fetch_active_strategy_sync,
    _process_single_resume,
    _safe_extract_avatar_url,
    _safe_extract_text,
    _update_active_strategy_sync,
    activate_target_resume,
    delete_preference_service,
    delete_strategy_service,
    get_active_resume_text_async,
    get_active_strategy,
    get_all_strategy_configs,
    get_db_path,
    get_preferences_service,
    get_weights_service,
    save_strategy_config_service,
    update_active_strategy_in_db,
    update_weights_service,
    upsert_preference_service,
)

# 2.1 简历排版（自 grill_service 拆出，≤500 行治理）
from app.strategy.format_service import (  # noqa: E402
    format_markdown_service,
)

# 2. Grill 追问与基础模块联动
from app.strategy.grill_service import (  # noqa: E402
    _build_grill_context,
    _build_grill_messages,
    grill_experience_service,
    grill_experience_stream_service,
    grill_suggestion_service,
    predict_keyword_desc_service,
    sync_basic_module_service,
)

# 3. 全局 A 级 JD 能力画像报告
from app.strategy.jd_report_service import (  # noqa: E402
    generate_jd_report_service,
    get_global_jd_report,
    update_global_jd_report,
)

__all__ = [
    "requests",
    "httpx",
    "settings",
    "feishu_client",
    "get_tenant_access_token",
    "get_openai_client",
    "logger",
    "CONTENT_TYPE_JSON",
    "MARKDOWN_JSON_PREFIX",
    "MARKDOWN_PREFIX",
    "ERR_AI_FORMAT",
    "RESUME_SAVE_FIELD_WHITELIST",
    "_safe_extract_text",
    "_safe_extract_avatar_url",
    "_process_single_resume",
    "get_all_strategy_configs",
    "activate_target_resume",
    "get_db_path",
    "_fetch_active_strategy_sync",
    "get_active_strategy",
    "_update_active_strategy_sync",
    "update_active_strategy_in_db",
    "get_active_resume_text_async",
    "save_strategy_config_service",
    "delete_strategy_service",
    "get_preferences_service",
    "upsert_preference_service",
    "get_weights_service",
    "update_weights_service",
    "delete_preference_service",
    "_build_grill_context",
    "_build_grill_messages",
    "grill_experience_service",
    "grill_experience_stream_service",
    "grill_suggestion_service",
    "sync_basic_module_service",
    "format_markdown_service",
    "predict_keyword_desc_service",
    "generate_jd_report_service",
    "get_global_jd_report",
    "update_global_jd_report",
    "_parse_json_safely",
    "ats_align_experience_service",
    "filter_projects_service",
    "compress_work_experience_service",
    "global_diagnosis_service",
    "generate_initial_draft_service",
]
