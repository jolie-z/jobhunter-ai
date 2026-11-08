"""岗位表卫生：存量去重归档 + 存活检测积压规划（v1）。

去重（本模块完整实现）：「同公司+同岗位」的存量双胞胎分组 → 保护过滤 → 影子归档
（跟进状态 = 已归档-重复，不物理删除，随时可恢复）。
存活检测（v1 只做积压规划）：统计抓取超龄仍处活跃态的岗位；分批执行器（每批20条/
条间随机休息/风控熔断/51job 排除）下一步接入 check_stale_jobs_liveness.py 的判定函数——
该脚本现有处置语义是删飞书行，与本模块「归档不删除」哲学冲突，接入时需改写处置段。

安全铁律：
- plan / execute 分离：先试运行出清单，用户确认才执行；
- 绝不物理删除；绝不碰：进行中评估（inflight_registry）、会话指针引用的记录
  （交付锚点/编辑目标）、已投递/面试中/待投递、去重白名单（job_dedup_gate，人工放行过的相似岗位）。
"""
import asyncio
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

ARCHIVE_STATUS = "已归档-重复"
# 受保护状态：这些记录哪怕重复也不归档（正主/影子都不行）
PROTECTED_STATUSES = ("已投递", "面试中", "Offer", "待投递", "简历人工复核", "海投人工复核")
# 存活检测的活跃态：这些状态里的超龄岗位才需要查链接是否失效
ACTIVE_STALE_STATUSES = ("新线索", "已完成初步评估", "已深度初步评估", "已完成深度评估", "疑似重复")
STALE_DAYS = 30


def _squash(s: Any) -> str:
    return re.sub(r"[\W_]+", "", str(s or "")).lower()


def _norm_key(company: Any, job_title: Any) -> tuple[str, str]:
    return _squash(company), _squash(job_title)


def _richness(job: dict[str, Any]) -> tuple[int, str]:
    """信息完整度：有定制简历的优先，其次抓取时间新者优先。"""
    return (1 if str(job.get("ai_rewrite_json") or "").strip() else 0,
            str(job.get("fetch_time") or ""))


def _collect_protected_record_ids() -> tuple[set, set]:
    """进行中评估 + 会话指针引用的 record_id 集合。"""
    from app.automation import inflight_registry
    from app.services import resume_edit_chat

    inflight = set(inflight_registry.list_entries().keys())
    referenced = set()
    for store in (resume_edit_chat._last_delivered, resume_edit_chat._edit_target):
        for _, _raw in store.items():
            rid, _ = resume_edit_chat._read_ptr(store, _)
            if rid:
                referenced.add(rid)
    return inflight, referenced


async def plan_dedup(force: bool = True) -> dict[str, Any]:
    """去重试运行：全表分组 → 定正主 → 安全过滤，返回完整清单（只读，不改任何数据）。"""
    from app.jobs import service as jobs_service
    from app.services.job_dedup_gate import load_overrides

    jobs = await jobs_service.fetch_and_clean_all_jobs(force=force)
    overrides = load_overrides()
    inflight_ids, pointer_ids = _collect_protected_record_ids()

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for j in jobs:
        if str(j.get("follow_status") or "").strip() == ARCHIVE_STATUS:
            continue  # 已归档的不再参与分组
        key = _norm_key(j.get("company_name"), j.get("job_name"))
        if not key[0] or not key[1]:
            continue
        groups.setdefault(key, []).append(j)

    dup_groups: list[dict[str, Any]] = []
    for _key, members in groups.items():
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=_richness, reverse=True)
        leader = members_sorted[0]
        shadows = []
        for m in members_sorted[1:]:
            rid = str(m.get("record_id") or "")
            protected = None
            st = str(m.get("follow_status") or "").strip()
            if st in PROTECTED_STATUSES:
                protected = f"状态受保护（{st}）"
            elif rid in inflight_ids:
                protected = "评估进行中"
            elif rid in overrides:
                protected = "去重白名单（人工放行过）"
            elif rid in pointer_ids:
                protected = "会话上下文引用中"
            shadows.append({
                "record_id": rid,
                "company": m.get("company_name"),
                "job_title": m.get("job_name"),
                "platform": m.get("platform"),
                "follow_status": st,
                "protected_reason": protected,
            })
        dup_groups.append({
            "company": leader.get("company_name"),
            "job_title": leader.get("job_name"),
            "leader_record_id": str(leader.get("record_id") or ""),
            "leader_has_resume": bool(str(leader.get("ai_rewrite_json") or "").strip()),
            "shadows": shadows,
            "archivable": [s for s in shadows if not s["protected_reason"]],
            "protected_shadows": [s for s in shadows if s["protected_reason"]],
        })

    archivable = [s for g in dup_groups for s in g["archivable"]]
    return {
        "total_jobs": len(jobs),
        "group_count": len(dup_groups),
        "archivable_count": len(archivable),
        "protected_count": len(dup_groups) * 0 + sum(len(g["protected_shadows"]) for g in dup_groups),
        "groups": sorted(dup_groups, key=lambda g: -len(g["shadows"])),
        "archivable_record_ids": [s["record_id"] for s in archivable],
    }


