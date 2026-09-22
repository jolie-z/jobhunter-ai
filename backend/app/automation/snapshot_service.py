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
from typing import Any

from app.automation import db as automation_db
from app.automation import run_snapshot as _rs
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
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "job_hunter.db"
    )


# SQLite process_status → 快照卡片状态白名单映射。
# 未知值兜底为 running+ai_eval_queued（评估排队），绝不输出裸 running——
# 裸 running 会被前端合并层乐观注入 sub_status="delivering"，卡片误锁成「正在自动投递中」
# （召回待初评/已确认淘汰/待投递遗留值曾中招）。
_SQLITE_REJECTED_STATUSES = {"清洗淘汰", "ai清洗淘汰", "已确认淘汰"}


def _map_sqlite_process_status(p_status: str) -> dict[str, str | None]:
    """把 raw_jobs.process_status 映射为快照卡片的 {status, sub_status, last_action_desc}。"""
    if p_status == "ai清洗淘汰":
        return {"status": "rejected", "sub_status": None, "last_action_desc": "触发AI排雷规则淘汰"}
    if p_status == "清洗淘汰":
        return {"status": "rejected", "sub_status": None, "last_action_desc": "触发规则清洗淘汰"}
    if p_status == "已确认淘汰":
        return {"status": "rejected", "sub_status": None, "last_action_desc": "已确认淘汰"}
    if p_status == "已存入数据":
        return {"status": "scraped", "sub_status": None, "last_action_desc": "入库待清洗"}
    if p_status == "召回待初评":
        return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "♻️ 已召回，等待AI重新初评"}
    if p_status == "待推送至飞书":
        return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "已入库，待推送至飞书"}
    if p_status == "已进行打分":
        return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "AI打分完成，等待流转"}
    if p_status == "待投递":
        return {"status": "ready_to_deliver", "sub_status": None, "last_action_desc": "待投递"}
    return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "入库待清洗"}


def _triage_classify(error: str) -> str:
    """快照展示用：复用 L1 分诊对错误文本的分类结果。"""
    try:
        from app.automation.failure_triage import classify_delivery_failure
        return classify_delivery_failure(error)
    except Exception:
        return "unknown"


def build_failure_suggestion(err_msg: str) -> str:
    """按失败文本生成执行失败卡片的推进建议。

    结构化标签（引擎明确断言的事实）必须先于自由关键词匹配：
    「[物料] 打招呼语为非法内容」含"打招呼"却是物料问题，先匹配自由关键词会误导向补发打招呼。
    "附件已送达"只在引擎带 [微聊受阻] 标签时才成立，自由文本命中不做该断言。
    """
    text = str(err_msg or "")
    lower = text.lower()
    if "附件未送达" in text:
        return "打招呼语已成功送达！简历附件选择受阻，可点击右下角【重试】单独补发附件简历。"
    if "微聊受阻" in text:
        return "附件简历已成功送达！可点击右下角【重试】单独补发专属打招呼语。"
    if any(k in text for k in ("[下架]", "已下线", "已下架", "已关闭")):
        return "岗位已在对应平台下架或关闭，建议点击【放弃】移除。"
    if any(k in text for k in ("[物料]", "缺少", "简历下载失败")):
        return "物料缺失或异常，请在飞书检查简历附件与字段后重试。"
    if any(k in text for k in ("[登录]", "登录态", "未登录")):
        return "检测到平台会话失效，请前往对应浏览器重新扫码登录后点击【重试】。"
    if "超时" in text or "timeout" in lower:
        return "投递过程等待超时，多为页面加载或网络波动，可稍后点击【重试】。"
    if "tab" in lower:
        return "已修复微聊标签页捕获逻辑，可点击重试重新发射。"
    if any(k in text for k in ("微聊", "打招呼")):
        return "打招呼环节受阻，可点击右下角【重试】重新发起沟通。"
    return "建议检查投递日志或平台页面状态后点击重试。"


