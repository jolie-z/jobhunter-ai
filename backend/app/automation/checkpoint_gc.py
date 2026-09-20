"""
LangGraph checkpoint 库垃圾回收（GC）。

背景：AsyncSqliteSaver 每个 super-step 全量写入 checkpoints/writes 两张表，
流水线一轮几十个 step，且 LangGraph 无内置清理策略，库文件只增不减
（backend/langgraph_checkpoints.db 曾膨胀到 166MB）。

安全性设计（对应 2026-09-05 三方质检结论，缺一不可）：
1. 绝不 CAST(checkpoint_id AS INTEGER)：checkpoint_id 是 UUIDv6 十六进制串，
   CAST 遇到字母即截断、全库恒等于 1，会导致整库被误删。
   本模块用 UUIDv6 时间戳数学换算（微秒级，已与 blob 内 ts 字段对拍验证），
   并对每个候选 thread 再解码 checkpoint blob 里的 ts 做二次核对，两者不一致即保护。
2. 只删「最新 checkpoint 已超期」的 thread，且按 thread 整体级联删除
   （writes 先于 checkpoints），绝不按行删、不破坏 parent 链。
3. 保护三层：
   a. pending_delivery_pool 中 parked_at 在宽限期内的待审批 thread（thread_id=record_id）；
   b. 流水线运行中（pipeline_latest_run.running=1）时整轮中止，绝不与运行中的状态机并发；
   c. 任何解析失败（msgpack 解码/时间换算失败）的 thread 一律保护并告警，绝不猜测。
4. 空间回收：先 PRAGMA wal_checkpoint(TRUNCATE) 再 VACUUM，且仅在确有删除时执行；
   连接全程 isolation_level=None（autocommit），避免 VACUUM 撞上隐式事务。

覆盖目标：
- backend/langgraph_checkpoints.db   流水线断点，保留 14 天（审批窗口足够）
- backend/data/agent_chat_checkpoints.db  ChatAgent 对话历史，保留 90 天
- backend/data/agent_chat_memory.db  不回收（飞书 Agent 记忆，仅数 KB，无膨胀风险）
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# UUIDv6 与 Unix 纪元之间的秒差（1582-10-15 格里高利历 → 1970-01-01）
_UUID6_EPOCH_OFFSET_S = 12219292800

# 待审批岗位保护宽限期：parked_at 在此窗口内的 thread 强制保留；
# 超期仍停在停车场视为僵尸记录，对应 thread 可被回收（会打告警日志提示清理池）
PENDING_GRACE_DAYS = 30

# 流水线 running 标记的保鲜期：超过该时长仍为 running 视为异常残留，不再阻塞 GC
RUNNING_STALE_HOURS = 24

# DELETE ... IN 的分批大小
_CHUNK = 500


@dataclass
class GCTarget:
    """单个 checkpoint 库的回收策略。"""

    path: Path
    keep_days: int
    label: str
    # 流水线类库才需要 pending_delivery_pool / running 保护
    pipeline_protections: bool = True


@dataclass
class GCResult:
    """单个库的回收结果统计。"""

    label: str
    db: str
    skipped_reason: str = ""
    threads_total: int = 0
    threads_deleted: int = 0
    checkpoints_deleted: int = 0
    writes_deleted: int = 0
    protected: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.skipped_reason:
            return f"[{self.label}] 跳过: {self.skipped_reason}"
        reclaimed = (self.bytes_before - self.bytes_after) / 1024 / 1024
        return (
            f"[{self.label}] thread {self.threads_deleted}/{self.threads_total} 已回收"
            f"（checkpoint {self.checkpoints_deleted} 行 / writes {self.writes_deleted} 行），"
            f"保护 {self.protected} 个，文件 {self.bytes_before / 1024 / 1024:.1f}MB"
            f" → {self.bytes_after / 1024 / 1024:.1f}MB（释放 {reclaimed:.1f}MB）"
        )


def _unpack_blob(blob: bytes) -> dict[str, Any] | None:
    """兼容 ormsgpack（venv 实际依赖）与 msgpack 两种解码器。失败返回 None。"""
    for mod_name, kwargs in (("ormsgpack", {}), ("msgpack", {"strict_map_key": False})):
        try:
            mod = __import__(mod_name)
        except ImportError:
            continue
        try:
            data = mod.unpackb(blob, **kwargs)
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _parse_iso_ts(value: Any) -> datetime | None:
    """解析 ISO 时间串为带时区 datetime；兼容 'Z' 后缀与 naive 本地时间。失败返回 None。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def _uuid6_datetime(checkpoint_id: str) -> datetime | None:
    """从 UUIDv6 形式的 checkpoint_id 换算 UTC 时间（微秒级，已与 blob ts 对拍验证）。

    非法/非 v6 格式（如兜底路径用 uuid4 生成的 thread）返回 None，由调用方走保护路径。
    """
    h = str(checkpoint_id).replace("-", "")
    if len(h) != 32:
        return None
    try:
        if int(h[12:13], 16) != 6:  # version nibble 必须是 6
            return None
        time_high = int(h[0:8], 16)
        time_mid = int(h[8:12], 16)
        time_low = int(h[13:16], 16)
        ts_100ns = (time_high << 28) | (time_mid << 12) | time_low
        local_tz = datetime.now().astimezone().tzinfo
        return datetime.fromtimestamp(ts_100ns / 1e7 - _UUID6_EPOCH_OFFSET_S, tz=local_tz)
    except (ValueError, OverflowError, OSError):
        return None