async def execute_dedup(confirmed: bool = False) -> dict[str, Any]:
    """执行归档：把可归档影子的跟进状态改为「已归档-重复」。必须显式 confirmed=True（用户同意后）。"""
    if not confirmed:
        return {"executed": False, "reason": "未经确认；请先把 plan 清单展示给用户并取得同意"}
    from app.core.config import settings
    from app.core.feishu_client import feishu_client

    plan = await plan_dedup()
    results = []
    ok = fail = 0
    for group in plan["groups"]:
        for shadow in group["archivable"]:
            rid = shadow["record_id"]
            try:
                await feishu_client.update_record(
                    settings.FEISHU_TABLE_ID_JOBS, rid, {"跟进状态": ARCHIVE_STATUS})
                results.append({"record_id": rid, "company": shadow["company"],
                                "job_title": shadow["job_title"], "ok": True})
                ok += 1
            except Exception as e:
                results.append({"record_id": rid, "ok": False, "error": str(e)[:120]})
                fail += 1
            await asyncio.sleep(0.5)  # 温和速率，别把飞书 API 打满
    return {"executed": True, "archived": ok, "failed": fail, "results": results,
            "plan_group_count": plan["group_count"]}


def _parse_time(s: str) -> float:
    """兼容常见抓取时间格式，解析失败返回 0（不计入超龄统计）。"""
    s = str(s or "").strip()
    if not s:
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return 0.0


async def plan_liveness_backlog() -> dict[str, Any]:
    """存活检测积压规划（只读）：抓取超龄仍处活跃态的岗位按平台分列。

    v1 只出规划不执行——分批执行器（每批20条/条间随机休息/风控熔断/51job排除）待接入
    check_stale_jobs_liveness.py 判定函数并改写其「删行」处置为「标已下架」后启用。
    """
    from app.jobs import service as jobs_service

    jobs = await jobs_service.fetch_and_clean_all_jobs()
    cutoff = time.time() - STALE_DAYS * 86400
    by_platform: dict[str, int] = {}
    total = 0
    for j in jobs:
        if str(j.get("follow_status") or "").strip() not in ACTIVE_STALE_STATUSES:
            continue
        ts = _parse_time(j.get("fetch_time"))
        if not ts or ts > cutoff:
            continue
        total += 1
        platform = str(j.get("platform") or "未知").strip()
        by_platform[platform] = by_platform.get(platform, 0) + 1
    batches = (total + 19) // 20  # 每批20条
    return {
        "stale_days_threshold": STALE_DAYS,
        "backlog_total": total,
        "by_platform": dict(sorted(by_platform.items(), key=lambda kv: -kv[1])),
        "planned_batches": batches,
        "note": "v1 仅规划；执行器按每批20条/条间随机休息/风控熔断运行，51job 平台排除（风控最敏感）",
    }


async def hygiene_report() -> dict[str, Any]:
    """总入口「体检」（只读）：去重清单 + 存活积压，供 ChatAgent / 页面展示。"""
    dedup = await plan_dedup()
    liveness = await plan_liveness_backlog()
    return {
        "generated_at": int(time.time()),
        "dedup": {
            "group_count": dedup["group_count"],
            "archivable_count": dedup["archivable_count"],
            "protected_count": dedup["protected_count"],
            "groups": [
                {
                    "name": f"{g['company']} · {g['job_title']}",
                    "leader_record_id": g["leader_record_id"],
                    "archivable": g["archivable"],
                    "protected": g["protected_shadows"],
                }
                for g in dedup["groups"]
            ],
        },
        "liveness": liveness,
    }


