"""初评淘汰回写 raw_jobs 服务层（2026-11-02 审计 P1-6）。

背景：现行 wave 链初评 F 只写飞书「跟进状态/评级」、不再回写本地 raw_jobs
（老链路 step3_ai_evaluator 曾回写），导致回收站「确认淘汰」的归档 guard
（processor.confirm_reject 的 REJECTED_STATUSES 校验）撞上 process_status='已同步'
必然 409，淘汰岗永远清不掉。

本服务把淘汰结论回写 raw 生命周期（process_status=REJECT_AI），匹配键=job_link
（岗位链接字段中的网页 URL，与 confirm-reject 实测同构；raw 侧存量以网页 URL 存档，
feishu:// 仅 5 条历史残留）。单条 UPDATE 白名单守卫（process_status IN
EVAL_REJECT_WRITABLE_STATUSES，词表单一事实源在 app/core/process_status，CR-R3-P2
下沉）：仅初评前/流转中的归档态可改写，同链接多行一次全部处理，返回 rowcount 即
实际回写行数；淘汰终态与投递后段不在白名单、绝不触碰。幂等：已回写过的行不会被
再次改写。放服务层而非路由层，避免 wave_pipeline → jobs_router 的反向依赖
（Opus CR-R1-P2）。
"""
import logging
import os
import sqlite3
from pathlib import Path

from app.core.db_paths import job_hunter_db_path
from app.core.process_status import EVAL_REJECT_WRITABLE_STATUSES, REJECT_AI

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # services/ → automation/ → app/ → backend/


def sync_eval_reject_to_raw(job_link: str, reject_reason: str) -> int:
    """把初评淘汰结论回写 raw_jobs（幂等）。返回实际回写行数（rowcount，0=未回写）。

    行不存在 / 链接为空 / 无白名单内可写行 → 0（不视为错误，调用方仅记日志）。
    """
    link = str(job_link or "").strip()
    if not link:
        return 0
    placeholders = ",".join("?" for _ in EVAL_REJECT_WRITABLE_STATUSES)
    conn = sqlite3.connect(job_hunter_db_path(os.path.join(_PROJECT_ROOT, "data", "job_hunter.db")), timeout=30.0)
    try:
        cur = conn.execute(
            f"UPDATE raw_jobs SET process_status = ?, reject_reason = ? "
            f"WHERE job_link = ? AND process_status IN ({placeholders})",
            (REJECT_AI, str(reject_reason or "")[:200], link, *EVAL_REJECT_WRITABLE_STATUSES),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
