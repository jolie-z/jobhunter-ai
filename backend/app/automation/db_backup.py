"""
SQLite 核心库每日滚动热备（TODO.md 数据库治理清单第 7 项）。

设计：
- 用 SQLite 官方 VACUUM INTO 在线热备：读源写新文件，不阻塞业务连接，
  且产物天然完成碎片整理，quick_check 级一致（WAL 库安全，优于文件拷贝）。
- 备份对象：job_hunter.db（全系统单点业务库）、autopilot.db（配置/审批/日志）、
  sessions.db（会话状态）。两个 LangGraph checkpoint 库不备份——它们是可重建的
  运行时状态机断点，且体积大（166MB/73MB），日常快照性价比低。
- 保留策略：每个库默认保留最近 7 份，超出自动清理。
- 结果落 automation_logs（task_id=backup_daily_时间戳，防主键冲突）。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = BACKEND_ROOT / "data" / "backups"

# (源库绝对路径, 备份文件名前缀)
DEFAULT_TARGETS: list[tuple[Path, str]] = [
    (BACKEND_ROOT / "data" / "job_hunter.db", "job_hunter"),
    (BACKEND_ROOT / "autopilot.db", "autopilot"),
    (BACKEND_ROOT / "data" / "sessions.db", "sessions"),
]

DEFAULT_RETENTION = 7


def _prune_old_snapshots(backup_dir: Path, prefix: str, retention: int) -> int:
    """同名前缀只保留最近 retention 份，返回删除数。"""
    snaps = sorted(backup_dir.glob(f"{prefix}_*.db"))
    removed = 0
    for old in snaps[:-retention] if retention > 0 else snaps:
        try:
            old.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("📦 清理过期快照失败 %s: %s", old.name, exc)
    return removed


def run_daily_backup(
    targets: list[tuple[Path, str]] | None = None,
    backup_dir: Path | None = None,
    retention: int = DEFAULT_RETENTION,
) -> dict[str, Any]:
    """执行一轮热备。单库失败互相隔离，绝不拖垮整轮。"""
    targets = targets or DEFAULT_TARGETS
    backup_dir = backup_dir or BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    results: list[dict[str, Any]] = []
    for src, prefix in targets:
        entry: dict[str, Any] = {"name": prefix, "source": str(src), "status": "skipped"}
        if not src.exists():
            entry["status"] = "skipped"
            entry["detail"] = "源库不存在"
            results.append(entry)
            continue
        dest = backup_dir / f"{prefix}_{stamp}.db"
        try:
            src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
            try:
                # VACUUM INTO 不允许目标已存在；同分钟重复运行时覆盖旧产物
                if dest.exists():
                    dest.unlink()
                src_conn.execute("VACUUM INTO ?", (str(dest),))
            finally:
                src_conn.close()
            check = sqlite3.connect(str(dest)).execute("PRAGMA quick_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"快照完整性异常: {check}")
            entry.update(
                status="ok",
                file=str(dest),
                size_mb=round(dest.stat().st_size / 1024 / 1024, 2),
            )
            entry["pruned"] = _prune_old_snapshots(backup_dir, prefix, retention)
        except Exception as exc:  # 单库失败隔离
            entry.update(status="failed", detail=str(exc))
            logger.error("📦 [%s] 备份失败: %s", prefix, exc)
        results.append(entry)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    summary = "；".join(
        f"{r['name']}:{r['status']}" + (f"({r.get('size_mb')}MB)" if r.get("size_mb") else "")
        for r in results
    )
    logger.info("📦 每日热备完成 %s/%s —— %s", ok_count, len(results), summary)
    return {"ok": ok_count, "total": len(results), "results": results, "summary": summary}


def run_scheduled_backup() -> dict[str, Any]:
    """调度入口，结果落 automation_logs。"""
    from .db import append_autopilot_log, complete_autopilot_log

    task_id = f"backup_daily_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    append_autopilot_log(task_id, "running", 0, "每日热备启动")
    try:
        outcome = run_daily_backup()
        details = outcome["summary"]
        status = "completed" if outcome["ok"] == outcome["total"] else "partial"
    except Exception as exc:  # 防御：备份失败绝不影响调度器主循环
        details = f"备份异常: {exc}"
        status = "failed"
        logger.exception("📦 每日热备执行异常")
    complete_autopilot_log(task_id, status, 0, details)
    return {"status": status, "details": details}


async def run_scheduled_backup_async() -> dict[str, Any]:
    """供 APScheduler 注册的异步包装：SQLite 阻塞操作放线程池，不卡事件循环。"""
    import asyncio

    return await asyncio.to_thread(run_scheduled_backup)