def _latest_rows(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """每个 thread 取字符串字典序最大的 checkpoint_id。

    UUIDv6 定长前缀（time_high+time_mid）保证字典序=时间序，已在生产库验证。
    """
    return conn.execute(
        "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id"
    ).fetchall()


def _blob_ts_of(conn: sqlite3.Connection, thread_id: str, checkpoint_id: str) -> datetime | None:
    """读取指定 checkpoint blob 并解出权威 ts。任何失败返回 None。"""
    row = conn.execute(
        "SELECT checkpoint FROM checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
        (thread_id, checkpoint_id),
    ).fetchone()
    if not row or not row[0]:
        return None
    data = _unpack_blob(row[0])
    if data is None:
        return None
    return _parse_iso_ts(data.get("ts"))


def _select_expired_threads(
    conn: sqlite3.Connection, cutoff: datetime
) -> tuple[set[str], set[str]]:
    """返回 (超期可删 thread 集合, 因解析失败被保护的 thread 集合)。

    双保险：UUIDv6 数学换算先粗筛，候选者再用 blob 内 ts 复核；
    两条路径结论不一致或任一失败 → 保护该 thread。
    """
    candidates: set[str] = set()
    unparsable: set[str] = set()
    for thread_id, max_cid in _latest_rows(conn):
        math_ts = _uuid6_datetime(max_cid)
        blob_ts = _blob_ts_of(conn, thread_id, max_cid)
        if math_ts is None or blob_ts is None:
            unparsable.add(thread_id)
            continue
        if math_ts < cutoff and blob_ts < cutoff:
            candidates.add(thread_id)
    return candidates, unparsable


def _load_pending_protections(autopilot_db: Path, grace_days: int) -> tuple[set[str], list[str]]:
    """从 pending_delivery_pool 读取保护名单。

    返回 (强制保护的 thread 集合, 停车超期的僵尸 record_id 列表)。
    thread_id = 飞书 record_id（scheduler.run_pipeline_for_job 用 record_id 作 thread_id）。
    """
    protected: set[str] = set()
    stale: list[str] = []
    if not autopilot_db.exists():
        return protected, stale
    now = datetime.now().astimezone()
    conn = sqlite3.connect(f"file:{autopilot_db}?mode=ro", uri=True)
    try:
        for record_id, parked_at in conn.execute(
            "SELECT record_id, parked_at FROM pending_delivery_pool"
        ):
            parked_dt = _parse_iso_ts(parked_at)
            if parked_dt is None:
                # 时间字段异常 → 保守视为在保护期内
                protected.add(record_id)
                continue
            if now - parked_dt <= timedelta(days=grace_days):
                protected.add(record_id)
            else:
                stale.append(record_id)
    finally:
        conn.close()
    return protected, stale


def _pipeline_running_block_reason(job_hunter_db: Path) -> str:
    """检查流水线是否运行中。返回空串表示空闲，否则返回中止原因。"""
    if not job_hunter_db.exists():
        return ""
    conn = sqlite3.connect(f"file:{job_hunter_db}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT running, updated_at FROM pipeline_latest_run WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return ""
    updated = _parse_iso_ts(row[1])
    if updated and datetime.now().astimezone() - updated > timedelta(hours=RUNNING_STALE_HOURS):
        logger.warning(
            "🧹 pipeline_latest_run.running=1 但 updated_at 已超过 %s 小时，视为异常残留标记，不阻塞 GC",
            RUNNING_STALE_HOURS,
        )
        return ""
    return "流水线运行中（pipeline_latest_run.running=1），为避免与状态机并发，本轮 GC 中止"


def _chunked(items: list[str], size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _gc_one_target(target: GCTarget, protected: set[str], cutoff: datetime, dry_run: bool) -> GCResult:
    result = GCResult(label=target.label, db=str(target.path))
    if not target.path.exists():
        result.skipped_reason = "库文件不存在"
        return result

    result.bytes_before = target.path.stat().st_size
    conn = sqlite3.connect(str(target.path), isolation_level=None)
    try:
        expired, unparsable = _select_expired_threads(conn, cutoff)
        result.threads_total = conn.execute(
            "SELECT COUNT(DISTINCT thread_id) FROM checkpoints"
        ).fetchone()[0]
        result.protected = len(unparsable) + len(expired & protected)
        result.warnings.extend(
            f"thread 最新 checkpoint 时间戳解析失败，已保护: {tid}"
            for tid in sorted(unparsable - protected)
        )
        to_delete = sorted(expired - protected)
        if not to_delete:
            result.bytes_after = result.bytes_before
            return result

        # dry-run 与真实删除同构分批：SQLite 老版本（<3.32）默认上限 999 个绑定变量，
        # 超大批量时一次性拼占位符会让预演分支报 too many SQL variables
        if dry_run:
            result.threads_deleted = len(to_delete)
            for chunk in _chunked(to_delete):
                ph = ",".join("?" * len(chunk))
                result.checkpoints_deleted += conn.execute(
                    f"SELECT COUNT(*) FROM checkpoints WHERE thread_id IN ({ph})",
                    chunk,
                ).fetchone()[0]
                result.writes_deleted += conn.execute(
                    f"SELECT COUNT(*) FROM writes WHERE thread_id IN ({ph})",
                    chunk,
                ).fetchone()[0]
            result.bytes_after = result.bytes_before
            return result

        # 按 thread 整体级联删除：writes 先于 checkpoints
        for chunk in _chunked(to_delete):
            ph = ",".join("?" * len(chunk))
            cur = conn.execute(f"DELETE FROM writes WHERE thread_id IN ({ph})", chunk)
            result.writes_deleted += cur.rowcount
            cur = conn.execute(f"DELETE FROM checkpoints WHERE thread_id IN ({ph})", chunk)
            result.checkpoints_deleted += cur.rowcount
        result.threads_deleted = len(to_delete)

        # SQLite 删除不回收文件空间，须执行 VACUUM 整理页面，再截断 WAL 彻底释放磁盘空间（autocommit 连接，无隐式事务）
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result.bytes_after = target.path.stat().st_size
        return result
    finally:
        conn.close()


def run_gc(
    dry_run: bool = True,
    targets: list[GCTarget] | None = None,
    job_hunter_db: Path | None = None,
    autopilot_db: Path | None = None,
    grace_days: int = PENDING_GRACE_DAYS,
) -> list[GCResult]:
    """执行一轮 GC。默认 dry_run=True 只统计不删除；调度任务传 dry_run=False。"""
    if targets is None:
        targets = [
            GCTarget(BACKEND_ROOT / "langgraph_checkpoints.db", 14, "流水线checkpoint"),
            GCTarget(
                BACKEND_ROOT / "data" / "agent_chat_checkpoints.db",
                90,
                "ChatAgent对话checkpoint",
                pipeline_protections=False,
            ),
        ]
    job_hunter_db = Path(job_hunter_db or BACKEND_ROOT / "data" / "job_hunter.db")
    autopilot_db = Path(autopilot_db or BACKEND_ROOT / "autopilot.db")

    # pending/running 保护只对流水线类目标生效；聊天库的活跃会话天然由保留窗口覆盖
    need_pipeline_guard = any(t.pipeline_protections for t in targets)
    pending_protected: set[str] = set()
    stale_parked: list[str] = []
    if need_pipeline_guard:
        pending_protected, stale_parked = _load_pending_protections(autopilot_db, grace_days)
        if stale_parked:
            logger.warning(
                "🧹 pending_delivery_pool 中 %s 条记录停车超过 %s 天（如 %s），"
                "视为僵尸记录，其 thread 不再强制保护；建议清理待投递池",
                len(stale_parked), grace_days, stale_parked[:3],
            )
        running_reason = _pipeline_running_block_reason(job_hunter_db)
        if running_reason:
            # 流水线类全部中止，聊天类照常
            results: list[GCResult] = []
            for target in targets:
                if target.pipeline_protections:
                    logger.info("🧹 [%s] 跳过: %s", target.label, running_reason)
                    results.append(
                        GCResult(label=target.label, db=str(target.path), skipped_reason=running_reason)
                    )
                else:
                    cutoff = datetime.now().astimezone() - timedelta(days=target.keep_days)
                    results.append(_gc_one_target(target, set(), cutoff, dry_run))
            return results

    results = []
    for target in targets:
        cutoff = datetime.now().astimezone() - timedelta(days=target.keep_days)
        guard = pending_protected if target.pipeline_protections else set()
        try:
            result = _gc_one_target(target, guard, cutoff, dry_run)
        except sqlite3.Error as exc:
            result = GCResult(label=target.label, db=str(target.path), skipped_reason=f"数据库错误: {exc}")
            logger.error("🧹 [%s] GC 失败: %s", target.label, exc)
        results.append(result)
        suffix = "（dry-run 预演，未实际删除）" if dry_run and not result.skipped_reason else ""
        logger.info("🧹 %s%s", result.summary(), suffix)
    return results


def run_scheduled_gc() -> dict[str, Any]:
    """调度入口（真实删除），结果落 automation_logs。task_id 带时间戳避免撞主键。"""
    from datetime import datetime as _dt

    from .db import append_autopilot_log, complete_autopilot_log

    task_id = f"checkpoint_gc_{_dt.now().strftime('%Y%m%d_%H%M%S')}"
    append_autopilot_log(task_id, "running", 0, "定时 GC 启动")
    try:
        results = run_gc(dry_run=False)
        details = "；".join(r.summary() for r in results)
        status = "completed"
    except Exception as exc:  # 防御：GC 失败绝不能影响调度器主循环
        details = f"GC 异常: {exc}"
        status = "failed"
        logger.exception("🧹 checkpoint GC 执行异常")
    complete_autopilot_log(task_id, status, 0, details)
    return {"status": status, "details": details}


async def run_scheduled_gc_async() -> dict[str, Any]:
    """供 APScheduler 注册的异步包装：SQLite 阻塞操作放线程池，不卡事件循环。"""
    import asyncio

    return await asyncio.to_thread(run_scheduled_gc)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LangGraph checkpoint 库垃圾回收")
    parser.add_argument("--now", action="store_true", help="真实执行删除（默认 dry-run 预演）")
    parser.add_argument(
        "--keep-days", type=int, default=None, help="临时覆盖流水线库保留天数（默认 14）"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cli_targets = None
    if args.keep_days:
        cli_targets = [
            GCTarget(BACKEND_ROOT / "langgraph_checkpoints.db", args.keep_days, "流水线checkpoint"),
            GCTarget(
                BACKEND_ROOT / "data" / "agent_chat_checkpoints.db",
                90,
                "ChatAgent对话checkpoint",
                pipeline_protections=False,
            ),
        ]
    run_gc(dry_run=not args.now, targets=cli_targets)
