"""
全链路抓取阶段执行器
====================
负责：
- 搜索参数推导（per-platform 配置推导统一搜索单）
- 孤儿抓取任务兜底收尾清理
- 全自动链路中的「平台抓取」阶段（execute_pipeline_scrape）
- 单独执行「平台抓取」阶段（run_scrape_stage_only / _execute_scrape_only）
"""
import asyncio
import logging
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.automation import pipeline_broadcast as pb
from app.automation.db import get_autopilot_config

logger = logging.getLogger(__name__)

PLATFORM_CN = {
    "boss": "BOSS直聘",
    "liepin": "猎聘",
    "51job": "51job",
    "zhilian": "智联招聘",
    "xiaohongshu": "小红书",
}


def _get_raw_db_path() -> str:
    import sys
    fa = sys.modules.get("app.automation.full_auto")
    if fa and hasattr(fa, "RAW_DB_PATH"):
        return fa.RAW_DB_PATH
    import os

    from app.core.db_paths import job_hunter_db_path
    return str(job_hunter_db_path(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "job_hunter.db"
    )))


def _derive_search_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """从 autopilot 的 per-platform 配置推导出一份统一搜索单。"""
    plat_configs = config.get("platform_configs", {}) or {}
    selected, keyword, city, salary, target_jobs = [], "", "广州", "不限", 0

    for platform, pcfg in plat_configs.items():
        if isinstance(pcfg, (int, float)):
            limit = int(pcfg)
            pcfg = {}
        elif isinstance(pcfg, dict):
            limit = int(pcfg.get("limit", 0) or 0)
        else:
            continue
        if limit <= 0:
            continue
        selected.append(platform)
        if not keyword and pcfg.get("keyword"):
            keyword = pcfg["keyword"]
        if pcfg.get("city") and pcfg["city"] != "全国" and city == "广州":
            city = pcfg["city"]
        if pcfg.get("salary") and pcfg["salary"] != "不限" and salary == "不限":
            salary = pcfg["salary"]
        target_jobs = max(target_jobs, limit)

    return {
        "keyword": keyword or "招聘",
        "city": city,
        "salary": salary,
        "target_jobs": target_jobs,
        "platforms": selected,
    }


def _resolve_platform_limits(
    scrape_cfg: dict[str, Any],
    search: dict[str, Any],
    override_limit: int | None = None,
) -> dict[str, int]:
    """解析本轮各平台预算。

    2026-10-30 修复：
    - 抓取配置里只要存在 platforms 段，就以它为准；enabled=false 或 limit<=0 都算关闭。
      这样「把平台全部关掉」不会被 autopilot 的 search 平台静默复活。
    - 只有配置里完全没有 platforms 段（老数据/首次运行）才回落到 autopilot 搜索单。
    """
    sc_plats = (scrape_cfg or {}).get("platforms") or {}
    if sc_plats:
        out: dict[str, int] = {}
        for key, conf in sc_plats.items():
            # 缺省 enabled 视为开（有 limit 即意图抓取）；旧实现视为关，属有意修正
            if not isinstance(conf, dict) or not conf.get("enabled", True):
                continue
            limit = int(conf.get("limit", 0) or 0)
            if limit <= 0:
                continue
            out[key] = int(override_limit) if override_limit and int(override_limit) > 0 else limit
        return out
    base = int(override_limit) if override_limit and int(override_limit) > 0 else int(search.get("target_jobs") or 3)
    return dict.fromkeys(search.get("platforms") or [], base)


def _order_active_conditions(active: list[tuple]) -> list[tuple]:
    """公平轮巡排序：最久没跑过的条件优先；同时间按队列顺序。"""
    return sorted(active, key=lambda row: (row[4].get("last_run") or "", row[0]))


