"""
全链路全自动总编排器
====================
串联平台抓取、规则清洗、飞书推送、AI评估与状态机自动投递：
    平台抓取(scrape_runner) → 规则清洗(step1) → 飞书推送(step2)
    → 捞新线索(feishu) → AI初评/深评/改写/欢迎语/投递(graph_runner)
"""
import asyncio
import logging
import sqlite3
import time
import uuid
from datetime import datetime
from typing import Any

from app.automation import pipeline_broadcast as pb
from app.automation.abort import PipelineAbortedError
from app.automation.db import (
    append_autopilot_log,
    complete_autopilot_log,
    get_autopilot_config,
)
from app.automation.graph_runner import _run_jobs_through_graph
from app.automation.link_precheck import build_checked_batch
from app.automation.scrape_runner import (
    PLATFORM_CN,
    _derive_search_from_config,
    _get_raw_db_path,
    _reap_orphan_scrapers,
    execute_pipeline_scrape,
)
from app.core.feishu_utils import extract_feishu_text as _txt

logger = logging.getLogger(__name__)

# 裸 asyncio.create_task 强引用（2026-11-02 审计 P2-25）：CPython 事件循环只持弱引用，
# 不持引用的任务可能在长 await 期间被 GC 静默消失（对照 delivery_router._BACKGROUND_TASKS
# 与 batch_retry_service 的既有正确做法）
_BACKGROUND_TASKS: set = set()


def _spawn_tracked(coro, *, name: str | None = None):
    # name 透传给 asyncio.create_task（清洗泵启动处曾传 name= 触发 TypeError 被静默吞掉，
    # 0.4.2 流式清洗泵整轮未启动——2026-11-03 排查实录，见 release-notes/0.4.2）
    t = asyncio.create_task(coro, name=name)
    _BACKGROUND_TASKS.add(t)
    t.add_done_callback(_BACKGROUND_TASKS.discard)
    return t


async def _await_pump_closable(pump_task: "asyncio.Task", pipeline_task_id: str, *, timeout: float = 300.0):
    """等待清洗泵收口（D2）：LLM 阻塞登记在案时不再死等整段超时。

    分片轮询：asyncio.wait({pump_task}, timeout=10s) 只「到点返回」、绝不取消泵、
    也绝不重放泵自身异常（GLM 复审 round2 P1：不能用 wait_for+吞 TimeoutError——
    泵内部以 TimeoutError 结束会被误当分片到期吞掉，退化成 300s 紧密空转并掩盖
    真实错误）。done 即取 result()：正常结束返回结果，泵自身异常原样上抛，
    与旧 wait_for(pump_task, 300) 的异常语义一致。

    期间检测任务级 LLM 阻塞登记（pipeline_blocked）：一旦登记，剩余等待收紧为 30s
    缓冲（够在途批次收尾），到点仍没跑完就取消泵并抛 TimeoutError，调用方既有
    TimeoutError 路径让剩余岗位走兜底清洗。

    取消责任与原 wait_for(pump_task, 300) 严格等价（GLM 复审 round1 P1）：
    - 到点路径：先 cancel 泵并 gather 等取消完成，再抛 TimeoutError——杜绝「泵还在
      收尾、兜底清洗已并发写库」的双写窗口；
    - 外层取消路径：asyncio.wait 不连带取消泵，这里补齐——cancel 泵并等待后再向上
      传播，使调用方 except CancelledError 的 pump_task.cancelled() 判定与旧行为一致。
    """
    deadline = time.monotonic() + timeout
    blocked_grace_armed = False
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pump_task.cancel()
                await asyncio.gather(pump_task, return_exceptions=True)
                raise asyncio.TimeoutError()
            done, _pending = await asyncio.wait({pump_task}, timeout=min(remaining, 10.0))
            if done:
                return pump_task.result()
            if not blocked_grace_armed:
                try:
                    from app.automation import pipeline_blocked as _pbm
                    if _pbm.get_blocked_state(pipeline_task_id):
                        blocked_grace_armed = True
                        deadline = min(deadline, time.monotonic() + 30.0)
                        logger.warning("[FullAuto] 检测到 LLM 阻塞登记，清洗泵收口等待收紧为 30s 缓冲")
                except Exception:
                    pass
    except asyncio.CancelledError:
        pump_task.cancel()
        try:
            # shield：二次取消送达时取消收尾转入后台完成，不阻塞异常向上传播
            await asyncio.shield(asyncio.gather(pump_task, return_exceptions=True))
        except asyncio.CancelledError:
            pass
        raise


