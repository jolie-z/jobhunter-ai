"""全链路指挥中心 API 路由 Facade.

聚合底层的抓取配置、飞书连通性探针、AI初评与基准简历、以及打招呼/审批/自动投递配置。
"""

import logging

from fastapi import APIRouter

from app.pipeline.routes.delivery_config_router import (  # noqa: F401
    DeliveryConfigBody,
    GreetingConfigBody,
    ReviewConfigBody,
)
from app.pipeline.routes.delivery_config_router import (
    router as delivery_config_subrouter,
)
from app.pipeline.routes.eval_config_router import (  # noqa: F401
    ActivateResumeBody,
    EvalConfigBody,
    EvalPreferenceBody,
    RewriteConfigBody,
    SetMassApplyResumeBody,
)
from app.pipeline.routes.eval_config_router import (
    router as eval_config_subrouter,
)
from app.pipeline.routes.feishu_status_router import (  # noqa: F401
    _PROJECT_ROOT,
    AUTOPILOT_DB,
    DB_PATH,
    FeishuConfigBody,
    _get_active_resume_meta_cached,
)
from app.pipeline.routes.feishu_status_router import (
    router as feishu_status_subrouter,
)
from app.pipeline.routes.scrape_router import (  # noqa: F401
    MAX_KEYWORD_QUEUE,
    ArchiveItem,
    KeywordItem,
    LaunchPlatformBody,
    ResetConditionBody,
    RunScrapeOnlyBody,
    ScrapeConfigBody,
)
from app.pipeline.routes.scrape_router import (
    router as scrape_subrouter,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline Command Center"])

# 挂载子路由
router.include_router(scrape_subrouter)
router.include_router(feishu_status_subrouter)
router.include_router(eval_config_subrouter)
router.include_router(delivery_config_subrouter)

__all__ = [
    "router",
    "DB_PATH",
    "AUTOPILOT_DB",
    "_PROJECT_ROOT",
    "MAX_KEYWORD_QUEUE",
    "_get_active_resume_meta_cached",
    "KeywordItem",
    "ScrapeConfigBody",
    "RunScrapeOnlyBody",
    "LaunchPlatformBody",
    "ArchiveItem",
    "ResetConditionBody",
    "FeishuConfigBody",
    "EvalConfigBody",
    "EvalPreferenceBody",
    "ActivateResumeBody",
    "SetMassApplyResumeBody",
    "RewriteConfigBody",
    "GreetingConfigBody",
    "ReviewConfigBody",
    "DeliveryConfigBody",
]
