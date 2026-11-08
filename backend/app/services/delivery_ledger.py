"""投递失败台账任务侧门面（2026-11-02 拆分子任务）。

tasks 层（executor/wave_pipeline）此前直接 import app.automation.run_snapshot——
tasks→automation 的反向依赖（Feature Envy 审计项）。本门面把任务侧常用的
step 常量与台账写入收敛到 services 层；run_snapshot 仍是存储本体（内存+落盘）。

CR-Split-R1-P2 修正：STEP_RESUME_GREETING 改为从 run_snapshot 单点导入转发
（消除常量双份定义）；显式签名替代 *args/**kwargs。
"""
from app.automation.run_snapshot import record_delivery_failure as _record, STEP_RESUME_GREETING  # noqa: F401

__all__ = ["STEP_RESUME_GREETING", "record_delivery_failure"]


def record_delivery_failure(
    job_id: str,
    error: str = "",
    step: str = "自动投递阶段",
    company: str = "",
    job_name: str = "",
    platform: str = "",
    job_url: str = "",
    grade: str = "",
) -> None:
    """透传 run_snapshot.record_delivery_failure（签名与语义不变）。"""
    return _record(job_id, error, step=step, company=company, job_name=job_name,
                   platform=platform, job_url=job_url, grade=grade)
