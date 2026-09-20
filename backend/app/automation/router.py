"""
自动驾驶与流转总路由（门面层 Facade）
====================================
本文件作为门面层（Facade），为保证 100% 向后兼容性，保持原有路由定义、前缀、导入路径与符号导出不变。
具体业务路由拆分为：
- app.automation.routes.control_router: 链路启动、终止、状态及实时日志流
- app.automation.routes.delivery_router: 岗位物料检查、自愈、审批放行与批量投递
- app.automation.routes.config_router: 自动驾驶全局配置、定时调度、节假日及日志
- app.automation.routes.jobs_router: 岗位快照呈现、失败重试、主动放弃与AI诊断
- app.automation.snapshot_service: 岗位快照数据聚合底层服务
"""
from fastapi import APIRouter

from app.automation.db import get_autopilot_config
from app.automation.full_auto import PLATFORM_CN, RAW_DB_PATH
from app.automation.routes.config_router import (
    ScheduleConfigBody,
)
from app.automation.routes.config_router import (
    router as config_router,
)
from app.automation.routes.control_router import (
    AbortRequest,
)
from app.automation.routes.control_router import (
    router as control_router,
)
from app.automation.routes.delivery_router import (
    _DELIVERY_BG_TASKS,
    AutoHealRequest,
    CheckMaterialsRequest,
    DeliverApprovedRequest,
    ResumeBatchRequest,
    ResumeRequest,
    _deliver_approved_worker,
    # 门面层向后兼容再导出：历史调用方/测试通过 automation_router.resume_workflow 直连
    resume_workflow,
    resume_workflow_batch,
)
from app.automation.routes.delivery_router import (
    router as delivery_router,
)
from app.automation.routes.jobs_router import (
    _RETRY_BG_TASKS,
    _RETRY_INITIAL_KEYS,
    DiagnoseFailureRequest,
    DismissFailedJobRequest,
    RetryFailedJobRequest,
    RetryJobRequest,
    jobs_snapshot,
)
from app.automation.routes.jobs_router import (
    router as jobs_router,
)
from app.automation.schemas import AutopilotConfigSchema
from app.automation.snapshot_service import _triage_classify

router = APIRouter()

# 聚合挂载所有子路由模块（保持扁平路由路径完全不变）
router.include_router(control_router)
router.include_router(delivery_router)
router.include_router(config_router)
router.include_router(jobs_router)

__all__ = [
    "router",
    "get_autopilot_config",
    "PLATFORM_CN",
    "RAW_DB_PATH",
    "AutopilotConfigSchema",
    "ResumeRequest",
    "ResumeBatchRequest",
    "DeliverApprovedRequest",
    "CheckMaterialsRequest",
    "AutoHealRequest",
    "AbortRequest",
    "ScheduleConfigBody",
    "RetryJobRequest",
    "DiagnoseFailureRequest",
    "DismissFailedJobRequest",
    "RetryFailedJobRequest",
    "_DELIVERY_BG_TASKS",
    "_deliver_approved_worker",
    "resume_workflow",
    "resume_workflow_batch",
    "_RETRY_BG_TASKS",
    "_RETRY_INITIAL_KEYS",
    "_triage_classify",
    "jobs_snapshot",
]