async def _run_platform_condition_worker(
    p: str,
    *,
    pipeline_task_id: str,
    queue: list[dict[str, Any]],
    budgets: dict[str, int],
    default_city: str,
    default_salary: str,
    start_rowid: int,
    count_new,
    emit_scraped_jobs,
    budget_label: str,
) -> None:
    """单平台 worker：公平轮巡队列里的未抓尽条件。

    2026-10-30 重构：
    - 不再「队首条件吃满整轮预算」。每轮把预算均分给所有未抓尽条件，至少 1 条/条件；
      条件按 last_run 升序排序（最久没跑的优先），因此 cap < 条件数 时也会逐轮轮换，
      不会出现队首永远复活、后面条件饿死。
    - 抓尽判定改用台账持久状态（hit_bottom / 连续0新增 / TTL），不再用单轮内存集合。
    """
    from app.api.routes.crawlers import run_dispatch_collect, running_platform_tasks
    from app.automation import abort as abort_mod
    from app.automation import platform_mutex
    from app.session.scrape_sessions import get_condition_state

    cap = int(budgets.get(p, 0) or 0)
    cn = PLATFORM_CN.get(p, p)
    zero_new_seen: set[int] = set()  # 本平台本轮「成功但 0 新增」的条件，下一轮跳过

    def _triple(item: dict[str, Any]):
        return (
            (item.get("keyword") or "").strip(),
            (item.get("city") or "").strip() or default_city,
            (item.get("salary") or "").strip() or default_salary,
        )

    try:
        while cap > 0 and not abort_mod.is_aborted() and not abort_mod.is_platform_aborted(p):
            active = []
            for idx, item in enumerate(queue):
                if idx in zero_new_seen:
                    continue
                kw, c, s = _triple(item)
                state = await asyncio.to_thread(get_condition_state, kw, c, s, p)
                if not state.get("exhausted"):
                    active.append((idx, kw, c, s, state))
            if not active:
                await pb.emit_log(pipeline_task_id, f"✅ [{cn}] 所有条件均已抓尽或本轮无新增，本平台本轮收工")
                break

            # 公平轮巡：最久没跑过的条件优先；同轮内按剩余预算均分
            active = _order_active_conditions(active)
            per_cond = max(1, cap // len(active))
            progressed = False

            for idx, kw, c, s, state in active:
                if cap <= 0 or abort_mod.is_aborted() or abort_mod.is_platform_aborted(p):
                    break
                scraped = int(state.get("scraped") or 0)
                predicted = int(state.get("predicted") or 0)
                remaining = max(1, predicted - scraped) if predicted > 0 else per_cond
                target = max(1, min(cap, per_cond, remaining))

                # 平台级抓取↔投递互斥：派发前冷静等待同平台投递清场（最长 10 分钟）。
                # 外审 R2-P1-1：条件变量等待不感知终止标志——按 1s 切片轮询终止标志
                # （全局/单平台终止后 ≤1s 退出等待，不再挂满 10 分钟），且清场返回后、
                # 派发前重检终止标志，绝不给已终止的链路幽灵拉起新一轮浏览器抓取
                cleared = False
                clear_deadline = time.monotonic() + platform_mutex.SCRAPE_WAIT_DELIVERY_TIMEOUT_S
                while not (abort_mod.is_aborted() or abort_mod.is_platform_aborted(p)):
                    if await platform_mutex.wait_delivery_clear(p, timeout_s=1.0):
                        cleared = True
                        break
                    if time.monotonic() >= clear_deadline:
                        break
                if abort_mod.is_aborted() or abort_mod.is_platform_aborted(p):
                    await pb.emit_log(pipeline_task_id, f"🛑 [{cn}] 投递清场等待期间收到终止指令，本轮抓取取消")
                    return
                if not cleared:
                    await pb.emit_log(
                        pipeline_task_id,
                        f"⏭️ [{cn}] 投递进行中且超 10 分钟未清场，本轮抓取跳过（下轮波次/续抓自动补上）", "error")
                    return
                if any(not t.done() for t in running_platform_tasks.get(p, ())):
                    await pb.emit_log(
                        pipeline_task_id,
                        f"⚠️ [{cn}] 上一轮抓取任务未结束，本轮放弃新派发以避免并发超抓", "error")
                    return

                base = (await asyncio.to_thread(count_new)).get(cn, 0)
                await run_dispatch_collect(
                    keyword=kw, city=c, salary=s, target_jobs=target,
                    platforms=[p], master_task_id=pipeline_task_id,
                    platform_search={p: {"keyword": kw, "city": c, "salary": s, "target": target}},
                )
                inserted = (await asyncio.to_thread(count_new)).get(cn, 0) - base
                cap -= max(0, inserted)
                if inserted > 0:
                    progressed = True
                    await emit_scraped_jobs(pipeline_task_id, start_rowid, p, cn)
                else:
                    zero_new_seen.add(idx)

                new_state = await asyncio.to_thread(get_condition_state, kw, c, s, p)
                ttl_txt = (
                    f"{new_state['scraped']}/{new_state['predicted']}"
                    if new_state["predicted"] > 0 else f"{new_state['scraped']}/分母待获取"
                )
                exhausted_txt = " | 已抓尽" if new_state.get("exhausted") else ""
                await pb.emit_log(
                    pipeline_task_id,
                    f"🕷️ [{cn}] 条件「{kw}」本轮 +{inserted} | 累计进度 {ttl_txt} | {budget_label} {cap}{exhausted_txt}",
                )

            if not progressed:
                break
        if abort_mod.is_platform_aborted(p):
            await pb.emit_log(pipeline_task_id, f"🛑 [{cn}] 已按指令终止")
    except Exception as we:
        logger.error(f"[FullAuto] 平台 {p} 抓取 worker 异常: {we}", exc_info=True)
        await pb.emit_log(pipeline_task_id, f"⚠️ [{cn}] 抓取异常: {we}", "error")


async def _reap_orphan_scrapers(pipeline_task_id: str, timeout: float = 30.0) -> None:
    """收尾点名：对仍有未结束抓取任务的平台拉急刹并限时等其退出。"""
    from app.api.routes.crawlers import running_platform_tasks, stop_platform

    for platform, tasks in list(running_platform_tasks.items()):
        alive = [t for t in tasks if not t.done()]
        if not alive:
            continue
        logger.warning(f"[FullAuto] 清理孤儿抓取任务: {platform} x{len(alive)}")
        await pb.emit_log(
            pipeline_task_id,
            f"🧹 [{platform}] 检测到未结束的抓取任务，已拉急刹并等待退出…", "error")
        stop_platform(platform)
        await asyncio.wait(alive, timeout=timeout)


async def _emit_scraped_jobs(pipeline_task_id: str, start_rowid: int, platform: str, cn: str) -> None:
    """查询并向 SSE 广播本轮新增入库的抓取岗位卡片。"""
    def _fetch():
        with sqlite3.connect(_get_raw_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT rowid, platform, job_title, company_name, salary, city, job_link FROM raw_jobs WHERE rowid > ? AND (platform = ? OR platform = ?) ORDER BY rowid ASC",
                    (start_rowid, platform, cn),
                ).fetchall()
            ]
    rows = await asyncio.to_thread(_fetch)
    for nj in rows:
        await pb.emit_job(
            pipeline_task_id,
            job_id=f"raw_{nj['rowid']}",
            job_name=nj.get("job_title") or "未知岗位",
            node="scrape_node",
            status="scraped",
            platform=nj.get("platform") or cn,
            company_name=nj.get("company_name") or "",
            salary=nj.get("salary") or "",
            city=nj.get("city") or "",
            job_url=nj.get("job_link") or "",
        )


