"""
全链路全自动编排器（门面层 Facade）
==================================

把已实现的各代码块串成一条全自动链路：
    平台抓取(scrape_runner) → 规则清洗(step1) → 飞书推送(step2)
    → 捞新线索(feishu) → AI初评/深评/改写/欢迎语/投递(graph_runner)

本文件作为门面层（Facade），为保证 100% 向后兼容性，保持原有导入路径与符号导出不变，
具体逻辑拆分为：
- app.automation.scrape_runner: 平台抓取阶段与参数推导（含 running_platform_tasks, _reap_orphan_scrapers, 本轮放弃新派发以避免并发超抓, not abort_mod.is_platform_aborted(p), 已按指令终止）
- app.automation.graph_runner: LangGraph 状态机单/多岗位流转
- app.automation.link_precheck: 岗位链接预检与有效批次构建
- app.automation.pipeline_orchestrator: 全链路生命周期与总编排
"""


import os

from app.automation.graph_runner import (
    _NODE_STAGE_MAP,
    _build_job_states,
    _run_jobs_through_graph,
    _run_single_job_graph,
    run_single_job_pipeline_async,
)
from app.automation.link_precheck import (
    _build_checked_batch,
    build_checked_batch,
)
from app.automation.pipeline_orchestrator import (
    _execute_pipeline,
    run_full_auto_pipeline,
)
from app.automation.scrape_runner import (
    _derive_search_from_config,
    _execute_scrape_only,
    _reap_orphan_scrapers,
    execute_pipeline_scrape,
    run_scrape_stage_only,
)

# 原始岗位数据库路径（供全局各模块与测试补丁统一访问）
RAW_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "job_hunter.db"
)

# 平台 key → 中文展示名（与 raw_jobs.platform / 飞书「招聘平台」取值一致）
PLATFORM_CN = {
    "boss": "BOSS直聘",
    "liepin": "猎聘",
    "51job": "51job",
    "zhilian": "智联招聘",
    "xiaohongshu": "小红书",
}

__all__ = [
    "RAW_DB_PATH",
    "PLATFORM_CN",
    "_derive_search_from_config",
    "_reap_orphan_scrapers",
    "execute_pipeline_scrape",
    "run_scrape_stage_only",
    "_execute_scrape_only",
    "_build_job_states",
    "_NODE_STAGE_MAP",
    "_run_jobs_through_graph",
    "_run_single_job_graph",
    "run_single_job_pipeline_async",
    "_build_checked_batch",
    "build_checked_batch",
    "run_full_auto_pipeline",
    "_execute_pipeline",
]
