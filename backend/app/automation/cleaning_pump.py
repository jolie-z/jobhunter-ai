"""
抓取期流式清洗泵
================
全自动链路原先是「所有平台抓完 → 整批清洗」的屏障：岗位在抓取期间只能停在
「入库待清洗」，最后一个平台结束前不会有任何清洗/飞书动作。

清洗泵把清洗段拆成可增量执行的小批次：抓取期间轮询本轮新增行，一有岗位入库就
执行一次 Tier1+Tier2（复用 step1._async_run_pipeline 的完整语义：逐岗位卡片事件、
通过即推飞书、即时落库），抓取结束后做最后一轮排空并退出。

设计约束：
- 不修改 step1 的过滤/排雷逻辑，只作为其调用方（与 Tier1 谓词修复等改动解耦）。
- 每批都重新获取 GLOBAL_CLEAN_LOCK，不长期占用；手动清洗任务可穿插执行。
- 每批只处理「本轮 rowid > start_rowid」的待清洗行；PRESERVE 的岗位留在
  「待AI初筛」，不会被下一批重复捞起（下一批只捞「已存入数据」）。
- 抓取结束信号与最后一轮排空之间做二次确认，堵住「插入提交/置位」竞态。
"""
import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from app.automation import pipeline_broadcast as pb

logger = logging.getLogger(__name__)

# 单批最多清洗的岗位数：限制 Tier2 并发压力与飞书推送突发
DRAIN_BATCH_SIZE = 20
# 无唤醒信号时的空闲轮询间隔（唤醒信号由抓取轮次提供，正常远小于该值）
IDLE_POLL_SECONDS = 5.0
# 连续失败上限：达到后交回抓取结束后的兜底清洗，避免泵内死循环
MAX_CONSECUTIVE_FAILURES = 3
# 失败退避基数（秒）：第 N 次失败后等待 base * 2^(N-1)，封顶 10s
RETRY_BACKOFF_BASE_SECONDS = 2.0

_PENDING_STATUSES = ("已存入数据", "清洗中")


def _is_aborted() -> bool:
    try:
        from app.automation import abort as abort_mod
        return bool(abort_mod.is_aborted())
    except Exception:
        return False


def _cleaning_stopped() -> bool:
    """用户是否手动终止了清洗（面板「终止清洗」）。"""
    try:
        from job_processor import step1_rule_filter
        return bool(step1_rule_filter.get_stop_flag())
    except Exception:
        return False


def count_pending_rows(db_path: str, start_rowid: int) -> int:
    """本轮尚未清洗的行数（含崩溃遗留的「清洗中」，下一批会自愈回收）。

    查库失败返回 -1（未知），绝不返回 0：调用方必须把「查不到」和「没有」
    区分开，否则一次瞬时锁冲突就会让兜底清洗被整段跳过（GLM 复审 P1-2）。
    """
    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM raw_jobs WHERE rowid > ? AND process_status IN (?, ?)",
                (int(start_rowid), *_PENDING_STATUSES),
            ).fetchone()
            return int(row[0] or 0)
    except Exception as e:
        logger.warning(f"[CleaningPump] 查询待清洗数量失败（按未知处理）: {e}")
        return -1


def collect_progress(db_path: str, start_rowid: int) -> dict[str, int]:
    """本轮累计清洗进度（供导轨 phase_progress 的累计口径）。

    完成数必须排除未处理的待清洗行与 PRESERVE 残留，否则失败/终止路径会把
    导轨谎报成 100%（GLM 复审 P1-1）。
    """
    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            def one(sql: str) -> int:
                return int(conn.execute(sql, (int(start_rowid),)).fetchone()[0] or 0)

            total = one("SELECT COUNT(*) FROM raw_jobs WHERE rowid > ?")
            pending = one(
                "SELECT COUNT(*) FROM raw_jobs WHERE rowid > ? "
                "AND process_status IN ('已存入数据', '清洗中')")
            hard_rejected = one(
                "SELECT COUNT(*) FROM raw_jobs WHERE rowid > ? AND process_status = '清洗淘汰'")
            tier1_done = one(
                "SELECT COUNT(*) FROM raw_jobs WHERE rowid > ? "
                "AND process_status NOT IN ('已存入数据', '清洗中', '已确认淘汰')")
            ai_rejected = one(
                "SELECT COUNT(*) FROM raw_jobs WHERE rowid > ? AND process_status = 'ai清洗淘汰'")
            ai_passed = one(
                "SELECT COUNT(*) FROM raw_jobs WHERE rowid > ? "
                "AND process_status IN ('待推送至飞书', '已同步')")
            ai_preserved = one(
                "SELECT COUNT(*) FROM raw_jobs WHERE rowid > ? AND process_status = '待AI初筛'")
    except Exception as e:
        logger.warning(f"[CleaningPump] 汇总清洗进度失败: {e}")
        return {}

    ai_total = max(0, tier1_done - hard_rejected)
    return {
        "total": total,
        "pending": pending,
        "hard_done": tier1_done,
        "hard_passed": max(0, tier1_done - hard_rejected),
        "hard_rejected": hard_rejected,
        "ai_total": ai_total,
        # 保留（PRESERVE）的岗位已被 Tier2 尝试但未完成，不能计入完成数
        "ai_done": max(0, ai_total - ai_preserved),
        "ai_passed": ai_passed,
        "ai_rejected": ai_rejected,
        "ai_preserved": ai_preserved,
    }