def summarize_report(report: dict[str, Any]) -> str:
    """体检报告 → 人类可读摘要（中文）。"""
    d, liv = report["dedup"], report["liveness"]
    lines = ["🧹 岗位表体检结果：",
             f"① 重复岗位：{d['group_count']} 组，可归档 {d['archivable_count']} 条"
             f"（受保护跳过 {d['protected_count']} 条）"]
    for g in d["groups"][:8]:
        lines.append(f"   - {g['name']}：{len(g['archivable']) + len(g['protected'])} 条重复"
                     f"（可归档 {len(g['archivable'])}）")
    if len(d["groups"]) > 8:
        lines.append(f"   - …还有 {len(d['groups']) - 8} 组")
    lines.append(f"② 过期岗位积压：{liv['backlog_total']} 条超{liv['stale_days_threshold']}天未动"
                 f"（按平台：{json.dumps(liv['by_platform'], ensure_ascii=False)}），"
                 f"按每批20条约需 {liv['planned_batches']} 批查完")
    lines.append("归档 = 改跟进状态为「已归档-重复」，绝不物理删除，随时可恢复。")
    return "\n".join(lines)


# ==========================================
# 存活检测分批执行器（v1）
# 设计四道防风控闸：每批默认20条、条间随机休息（20~60秒）、风控熔断（登录态失效/连续异常即停）、
# 51job 平台排除（风控最敏感）。处置继承判死标准但弃用脚本的「删飞书行」——
# 改为飞书标「已下架」+ SQLite 标「已确认淘汰」（防再同步复活），符合「归档不删除」哲学。
# 判定函数复用已提交的 scripts/check_stale_jobs_liveness.py（懒加载，运行在常驻浏览器会话上）。
# ==========================================

LIVE_BATCH_LIMIT = 20
LIVE_SLEEP_RANGE = (20.0, 60.0)
LIVE_PLATFORMS = ("boss", "zhilian", "liepin")  # 51job 排除
# 批级持锁硬时长上限（外审 round3-P1-3' / round4-P1-2'''）：单条最坏 ≈38s + 间隔
# 20-60s，20 条可达 33 分钟——期间引擎波次每轮撞 [环境] 会消耗重试预算
# （MAX_AUTO_RETRIES=2 耗尽后岗位出列等人工）。240s 硬顶（< 投递闸门 300s 超时）：
# 一批持锁期间同平台投递至多撞 1 次超时，第 2 次重试必然发生在批结束后；到点未检
# 完的岗位按「无法判定」保留，下批再检。间隔 sleep 前也复查 deadline，避免
# 「240s + 最后一次 sleep 60s」越过 300s（见 _liveness_worker_inner）。
LIVENESS_MAX_HOLD_SECONDS = 240.0
_CIRCUIT_SESSION_FAILS = 2  # 连续登录态失效 → 熔断
_CIRCUIT_ERRORS = 5         # 连续检测异常 → 熔断

_liveness_state: dict[str, Any] = {
    "running": False, "platform": "", "total": 0, "done": 0,
    "alive": 0, "dead": 0, "unknown": 0, "aborted": "",
    "started_epoch": 0.0, "finished_epoch": 0.0, "log": [],
}

_PLATFORM_KEY_MATCH = {"boss": "boss", "zhilian": "智联", "liepin": "猎聘"}
_PLATFORM_CN = {"boss": "BOSS直聘", "zhilian": "智联招聘", "liepin": "猎聘"}