async def run_full_auto_pipeline(
    keyword: str | None = None,
    city: str | None = None,
    salary: str | None = None,
    target_jobs: int | None = None,
    platforms: list[str] | None = None,
    stop_at_review: bool = False,
    trigger_source: str = "scheduled",
) -> str:
    """
    启动一轮全自动链路（后台异步执行），立即返回 pipeline_task_id 供前端订阅 SSE。
    未显式传入的抓取参数将从 autopilot 配置自动推导。
    stop_at_review=True 为定时链路模式：改写/话术全部做完后一律挂审批断点。
    trigger_source 标记触发来源（scheduled=定时任务 / manual=手动即时），
    随链路贯穿到飞书主战报卡片标题。
    """
    cur = pb.get_current_pipeline()
    if cur.get("running"):
        raise RuntimeError(f"已有链路正在运行中（{cur.get('task_id')}），请等待其完成或先终止后再启动")

    # ===== 先占坑（2026-11-02 双开竞态根治）=====
    # running 检查与置位之间必须零 await：旧顺序「检查 → await LLM 预检(≤30s) → 才置位」
    # 在窗口期内定时触发与手动点击可双双通过检查并发跑两条链（互相清空对方岗位/阶段
    # 状态、先收尾方把在跑方标"未运行"、期间 /abort 409 静默失效）。占坑与检查同为
    # 同步调用，窗口关闭；预检失败路径在 finally 中恢复占坑前原值（Opus CR-R1-P1：
    # 不能把幽灵 task_id 留在 current_pipeline 上，否则前端会把从未运行的链路当
    # 服务端当前任务、清掉上一轮看板）。
    prev_pipeline = pb.get_current_pipeline()
    pipeline_task_id = f"pipeline_{uuid.uuid4().hex[:8]}"
    pb.create_pipeline_queue(pipeline_task_id)
    pb.set_current_pipeline(pipeline_task_id, True)
    # begin 提前到预检 await 之前（Opus CR-R1-P2）：begin 语义=清上一轮终止标记并登记
    # 当前任务。若仍在预检后执行，预检窗口（≤30s，此时 running 已 True、/abort 可受理）
    # 内受理的终止标记会被 begin 的清标记语义冲掉——终止被静默吞掉，与本次根治的 409
    # 失效同类。回滚分支按「链路收尾」语义调 end_pipeline 释放登记。
    from app.automation import abort as abort_mod
    abort_mod.begin_pipeline(pipeline_task_id)
    _launched = False
    try:
        await _start_pipeline_inner(pipeline_task_id, keyword=keyword, city=city, salary=salary,
                                    target_jobs=target_jobs, platforms=platforms,
                                    stop_at_review=stop_at_review, trigger_source=trigger_source)
        _launched = True
        return pipeline_task_id
    finally:
        if not _launched:
            try:
                pb.set_current_pipeline(prev_pipeline.get("task_id"), bool(prev_pipeline.get("running")))
                pb.discard_pipeline_queue(pipeline_task_id)
                abort_mod.end_pipeline()
                logger.warning("⚠️ [发射占坑] 预检/推导未通过，已恢复占坑前链路状态并释放登记: %s", pipeline_task_id)
            except Exception as _rollback_e:
                logger.error("❌ [发射占坑] 占坑状态回滚失败，需人工检查 current_pipeline: %s", _rollback_e)


async def _start_pipeline_inner(
    pipeline_task_id: str,
    keyword: str | None,
    city: str | None,
    salary: str | None,
    target_jobs: int | None,
    platforms: list[str] | None,
    stop_at_review: bool,
    trigger_source: str,
) -> None:
    """占坑后的发射预检与链路装配（失败抛异常，由占坑方 finally 回滚）。"""
    # ===== D0: LLM 网关发射预检 =====
    # 定时链路（trigger_source=scheduled）：网关不可用时整轮跳过并飞书提醒——否则
    # 抓取白烧浏览器资源、清洗整批滞留待AI初筛（2026-10-31 上游聚合网关 账号池全灭事故）。
    # 其余来源（manual 手动即时）：用户在场且意图明确，只告警不拦截
    # （阻塞登记/继续任务兜底）。
    # 预检自身故障（模块缺失/探测异常）一律降级为「未知→放行」：预检是增强护栏，
    # 绝不能因护栏自身故障阻断发射主链路（GLM 复审 round2 P1）。
    try:
        from app.automation import llm_health as _llm_health
        _probe = await asyncio.to_thread(_llm_health.probe_llm)
    except Exception as _probe_e:
        logger.warning("⚠️ [发射预检] 预检自身异常，降级放行（不阻断发射主链路）: %s", _probe_e)
        _probe = {"ok": True}
    if not _probe.get("ok"):
        _reason = _probe.get("message") or "未知原因"
        if trigger_source == "scheduled":
            logger.warning("⏭️ [发射预检] LLM 网关不可用，本轮定时发射已跳过: %s", _reason)
            try:
                from app.automation.pipeline_report import send_pipeline_report
                await send_pipeline_report(
                    "⏭️ JobHunter 定时发射已跳过\n"
                    f"原因：LLM 网关不可用（{_reason}）\n"
                    f"模型：{_probe.get('model') or '未知'}\n"
                    "恢复后可在指挥中心重新触发，或对遗留岗位点「继续任务」。"
                )
            except Exception as _notify_e:
                logger.warning("[发射预检] 跳过通知发送失败（不影响跳过决策）: %s", _notify_e)
            raise RuntimeError(f"LLM 网关不可用，本轮定时发射已跳过: {_reason}")
        logger.warning(
            "⚠️ [发射预检] LLM 网关不可用，仍按触发来源 trigger_source=%s 启动（清洗可能整批滞留待AI初筛）: %s",
            trigger_source, _reason,
        )

    # begin_pipeline 已在占坑块执行（先于本预检，见占坑注释）

    config = get_autopilot_config()
    derived = _derive_search_from_config(config)
    search = {
        "keyword": keyword or derived["keyword"],
        "city": city or derived["city"],
        "salary": salary or derived["salary"],
        "target_jobs": target_jobs or derived["target_jobs"],
        "platforms": platforms or derived["platforms"],
    }

    _spawn_tracked(_run_pipeline_with_watchdog(
        pipeline_task_id, config, search,
        stop_at_review=stop_at_review, trigger_source=trigger_source))
    return pipeline_task_id