async def execute_pipeline_scrape(
    pipeline_task_id: str,
    search: dict[str, Any],
    on_start: Callable[[int], Awaitable[None]] | None = None,
    on_rows_inserted: Callable[[], None] | None = None,
) -> tuple[int, dict[str, int], list[str]]:
    """执行全自动链路中的「平台抓取」阶段。

    on_start(start_rowid)：拿到本轮权威起始 rowid 后、派发抓取前回调
    （编排器用它启动抓取期清洗泵；start_rowid 由本函数查库确定，避免调用方
    提前查库与手动抓取并发插入产生边界漂移）。
    on_rows_inserted()：任一平台本轮有新行入库并已广播卡片后回调
    （唤醒清洗泵，缩短「入库→开始清洗」延迟）。
    """
    await pb.emit_stage(pipeline_task_id, "scraping", "running")

    from app.automation import run_snapshot as run_snapshot_mod
    from app.pipeline import add_keyword_history, get_scrape_config
    from app.session.preflight import ensure_platforms_ready
    from app.session.scrape_sessions import get_condition_progress

    with sqlite3.connect(_get_raw_db_path()) as _c:
        start_rowid = _c.execute("SELECT IFNULL(MAX(rowid),0) FROM raw_jobs").fetchone()[0]

    def _count_new():
        with sqlite3.connect(_get_raw_db_path()) as _c:
            return dict(_c.execute(
                "SELECT platform, COUNT(*) FROM raw_jobs WHERE rowid > ? GROUP BY platform",
                (start_rowid,)).fetchall())

    scrape_cfg = get_scrape_config() or {}
    queue = [k for k in (scrape_cfg.get("keywords") or []) if (k.get("keyword") or "").strip()]
    limits_map = _resolve_platform_limits(scrape_cfg, search)

    ready_map = await ensure_platforms_ready(
        list(limits_map.keys()),
        emit_log=lambda msg: pb.emit_log(pipeline_task_id, msg),
    )
    disabled_platforms = [p for p, ok in ready_map.items() if not ok]
    if disabled_platforms:
        for p in disabled_platforms:
            limits_map.pop(p, None)
        await pb.emit_log(
            pipeline_task_id,
            "⚠️ 本轮跳过失效平台: "
            + "、".join(PLATFORM_CN.get(p, p) for p in disabled_platforms)
            + "（无新抓取，本次任务也不会投递这些平台的岗位）",
            "error",
        )

    budgets = dict(limits_map)
    default_city = (scrape_cfg.get("default_city") or "").strip() or search["city"]
    default_salary = (scrape_cfg.get("default_salary") or "").strip() or search["salary"]
    run_snapshot_mod.begin(pipeline_task_id, start_rowid, budgets, disabled_platforms)

    if on_start is not None:
        try:
            # begin() 之后再启动清洗泵：泵内推送会 register_record_ids，
            # begin 会重置 record_ids，必须在重置完成后才允许登记。
            await on_start(int(start_rowid))
        except Exception as e:
            # 回调只服务流式清洗，任何异常不得阻断抓取
            logger.warning(f"[FullAuto] 抓取启动回调异常（不阻断抓取）: {e}")

    if not queue:
        queue = [{"keyword": search["keyword"], "city": "", "salary": ""}]

    def _cond_triple(item):
        return (
            (item.get("keyword") or "").strip(),
            (item.get("city") or "").strip() or default_city,
            (item.get("salary") or "").strip() or default_salary,
        )

    def _cond_scraped_sum(item):
        kw, c, s = _cond_triple(item)
        return sum(get_condition_progress(kw, c, s, p)[0] for p in budgets)

    history_baseline = {i: _cond_scraped_sum(item) for i, item in enumerate(queue)}

    if not budgets:
        await pb.emit_log(pipeline_task_id, "⚠️ 无可用抓取平台（limit 均为 0 或登录态全部失效），跳过抓取段", "error")
    else:
        async def _emit_and_wake(pid: str, sr: int, platform: str, cn: str) -> None:
            """先广播抓取卡，再唤醒清洗泵：保证前端先收到 scraped 事件，卡片不会倒序。"""
            try:
                await _emit_scraped_jobs(pid, sr, platform, cn)
            finally:
                if on_rows_inserted is not None:
                    try:
                        on_rows_inserted()
                    except Exception as wake_e:
                        logger.warning(f"[FullAuto] 清洗泵唤醒回调异常（不阻断抓取）: {wake_e}")

        await pb.emit_log(
            pipeline_task_id,
            f"🕷️ 条件队列 {len(queue)} 组 × 平台 {list(budgets)}"
            "（抓尽制：到平台底部 / 连续0新增 / 分母追平即抓尽；预算在未抓尽条件间均分轮巡，limit 为本任务上限）")
        worker_results = await asyncio.gather(
            *[
                _run_platform_condition_worker(
                    p,
                    pipeline_task_id=pipeline_task_id,
                    queue=queue,
                    budgets=budgets,
                    default_city=default_city,
                    default_salary=default_salary,
                    start_rowid=start_rowid,
                    count_new=_count_new,
                    emit_scraped_jobs=_emit_and_wake,
                    budget_label="本任务剩余上限",
                )
                for p in list(budgets)
            ],
            return_exceptions=True,
        )
        for p, r in zip(list(budgets), worker_results, strict=False):
            if isinstance(r, Exception):
                logger.error(f"[FullAuto] 平台 {p} worker 抛出: {r}", exc_info=True)

        await _reap_orphan_scrapers(pipeline_task_id)

        for idx, item in enumerate(queue):
            delta = _cond_scraped_sum(item) - history_baseline.get(idx, 0)
            if delta > 0:
                kw, c, s = _cond_triple(item)
                try:
                    await asyncio.to_thread(
                        add_keyword_history, kw, c, s, delta, "auto", pipeline_task_id)
                except Exception as _hist_e:
                    logger.warning(f"[FullAuto] 条件历史写入失败（不阻断链路）: {_hist_e}")

    scrape_counts_cn = await asyncio.to_thread(_count_new)
    total_new = sum(scrape_counts_cn.values())
    await pb.emit_log(pipeline_task_id, f"🕷️ 抓取段结束：本轮共新增 {total_new} 条")
    await pb.emit_stage(pipeline_task_id, "scraping", "done")
    return start_rowid, scrape_counts_cn, disabled_platforms


