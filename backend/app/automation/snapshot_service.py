"""
全链路指挥中心快照数据服务
==========================
负责：
- 聚合当前任务入库、清洗淘汰岗位（SQLite）
- 聚合本轮流转中待审批、已拒绝、待投递、已投递及初评中岗位（飞书）
- 投递异常错误分诊（L1 triage）与诊断回填
- 跨段强去重（SQLite 与飞书卡片强去重）
- 产出 /jobs-snapshot 结构化数据
"""
import asyncio
import logging
import re
import sqlite3
import time
from datetime import datetime
from typing import Any

from app.automation import db as automation_db
from app.automation import pipeline_broadcast as pb
from app.automation import run_snapshot as _rs
from app.automation.snapshot_dispatch import (  # 拆分子任务：分诊/失败卡/SQLite 映射抽离（<500 行门禁）
    _SQLITE_REJECTED_STATUSES,
    _map_sqlite_process_status,
    _mass_review_reason,
    _triage_classify,
    build_failure_job,
    build_failure_suggestion,
    classify_feishu_followup,
)
from app.core import process_status
from app.core.process_status import APPROVAL_FOLLOW_STATUSES
from app.core.utils import is_greeting_supported_platform, normalize_platform_code
from app.services import feishu_service

logger = logging.getLogger(__name__)

_last_snapshot_params: tuple[Any, ...] | None = None
_last_jobs_status_sig: tuple[Any, ...] | None = None


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


# SQLite process_status → 快照卡片状态白名单映射。
# 淘汰词表以 app/core/process_status 为单一事实源（2026-10-09 事故：飞书归档写入「已淘汰」
# 不在白名单，兜底把它画成「评估中」幽灵卡）。未知值兜底为 rejected+告警文案——绝不输出
# 裸 running 或活跃近似态伪装岗位在流转（旧兜底 running+ai_eval_queued 正是幽灵卡根源；
# 词表漂移宁可显示为淘汰态让人发现，也不能让已归档岗位假装还在评估）。
_FEISHU_TERMINAL_STATUSES = {
    "delivered", "已投递", "error", "failed", "执行失败", "投递失败",
}
# 实时 running 态超过 30 分钟没有任何更新，视为崩溃遗留，不再覆盖快照
_LIVE_RUNNING_TTL_SECONDS = 30 * 60


def _live_action_desc(st: dict) -> str:
    # 文案唯一事实源在 pipeline_broadcast，避免前后端双份中文映射漂移
    return pb.node_action_desc(st.get("node"), st.get("sub_status"))