# 终止看门狗宽限（2026-11-05 僵尸链路事故）：优雅终止预期在秒级~分钟级收口
# （预检检查点 + 同步段 120s 看门狗均已加密），10 分钟仍未收口即判定协程挂死
# 于某个不检查终止旗子的深调用。强收是最后防线：宁可撕裂一个挂死的慢调用，
# 也不能让占坑永久占用、后续启动全部被 409 挡死。
PIPELINE_ABORT_GRACE_SECONDS = 600.0


async def _run_pipeline_with_watchdog(
    pipeline_task_id: str,
    config: dict[str, Any],
    search: dict[str, Any],
    stop_at_review: bool,
    trigger_source: str,
) -> None:
    """包装 _execute_pipeline：终止宽限超时后强制收尾 + 取消挂死协程。

    正常路径：链路完成 → 看门狗协程随 body 结束自然退出，零介入。
    兜底路径：is_aborted 置位起计时，宽限内 body 未结束 → 视为挂死：
    watchdog cancel 宿主 task，CancelledError 穿透 body 的 except Exception
    （BaseException 语义）直达本包装 finally——body 自己的 finally 释放占坑后，
    此处再以「看门狗强收」语义补齐 automation_logs 终态 + SSE end 帧（P1 修复：
    这两笔若不补，看门狗触发的轮次 automation_logs 仍会永久 running、前端无收口）。
    emit_end 幂等性由 pipeline_broadcast 保证（重复 end 只覆盖 queue 终态帧）。
    """

    # 台账行 id 上移到包装层生成：正常路径由 _execute_pipeline 各收口分支写终态；
    # 看门狗强收路径（body 被 cancel，except Exception 拦不住）由
    # _force_finalize_after_watchdog 用同一 id 补写——两路必有一路收口台账。
    log_task_id = str(uuid.uuid4())
    host_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    watchdog = loop.create_task(_abort_watchdog(pipeline_task_id, host_task))
    try:
        await _execute_pipeline(
            pipeline_task_id, config, search, log_task_id=log_task_id,
            stop_at_review=stop_at_review, trigger_source=trigger_source)
    except asyncio.CancelledError:
        # 看门狗强收路径（或外层关停）：CancelledError 是 BaseException，body 的
        # except Exception 拦不住——这里必须先补台账与 SSE 终态再向上传播
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass
        await _force_finalize_after_watchdog(pipeline_task_id, log_task_id)
        raise
    finally:
        watchdog.cancel()
        # 看门狗自身被 cancel 时的 CancelError 属预期，吞掉；其余异常记录不阻断
        try:
            await watchdog
        except asyncio.CancelledError:
            pass
        except Exception as wd_e:
            logger.warning(f"[FullAuto] 看门狗协程异常（不阻断收尾）: {wd_e}", exc_info=True)
        # 除强收路径（上方 except 已收口并 raise）外的正常/异常退出：
        # body 的 finally 已释放占坑，无需补刀。


async def _abort_watchdog(pipeline_task_id: str, host_task: "asyncio.Task | None") -> None:
    """终止宽限倒计时：到点且链路仍未收口（current_pipeline 仍登记本任务）则取消宿主协程。

    未终止/已收口（end_pipeline 已清登记）时静默退出（由宿主 finally cancel）。
    """
    from app.automation import abort as abort_mod
    from app.automation import pipeline_broadcast as pb

    while True:
        aborted_ts = abort_mod.aborted_at()
        if not aborted_ts:
            await asyncio.sleep(2)
            continue
        elapsed = time.monotonic() - aborted_ts
        remaining = PIPELINE_ABORT_GRACE_SECONDS - elapsed
        if remaining <= 0:
            break
        await asyncio.sleep(min(remaining, 5))
        if not abort_mod.is_aborted():
            continue  # 旗子被 end_pipeline 清掉（已收口），外层 finally 会 cancel 本协程
    cur = pb.get_current_pipeline()
    if cur.get("running") and cur.get("task_id") == pipeline_task_id:
        logger.error(
            "🐕 [FullAuto] 终止看门狗触发：终止已置位 %.0fs 链路 %s 仍未收口，判定协程挂死，强制取消收尾",
            PIPELINE_ABORT_GRACE_SECONDS, pipeline_task_id,
        )
        if host_task is not None and not host_task.done():
            host_task.cancel()


async def _force_finalize_after_watchdog(pipeline_task_id: str, log_task_id: str) -> None:
    """看门狗强收：补齐台账终态 + SSE end 帧 + 占坑释放（与 _execute_pipeline
    各收口分支同款，全部幂等；仅在宿主被 cancel 时调用）。"""
    logger.warning(f"🐕 [FullAuto] 链路 {pipeline_task_id} 由终止看门狗强制收尾")
    try:
        complete_autopilot_log(log_task_id, "failed", 0, "终止看门狗强制收尾（协程挂死）")
    except Exception as log_e:
        logger.warning(f"[FullAuto] 看门狗强收·台账补写异常: {log_e}")
    try:
        await pb.emit_end(pipeline_task_id, {"reason": "aborted", "watchdog": True})
    except Exception as end_e:
        logger.warning(f"[FullAuto] 看门狗强收·end 帧发送异常: {end_e}")
    try:
        await _reap_orphan_scrapers(pipeline_task_id, timeout=10.0)
    except Exception as reap_e:
        logger.warning(f"[FullAuto] 看门狗强收·孤儿清理异常: {reap_e}")
    # 外审 R1-P1e：占坑释放后到孤儿收割完成的窗口内，用户可能已在 UI 启动新链路——
    # 全局运行态只能由仍归属本任务的收尾复位，绝不抹掉新链路的登记、终止标记与快照
    _cur = pb.get_current_pipeline()
    if not _cur.get("task_id") or _cur.get("task_id") == pipeline_task_id:
        pb.set_current_pipeline(pipeline_task_id, False)
        from app.automation import abort as abort_mod
        abort_mod.end_pipeline()
        from app.automation import run_snapshot as run_snapshot_mod
        run_snapshot_mod.end()
    else:
        logger.warning(
            "🐕 [FullAuto] 看门狗强收收尾时检测到新链路 %s 已接管全局态，跳过复位",
            _cur.get("task_id"))
    from app.tasks.state import schedule_task_cleanup
    schedule_task_cleanup(pipeline_task_id)