async def run_cleaning_pump(
    pipeline_task_id: str,
    db_path: str,
    start_rowid: int,
    scraping_done: asyncio.Event,
    wake: asyncio.Event,
    on_job_passed: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    emit_job_events: bool = True,
    drain_once: Callable[[], Awaitable[Any]] | None = None,
    count_pending: Callable[[], int] | None = None,
) -> dict[str, Any]:
    """抓取期持续清洗，抓取结束且本轮排空后返回。

    drain_once / count_pending 仅测试注入用；生产路径走 step1 的完整清洗语义。
    返回 {"passes", "cleaned", "progress"}，供编排器记录日志与收口判断。
    """
    if drain_once is None:
        from job_processor import step1_rule_filter

        async def drain_once():
            return await step1_rule_filter._async_run_pipeline(
                sse_task_id=pipeline_task_id,
                limit=DRAIN_BATCH_SIZE,
                min_rowid=start_rowid,
                emit_job_events=emit_job_events,
                on_job_passed=on_job_passed,
            )

    if count_pending is None:
        def count_pending() -> int:
            return count_pending_rows(db_path, start_rowid)

    # 新链路接管清洗：清掉上一轮残留的「终止清洗」标志，避免泵刚启动就退出
    try:
        from job_processor import step1_rule_filter
        step1_rule_filter.set_stop_flag(False)
    except Exception:
        pass

    passes = 0
    cleaned = 0
    failures = 0
    unknown_streak = 0
    blocked_announced = False

    def _task_blocked() -> dict | None:
        try:
            from app.automation import pipeline_blocked
            return pipeline_blocked.get_blocked_state(pipeline_task_id)
        except Exception:
            return None

    while True:
        if _is_aborted() or _cleaning_stopped():
            logger.info("[CleaningPump] 收到终止信号，清洗泵退出")
            break

        pending = await asyncio.to_thread(count_pending)
        if pending < 0:
            # 查库失败：按「有待清洗」处理，但连续未知必须退出，避免忙循环
            unknown_streak += 1
            if unknown_streak >= MAX_CONSECUTIVE_FAILURES:
                await pb.emit_log(
                    pipeline_task_id,
                    "⚠️ 连续无法查询待清洗数量，流式清洗泵退出，剩余岗位交回抓取结束后兜底清洗",
                    "error")
                break
        else:
            unknown_streak = 0
        # pending < 0 表示查库失败（未知）：按「有待清洗」处理，宁可空跑一次也不能跳过
        if pending != 0:
            try:
                await drain_once()
                passes += 1
                remaining = await asyncio.to_thread(count_pending)
                if pending > 0 and remaining >= 0:
                    cleaned += max(0, pending - remaining)
                failures = 0
                batch_desc = str(pending) if pending > 0 else "未知数量"
                await pb.emit_log(
                    pipeline_task_id,
                    f"🧹 流式清洗：本批 {batch_desc} 个岗位已处理（累计 {cleaned} 个）")
                # LLM 阻塞的实时出口：PRESERVE 卡片只有一行紫色小字，用户感知不到网关已挂。
                # 首次置位即广播 blocked 阶段事件与人话摘要（此后编排器收口会带最新明细重发）。
                blocked_now = await asyncio.to_thread(_task_blocked)
                if blocked_now and not blocked_announced:
                    blocked_announced = True
                    await pb.emit_log(
                        pipeline_task_id,
                        f"⏸️ AI 排雷持续失败（{blocked_now.get('kind')}）：{blocked_now.get('message')}，"
                        f"遗留岗位保留在待AI初筛，修复 LLM 后可继续任务",
                        "error")
                    await pb.emit_stage(
                        pipeline_task_id, "cleaning", "blocked", extra={"blocked": blocked_now})
            except Exception as e:
                failures += 1
                logger.warning(
                    f"[CleaningPump] 清洗批次异常（连续第 {failures} 次）: {e}", exc_info=True)
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    await pb.emit_log(
                        pipeline_task_id,
                        f"⚠️ 流式清洗连续失败 {failures} 次，剩余岗位交回抓取结束后兜底清洗",
                        "error")
                    break
                await asyncio.sleep(
                    min(RETRY_BACKOFF_BASE_SECONDS * (2 ** (failures - 1)), 10))
            continue

        if scraping_done.is_set():
            # 抓取结束置位与最后一批插入提交之间存在微秒级竞态：再确认一次
            if await asyncio.to_thread(count_pending) != 0:
                continue
            break

        try:
            await asyncio.wait_for(wake.wait(), timeout=IDLE_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
        wake.clear()

    progress = await asyncio.to_thread(collect_progress, db_path, start_rowid)
    if progress.get("total"):
        await pb.emit_phase_progress(
            pipeline_task_id, "hard_clean",
            current=progress["hard_done"], total=progress["total"],
            passed=progress["hard_passed"], rejected=progress["hard_rejected"])
        await pb.emit_phase_progress(
            pipeline_task_id, "ai_scout",
            current=progress["ai_done"], total=progress["ai_total"],
            passed=progress["ai_passed"], rejected=progress["ai_rejected"])

    return {"passes": passes, "cleaned": cleaned, "progress": progress}
