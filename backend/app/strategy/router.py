"""Strategy Router Facade.

聚合所有子路由并提供向下兼容的路由导出、模型导出与 ChatOps 工具别名。
"""

import logging

from fastapi import APIRouter

# 2. 导入子路由
from app.strategy.routes.ai_router import (  # noqa: F401
    FillResumeFromMarkdownRequest,
    GenerateGreetingRequest,
)
from app.strategy.routes.ai_router import (
    router as ai_subrouter,
)
from app.strategy.routes.render_router import router as render_subrouter  # noqa: F401
from app.strategy.routes.rules_router import router as rules_subrouter  # noqa: F401
from app.strategy.routes.skill_agent_router import (  # noqa: F401
    SkillRewriteAndSaveRequest,
    TestSkillRewriteRequest,
    skill_rewrite_and_save_api,
)
from app.strategy.routes.skill_agent_router import (
    router as skill_agent_subrouter,
)
from app.strategy.routes.skill_artifacts_router import (  # noqa: F401
    router as skill_artifacts_subrouter,
)
from app.strategy.routes.upload_router import router as upload_subrouter  # noqa: F401

# 1. 导出所有 schemas
from app.strategy.schemas import (  # noqa: F401
    ActivateResumeRequest,
    ActiveStrategyResponse,
    AtsAlignRequest,
    CompressWorkRequest,
    DeleteStrategyRequest,
    FilterProjectsRequest,
    FormatMarkdownRequest,
    GlobalDiagnosisRequest,
    GrillExperienceRequest,
    GrillSuggestionRequest,
    InitialDraftRequest,
    PredictDescRequest,
    PreferenceUpsertRequest,
    PreviewPdfDirectRequest,
    ResetResumeRequest,
    ResumePdfRequest,
    SaveConfigRequest,
    SyncBasicModuleRequest,
    UpdateStrategyRequest,
    WeightsUpdateRequest,
)

logger = logging.getLogger("strategy_router")
logger.setLevel(logging.INFO)

# 3. 根路由实例
router = APIRouter(prefix="/api/strategy", tags=["Strategy Lab"])

# 4. 挂载子路由
router.include_router(rules_subrouter)
router.include_router(upload_subrouter)
router.include_router(render_subrouter)
router.include_router(ai_subrouter)
router.include_router(skill_agent_subrouter)
router.include_router(skill_artifacts_subrouter)

# 5. ChatOps 适配层函数（兼容 app.core.chatops_tools 动态导入）


async def global_diagnosis_service():
    """ChatOps 诊断别名：使用全局启用简历进行快速诊断"""
    from app.strategy.service import get_active_resume_text_async
    from app.strategy.service import (
        global_diagnosis_service as _diag_svc,
    )

    resume = await get_active_resume_text_async()
    payload = GlobalDiagnosisRequest(jd_text="综合互联网大厂通用高级岗位", full_resume_context=resume)
    return await _diag_svc(payload)


async def generate_greeting_and_save_service(job_id: str):
    """ChatOps 生成打招呼语别名"""
    from app.core.config import settings
    from app.core.feishu_client import feishu_client
    from app.strategy.routes.ai_router import (
        generate_greeting_and_save_api,
    )
    from app.strategy.service import get_active_resume_text_async

    resume = await get_active_resume_text_async()
    record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, job_id)
    fields = (record or {}).get("fields", {})
    jd = str(fields.get("岗位详情", ""))
    job_name = str(fields.get("岗位名称", ""))
    req = GenerateGreetingRequest(job_id=job_id, jd_text=jd, job_name=job_name, resume_text=resume)
    res = await generate_greeting_and_save_api(req)
    return res.get("data", {}).get("greeting", "")


async def skill_rewrite_and_save_service(job_id: str):
    """ChatOps 简历改写别名"""
    from app.core.config import settings
    from app.core.feishu_client import feishu_client
    from app.strategy.routes.skill_agent_router import (
        SkillRewriteAndSaveRequest,
        skill_rewrite_and_save_api,
    )

    record = await feishu_client.get_record(settings.FEISHU_TABLE_ID_JOBS, job_id)
    fields = (record or {}).get("fields", {})
    jd = str(fields.get("岗位详情", ""))
    job_name = str(fields.get("岗位名称", ""))
    req = SkillRewriteAndSaveRequest(job_id=job_id, jd_text=jd, job_name=job_name)
    return await skill_rewrite_and_save_api(req)


async def ats_align_service(job_id: str):
    """ChatOps ATS预检别名"""
    _ = job_id
    from app.strategy.service import (
        ats_align_experience_service,
        get_active_resume_text_async,
        get_global_jd_report,
    )

    resume = await get_active_resume_text_async()
    jd_report = await get_global_jd_report() or ""
    req = AtsAlignRequest(
        original_experience=resume[:500],
        jd_report_context=jd_report,
        full_resume_context=resume,
    )
    return await ats_align_experience_service(req)


__all__ = [
    "router",
    "global_diagnosis_service",
    "generate_greeting_and_save_service",
    "skill_rewrite_and_save_service",
    "ats_align_service",
    "SkillRewriteAndSaveRequest",
    "TestSkillRewriteRequest",
    "skill_rewrite_and_save_api",
]