async def _execute_pipeline(
    pipeline_task_id: str,
    config: dict[str, Any],
    search: dict[str, Any],
    stop_at_review: bool = False,
    trigger_source: str = "scheduled",
    log_task_id: str | None = None,
):
    """全链路主体：抓取 → 清洗 → 飞书 → 评估投递。全程广播阶段事件，结束时发飞书任务报告。

    log_task_id 由包装层下传（看门狗强收需用同一 id 补台账终态）；直调（旧测试）
    兼容 None 时自行生成。
    """
    if not log_task_id:
        log_task_id = str(uuid.uuid4())
    append_autopilot_log(log_task_id, "running", 0, f"全自动链路启动: {search['keyword']} / {search['city']}")

    started_at = datetime.now()
    scrape_counts_cn: dict[str, int] = {}
    disabled_platforms: list[str] = []
    synced_ids: list[str] = []
    rejected_rowids: list[str] = []

    from app.automation import abort as abort_mod

    try:
        await pb.emit_log(pipeline_task_id, f"🚀 全自动链路启动 | 关键词「{search['keyword']}」城市「{search['city']}」平台 {search['platforms']}")

        # ===== 阶段 1: 平台抓取（关键词队列 + 平台预算制）=====
        # 抓取期流式清洗：泵在抓取期间就把新入库岗位洗掉并推飞书，不再等所有平台结束。
        # 推送定义必须早于抓取启动（泵的 on_job_passed 会用到）。
        streamed_synced_ids: list[str] = []
        push_sem = asyncio.Semaphore(2)
        # 同三元组（公司+岗位+城市）串行：查重与建档之间没有原子性，并发 2 下
        # 两个不同链接的同名岗位可能同时查到「不存在」→ 飞书重复建档（2026-10-31 审查 P1）。
        push_key_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

        def _dedup_key(job: dict[str, Any]) -> tuple[str, str, str]:
            return (
                str(job.get("company_name") or "").strip(),
                str(job.get("job_title") or "").strip(),
                str(job.get("city") or "").strip(),
            )

        async def _push_passed_job(job: dict[str, Any]) -> None:
            if abort_mod.is_aborted():
                return
            link = job.get("job_link") or ""
            if not link:
                return
            key_lock = push_key_locks.setdefault(_dedup_key(job), asyncio.Lock())
            async with key_lock:
                async with push_sem:
                    try:
                        from job_processor import step2_sync_feishu
                        ids = await step2_sync_feishu.sync_one_link_async(
                            _get_raw_db_path(), "raw_jobs", pipeline_task_id, link)
                        if ids:
                            streamed_synced_ids.extend(ids)
                            # 建档即登记：raw 行变「已同步」后不再进快照，必须立刻纳入本轮
                            # record_ids，否则 12 秒轮询会把已推送的卡片从看板抹掉。
                            from app.automation import run_snapshot as _rs
                            _rs.register_record_ids(ids)
                    except Exception as push_e:
                        logger.warning(f"[FullAuto] 单岗即时推送异常（批量段兜底）: {push_e}")

        pump_wake = asyncio.Event()
        scraping_done = asyncio.Event()
        pump_task: asyncio.Task | None = None
        pump_result: dict[str, Any] = {}

        async def _on_scrape_start(sr: int) -> None:
            nonlocal pump_task
            from app.automation.cleaning_pump import run_cleaning_pump
            pump_task = _spawn_tracked(
                run_cleaning_pump(
                    pipeline_task_id, _get_raw_db_path(), sr,
                    scraping_done, pump_wake,
                    on_job_passed=_push_passed_job,
                ),
                name=f"cleaning_pump_{pipeline_task_id}",
            )

        try:
            start_rowid, scrape_counts_cn, disabled_platforms = await execute_pipeline_scrape(
                pipeline_task_id=pipeline_task_id,
                search=search,
                on_start=_on_scrape_start,
                on_rows_inserted=pump_wake.set,
            )
        finally:
            # 抓取段无论成功/异常都要收口清洗泵，避免后台协程悬挂
            scraping_done.set()
            pump_wake.set()
            if pump_task is not None:
                pump_cancelled_for_abort = False
                if abort_mod.is_aborted():
                    # 终止轮次：立即取消泵（不再等当前批 LLM 跑完）；
                    # 残留「清洗中」行由下一轮的僵尸自愈回收。
                    pump_task.cancel()
                    pump_cancelled_for_abort = True
                try:
                    pump_result = await _await_pump_closable(pump_task, pipeline_task_id, timeout=300) or {}
                except asyncio.CancelledError:
                    if pump_cancelled_for_abort and pump_task.cancelled():
                        # 泵被我们自己取消（终止信号）：预期路径，吞掉。
                        # 外审 R1-P1d：不能只凭 pump_task.cancelled() 判据——宿主任务被取消时
                        # _await_pump_closable 的收尾也会替我们取消泵，原判据恒真，
                        # 进程关停/任务树取消的 CancelledError 会被静默吞掉
                        logger.info("[FullAuto] 清洗泵已取消（收到终止信号）")
                    else:
                        # 外层任务（进程关停/任务树取消）被取消：必须继续向上传播
                        raise
                except asyncio.TimeoutError:
                    logger.warning("[FullAuto] 清洗泵收口超时，取消后台任务，剩余岗位走兜底清洗")
                    pump_task.cancel()
                except Exception as pump_e:
                    logger.warning(f"[FullAuto] 清洗泵收口异常（剩余岗位走兜底清洗）: {pump_e}")

        # 终止/异常收尾时战报也要如实统计已流式推送的岗位
        synced_ids = list(dict.fromkeys(streamed_synced_ids))

        async def _send_task_report(
            job_results: list[dict[str, Any]],
            dedup_count: int = 0,
            rejected_ids: list[str] | None = None,
        ):
            """链路出口统一发飞书任务报告；报告失败只告警，不影响链路收尾。"""
            try:
                if not config.get("feishu_enable_report", True):
                    await pb.emit_log(pipeline_task_id, "📮 任务报告推送已在飞书面板关闭，跳过发送")
                    return
                from app.automation import pipeline_report as pr
                raw_db = _get_raw_db_path()
                cleaning_stats = await asyncio.to_thread(
                    pr.collect_cleaning_stats, raw_db, start_rowid)
                text = pr.build_pipeline_report(
                    started_at=started_at,
                    scrape_counts=scrape_counts_cn,
                    disabled_platforms=[PLATFORM_CN.get(p, p) for p in disabled_platforms],
                    platform_cn={},
                    cleaning=cleaning_stats,
                    synced_count=len(synced_ids),
                    job_results=job_results,
                    aborted=abort_mod.is_aborted(),
                    dedup_count=dedup_count,
                )
                actual_rejected_ids = rejected_ids if rejected_ids is not None else []
                await pb.emit_log(pipeline_task_id, "📮 正在生成任务战报卡片并推送飞书…")
                card_ok = await pr.send_pipeline_master_card(
                    started_at=started_at,
                    scrape_counts=scrape_counts_cn,
                    cleaning=cleaning_stats,
                    job_results=job_results,
                    dedup_count=dedup_count,
                    rejected_ids=actual_rejected_ids,
                    trigger_source=trigger_source,
                    # 2026-10-24 工单：主卡片是飞书侧第一事实源，终止轮次必须带手动终止横幅
                    aborted=abort_mod.is_aborted(),
                )
                if not card_ok:
                    await pr.send_pipeline_report(text)
            except Exception as rep_e:
                logger.warning(f"[FullAuto] 任务报告发送异常（不阻断链路）: {rep_e}")

        async def _safe_send_abort_report() -> None:
            """终止战报加超时上限——飞书网络抖动绝不阻断 emit_end 与台账清零（0928 事故）。"""
            try:
                await asyncio.wait_for(_send_task_report([]), timeout=15)
            except Exception as rep_e:
                logger.warning(f"[FullAuto] 终止战报发送异常/超时（不阻断终止收尾）: {rep_e}")

        # 终止守卫
        if abort_mod.is_aborted():
            await _safe_send_abort_report()
            await pb.emit_stage(pipeline_task_id, "done", "done")
            await pb.emit_end(pipeline_task_id, {"reason": "aborted"})
            complete_autopilot_log(log_task_id, "failed", 0, "手动终止")
            return

        # ===== 阶段 2: 规则清洗（抓取期已流式清洗，此处仅收口/兜底）=====
        await pb.emit_stage(pipeline_task_id, "cleaning", "running")
        from app.automation.cleaning_pump import count_pending_rows
        from job_processor import step1_rule_filter

        leftover = await asyncio.to_thread(
            count_pending_rows, _get_raw_db_path(), start_rowid)
        # leftover < 0 = 查库失败（未知）：宁可空跑一次兜底清洗，也不能静默跳过（GLM 复审 P1-2）
        if leftover != 0:
            leftover_desc = f"{leftover} 个岗位待清洗" if leftover > 0 else "待清洗数量未知（查库失败）"
            await pb.emit_log(
                pipeline_task_id,
                f"🧹 抓取结束仍有{leftover_desc}，执行收口清洗")
            # emit_job_events=True：逐岗位广播卡片事件；on_job_passed 继续「过一个推一条」
            await step1_rule_filter._async_run_pipeline(
                sse_task_id=pipeline_task_id, limit=None, min_rowid=start_rowid,
                emit_job_events=True, on_job_passed=_push_passed_job)
        else:
            await pb.emit_log(
                pipeline_task_id,
                f"🧹 抓取期已流式清洗 {int(pump_result.get('cleaned') or 0)} 个岗位，无需收口")

        preserved = int((pump_result.get("progress") or {}).get("ai_preserved") or 0)
        if preserved:
            await pb.emit_log(
                pipeline_task_id,
                f"↩️ {preserved} 个岗位 AI 排雷未完成（模型输出异常），保留在待AI初筛，可稍后重洗")

        # 任务级 LLM 阻塞登记（AI 侦察兵 PRESERVE 路径上报）：把本轮清洗范围附着到阻塞态，
        # 「继续任务」据此只重洗本轮遗留的待AI初筛行。
        from app.automation import pipeline_blocked as pipeline_blocked_mod
        blocked_state = pipeline_blocked_mod.get_blocked_state(pipeline_task_id)
        if blocked_state:
            pipeline_blocked_mod.attach_scope(pipeline_task_id, min_rowid=start_rowid)
            blocked_state = pipeline_blocked_mod.get_blocked_state(pipeline_task_id)
            await pb.emit_log(
                pipeline_task_id,
                f"⏸️ 本轮链路被 LLM 异常阻塞（{blocked_state.get('kind')}）：{blocked_state.get('message')}。"
                f"修复模型服务后可在指挥中心点「继续任务」重洗遗留岗位",
                "error")

        try:
            def _fetch_rejected_jobs():
                with sqlite3.connect(_get_raw_db_path()) as _c:
                    _c.row_factory = sqlite3.Row
                    return [
                        dict(r) for r in _c.execute(
                            "SELECT rowid, platform, job_title, company_name, salary, city, "
                            "education_req, experience_req, jd_text, job_link, process_status, reject_reason "
                            "FROM raw_jobs WHERE rowid > ? AND process_status IN ('清洗淘汰', 'ai清洗淘汰')",  # 本轮清洗语义,词表见 app/core/process_status
                            (start_rowid,)
                        ).fetchall()
                    ]
            rejected_list = await asyncio.to_thread(_fetch_rejected_jobs)
            rejected_rowids = [str(rj["rowid"]) for rj in rejected_list if rj.get("rowid")]
            # 淘汰卡已由 step1 在判定瞬间逐岗位广播（emit_job_events=True），
            # 此处不再重复补发；仅保留统计口径供战报使用。
            if rejected_list:
                await pb.emit_log(pipeline_task_id, f"🧹 本轮共拦截淘汰 {len(rejected_list)} 个岗位（已沉淀至「淘汰岗位」回收站）")
        except Exception as _rej_e:
            logger.warning(f"[FullAuto] 广播淘汰岗位异常（不阻断链路）: {_rej_e}")

        # 阻塞轮次不把清洗阶段标成 done：导轨停留 blocked 态，徽标/横幅据此显示「已暂停」
        if blocked_state:
            await pb.emit_stage(
                pipeline_task_id, "cleaning", "blocked", extra={"blocked": blocked_state})
        else:
            await pb.emit_stage(pipeline_task_id, "cleaning", "done")

        # ===== 阶段 3: 飞书推送（流式段已推完的岗位此处为空，仅兜底失败/遗留行）=====
        await pb.emit_stage(pipeline_task_id, "feishu_sync", "running")
        if streamed_synced_ids:
            await pb.emit_log(
                pipeline_task_id,
                f"🧾 清洗段已流式推送 {len(streamed_synced_ids)} 个岗位至飞书，本段仅做兜底校验")
        from job_processor import step2_sync_feishu
        batch_synced_ids = await step2_sync_feishu.sync_sqlite_to_feishu_async(
            _get_raw_db_path(), "raw_jobs", pipeline_task_id, None, start_rowid
        )
        synced_ids = list(dict.fromkeys([
            *streamed_synced_ids,
            *[rid for rid in (batch_synced_ids or []) if isinstance(rid, str)],
        ]))
        # 同步完成即登记本轮记录 ID：step2 落库后 raw 行变「已同步」不再进快照，
        # 若等图启动才登记，12 秒轮询会短暂把卡片从看板抹掉（流式体验断档）。
        try:
            from app.automation import run_snapshot as _rs
            _rs.register_record_ids(synced_ids)
        except Exception as _reg_e:
            logger.warning(f"[FullAuto] 登记本轮同步记录异常（不阻断链路）: {_reg_e}")
        await pb.emit_stage(pipeline_task_id, "feishu_sync", "done")

        # 终止守卫
        if abort_mod.is_aborted():
            await _safe_send_abort_report()
            await pb.emit_stage(pipeline_task_id, "done", "done")
            await pb.emit_end(pipeline_task_id, {"reason": "aborted"})
            complete_autopilot_log(log_task_id, "failed", 0, "手动终止")
            return

        # ===== 阶段 4: 只评估本轮采集的岗位 =====
        from app.services.feishu_service import (
            TABLE_ID,
            get_active_resume_from_feishu,
            get_job_record_from_feishu,
            get_my_preferences,
            get_resume_text_by_id,
        )

        mass_resume_id = (config.get("mass_apply_resume_id") or "").strip()
        resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
        preferences_text = await asyncio.to_thread(get_my_preferences)
        if not resume_text:
            await pb.emit_log(pipeline_task_id, "❌ 找不到激活简历，评估投递段中止", "error")
            await _send_task_report([])
            await pb.emit_stage(pipeline_task_id, "done", "done")
            await pb.emit_end(pipeline_task_id, {"reason": "no_resume"})
            complete_autopilot_log(log_task_id, "failed", 0, "找不到激活简历")
            return

        rewrite_base_id = (config.get("rewrite_base_resume_id") or "").strip()
        if rewrite_base_id:
            base_text = await asyncio.to_thread(get_resume_text_by_id, rewrite_base_id)
            if base_text:
                resume_text = base_text
                await pb.emit_log(pipeline_task_id, "🧾 已启用指定 A/B 底稿：本轮评估与改写均使用该简历")
            else:
                await pb.emit_log(pipeline_task_id, "⚠️ 指定的 A/B 底稿读取失败，回退使用启用简历", "error")

        mass_resume_text = ""
        if mass_resume_id:
            mass_resume_text = await asyncio.to_thread(get_resume_text_by_id, mass_resume_id)
        if not mass_resume_text:
            mass_resume_text = resume_text

        def _get_raw_id_mapping():
            with sqlite3.connect(_get_raw_db_path()) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT rowid, feishu_record_id, job_link FROM raw_jobs WHERE rowid > ?",
                    (start_rowid,)
                ).fetchall()
                rec_to_raw = {}
                for r in rows:
                    if r["feishu_record_id"]:
                        rec_to_raw[r["feishu_record_id"]] = (f"raw_{r['rowid']}", r["job_link"] or "")
                return rec_to_raw

        raw_id_map = await asyncio.to_thread(_get_raw_id_mapping)

        new_jobs = []
        for rid in synced_ids:
            rec = await asyncio.to_thread(get_job_record_from_feishu, rid, TABLE_ID)
            if not rec:
                continue
            f = rec.get("fields", {})
            raw_info = raw_id_map.get(rid, ("", ""))
            raw_jid = raw_info[0]
            raw_link = raw_info[1]
            job_url = _txt(f.get("岗位链接", "")) or raw_link

            new_jobs.append({
                "job_id": rid,
                "record_id": rid,
                "raw_job_id": raw_jid,
                "job_url": job_url,
                "platform": _txt(f.get("招聘平台", "")),
                "company_name": _txt(f.get("公司名称", "")),
                "job_name": _txt(f.get("岗位名称", "")),
                "jd_text": _txt(f.get("岗位详情", "")),
                "salary": _txt(f.get("薪资", "")),
                "city": _txt(f.get("城市", "")),
                "experience": _txt(f.get("经验要求", "")),
                "education": _txt(f.get("学历要求", "")),
                "company_scale": _txt(f.get("公司规模", "")) or "",
                "feishu_fields": f,
                "_created_time": rec.get("created_time", 0),
            })
        await pb.emit_log(
            pipeline_task_id,
            f"📥 本轮新采集 {len(new_jobs)} 条（全自动链只评估本轮；旧存量走人工批量评估）")

        # 匿名功能计数：本轮发射 + 抓取入库量 + AI 排雷完成量（纯数字，不出机器）。
        # 外审 R1-P1e：统计前移到零岗位早退之前（阻塞/空轮也要计入发射与入库）；
        # collect_progress 无 "cleaned" 键（改读 total=本轮入库 / ai_done=排雷完成）；
        # 查库放 to_thread，不在事件循环线程同步查。
        try:
            from app.automation.cleaning_pump import collect_progress as _cp
            from app.core import usage_counters as _uc
            _progress = await asyncio.to_thread(_cp, _get_raw_db_path(), start_rowid) or {}
            _uc.bump("pipeline_run")
            _uc.bump("pipeline_scraped", int(_progress.get("total") or 0))
            _uc.bump("pipeline_cleaned", int(_progress.get("ai_done") or 0))
        except Exception:  # noqa: BLE001 — 计数失败绝不影响链路
            pass

        if not new_jobs:
            await _send_task_report([])
            await pb.emit_stage(pipeline_task_id, "done", "done")
            # 阻塞轮次即使无岗位进入评估段，end 也必须如实标注 outcome，不能伪装成功。
            # 外审 R1-P0：emit_end 首参是 task_id——此前把 apply_outcome 返回的 dict
            # 当 task_id 传入，task_queues 取键触发 TypeError，前端永远收不到 end 帧
            def _preserved_now() -> int:
                from app.automation.cleaning_pump import collect_progress
                return int((collect_progress(_get_raw_db_path(), start_rowid) or {}).get("ai_preserved") or 0)
            preserved_at_end = await asyncio.to_thread(_preserved_now)
            end_summary = pipeline_blocked_mod.apply_outcome(
                {"jobs": 0}, pipeline_task_id, preserved_at_end)
            await pb.emit_end(pipeline_task_id, end_summary)
            if end_summary.get("outcome") == "blocked":
                complete_autopilot_log(
                    log_task_id, "success", 0,
                    f"链路被 LLM 异常阻塞，{preserved_at_end} 个岗位滞留待AI初筛（可继续任务）")
            else:
                complete_autopilot_log(log_task_id, "success", 0, "本轮无新采集岗位")
            return

        dedup_pending_pairs: list = []
        dedup_count: int = 0
        try:
            from app.services.job_dedup_gate import run_dedup_gate
            new_jobs, marked_duplicates, dedup_pending_pairs = await run_dedup_gate(
                new_jobs, log=lambda m: pb.emit_log(pipeline_task_id, m))
            dedup_count = len(marked_duplicates)
        except Exception as e:
            logger.warning(f"[FullAuto] 疑似重复检测异常（不阻断链路，岗位照常评估）: {e}", exc_info=True)

        batch_limit = config.get("batch_limit", 20)
        new_jobs = await build_checked_batch(new_jobs, batch_limit, pipeline_task_id)

        await pb.emit_stage(pipeline_task_id, "evaluating", "running")
        job_results = await _run_jobs_through_graph(
            new_jobs, resume_text, preferences_text, pipeline_task_id,
            mass_resume_text, stop_at_review=stop_at_review
        )
        # 本轮所有岗位的图流转结束：给 AI 初评阶段一个明确的收口事件。
        # 深评/改写/打招呼/投递是并发子阶段，活动态由实时岗位登记表按运行数聚合，
        # 不能靠单岗位节点完成事件推进全局阶段。
        await pb.emit_stage(pipeline_task_id, "evaluating", "done")

        # 匿名功能计数（纯数字，不出机器）：评估量与投递成败，供产品漏斗分析
        try:
            from app.core import usage_counters as _uc
            _uc.bump("pipeline_evaluated", len(job_results))
            for _r in job_results:
                if _r.get("outcome") == "delivered":
                    _uc.bump("pipeline_delivered_ok")
                elif _r.get("outcome") == "failed":
                    _uc.bump("pipeline_delivered_fail")
        except Exception:  # noqa: BLE001 — 计数失败绝不影响链路收尾
            pass

        if dedup_pending_pairs:
            try:
                from app.services.job_dedup_gate import backfill_batch_dup_conclusions
                await backfill_batch_dup_conclusions(
                    dedup_pending_pairs, log=lambda m: pb.emit_log(pipeline_task_id, m))
            except Exception as e:
                logger.warning(f"[FullAuto] 重复岗位母本结论回填异常（不阻断链路）: {e}", exc_info=True)

        await _send_task_report(job_results, dedup_count=dedup_count, rejected_ids=rejected_rowids)

        await pb.emit_stage(pipeline_task_id, "done", "done")
        # 2026-10-24 工单：评估/投递阶段被终止时，台账与结束事件必须如实标注，
        # 不能把「手动终止」记成 success。
        if abort_mod.is_aborted():
            await pb.emit_end(pipeline_task_id, {"reason": "aborted", "jobs": len(new_jobs)})
            complete_autopilot_log(log_task_id, "failed", len(new_jobs), "手动终止")
        else:
            # LLM 阻塞且有「待AI初筛」遗留时，end 摘要带 outcome=blocked：
            # 前端徽标显示「已暂停」而非「任务完成」，dashboard-sync 快照亦据此恢复阻塞态。
            def _preserved_now() -> int:
                from app.automation.cleaning_pump import collect_progress
                return int((collect_progress(_get_raw_db_path(), start_rowid) or {}).get("ai_preserved") or 0)
            preserved_at_end = await asyncio.to_thread(_preserved_now)
            end_summary = pipeline_blocked_mod.apply_outcome(
                {"jobs": len(new_jobs)}, pipeline_task_id, preserved_at_end)
            await pb.emit_end(pipeline_task_id, end_summary)
            if end_summary.get("outcome") == "blocked":
                complete_autopilot_log(
                    log_task_id, "success", len(new_jobs),
                    f"链路被 LLM 异常阻塞，{preserved_at_end} 个岗位滞留待AI初筛（可继续任务）")
            else:
                complete_autopilot_log(log_task_id, "success", len(new_jobs), f"已派发 {len(new_jobs)} 个岗位流水线")

    except PipelineAbortedError as e:
        # 终止检查点快速失败（2026-11-05 僵尸链路事故）：preflight/编排片段间命中
        # 终止旗子主动抛出。这不是崩溃——按「手动终止」语义收口，不发失败告警。
        logger.info(f"⏹️ [FullAuto] 链路已被手动终止（{e}），按终止收口")
        await pb.emit_log(pipeline_task_id, f"⏹️ 链路已手动终止（{e}）")
        await pb.emit_end(pipeline_task_id, {"reason": "aborted"})
        complete_autopilot_log(log_task_id, "failed", 0, "手动终止")
    except Exception as e:
        logger.error(f"🚨 [FullAuto] 链路崩溃: {e}", exc_info=True)
        await pb.emit_log(pipeline_task_id, f"🚨 链路异常: {e}", "error")
        try:
            from app.automation import pipeline_report as pr
            fail_lines = [
                "🚨 全链路任务失败通知",
                f"🕐 {started_at.strftime('%Y-%m-%d %H:%M')}",
                f"❌ 失败原因: {str(e)[:200]}",
            ]
            if scrape_counts_cn:
                fail_lines.append("🕷️ 失败前已抓取: " + " · ".join(f"{k} {v}" for k, v in scrape_counts_cn.items()))
            if not config.get("feishu_enable_alert", True):
                logger.info("[FullAuto] 异常告警推送已在飞书面板关闭，跳过发送")
            else:
                await pr.send_pipeline_report("\n".join(fail_lines))
        except Exception as rep_e:
            logger.warning(f"[FullAuto] 失败通知发送异常: {rep_e}")
        await pb.emit_end(pipeline_task_id, {"error": str(e)})
        complete_autopilot_log(log_task_id, "failed", 0, f"执行崩溃: {e}")
    finally:
        try:
            await _reap_orphan_scrapers(pipeline_task_id, timeout=10.0)
        except Exception as reap_e:
            logger.warning(f"[FullAuto] 孤儿清理异常（不阻断收尾）: {reap_e}")
        pb.set_current_pipeline(pipeline_task_id, False)
        from app.automation import abort as abort_mod
        abort_mod.end_pipeline()
        from app.automation import run_snapshot as run_snapshot_mod
        run_snapshot_mod.end()
        # 队列延迟清理（2026-11-02 审计 P2-13）：task_queues 此前只增不减，每轮链路/
        # 每次单岗重试各泄漏一个 TaskChannel（含 50 条 history）。延迟 5 分钟给前端
        # SSE 重连留窗口，与爬虫/清洗任务的既有清理契约一致
        from app.tasks.state import schedule_task_cleanup
        schedule_task_cleanup(pipeline_task_id)