async def run_scrape_stage_only(
    platforms_limit: int | None = None,
    keyword: str | None = None,
    city: str | None = None,
    salary: str | None = None,
    platforms: list[str] | None = None,
) -> str:
    """单独执行「平台抓取」阶段（不进入规则清洗、AI评估与自动投递），立即返回 pipeline_task_id。"""
    cur = pb.get_current_pipeline()
    if cur.get("running"):
        raise RuntimeError(f"已有链路正在运行中（{cur.get('task_id')}），请等待其完成或先终止后再启动")
    pipeline_task_id = f"scrape_{uuid.uuid4().hex[:8]}"
    pb.create_pipeline_queue(pipeline_task_id)
    pb.set_current_pipeline(pipeline_task_id, True)

    from app.automation import abort as abort_mod
    abort_mod.begin_pipeline(pipeline_task_id)

    config = get_autopilot_config()
    derived = _derive_search_from_config(config)
    search = {
        "keyword": keyword or derived["keyword"],
        "city": city or derived["city"],
        "salary": salary or derived["salary"],
        "target_jobs": platforms_limit or derived["target_jobs"] or 3,
        "platforms": platforms or derived["platforms"],
    }

    asyncio.create_task(_execute_scrape_only(pipeline_task_id, search, platforms_limit))
    return pipeline_task_id