def build_live_job(st: dict) -> dict:
    """把实时登记表里的在途岗位组装成快照卡片（快照各分段都没覆盖到时兜底）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "job_id": str(st.get("job_id") or ""),
        "job_name": st.get("job_name") or "未知岗位",
        "company_name": st.get("company_name") or "",
        "platform": st.get("platform") or "",
        "salary": st.get("salary") or "",
        "city": st.get("city") or "",
        "education": st.get("education") or "",
        "experience": st.get("experience") or "",
        "job_url": st.get("job_url") or "",
        "jd_text": st.get("jd_text") or "",
        "company_scale": st.get("company_scale") or "",
        "grade": st.get("grade") or "",
        "score": st.get("score"),
        "review_type": st.get("review_type"),
        "has_rewrite": bool(st.get("has_rewrite")),
        "greeting_msg": st.get("greeting_msg") or "",
        "status": "running",
        "node": st.get("node") or "evaluate_node",
        "sub_status": st.get("sub_status"),
        "failure_info": None,
        "deep_eval_done": bool(st.get("deep_eval_done")),
        "is_current_run": True,
        "crawl_time": "",
        "last_action_time": now,
        "last_action_desc": _live_action_desc(st),
    }


def apply_live_job_overlay(jobs: list[dict], live_jobs: dict[str, dict]) -> list[dict]:
    """用进程内实时岗位态覆盖 Feishu/SQLite 派生快照。

    只覆盖 status=running 的实时项：终态（waiting/ready/delivered/error）必须让 Feishu
    权威数据获胜，否则用户放行/投递后会被旧实时态拉回。运行态则相反——Feishu 的
    「已完成初步评估 / 简历人工复核」无法表达深评/改写/打招呼/投递进行中，必须由
    SSE 实时态覆盖，否则 12 秒轮询会把卡片打回「AI初评完成 / 待审批」。
    """
    if not live_jobs:
        return jobs

    index: dict[str, dict] = {}
    for j in jobs:
        jid = str(j.get("job_id") or "")
        if jid:
            index[jid] = j
        raw_id = str(j.get("raw_job_id") or "")
        if raw_id:
            index.setdefault(raw_id, j)

    now = time.time()
    for jid, st in live_jobs.items():
        if st.get("status") != "running":
            continue
        updated_at = float(st.get("updated_at") or 0)
        if updated_at and now - updated_at > _LIVE_RUNNING_TTL_SECONDS:
            # 长时间无更新的 running 视为崩溃/丢事件遗留，不再覆盖 Feishu 快照
            continue
        jid = str(jid)
        raw_key = str(st.get("raw_job_id") or "")
        rec_target = index.get(jid)
        raw_target = index.get(raw_key) if raw_key else None
        target = rec_target or raw_target
        if target is None:
            target = build_live_job({**st, "job_id": jid})
            jobs.append(target)
            index[jid] = target
            continue

        if target.get("status") in _FEISHU_TERMINAL_STATUSES:
            # Feishu 已落终态：宁可显示终态，也不被崩溃遗留的 running 拉回运行中
            continue

        # 同一岗位已有 rec 卡：先移除 raw 卡，避免去重执行前的短暂双卡/顶卡
        if rec_target is not None and raw_target is not None and raw_target is not rec_target:
            try:
                jobs.remove(raw_target)
            except ValueError:
                pass
            index.pop(str(raw_target.get("job_id") or ""), None)
            index.pop(raw_key, None)

        target["node"] = st.get("node") or target.get("node")
        target["status"] = "running"
        target["sub_status"] = st.get("sub_status")
        if st.get("grade"):
            target["grade"] = st["grade"]
        if st.get("score") is not None:
            target["score"] = st["score"]
        if st.get("review_type"):
            target["review_type"] = st["review_type"]
        target["failure_info"] = None
        target["deep_eval_done"] = bool(st.get("deep_eval_done") or target.get("deep_eval_done"))
        target["last_action_desc"] = _live_action_desc(st)
        target["last_action_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target["is_current_run"] = True
        # 只有「仅有 raw 卡、尚无 rec 卡」时才原地升级 ID；已有 rec 卡时让 rec 卡获胜
        if target is raw_target and rec_target is None and raw_key and not jid.startswith("raw_"):
            target["job_id"] = jid
            index[jid] = target
            index.pop(raw_key, None)

    return jobs


async def build_jobs_snapshot() -> dict[str, Any]:
    """全链路指挥中心本轮岗位快照：
    - 仅查询当前任务（rowid > start_rowid）的入库与清洗淘汰岗位；
    - 仅查询当前任务进入流转（job_id in run_record_ids）的飞书岗位；
    - 彻底隔离历史存量，保证指挥中心数据 100% 纯净并与顶部轨道数字对齐；
    - 回传当前配置的动态发射时间 mass_deliver_time 与 custom_deliver_time。"""
    raw_db_path = _get_raw_db_path()
    runtime = _rs.current_runtime()
    start_rowid = int(runtime.get("start_rowid") or 0)
    run_record_ids = set(runtime.get("record_ids") or [])
    has_active_run = bool(runtime.get("started"))
    dismissed_ids = _rs.get_dismissed_job_ids()
    retrying_ids = _rs.get_retrying_job_ids()

    # 🚀 性能优化（质检 Q21）：五个飞书列表查询并发预取，墙钟从「串行求和」降为「最慢单请求」。
    # 预取结果按原段位消费（pending/rejected 仅活跃任务期拉取，与原守卫一致），
    # 各段处理逻辑与卡片产出顺序保持完全不变；单请求失败归一为 None，
    # 由下游 (结果 or []) 空安全消化，段位行为与原先「异常进 try/except 跳段」等价。
    async def _safe_fetch(label: str, coro):
        try:
            return await coro
        except Exception as e:
            logger.warning(f"jobs_snapshot 飞书并发预取失败(不阻断) [{label}]: {e}")
            return None

    _gated = bool(has_active_run and run_record_ids)

    async def _noop():
        return None

    feishu_lists = dict(zip(
        ("pending", "rejected_manual", "failed", "scheduled", "delivered"),
        await asyncio.gather(
            _safe_fetch("pending", asyncio.to_thread(feishu_service.get_pending_review_jobs_from_feishu)) if _gated else _noop(),
            _safe_fetch("rejected_manual", asyncio.to_thread(feishu_service.get_manual_rejected_jobs_from_feishu)) if _gated else _noop(),
            _safe_fetch("failed", asyncio.to_thread(feishu_service.get_failed_jobs_from_feishu)),
            _safe_fetch("scheduled", asyncio.to_thread(feishu_service.get_scheduled_delivery_jobs_from_feishu)),
            _safe_fetch("delivered", asyncio.to_thread(feishu_service.get_delivered_jobs_from_feishu, 5, True)),
        ),
        strict=True,
    ))

    jobs: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    global _last_snapshot_params, _last_jobs_status_sig
    curr_params = (runtime.get("task_id"), start_rowid, len(run_record_ids))
    if curr_params != _last_snapshot_params:
        logger.info(f"📊 [jobs_snapshot] 读取本轮快照(参数变更): task_id={curr_params[0]}, start_rowid={start_rowid}, record_ids_count={curr_params[2]}")
        _last_snapshot_params = curr_params
    else:
        logger.debug(f"📊 [jobs_snapshot] 读取本轮快照(无变更): task_id={curr_params[0]}")

    # 0. 预加载近期抓取时间映射表
    crawl_time_map: dict[Any, str] = {}
    try:
        def _fetch_crawl_times():
            with sqlite3.connect(raw_db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("PRAGMA table_info(raw_jobs)")
                cols = {c[1] for c in cursor.fetchall()}
                ct_expr = "crawl_time" if "crawl_time" in cols else "'' AS crawl_time"
                pub_expr = "publish_date" if "publish_date" in cols else ("created_at" if "created_at" in cols else "'' AS publish_date")
                rows = conn.execute(f"SELECT job_link, company_name, job_title, {ct_expr}, {pub_expr} FROM raw_jobs ORDER BY rowid DESC LIMIT 1000").fetchall()
                tmap = {}
                for row in rows:
                    r = dict(row)
                    ct = r.get("crawl_time") or r.get("publish_date") or ""
                    link = r.get("job_link") or ""
                    if link:
                        tmap[link] = ct
                        tmap[link.split("?")[0].rstrip("/")] = ct
                    cname = (r.get("company_name") or "").strip().lower()
                    jname = (r.get("job_title") or "").strip().lower()
                    if cname and jname:
                        tmap[(cname, jname)] = ct
                return tmap
        crawl_time_map = await asyncio.to_thread(_fetch_crawl_times)
    except Exception as e:
        logger.warning(f"jobs_snapshot 读取 crawl_times 异常: {e}")

    def _lookup_crawl_time(link_str: str, company: str, title: str, default_val: str = "") -> str:
        if link_str:
            clean_l = link_str.split("?")[0].rstrip("/")
            if clean_l in crawl_time_map:
                return crawl_time_map[clean_l]
            if link_str in crawl_time_map:
                return crawl_time_map[link_str]
        ckey = ((company or "").strip().lower(), (title or "").strip().lower())
        if ckey in crawl_time_map:
            return crawl_time_map[ckey]
        return default_val

    def _is_recent_crawl(raw_time: str, window_seconds: int = 2 * 3600) -> bool:
        """抓取时间落在 window 内视为「刚入库还在排队评估」。

        宽容解析多格式时间源（SQLite crawl_time / 飞书「抓取时间」）。两处时间源均为
        本地时间（SQLite 建表 DEFAULT datetime('now','localtime')，见 app/core/db_bootstrap.py），
        与 datetime.now() 同基准，无时区换算问题。解析失败一律返回 False 走保守文案
        （「评估未完成」），宁可少排期也不误报排队。
        """
        if not raw_time:
            return False
        clean_time_str = str(raw_time).strip()
        fmts = ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S")
        dt = None
        for fmt in fmts:
            try:
                dt = datetime.strptime(clean_time_str[:19], fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return False
        return abs(datetime.now() - dt).total_seconds() <= window_seconds

    # 1. 查询 SQLite 岗位（仅限本轮新抓取与本轮清洗淘汰的记录）
    if has_active_run and start_rowid >= 0:
        try:
            def _fetch_sqlite_jobs():
                with sqlite3.connect(raw_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA table_info(raw_jobs)")
                    cols = {c[1] for c in cursor.fetchall()}
                    date_expr = "publish_date" if "publish_date" in cols else ("created_at" if "created_at" in cols else "'' AS publish_date")
                    crawl_expr = "crawl_time" if "crawl_time" in cols else "'' AS crawl_time"
                    # is_synced 必须真的查出来：下方「已同步行不再上板」的判定依赖它。
                    # 历史库可能没有该列（step2 首次同步时才 ALTER），缺列时补 0 保持旧行为。
                    is_synced_expr = "is_synced" if "is_synced" in cols else "0 AS is_synced"
                    # updated_at：淘汰行的真实流转时刻（判定于展示用），缺列时回退抓取时间
                    updated_expr = "updated_at" if "updated_at" in cols else "'' AS updated_at"

                    # 已确认淘汰与已放弃同为终态归档，不再上板（2026-10-10 用户报修：
                    # 飞书卡片确认淘汰后桌面端淘汰tab仍显示待确认——看板语义是
                    # 「待人工处理」队列，归档完成即离场；桌面端确认按钮同语义
                    # （confirm-reject 后 removeJob）。词取自单一事实源。）
                    query = f"""
                        SELECT rowid, platform, job_title, company_name, salary, city,
                               education_req, experience_req, jd_text, job_link, process_status, reject_reason, {crawl_expr}, {date_expr}, {is_synced_expr}, {updated_expr}
                        FROM raw_jobs
                        WHERE rowid > ? AND process_status NOT IN (?, ?)
                        ORDER BY rowid DESC
                    """
                    return [dict(r) for r in conn.execute(
                        query, (start_rowid, process_status.ABANDONED, process_status.REJECT_CONFIRMED)
                    ).fetchall()]

            sqlite_rows = await asyncio.to_thread(_fetch_sqlite_jobs)
            for r in sqlite_rows:
                p_status = r.get("process_status") or ""
                is_rejected = p_status in _SQLITE_REJECTED_STATUSES
                is_ai_reject = p_status == "ai清洗淘汰"
                is_synced = p_status == "已同步" or r.get("is_synced") == 1

                if is_synced and not is_rejected:
                    continue

                job_id_str = f"raw_{r['rowid']}"
                if job_id_str in dismissed_ids:
                    continue

                mapped = _map_sqlite_process_status(p_status)
                status = mapped["status"]
                sub_status = mapped["sub_status"]
                node = "clean_rejected" if is_rejected else "scrape_node"
                link = r.get("job_link") or ""
                if link:
                    seen_links.add(link)

                jobs.append({
                    "job_id": f"raw_{r['rowid']}",
                    "job_name": r.get("job_title") or "未知岗位",
                    "node": node,
                    "status": status,
                    "sub_status": sub_status,
                    "platform": r.get("platform") or "",
                    "company_name": r.get("company_name") or "",
                    "salary": r.get("salary") or "",
                    "city": r.get("city") or "",
                    "education": r.get("education_req") or "",
                    "experience": r.get("experience_req") or "",
                    "jd_text": r.get("jd_text") or "",
                    "job_url": link,
                    "company_scale": r.get("company_size") or r.get("scale") or "",
                    "reject_reason": r.get("reject_reason") or ("触发AI排雷规则" if is_ai_reject else "触发清洗淘汰规则"),
                    "reject_type": "ai" if is_ai_reject else "rule",
                    "is_current_run": True,
                    "created_at": r.get("publish_date") or "",
                    "crawl_time": r.get("crawl_time") or r.get("publish_date") or "",
                    # 最后动作时间用 updated_at（真实流转时刻）：此前用抓取时间，淘汰卡的
                    # 「判定于」会错显示成抓取时刻而非实际淘汰时刻（2026-11-01 用户实测）
                    "last_action_time": r.get("updated_at") or r.get("crawl_time") or r.get("publish_date") or "",
                    "last_action_desc": mapped["last_action_desc"],
                })
        except Exception as e:
            logger.warning(f"jobs_snapshot 查询 SQLite 异常: {e}")

    # 2. 查询飞书本轮待审批记录
    if has_active_run and run_record_ids:
        try:
            pending_feishu = feishu_lists["pending"]
            gate_config = automation_db.get_autopilot_config()  # 复算真实拦截原因，一次读取整批复用
            for pj in (pending_feishu or []):
                pj_id = pj.get("job_id") or pj.get("record_id")
                if pj_id not in run_record_ids:
                    continue
                if pj.get("follow_status") in ("待投递", "已完成初步评估"):
                    # 防御性过滤：审批查询只应返回复核门牌。待投递归 2.5 段，
                    # 已完成初步评估归第 4 段 done 映射，均不属于审批断点。
                    continue
                c_time = _lookup_crawl_time(pj.get("job_url", ""), pj.get("company_name", ""), pj.get("job_name", ""))
                is_custom_job = bool(pj.get("is_custom"))
                jobs.append({
                    "job_id": pj_id,
                    "job_name": pj.get("job_name"),
                    "company_name": pj.get("company_name"),
                    "platform": pj.get("platform"),
                    "grade": pj.get("grade"),
                    "score": pj.get("score"),
                    "salary": pj.get("salary"),
                    "city": pj.get("city"),
                    "education": pj.get("education") or "",
                    "experience": pj.get("experience") or "",
                    "job_url": pj.get("job_url"),
                    "company_scale": pj.get("company_scale") or "",
                    "review_type": "custom_tailored" if is_custom_job else "mass_apply",
                    "has_rewrite": bool(pj.get("has_rewrite")),
                    "greeting_msg": pj.get("greeting_msg") or pj.get("greeting_text") or "",
                    # 透传跟进状态：疑似重复等特殊审批态要在卡片上渲染专属徽章
                    "follow_status": pj.get("follow_status") or "",
                    "status": "waiting",
                    "node": "manual_review_node",
                    "is_current_run": True,
                    "crawl_time": c_time,
                    "last_action_time": c_time,
                    "last_action_desc": "已生成定制简历，待细审放行" if is_custom_job else _mass_review_reason(
                        pj.get("grade"), pj.get("platform"),
                        {"公司规模": pj.get("company_scale") or ""}, gate_config,
                    ),
                })
        except Exception as e:
            logger.warning(f"jobs_snapshot 查询飞书待审批异常: {e}")

    # 2.1 查询飞书已拒绝记录
    if has_active_run and run_record_ids:
        try:
            rejected_manual = feishu_lists["rejected_manual"]
            for rj in (rejected_manual or []):
                rj_id = rj.get("job_id") or rj.get("record_id")
                if rj_id not in run_record_ids:
                    continue
                if rj_id in dismissed_ids:
                    continue
                c_time = _lookup_crawl_time(rj.get("job_url", ""), rj.get("company_name", ""), rj.get("job_name", ""))
                jobs.append({
                    "job_id": rj_id,
                    "job_name": rj.get("job_name") or "未知岗位",
                    "company_name": rj.get("company_name") or "",
                    "platform": rj.get("platform"),
                    "grade": rj.get("grade"),
                    "salary": rj.get("salary"),
                    "city": rj.get("city"),
                    "job_url": rj.get("job_url"),
                    "company_scale": rj.get("company_scale") or "",
                    "has_rewrite": bool(rj.get("has_rewrite")),
                    "status": "rejected_manual",
                    "node": "manual_rejected",
                    "reject_type": "manual",
                    "reject_reason": "老板人工审批拒绝",
                    "is_current_run": True,
                    "crawl_time": c_time,
                    "last_action_time": c_time,
                    "last_action_desc": "老板已拒绝，AI草稿保留可复活",
                })
        except Exception as e:
            logger.warning(f"jobs_snapshot 查询飞书已拒绝异常: {e}")

    # 2.2 查询今日投递异常记录
    try:
        delivery_failures = _rs.get_delivery_failures()
        for fid, fval in delivery_failures.items():
            if fid in dismissed_ids or str(fid) in retrying_ids:
                continue
            failed_at = str(fval.get("failed_at") or "")
            c_time = _lookup_crawl_time(fval.get("job_url", ""), fval.get("company_name", ""), fval.get("job_name", ""), failed_at)
            is_this_run = bool(has_active_run and run_record_ids and fid in run_record_ids)
            jobs.append(build_failure_job(fid, fval, is_current_run=is_this_run, crawl_time=c_time))

        # 🌟 双轨聚合：查询飞书「跟进状态」为「投递失败」的记录，查漏补缺去重聚合
        feishu_failed_jobs = feishu_lists["failed"]
        for fj in (feishu_failed_jobs or []):
            f_jid = fj.get("job_id")
            if not f_jid or f_jid in delivery_failures or f_jid in dismissed_ids or str(f_jid) in retrying_ids:
                continue
            c_time = _lookup_crawl_time(fj.get("job_url", ""), fj.get("company_name", ""), fj.get("job_name", ""))
            # 🌟 failure_info 透出（2026-11-02 审计 P2-13）：飞书侧投递失败岗此前缺该字段，
            # 前端 failed-job-card 回退成万能文案「流水线节点处理超时或网络连接异常」，
            # 真实报错被抹平。与台账卡（build_failure_job）同构：真实原因+分诊建议原样透传
            _fj_err = fj.get("error_msg") or "投递执行失败"
            jobs.append({
                "job_id": f_jid,
                "job_name": fj.get("job_name") or "未知岗位",
                "company_name": fj.get("company_name") or "",
                "platform": fj.get("platform"),
                "job_url": fj.get("job_url", ""),
                "grade": fj.get("grade", "C"),
                "salary": fj.get("salary") or "",
                "city": fj.get("city") or "",
                "status": "failed",
                "is_current_run": False,
                "created_at": c_time,
                "last_action_time": c_time,
                "last_action_desc": _fj_err,
                "error_msg": _fj_err,
                "delivery_error": _fj_err,
                "failure_info": {
                    "stage": "delivery",
                    "step": "自动投递阶段",
                    "reason": _fj_err,
                    "suggestion": build_failure_suggestion(_fj_err),
                    "can_retry": True,
                    "failure_count": 1,
                    "triage": _triage_classify(_fj_err),
                    "heal_log": [],
                    "diagnosis": None,
                },
                "node": "delivery_node",
                "is_custom": fj.get("is_custom", False)
            })
    except Exception as e:
        logger.warning(f"jobs_snapshot 查询今日投递异常失败: {e}")

    # 2.5 查询飞书待投递记录
    try:
        ready_feishu = feishu_lists["scheduled"]
        # 🌟 放行时间取 SQLite boss_approvals（老板点放行的真实时刻）；
        # 免审直进待投递的岗位无审批标记，退回抓取时间兜底。前端据此按放行时间倒序置顶最新放行
        approval_times = await asyncio.to_thread(
            automation_db.get_approval_times,
            [str(rj.get("job_id") or rj.get("record_id") or "") for rj in (ready_feishu or [])],
        )
        for rj in (ready_feishu or []):
            rj_id = rj.get("job_id") or rj.get("record_id")
            if rj_id in delivery_failures:
                continue
            if rj_id in dismissed_ids:
                continue
            if str(rj_id) in retrying_ids:
                # 🌟 正在后台投递或重试中的岗位，由下方进行态守卫统一接管，绝不可带入待投递列表
                continue
            is_this_run = bool(has_active_run and run_record_ids and rj_id in run_record_ids)
            c_time = _lookup_crawl_time(rj.get("job_url", ""), rj.get("company_name", ""), rj.get("job_name", ""))
            released_at = approval_times.get(str(rj_id)) or ""
            jobs.append({
                "job_id": rj_id,
                "job_name": rj.get("job_name") or "未知岗位",
                "company_name": rj.get("company_name") or "",
                "platform": rj.get("platform"),
                "grade": rj.get("grade", "C"),
                "score": rj.get("score"),
                "salary": rj.get("salary", ""),
                "city": rj.get("city", ""),
                "education": rj.get("education") or "",
                "experience": rj.get("experience") or "",
                "job_url": rj.get("job_url"),
                "company_scale": rj.get("company_scale") or "",
                # 🌟 精投/海投只信 is_custom_record 统一口径（含 AI改写JSON），
                # 此前按评级 A/B 硬算，曾把 C 级定制改写岗误标成海投
                "review_type": "custom_tailored" if rj.get("is_custom") else "mass_apply",
                "has_rewrite": bool(rj.get("has_rewrite")),
                "greeting_msg": rj.get("greeting_msg") or rj.get("greeting_text") or "",
                "status": "ready_to_deliver",
                "node": "ready_to_deliver",
                "is_current_run": is_this_run,
                "crawl_time": c_time,
                "last_action_time": released_at or c_time,
                "last_action_desc": "老板放行就绪，等待定时发射" if released_at else "审批放行就绪，等待定时发射",
            })
    except Exception as e:
        logger.warning(f"jobs_snapshot 查询飞书待投递异常: {e}")

    # 3. 查询飞书已投递记录
    try:
        delivered_feishu = feishu_lists["delivered"]
        for dj in (delivered_feishu or []):
            dj_id = dj.get("job_id") or dj.get("record_id")
            is_this_run = bool(has_active_run and run_record_ids and dj_id in run_record_ids)
            c_time = _lookup_crawl_time(dj.get("job_url", ""), dj.get("company_name", ""), dj.get("job_name", ""))
            norm_dj_plat = normalize_platform_code(dj.get("platform"))
            is_greet_plat = is_greeting_supported_platform(norm_dj_plat)
            delivered_time = str(dj.get("delivered_at") or "")
            jobs.append({
                "job_id": dj_id,
                "job_name": dj.get("job_name") or dj.get("job_title") or "已投递岗位",
                "company_name": dj.get("company_name") or dj.get("company") or "",
                "platform": dj.get("platform"),
                "grade": dj.get("grade"),
                "salary": dj.get("salary"),
                "city": dj.get("city"),
                "job_url": dj.get("job_url"),
                "company_scale": dj.get("company_scale") or "",
                # 🌟 与待投递同口径：已投递卡片的精投/海投只信 is_custom_record，不再让前端按评级 A/B 兜底反推
                "review_type": "custom_tailored" if dj.get("is_custom") else "mass_apply",
                "has_rewrite": bool(dj.get("has_rewrite")),
                "greeting_msg": dj.get("greeting_msg") or "",
                "status": "delivered",
                "node": "delivery_node",
                "is_current_run": is_this_run,
                "is_today": True,
                "crawl_time": c_time,
                "last_action_time": delivered_time or c_time,
                "last_action_desc": "已成功送达简历与打招呼语",
                "delivery_materials": {
                    # 🌟 BOSS 微聊只发长图，「PDF 备份」仅为归档母本，严格屏蔽；
                    # 附件投递平台缺省兜底 True，与前端智联卡片口径一致
                    "pdf": False if norm_dj_plat == "boss" else dj.get("has_pdf", True),
                    # 🌟 长图简历仅 BOSS 微聊专属：智联/51job/猎聘均为纯附件 PDF 投递，一律屏蔽（数据层已过滤，此处双保险）
                    "image": False if norm_dj_plat in ("zhilian", "51job", "liepin") else dj.get("has_image", False),
                    # 🌟 真实回执：专属语绿标只在「平台具备微聊能力且配置了打招呼语且引擎确认微聊送达」时点亮，
                    # 未真实送达时置 greeting_failed 供前端渲染灰色警示，杜绝假绿标；非微聊平台两者均恒为 False
                    "greeting": bool(is_greet_plat and dj.get("has_greeting", False) and dj.get("greeting_delivered", True)),
                    "greeting_failed": bool(is_greet_plat and dj.get("has_greeting", False) and not bool(dj.get("greeting_delivered", True))),
                    "delivered_at": delivered_time,
                },
            })
    except Exception as e:
        logger.warning(f"jobs_snapshot 查询飞书已投递异常: {e}")

    # 4. 补齐本轮其余飞书初评完成记录
    if has_active_run and run_record_ids:
        try:
            known_feishu_ids = {j.get("job_id") for j in jobs if not str(j.get("job_id", "")).startswith("raw_")}
            missing_ids = [rid for rid in run_record_ids if rid not in known_feishu_ids]
            if missing_ids:
                from app.core.feishu_utils import (
                    extract_feishu_text as _txt,
                )
                from app.core.feishu_utils import (
                    extract_job_grade,
                    has_rewrite_output,
                    is_custom_record,
                )
                detail_gate_config = automation_db.get_autopilot_config()  # 复算真实拦截原因，一次读取整批复用
                # 🚀 Q21 配套：逐条记录详情并发获取（Semaphore 限流防飞书 429），按原 missing_ids 顺序消费（卡片顺序不变）
                _detail_sem = asyncio.Semaphore(10)

                async def _fetch_detail(rid: str):
                    async with _detail_sem:
                        return await _safe_fetch(f"detail:{rid}", asyncio.to_thread(feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID))

                _recs = await asyncio.gather(*(_fetch_detail(rid) for rid in missing_ids))
                for rid, rec in zip(missing_ids, _recs, strict=True):
                    if not rec:
                        continue
                    f = rec.get("fields", {})
                    f_status = _txt(f.get("跟进状态", ""))
                    grade = extract_job_grade(f)
                    score_val = f.get("初评总分") or f.get("初步评估得分")
                    try:
                        score_num = float(score_val) if score_val is not None else None
                    except (ValueError, TypeError):
                        score_num = None

                    raw_plat = _txt(f.get("招聘平台", "")) or "zhilian"
                    plat = "zhilian" if "智联" in raw_plat else ("boss" if "boss" in raw_plat.lower() else ("liepin" if "猎聘" in raw_plat else "51job"))

                    is_custom_job = is_custom_record(f)

                    pipeline_stopped = not runtime.get("running")
                    norm_grade = str(grade).strip().upper() if grade else ""

                    _section4_failure_info = None  # 循环每条记录重置（CR-B2-R2-P1：防跨条污染/UnboundLocal）
                    # 分诊唯一实现（CR-B2-R1-P4；R3-P2：「已拒绝」分支并入纯函数，调用方无特判）：
                    # classify_feishu_followup 纯函数，测试与生产共用（此前测试文件重抄分支、
                    # 生产改错测试照过的盲区）
                    _verdict = classify_feishu_followup(
                        f_status, norm_grade, is_custom_job=is_custom_job,
                        pipeline_stopped=pipeline_stopped,
                        crawl_recent=_is_recent_crawl(
                            _txt(f.get("抓取时间", "")) or _lookup_crawl_time(
                                _txt(f.get("岗位链接", "")), _txt(f.get("公司名称", "")), _txt(f.get("岗位名称", ""))
                            )
                        ) if (not norm_grade or norm_grade not in ("A", "B", "C", "D")) else False,
                    )
                    status, node, sub_status = _verdict["status"], _verdict["node"], _verdict["sub_status"]
                    last_action_desc = _verdict["last_action_desc"]
                    if _verdict.get("failure_reason"):
                        _section4_failure_info = {
                            "stage": "delivery" if node == "delivery_node" else "evaluate",
                            "step": f_status,
                            "reason": _verdict["failure_reason"],
                            "suggestion": build_failure_suggestion(_verdict["failure_reason"]),
                            "can_retry": True,
                            "failure_count": 1,
                            "triage": _triage_classify(_verdict["failure_reason"]),
                            "heal_log": [],
                            "diagnosis": None,
                        }
                    # waiting 文案回填（CR-B2-R1 回归修复·逐字对齐原版两分支）：
                    # ① 显式状态表（跟进状态∈审批集合）：精投固定文案在纯函数内；
                    #   海投回填 _mass_review_reason（原 is_waiting 分支行为）
                    # ② has_rating 兜底（跟进状态空/不在集合）：精投/海投各一句
                    #   硬编码（0c5a5d1f 三 tab 根治版），不区分停机
                    if status == "waiting" and node == "manual_review_node" and sub_status == "waiting":
                        if f_status in APPROVAL_FOLLOW_STATUSES:
                            if not is_custom_job and f_status != "疑似重复":
                                last_action_desc = _mass_review_reason(grade, raw_plat, f, detail_gate_config)
                        else:
                            last_action_desc = ("已生成定制简历，待细审放行" if is_custom_job
                                                else "评估完成，海投物料装配中，过安检后自动进待投递")

                    job_name = _txt(f.get("岗位名称", "")) or "未知岗位"
                    comp_name = _txt(f.get("公司名称", "")) or "未知公司"
                    job_link = _txt(f.get("岗位链接", ""))
                    c_time = _lookup_crawl_time(job_link, comp_name, job_name)

                    jobs.append({
                        "job_id": rid,
                        "job_name": job_name,
                        "company_name": comp_name,
                        "platform": plat,
                        "grade": grade.upper(),
                        "score": score_num,
                        "salary": _txt(f.get("薪资", "")) or "",
                        "city": _txt(f.get("城市", "")) or "",
                        "education": _txt(f.get("学历要求", "")) or _txt(f.get("学历", "")) or "",
                        "experience": _txt(f.get("经验要求", "")) or _txt(f.get("经验", "")) or "",
                        "company_scale": _txt(f.get("公司规模", "")) or "",
                        "job_url": job_link,
                        # 🌟 统一口径：与待审批/待投递/投递编排同源 is_custom_record，不再按评级硬算
                        "review_type": "custom_tailored" if is_custom_job else "mass_apply",
                        "has_rewrite": has_rewrite_output(f),
                        "status": status,
                        "node": node,
                        "sub_status": sub_status,
                        "is_current_run": True,
                        "crawl_time": c_time,
                        "last_action_time": c_time,
                        "last_action_desc": last_action_desc,
                        # 跟进状态原文下发（审计 C-5）：疑似重复等门牌徽章依赖此字段渲染
                        "follow_status": f_status,
                        # 失败卡补 failure_info（CR-B2-R1-P2）：与台账卡同构，前端不再回退万能文案
                        **({"failure_info": _section4_failure_info} if _section4_failure_info else {}),
                    })
        except Exception as e:
            logger.warning(f"jobs_snapshot 补齐飞书初评岗位异常: {e}")

    # 4.5 实时岗位态覆盖：SSE 是直播，快照是 12 秒轮询；在途岗位的节点/子状态
    # 只能以进程内实时登记表为准，否则改写中的岗位会被打回「AI初评完成 / 待审批」。
    try:
        live_jobs = pb.get_live_jobs(runtime.get("task_id"))
        if live_jobs:
            jobs = apply_live_job_overlay(jobs, live_jobs)
    except Exception as e:
        logger.warning(f"jobs_snapshot 实时岗位态覆盖异常（不阻断快照）: {e}")

    # 跨段强去重
    try:
        def _clean_entity_text(s: str) -> str:
            if not s:
                return ""
            s = s.lower()
            s = re.sub(r"[\s\-_—·（）\(\)【】\[\]、，,]", "", s)
            s = re.sub(r"股份有限公司|有限公司|有限责任公司|分公司|集团", "", s)
            return s.strip()

        def _clean_url(u: str) -> str:
            if not u:
                return ""
            return u.split("?")[0].rstrip("/").strip()

        feishu_urls = {
            _clean_url(j.get("job_url")) for j in jobs
            if j.get("job_url") and not str(j.get("job_id", "")).startswith("raw_")
        }
        feishu_urls.discard("")

        feishu_pairs = {
            (_clean_entity_text(j.get("company_name")), _clean_entity_text(j.get("job_name")))
            for j in jobs
            if not str(j.get("job_id", "")).startswith("raw_") and j.get("company_name") and j.get("job_name")
        }

        def _is_covered_by_feishu(raw_job):
            if raw_job.get("status") == "rejected" or raw_job.get("node") == "clean_rejected":
                return False
            url = _clean_url(raw_job.get("job_url"))
            if url and url in feishu_urls:
                return True
            comp = _clean_entity_text(raw_job.get("company_name"))
            name = _clean_entity_text(raw_job.get("job_name"))
            if comp and name and (comp, name) in feishu_pairs:
                return True
            return False

        jobs = [
            j for j in jobs
            if (not str(j.get("job_id", "")).startswith("raw_") or not _is_covered_by_feishu(j))
               and str(j.get("job_id", "")) not in dismissed_ids
        ]
    except Exception as e:
        logger.warning(f"jobs_snapshot 跨段去重异常: {e}")

    # 🌟 重试进行态常驻守卫：当前正在异步重试发射的岗位，强制展示为 running 进行态，杜绝状态乒乓
    if retrying_ids:
        known_ids = {str(j.get("job_id")) for j in jobs}
        for j in jobs:
            if str(j.get("job_id")) in retrying_ids:
                j["status"] = "running"
                j["node"] = "delivery_node"
                j["sub_status"] = "delivering"
                j["failure_info"] = None
                j["last_action_desc"] = "正在自动投递中…"
        # 若投递/重试中的岗位因未在快照各分段而缺失，补充注入进行态卡片
        missing_retrying = [rid for rid in retrying_ids if rid not in known_ids]
        for rid in missing_retrying:
            try:
                from app.core.feishu_utils import extract_feishu_text as _txt
                from app.core.feishu_utils import extract_job_grade
                rec = await asyncio.to_thread(feishu_service.get_job_record_from_feishu, rid, feishu_service.TABLE_ID)
                f = (rec or {}).get("fields", {})
                jobs.append({
                    "job_id": rid,
                    "job_name": _txt(f.get("岗位名称", "")) or "投递中岗位",
                    "company_name": _txt(f.get("公司名称", "")) or "",
                    "platform": _txt(f.get("招聘平台", "")) or "zhilian",
                    "grade": extract_job_grade(f).upper() if f else "C",
                    "status": "running",
                    "node": "delivery_node",
                    "sub_status": "delivering",
                    "failure_info": None,
                    "is_current_run": True,
                    "last_action_desc": "正在自动投递中…",
                })
            except Exception as re_err:
                logger.warning(f"补齐进行态岗位异常 ({rid}): {re_err}")

    cfg = automation_db.get_autopilot_config()
    mass_time = cfg.get("mass_deliver_time", "09:30") or "09:30"
    custom_time = cfg.get("custom_deliver_time", "14:00") or "14:00"

    curr_sig = tuple((str(j.get("job_id")), str(j.get("status")), str(j.get("node"))) for j in jobs)
    if _last_jobs_status_sig is not None and curr_sig != _last_jobs_status_sig:
        from collections import Counter
        counts = Counter(j.get("status") or "unknown" for j in jobs)
        logger.info(f"📊 [jobs_snapshot] 岗位状态变更: 岗位数={len(jobs)} [{', '.join(f'{k}={v}' for k, v in counts.items())}]")
    _last_jobs_status_sig = curr_sig

    return {
        "status": "success",
        "data": jobs,
        "task_id": runtime.get("task_id"),
        "delivery_schedule": {
            "mass_time": mass_time,
            "custom_time": custom_time,
        }
    }