def _liveness_script():
    """懒加载已提交的判定脚本模块（backend 上两级 = 仓库根/scripts）。"""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "scripts" / "check_stale_jobs_liveness.py"
    if not path.exists():
        raise RuntimeError(f"存活检测脚本不存在: {path}")
    spec = importlib.util.spec_from_file_location("check_stale_jobs_liveness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sqlite_db_path() -> str:
    from pathlib import Path

    from app.core.db_paths import job_hunter_db_path
    return str(job_hunter_db_path(Path(__file__).resolve().parents[2] / "data" / "job_hunter.db"))


def _mark_sqlite_dead(record_id: str) -> int:
    """SQLite 行标「已确认淘汰」（防再同步复活），数据行保留。返回受影响行数。"""
    import sqlite3

    with sqlite3.connect(_sqlite_db_path()) as conn:
        cur = conn.execute(
            "UPDATE raw_jobs SET process_status = '已确认淘汰' WHERE feishu_record_id = ?",
            (record_id,))
        conn.commit()
        return cur.rowcount


def _platform_match(job_platform: str, platform: str) -> bool:
    return _PLATFORM_KEY_MATCH.get(platform, "\0") in str(job_platform or "").lower()


async def _stale_jobs_for_platform(platform: str, limit: int) -> list[dict[str, Any]]:
    """该平台超龄+活跃态+有链接的待检岗位（计划器的执行版：直接给批次名单）。"""
    from app.jobs import service as jobs_service

    jobs = await jobs_service.fetch_and_clean_all_jobs()
    cutoff = time.time() - STALE_DAYS * 86400
    candidates = []
    for j in jobs:
        if str(j.get("follow_status") or "").strip() not in ACTIVE_STALE_STATUSES:
            continue
        if not _platform_match(j.get("platform"), platform):
            continue
        ts = _parse_time(j.get("fetch_time"))
        if not ts or ts > cutoff:
            continue
        if not str(j.get("job_link") or "").strip():
            continue
        candidates.append(j)
    candidates.sort(key=_richness)  # 信息最少的先检（正主最可能还有效，放后面）
    return candidates[:limit]


async def start_liveness_batch(platform: str = "", limit: int = LIVE_BATCH_LIMIT) -> dict[str, Any]:
    """启动一批存活检测（后台执行）。platform 空则自动选积压最多的支持平台。"""
    if _liveness_state["running"]:
        return {"started": False, "reason": "已有一批存活检测在跑，用 check_liveness_progress 查进度"}
    platform = (platform or "").strip().lower()
    if platform not in LIVE_PLATFORMS:
        if platform:
            return {"started": False, "reason": f"平台 {platform} 不支持（v1 仅支持 {'/'.join(LIVE_PLATFORMS)}；51job 风控最敏感已排除）"}
        # 自动选积压最多的支持平台
        backlog = await plan_liveness_backlog()
        by_platform = backlog["by_platform"]
        platform = max(LIVE_PLATFORMS, key=lambda p: by_platform.get(_PLATFORM_CN[p], 0))
    jobs = await _stale_jobs_for_platform(platform, max(1, min(limit, LIVE_BATCH_LIMIT)))
    if not jobs:
        return {"started": False, "reason": f"{_PLATFORM_CN.get(platform, platform)} 没有待检的过期岗位（全部有链接且超龄活跃才检）"}

    _liveness_state.update(
        running=True, platform=platform, total=len(jobs), done=0,
        alive=0, dead=0, unknown=0, aborted="",
        started_epoch=time.time(), finished_epoch=0.0, log=[],
    )
    task = asyncio.create_task(_liveness_worker(jobs, platform))
    _liveness_state["task"] = task  # 留句柄：测试可 join，进程内可观察
    return {"started": True, "platform": _PLATFORM_CN.get(platform, platform), "total": len(jobs),
            "note": "后台检测中（每条之间休息20~60秒防风控），用 check_liveness_progress 查进度"}


def _schedule_aux_release(platform: str, owner: str, token: str) -> None:
    """在当前循环里按 token 释放 aux（回调/兜底路径）；循环已关闭则放弃（进程收尾）。"""
    import asyncio as _aio

    from app.automation import platform_mutex

    try:
        loop = _aio.get_running_loop()
    except RuntimeError:
        return
    try:
        loop.create_task(platform_mutex.release_auxiliary(platform, owner=owner, token=token))
    except RuntimeError:
        # 循环正在关闭：进程即将退出，登记随进程清零
        return


async def _release_aux_after_threads(platform: str, owner: str, token: str,
                                     pending: set) -> None:
    """等所有在飞检测线程结束后再释放 aux（round5-P1-3）。

    存活检测的同步判定跑在 to_thread 里：协程被取消只中断 await，线程仍可能在
    page.get。若此刻释放 aux，引擎闸门会立即进入并撞上残留线程——与本次事故同源。
    因此批次收尾必须先 await 全部 pending 线程；若收尾本身被二次取消，则把释放
    挂到线程完成回调上（绝不在线程结束前放锁）。
    """
    import asyncio as _aio

    from app.automation import platform_mutex

    if pending:
        waiter = _aio.gather(*pending, return_exceptions=True)
        try:
            await _aio.shield(waiter)
        except _aio.CancelledError:
            # 二次取消（进程收尾等）：线程还在跑——释放挂到线程完成回调，绝不放早
            waiter.add_done_callback(
                lambda _f: _schedule_aux_release(platform, owner, token))
            raise
    await _aio.shield(platform_mutex.release_auxiliary(platform, owner=owner, token=token))


async def _run_tracked_thread(pending: set, fn, *args):
    """在线程池执行同步浏览器操作，并把 future 登记到 pending（round5-P1-3）。

    用 shield 等待：协程取消时 future 不被取消、线程继续跑并留在 pending 集合里，
    批次收尾 await 到线程自然结束才释放 aux。
    """
    import asyncio as _aio

    loop = _aio.get_running_loop()
    fut = loop.run_in_executor(None, fn, *args)
    pending.add(fut)
    fut.add_done_callback(pending.discard)
    return await _aio.shield(fut)


async def _liveness_worker(jobs: list, platform: str) -> None:
    state = _liveness_state
    log = state["log"]

    # 外审 round4 R9 收口：存活检测与抓取/投递引擎共用同平台浏览器，批级拿互斥闸门
    # （整个批次持有——逐条间 20~60s 休息也在持锁期内，避免条间空隙被引擎钻入后
    # 批内后续条目反被自己的闸门卡住）。批次整体作为 aux 阻塞位，抓取/投递/
    # 死链预检在它持锁期间排队；它自己也等引擎清场（超时按整批取消，逐条语义 =
    # 「无法判定保留岗位」，无破坏性副作用）。批时长受 LIVENESS_MAX_HOLD_SECONDS
    # 硬顶（round3-P1-3'：引擎重试预算不被长批耗尽）。
    from app.automation import platform_mutex
    try:
        _liveness_token = await platform_mutex.acquire_auxiliary(platform, owner=f"liveness:{platform}",
                                                                 timeout_s=platform_mutex.AUXILIARY_WAIT_TIMEOUT_S)
        if not _liveness_token:
            # 原因按实际占用槽精确生成（round1-P2）：可能被投递/抓取/另一批存活检测占用
            blockers = [name for name, kind in (("投递", "deliver"), ("抓取", "scrape"),
                                                ("另一批存活检测", "aux"))
                        if platform_mutex._state(platform_mutex.normalize_platform(platform))[kind] is not None]
            reason = "、".join(blockers) or "其他浏览器操作"
            state["aborted"] = f"{reason}进行中，本次存活检测取消（岗位全部保留，可稍后重试）"
            log.append(f"⏭️ {state['aborted']}")
            logger.warning(f"[岗位卫生] 存活检测取消：{platform} 占用者=[{reason}]，避免抢浏览器")
            return
        pending: set = set()
        try:
            remaining = await _liveness_worker_inner(
                jobs, platform, state,
                deadline=time.time() + LIVENESS_MAX_HOLD_SECONDS, pending=pending)
            if remaining:
                log.append(f"⏱️ 达 {LIVENESS_MAX_HOLD_SECONDS // 60:.0f} 分钟批上限，剩余 {len(remaining)} 条未检（岗位保留，可再触发补检）")
                state["aborted"] = state["aborted"] or f"达批时长上限，剩余 {len(remaining)} 条未检（岗位保留）"
        except Exception as e:
            state["aborted"] = state["aborted"] or f"执行异常中止: {str(e)[:120]}"
            logger.exception(f"[岗位卫生] 存活检测批次异常: {e}")
        finally:
            # round5-P1-3：先等所有在飞检测线程结束，再释放 aux——取消路径若提前放锁，
            # 引擎闸门会立即进入并与仍在 page.get 的线程共用浏览器（本次事故同源）。
            # 释放本身走 shield（round1-P1-4），token 精确校验（round3-P1-2）。
            try:
                await _release_aux_after_threads(
                    platform, owner=f"liveness:{platform}", token=_liveness_token,
                    pending=pending)
            except Exception as e:
                logger.warning(f"[岗位卫生] 释放辅助闸门异常（按超时自愈兜底）: {e}")
    finally:
        # 外审 A3-P1：running/finished_epoch 的复位统一放最外层 finally（aux 释放与
        # 线程收尾完成之后）。原先留在 inner finally 有两个洞：acquire 等待期被取消时
        # 两个 finally 都不经过，running 永久卡死 True 直至重启；批内取消仍有在飞
        # 线程时 running 提前置 False，新批次与未退出的旧批次争用共享 _liveness_state
        state["running"] = False
        state["finished_epoch"] = time.time()


async def _liveness_worker_inner(jobs: list, platform: str, state: dict,
                                 deadline: float, pending: set | None = None) -> list:
    """批内逐条检测（原逻辑）。达 deadline 即停手，返回未检测的剩余岗位列表。

    熔断计数（session_fails/err_fails）为 inner 局部状态——外层不再消费。
    pending（round5-P1-3）：所有同步判定线程的 future 登记集合，供批次收尾
    「等线程结束再释放 aux」使用。"""
    session_fails = err_fails = 0
    import random

    from app.core.config import settings
    from app.core.feishu_client import feishu_client

    if pending is None:
        pending = set()
    log = state["log"]
    try:
        mod = _liveness_script()
        browser = None
        if platform in ("zhilian", "liepin"):
            browser = await _run_tracked_thread(pending, mod.get_platform_browser, platform)

        for i, job in enumerate(jobs, 1):
            # 批时长硬顶（round3-P1-3'）：到 deadline 未检的岗位整体留给下批（保留语义）
            if time.time() >= deadline:
                return jobs[i - 1:]
            link = str(job.get("job_link") or "")
            verdict, reason = None, ""
            try:
                if platform == "boss":
                    from app.automation.link_precheck import check_boss_link_sync
                    verdict = await _run_tracked_thread(pending, check_boss_link_sync, link)
                else:
                    fn = mod.check_zhilian_link if platform == "zhilian" else mod.check_liepin_link
                    verdict, reason = await _run_tracked_thread(pending, fn, browser, link)
            except Exception as e:
                reason = f"检测异常: {str(e)[:60]}"
                err_fails += 1

            state["done"] = i
            rid = str(job.get("record_id") or "")
            if verdict is True:
                state["alive"] += 1
                session_fails = 0
            elif verdict is False:
                state["dead"] += 1
                session_fails = 0
                try:
                    await feishu_client.update_record(
                        settings.FEISHU_TABLE_ID_JOBS, rid, {"跟进状态": "已下架"})
                    rowid = await _run_tracked_thread(pending, _mark_sqlite_dead, rid)
                    log.append(f"💀 已下架（飞书+SQLite{rowid or ''}）: {job.get('company_name')} · {job.get('job_name')}")
                except Exception as e:
                    log.append(f"⚠️ 死链标状态失败 {rid}: {str(e)[:80]}")
            else:
                state["unknown"] += 1
                if reason in ("未登录", "登录态失效"):
                    session_fails += 1
                else:
                    session_fails = 0
                log.append(f"🟡 无法判定: {job.get('company_name')} · {job.get('job_name')}（{reason}）")
            del log[:-30]  # 只留最近 30 条

            if session_fails >= _CIRCUIT_SESSION_FAILS:
                state["aborted"] = f"连续 {session_fails} 条登录态失效，已熔断停手（请先在页面恢复平台登录态）"
                break
            if err_fails >= _CIRCUIT_ERRORS:
                state["aborted"] = f"连续 {err_fails} 条检测异常，已熔断停手"
                break
            if i < len(jobs):
                # round5-P2：sleep 前复查 deadline——原实现只在本轮循环顶部检查，
                # 最后一次 60s 间隔会让持锁越过硬顶（240+60+38 可能 > 300s 引擎闸门）。
                # 若间隔会越过 deadline，直接停手把剩余岗位留给下批，不再空睡。
                if time.time() >= deadline:
                    return jobs[i:]
                sleep_s = random.uniform(*LIVE_SLEEP_RANGE)
                if time.time() + sleep_s >= deadline:
                    return jobs[i:]
                await asyncio.sleep(sleep_s)
        return []
    except Exception as e:
        state["aborted"] = f"执行异常中止: {str(e)[:120]}"
        logger.exception(f"[岗位卫生] 存活检测批次异常: {e}")
        return jobs[min(state.get("done", 0), len(jobs)):] if state.get("done") else list(jobs)
    # running/finished_epoch 的复位已统一移至外层 _liveness_worker 最外层 finally
    # （外审 A3-P1：inner finally 覆盖不到 acquire 等待期取消，且早于线程收尾）


def liveness_progress() -> dict[str, Any]:
    state = dict(_liveness_state)
    if state["started_epoch"]:
        state["elapsed_seconds"] = int((state.get("finished_epoch") or time.time()) - state["started_epoch"])
    else:
        state["elapsed_seconds"] = 0
    state.pop("log", None)
    return state


# ==========================================
# 疑似重复复核：逐条出母本案卷 + AI 参考意见；放行 = 改回新线索 + 进白名单
# ==========================================

SUSPECT_STATUS = "疑似重复"
# 真重复置信分层：相似度 ≥ 该值视为铁证（自动维持，不劳烦用户）；低于则属边界，需用户对比拍板
_IRON_SIMILARITY = 90
_SIM_RE = re.compile(r"综合相似度\s*(\d+)%")
_PARENT_TITLE_RE = re.compile(r"母本岗位[:：]\s*(.+)[（(]([^）)]*)[)）]")  # 贪婪：标题本身可含括号，平台取最后一对
_PARENT_LINK_RE = re.compile(r"母本链接[:：]\s*(\S+)")


def _similarity_of(dup_note: str) -> int:
    """从查重案卷提取综合相似度；缺失返回 0（按边界处理，宁给人看不给漏）。"""
    m = _SIM_RE.search(str(dup_note or ""))
    return int(m.group(1)) if m else 0


def _parent_of(dup_note: str) -> dict[str, str]:
    note = str(dup_note or "")
    t = _PARENT_TITLE_RE.search(note)
    match = _PARENT_LINK_RE.search(note)
    return {"parent_title": t.group(1).strip() if t else "",
            "parent_platform": t.group(2).strip() if t else "",
            "parent_link": match.group(1).strip() if match else ""}


async def review_duplicate_suspects() -> dict[str, Any]:
    """疑似重复复核（只读）——决策优先的三层漏斗：

    - 铁证层：相似度≥90% 且判真重复 → 自动维持，不打扰用户（摘要一句话）；
    - 建议层：AI 认为该放行 → 列出，等用户同意；
    - 边界层：相似度<90% 的真重复 / 无法判断 → 唯一需要用户拍板的部分，
      每条附「本条 vs 母本」对比（名称/平台/JD重合/链接），不回复=维持默认（真重复）。

    放行 = 改回「新线索」+ 记入去重白名单（approve_suspects 执行）。
    """
    from app.jobs import service as jobs_service

    jobs = await jobs_service.fetch_and_clean_all_jobs()
    suspects = [j for j in jobs if str(j.get("follow_status") or "").strip() == SUSPECT_STATUS]
    if not suspects:
        return {"count": 0, "items": [], "suggest_approve": [], "need_decision": [],
                "auto_kept_count": 0,
                "summary": "没有待复核的疑似重复岗位。"}

    try:
        verdicts = await _llm_verdicts(suspects)
    except Exception as e:
        logger.warning(f"[岗位卫生] AI 复核意见生成失败（按边界处理，全部交用户拍板）: {e}")
        verdicts = {}

    items = []
    for j in suspects:
        rid = str(j.get("record_id") or "")
        note = str(j.get("ai_evaluation_detail") or "")
        v = verdicts.get(rid, {})
        items.append({
            "record_id": rid,
            "company": j.get("company_name"),
            "job_title": j.get("job_name"),
            "platform": j.get("platform"),
            "salary": j.get("salary"),
            "city": j.get("city"),
            "job_link": str(j.get("job_link") or ""),
            "similarity": _similarity_of(note),
            "dup_note": note[:400],
            "parent": _parent_of(note),
            "ai_verdict": v.get("verdict") or "无法判断",
            "ai_reason": v.get("reason") or "",
        })

    def _decided(it, verdict):
        return it["ai_verdict"] == verdict

    auto_kept = [it for it in items if _decided(it, "真重复") and it["similarity"] >= _IRON_SIMILARITY]
    need_decision = [it for it in items
                     if it not in auto_kept and not _decided(it, "建议放行")]
    suggest_release = [it for it in items if _decided(it, "建议放行")]

    lines = [f"🧾 疑似重复复核：共 {len(items)} 条"]
    if auto_kept:
        lines.append(f"✅ {len(auto_kept)} 条铁证重复（相似度≥{_IRON_SIMILARITY}%）：已按真重复处理，自动继承母本结论，无需操作")
    if suggest_release:
        lines.append(f"🔵 {len(suggest_release)} 条 AI 建议放行：")
        for it in suggest_release:
            p = it["parent"]
            lines.append(f"   · {it['company']} {it['job_title']} ≈ 母本《{p['parent_title']}》"
                         f"（相似度 {it['similarity']}%）— {it['ai_reason']}；同意请回复「放行 {it['record_id'][:8]}…」或逐条指定")
    if need_decision:
        lines.append(f"🟡 {len(need_decision)} 条边界条目需要你对比拍板（不回复=默认维持真重复）：")
        for it in need_decision:
            p = it["parent"]
            lines.append(f"   · 【本条】{it['company']} {it['job_title']} | {it['salary']} | {it['city']} | {it['platform']}"
                         f" vs 【母本】《{p['parent_title']}》{p['parent_platform']} | 相似度 {it['similarity']}% | {it['ai_reason']}")
            if it["job_link"]:
                lines.append(f"     本条链接: {it['job_link']}")
    return {
        "count": len(items),
        "items": items,
        "auto_kept": auto_kept,
        "auto_kept_count": len(auto_kept),
        "suggest_approve": [it["record_id"] for it in suggest_release],
        "need_decision": need_decision,
        "summary": "\n".join(lines),
    }


async def _llm_verdicts(suspects: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """一次 LLM 调用批量给复核意见。返回 {record_id: {verdict, reason}}。"""
    from app.core.config import settings
    from app.core.llm_langchain import GovernedChatOpenAI
    from common.config import _cfg

    lines = []
    for j in suspects:
        lines.append(
            f"- record_id={j.get('record_id')} | 公司: {j.get('company_name')} | "
            f"岗位: {j.get('job_name')} | 平台: {j.get('platform')} | "
            f"薪资: {j.get('salary')} | 城市: {j.get('city')} | "
            f"查重案卷: {str(j.get('ai_evaluation_detail') or '')[:300]}")
    system = (
        "你是求职助理。下面每条岗位都被系统标为「疑似重复」（与已有岗位疑似同一机会，查重案卷里写了母本信息与相似度）。"
        "逐条判断：名称、城市、薪资、职能与母本基本一致 → verdict=真重复；"
        "名称相近但城市、薪资或职能方向明显不同 → verdict=建议放行；"
        "拿不准 → verdict=真重复（保守，避免重复评估烧 token）。"
        '只输出 JSON 数组，不要其他文字：[{"record_id":"...","verdict":"真重复或建议放行","reason":"30字内理由"}]'
    )
    model = GovernedChatOpenAI(
        model=settings.OPENAI_MODEL or "mimo-v2.5-pro",
        api_key=_cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY"),
        base_url=_cfg("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url", json_key="OPENAI_BASE_URL"),
        temperature=0, timeout=120, max_retries=2,  # TODO(Phase1): SDK max_retries 归零收敛至统一策略层
        gate_caller="job_table_hygiene",
    )
    resp = await model.ainvoke([
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    m = re.search(r"\[.*\]", content, re.S)
    if not m:
        raise ValueError(f"LLM 返回不含 JSON 数组: {content[:120]}")
    arr = json.loads(m.group(0))
    return {str(item.get("record_id")): {"verdict": str(item.get("verdict") or "无法判断"),
                                          "reason": str(item.get("reason") or "")}
            for item in arr if isinstance(item, dict)}


async def approve_suspects(record_ids: list[str]) -> dict[str, Any]:
    """放行：改回「新线索」+ 记入去重白名单（此后所有查重关卡不再拦截，岗位可正常评估）。"""
    from app.core.config import settings
    from app.core.feishu_client import feishu_client
    from app.services.job_dedup_gate import record_dedup_override

    results = []
    for rid in record_ids:
        rid = str(rid or "").strip()
        if not rid:
            continue
        try:
            await feishu_client.update_record(
                settings.FEISHU_TABLE_ID_JOBS, rid, {"跟进状态": "新线索"})
            record_dedup_override(rid)
            results.append({"record_id": rid, "approved": True})
        except Exception as e:
            results.append({"record_id": rid, "approved": False, "error": str(e)[:120]})
    ok = sum(1 for r in results if r["approved"])
    return {"approved": ok, "failed": len(results) - ok, "results": results}