def build_failure_job(fid: str, fval: dict, *, is_current_run: bool, crawl_time: str) -> dict:
    """把失败台账条目组装成执行失败 Tab 的卡片数据。

    reason 必须原样透传台账里的引擎真实报错：前端 failed-job-card 在该字段缺失时
    会回退成固定文案「流水线节点处理超时或网络连接异常」，等于把真实原因再次抹平。
    """
    err_msg = str(fval.get("error") or "投递异常")
    failed_at = str(fval.get("failed_at") or "")
    triage_kind = _triage_classify(err_msg)
    return {
        "job_id": fid,
        "job_name": fval.get("job_name") or "投递受阻岗位",
        "company_name": fval.get("company_name") or "",
        "platform": fval.get("platform") or "zhilian",
        "grade": fval.get("grade") or "D",
        "status": "error",
        "node": "error",
        "failure_info": {
            "stage": "delivery",
            "step": fval.get("step") or "自动投递阶段",
            "reason": err_msg,
            "suggestion": build_failure_suggestion(err_msg),
            "can_retry": True,
            "failure_count": int(fval.get("failure_count") or 1),
            "triage": triage_kind,
            "triage_note": ("持久性故障：自动重试无法自愈，已停止波次自动发射" if triage_kind == "persistent"
                            else ("暂时性故障：保留自动重试，连续失败达上限后停止" if triage_kind == "transient" else "")),
            "heal_log": fval.get("heal_log") or [],
            "diagnosis": fval.get("diagnosis") or None,
        },
        "is_current_run": is_current_run,
        "crawl_time": crawl_time,
        "last_action_time": failed_at or crawl_time,
        "last_action_desc": "尝试自动投递受阻",
    }


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

                    query = f"""
                        SELECT rowid, platform, job_title, company_name, salary, city,
                               education_req, experience_req, jd_text, job_link, process_status, reject_reason, {crawl_expr}, {date_expr}
                        FROM raw_jobs
                        WHERE rowid > ? AND process_status != '已放弃'
                        ORDER BY rowid DESC
                    """
                    return [dict(r) for r in conn.execute(query, (start_rowid,)).fetchall()]

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
                    "last_action_time": r.get("crawl_time") or r.get("publish_date") or "",
                    "last_action_desc": mapped["last_action_desc"],
                })
        except Exception as e:
            logger.warning(f"jobs_snapshot 查询 SQLite 异常: {e}")

    # 2. 查询飞书本轮待审批记录
    if has_active_run and run_record_ids:
        try:
            pending_feishu = feishu_lists["pending"]
            for pj in (pending_feishu or []):
                pj_id = pj.get("job_id") or pj.get("record_id")
                if pj_id not in run_record_ids:
                    continue
                if pj.get("follow_status") == "待投递":
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
                    "greeting_msg": pj.get("greeting_msg") or pj.get("greeting_text") or "",
                    "status": "waiting",
                    "node": "manual_review_node",
                    "is_current_run": True,
                    "crawl_time": c_time,
                    "last_action_time": c_time,
                    "last_action_desc": "已生成定制简历，待细审放行" if is_custom_job else "命中大厂规则，待人工过目",
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
                "last_action_desc": fj.get("error_msg") or "投递执行失败",
                "error_msg": fj.get("error_msg") or "投递执行失败",
                "delivery_error": fj.get("error_msg") or "投递执行失败",
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
                    is_custom_record,
                )
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

                    is_waiting = f_status in ("简历人工复核", "海投人工复核", "待审批")
                    is_ready_to_deliver = f_status == "待投递"
                    is_delivered = f_status == "已投递"
                    is_done = f_status in ("已完成初步评估", "已深度初步评估", "已完成深度评估")
                    is_rejected_manual = f_status == "已拒绝"
                    is_custom_job = is_custom_record(f)

                    pipeline_stopped = not runtime.get("running")
                    norm_grade = str(grade).strip().upper() if grade else ""
                    has_rating = norm_grade in ("A", "B", "C", "D")

                    if is_rejected_manual:
                        status, node, sub_status = "rejected_manual", "manual_rejected", "rejected_manual"
                        last_action_desc = "老板已拒绝"
                    elif is_ready_to_deliver:
                        status, node, sub_status = "ready_to_deliver", "ready_to_deliver", "ready_to_deliver"
                        last_action_desc = "已加入待投递队列"
                    elif is_waiting:
                        status, node, sub_status = "waiting", "manual_review_node", "waiting"
                        last_action_desc = "已生成定制简历，待细审放行" if is_custom_job else "命中大厂规则，待人工过目"
                    elif is_delivered:
                        status, node, sub_status = "delivered", "delivery_node", "ai_eval"
                        last_action_desc = "已成功投递"
                    elif is_done:
                        status, node, sub_status = "done", "evaluate_node", "eval_done"
                        last_action_desc = "已完成初步评估"
                    elif norm_grade in ("E", "F"):
                        status, node, sub_status = "rejected_auto", "clean_rule_rejected", "rejected_auto"
                        last_action_desc = "初评未达门槛，已自动淘汰"
                    elif f_status in ("清洗淘汰", "ai清洗淘汰", "ai 清洗淘汰") and not has_rating:
                        # Q19：清洗淘汰门牌且无有效评级（人工置牌/异常数据触达面）归自动淘汰，
                        # 不再落到 pipeline_stopped 的 error 半成品形态；与 Section 1 语义对齐。
                        # 置于 E/F 分支之后且要求无评级：生产波次流水线（wave_pipeline）对 F 级
                        # 同时写门牌「清洗淘汰」+评级 F，保持走 E/F 分支原分诊不变；
                        # 「门牌+A-D 评级」怪异组合同样维持 has_rating→waiting 旧行为；
                        # 「无效评级（如 G）」是否走本分支取决于 has_rating 的 A-D 有效性判定。
                        status, node, sub_status = "rejected_auto", "clean_rule_rejected", "rejected_auto"
                        # 词形耦合锁定：ai 系变体均以 "ai" 开头；扩词表时同步维护此判定
                        last_action_desc = "触发AI排雷规则淘汰" if f_status.startswith("ai") else "触发规则清洗淘汰"
                    elif has_rating:
                        # 🌟 无论在线还是停机，只要已有客观评级且尚未落盘待投递，均安全归入「待审批」人工把关池，杜绝误投
                        status, node, sub_status = "waiting", "manual_review_node", "waiting"
                        last_action_desc = "已生成定制简历，待细审放行" if is_custom_job else "海投话术已装配，待人工审批"
                    elif pipeline_stopped:
                        # 流水线已停机且无评级：判定为异常中断/半成品
                        status, node, sub_status = "error", "error", "incomplete"
                        last_action_desc = "流水线已停机，评估未完成"
                    else:
                        # 仅当流水线在线运行中且完全未出评级时，才展示为评估中
                        status, node, sub_status = "running", "evaluate_node", "ai_eval"
                        last_action_desc = "流水线处理中"

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
                        "status": status,
                        "node": node,
                        "sub_status": sub_status,
                        "is_current_run": True,
                        "crawl_time": c_time,
                        "last_action_time": c_time,
                        "last_action_desc": last_action_desc,
                    })
        except Exception as e:
            logger.warning(f"jobs_snapshot 补齐飞书初评岗位异常: {e}")

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