async def _execute_scrape_only(pipeline_task_id: str, search: dict[str, Any], override_limit: int | None = None):
    """独立抓取执行：前置登录检查 → 条件队列轮询 → 并发抓取 → 台账回写 → 抓取完成收尾。"""
    from app.automation import abort as abort_mod
    from app.automation import run_snapshot as run_snapshot_mod
    from app.pipeline import add_keyword_history, get_scrape_config
    from app.session.preflight import ensure_platforms_ready
    from app.session.scrape_sessions import get_condition_progress

    try:
        await pb.emit_log(pipeline_task_id, f"🕷️ [平台抓取 · 独立试跑] 任务已启动 | 目标平台: {search['platforms']}")
        await pb.emit_stage(pipeline_task_id, "scraping", "running")

        with sqlite3.connect(_get_raw_db_path()) as _c:
            start_rowid = _c.execute("SELECT IFNULL(MAX(rowid),0) FROM raw_jobs").fetchone()[0]

        def _count_new():
            with sqlite3.connect(_get_raw_db_path()) as _c:
                return dict(_c.execute(
                    "SELECT platform, COUNT(*) FROM raw_jobs WHERE rowid > ? GROUP BY platform",
                    (start_rowid,)).fetchall())

        scrape_cfg = get_scrape_config() or {}
        queue = [k for k in (scrape_cfg.get("keywords") or []) if (k.get("keyword") or "").strip()]
        limits_map = _resolve_platform_limits(scrape_cfg, search, override_limit)

        ready_map = await ensure_platforms_ready(
            list(limits_map.keys()),
            emit_log=lambda msg: pb.emit_log(pipeline_task_id, msg),
        )
        disabled_platforms = [p for p, ok in ready_map.items() if not ok]
        for p in disabled_platforms:
            limits_map.pop(p, None)

        budgets = dict(limits_map)
        default_city = (scrape_cfg.get("default_city") or "").strip() or search["city"]
        default_salary = (scrape_cfg.get("default_salary") or "").strip() or search["salary"]
        run_snapshot_mod.begin(pipeline_task_id, start_rowid, budgets, disabled_platforms)

        if not queue:
            queue = [{"keyword": search["keyword"], "city": default_city, "salary": default_salary}]

        def _cond_triple(item):
            return (
                (item.get("keyword") or "").strip(),
                (item.get("city") or "").strip() or default_city,
                (item.get("salary") or "").strip() or default_salary,
            )

        def _cond_scraped_sum(item):
            kw, c, s = _cond_triple(item)
            return sum(get_condition_progress(kw, c, s, p)[0] for p in budgets)

        history_baseline = {i: _cond_scraped_sum(item) for i, item in enumerate(queue)}

        if not budgets:
            await pb.emit_log(pipeline_task_id, "⚠️ 无可用抓取平台（预算均为 0 或登录失效），抓取结束", "error")
        else:
            await pb.emit_log(
                pipeline_task_id,
                f"🕷️ 条件队列 {len(queue)} 组 × 平台 {list(budgets)}"
                "（抓尽制推进：预算在未抓尽条件间均分轮巡，单平台上限为本轮预算）")
            worker_results = await asyncio.gather(
                *[
                    _run_platform_condition_worker(
                        p,
                        pipeline_task_id=pipeline_task_id,
                        queue=queue,
                        budgets=budgets,
                        default_city=default_city,
                        default_salary=default_salary,
                        start_rowid=start_rowid,
                        count_new=_count_new,
                        emit_scraped_jobs=_emit_scraped_jobs,
                        budget_label="剩余预算",
                    )
                    for p in list(budgets)
                ],
                return_exceptions=True,
            )
            for p, r in zip(list(budgets), worker_results, strict=False):
                if isinstance(r, Exception):
                    logger.error(f"[ScrapeOnly] 平台 {p} worker 抛出: {r}", exc_info=True)
            await _reap_orphan_scrapers(pipeline_task_id)

            for idx, item in enumerate(queue):
                delta = _cond_scraped_sum(item) - history_baseline.get(idx, 0)
                if delta > 0:
                    kw, c, s = _cond_triple(item)
                    try:
                        await asyncio.to_thread(add_keyword_history, kw, c, s, delta, "scrape_only", pipeline_task_id)
                    except Exception:
                        pass

        scrape_counts_cn = await asyncio.to_thread(_count_new)
        total_new = sum(scrape_counts_cn.values())
        summary_details = "、".join(f"{k} {v}条" for k, v in scrape_counts_cn.items() if v > 0) or "0条"
        await pb.emit_log(
            pipeline_task_id,
            f"🎉 [平台抓取 · 独立试跑完成] 本轮共抓取入库 {total_new} 条（{summary_details}）。\nℹ️ 仅测试平台抓取模块，后续规则清洗与AI评估已按指令跳过。")
        await pb.emit_stage(pipeline_task_id, "scraping", "done")
        await pb.emit_stage(pipeline_task_id, "done", "done")
        await pb.emit_end(pipeline_task_id, {"scraped": total_new})
    except Exception as e:
        logger.error(f"[ScrapeOnly] 任务异常: {e}", exc_info=True)
        await pb.emit_log(pipeline_task_id, f"❌ 抓取任务失败: {e}", "error")
        await pb.emit_end(pipeline_task_id, {"error": str(e)})
    finally:
        run_snapshot_mod.end()
        pb.set_current_pipeline(pipeline_task_id, False)
        abort_mod.end_pipeline()
