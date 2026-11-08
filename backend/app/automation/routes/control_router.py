"""
全链路控制与流转路由 (Control Router)
=====================================
负责：
- 手动立即触发全自动链路 (/trigger)
- 终止链路与按平台终止 (/abort, /abort/platform/{platform}, /abort/status)
- 当前链路运行状态 (/current-pipeline)
- 平台抓取入库实时台账快照 (/run-snapshot)
- 后端控制台 SSE 实时日志流 (/console-stream)
"""
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.automation.full_auto import PLATFORM_CN, RAW_DB_PATH

logger = logging.getLogger(__name__)
router = APIRouter()


class AbortRequest(BaseModel):
    task_id: str = ""


class TriggerRequest(BaseModel):
    """Q17 防误触发守卫：手动启动全链路必须显式携带 confirm=true。

    背景（质检第 4 层冒烟实证）：本端点原先无请求体校验，任何空参 POST
    （脚本探测/爬虫误碰/预检）都会直接启动一轮真实全自动流水线（抓取→评估→投递），
    属不可逆动作面。前端 CommandHeader 已同步升级为携带 {"confirm": true}。
    """
    confirm: bool = False


@router.post("/trigger")
async def trigger_autopilot_manual(req: TriggerRequest, request: Request):
    """手动立即触发一轮【全自动链路】(抓取→清洗→飞书→评估→投递)。

    必须携带 {"confirm": true}：防脚本/预检/误碰空参直启真实链路（Q17 守卫）。
    """
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="缺少确认参数：请携带 {\"confirm\": true} 启动全链路（防误触发守卫）",
        )
    # 触发审计（2026-11-05 事故取证需求）：用户反馈「没有点启动但链路自己跑了」时，
    # 必须能回答「这个 POST 是谁发的」。记客户端端口（配合浏览器 TCP 复用可定位到
    # 具体页面）、UA、referrer、confirm 状态；比 INFO 高一级，滚动日志必含。
    logger.warning(
        "📣 [trigger-audit] 手动全链路触发受理 | client=%s:%s | UA=%r | referer=%r | confirm=%s",
        request.client.host if request.client else "?",
        request.client.port if request.client else "?",
        request.headers.get("user-agent", "")[:120],
        request.headers.get("referer", "")[:200],
        req.confirm,
    )
    try:
        from app.automation.full_auto import run_full_auto_pipeline
        pipeline_task_id = await run_full_auto_pipeline(trigger_source="manual")
        return {
            "status": "success",
            "pipeline_task_id": pipeline_task_id,
            "message": "全自动链路已启动，可订阅实时进度",
        }
    except Exception as e:
        logger.error(f"手动触发失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/abort")
async def abort_pipeline(req: AbortRequest):
    """终止当前运行中的全自动链路（优雅终止）。

    task_id 匹配守卫失败时的降级语义（2026-10-23 真机工单：终止静默失效）：
    桌面单用户场景下「用户点了终止」的意图优先于 ID 精确匹配——传入 ID 与登记任务
    不一致时，降级对当前登记任务下达终止并在响应中返回实际终止的 task_id；
    当前无登记任务时返回 409 显式失败。失败路径一律打 WARNING 日志，不再静默。
    """
    from app.api.routes.crawlers import stop_platform
    from app.automation import abort as abort_mod

    current_tid = abort_mod.current_pipeline_task_id()
    # 预检：当前无登记运行任务时，携带非空 task_id 的终止请求直接显式失败——
    # 旧语义对不存在的任务也置 aborted 并返回成功，是「假受理」的另一形态。
    # 空串不设限（防御性强制终止语义保留：仅置标志，下一轮链路 begin 时自然清除）
    if not current_tid and req.task_id:
        logger.warning(f"🛑 [abort] 终止请求 task_id={req.task_id!r}，但当前无登记运行任务，终止无对象")
        raise HTTPException(
            status_code=409,
            detail="当前无运行中的链路任务，终止指令无对象（如任务刚结束请刷新页面）",
        )
    ok = abort_mod.request_abort(req.task_id)
    degraded = False
    if not ok:
        # 降级终止当前登记任务（桌面单用户语义：用户意图优先于 ID 匹配）。
        # 返回值必须检查：读 current_tid 与降级置位之间存在毫秒级竞态窗口，
        # 登记任务恰好收尾/切换时降级调用会 False——此时显式失败，绝不假受理
        if not abort_mod.request_abort(current_tid):
            logger.warning(
                f"🛑 [abort] 降级终止 {current_tid} 竞态失败（传入 task_id={req.task_id!r}，"
                f"任务已收尾或切换），本次终止未生效"
            )
            raise HTTPException(
                status_code=409,
                detail=f"任务 {current_tid} 恰好在终止瞬间收尾/切换，终止未生效，请刷新后确认状态",
            )
        degraded = True
        logger.warning(
            f"🛑 [abort] 终止请求 task_id={req.task_id!r} 与当前登记任务 {current_tid} 不匹配，"
            f"已降级终止当前登记任务"
        )

    for p in abort_mod.KNOWN_PLATFORMS:
        stop_platform(p)
        abort_mod.request_platform_abort(p)

    # 在途投递急刹（2026-10-24 工单）：终止标志只能拦住「尚未唤起引擎」的投递，已经打开
    # 浏览器/正在发送的岗位必须破门打断，否则会出现「已终止但打招呼语/简历图片仍真实送达」。
    # 复用单岗取消的 delivery_interrupter：关闭活跃标签页迫使阻塞等待抛异常退出、释放串行锁。
    interrupted: list[str] = []
    try:
        from app.automation import delivery_interrupter
        from app.automation import run_snapshot as rs

        for rid in sorted(rs.get_active_inflight_job_ids()):
            if await asyncio.to_thread(delivery_interrupter.interrupt_active_job, rid):
                interrupted.append(rid)
        if interrupted:
            logger.warning(f"🛑 [abort] 已破门打断在途投递岗位: {interrupted}")
    except Exception as ie:
        logger.warning(f"🛑 [abort] 在途投递破门打断异常（不阻断终止受理）: {ie}")

    message = "终止指令已下达，链路将在安全点收尾"
    if degraded:
        message = f"传入 task_id 与当前任务不匹配，已按当前运行任务 {current_tid} 下达终止"
    return {
        "status": "success",
        "message": message,
        "aborted": True,
        "task_id": current_tid,
        "degraded": degraded,
        "interrupted": interrupted,
    }


@router.post("/abort/platform/{platform}")
async def abort_platform(platform: str):
    """按平台终止：登记平台级终止 + 对该平台爬虫置急刹 flag。

    【Q11 已标注保留】运维/应急端点：前端暂未接线（应急场景走 curl/脚本调用），非死代码，勿清理。
    """
    from app.api.routes.crawlers import stop_platform
    from app.automation import abort as abort_mod
    if platform not in abort_mod.KNOWN_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"未知平台: {platform}")
    abort_mod.request_platform_abort(platform)
    stopped = stop_platform(platform)
    logger.info(f"🛑 按平台终止 [{platform}]：flag 置位{'成功' if stopped else '失败'}")
    return {
        "status": "success",
        "platform": platform,
        "flag_set": stopped,
        "message": f"{platform} 终止指令已下达，当轮抓取将在检查点刹车",
    }


@router.get("/abort/status")
async def abort_status():
    """当前是否有运行中的链路、是否已下达终止指令（供前端按钮态）。

    【Q11 已标注保留】运维/应急端点：前端暂未接线（按钮态预留），非死代码，勿清理。
    """
    from app.automation import abort as abort_mod
    return {
        "status": "success",
        "data": {
            "running": bool(abort_mod._state["pipeline_task_id"]),
            "aborted": abort_mod.is_aborted(),
        },
    }


@router.get("/current-pipeline")
async def current_pipeline():
    """当前/最近一次全链路的 task_id 与运行状态，供指挥页自动挂接 SSE。"""
    from app.automation import pipeline_broadcast as pb
    return {"status": "success", "data": pb.get_current_pipeline()}


@router.get("/llm-health")
async def llm_health():
    """LLM 网关体检：用当前生效的清洗 LLM 通道发一次最小请求。

    供前端阻塞横幅「检测恢复」轮询调用——探测通过 ≠ 链路自动恢复，
    仍需用户点「继续任务」重洗遗留的待AI初筛岗位。
    """
    from app.automation import llm_health as lh
    result = await asyncio.to_thread(lh.probe_llm)
    return {"status": "success", "data": result}


class ResumeCleaningRequest(BaseModel):
    task_id: str = ""


@router.post("/clear-blocked")
async def clear_blocked(req: ResumeCleaningRequest):
    """「终止任务」显式放弃被阻塞链路：清掉阻塞登记，刷新页面后横幅不再复现。

    此前终止只清前端 store（纯内存），登记表条目仍在——刷新后 dashboard-sync
    快照又把阻塞态种回来，横幅「越关越有」。"""
    from app.automation import pipeline_blocked as pipeline_blocked_mod

    if not req.task_id:
        raise HTTPException(status_code=400, detail="缺少 task_id")
    pipeline_blocked_mod.clear_task(req.task_id)
    logger.info(f"[resume] 阻塞登记已清除（终止任务出口）: task_id={req.task_id}")
    return {"status": "success", "task_id": req.task_id}


@router.post("/resume-cleaning")
async def resume_cleaning(req: ResumeCleaningRequest, background_tasks: BackgroundTasks):
    """继续被 LLM 异常阻塞的任务：只重洗该任务遗留的「待AI初筛」岗位，链路继续向下走。

    事件发回同一 task 通道（前端 SSE 无缝续播）；跑完按同一规则发 end（仍阻塞则
    outcome=blocked）。终止复用现有 abort（resume 期间 begin_pipeline 重新登记任务）。
    """
    from app.automation import pipeline_blocked as pipeline_blocked_mod
    from app.automation import pipeline_broadcast as pb

    cur = pb.get_current_pipeline()
    if cur.get("running"):
        raise HTTPException(status_code=409, detail=f"链路 {cur.get('task_id')} 正在运行中，无法继续任务")

    blocked = pipeline_blocked_mod.get_blocked_state(req.task_id)
    # 外审 R2-P1-2：必须存在真实阻塞登记才放行——旧逻辑在无登记时回退 cur.get("task_id")
    # 也会放行，worker 端 min_rowid 静默退化为 0，整库历史行被拉进 AI 排雷并自动投递、
    # 战报统计被全量污染。已通过 /clear-blocked 终止或正常完结的任务一律拒绝
    if not blocked or not blocked.get("task_id"):
        raise HTTPException(
            status_code=409,
            detail="无可继续的任务：该任务不在阻塞登记中（可能已终止或已恢复），请重新发起链路")
    task_id = blocked["task_id"]

    from job_processor.step1_rule_filter import GLOBAL_CLEAN_LOCK
    if GLOBAL_CLEAN_LOCK.locked():
        raise HTTPException(status_code=409, detail="清洗任务正在后台执行中，请稍后再试")

    # SSE 通道自愈：后端重启后原队列丢失，重建同名通道让前端订阅不 404
    from app.tasks.state import TaskChannel, task_queues
    if task_id not in task_queues:
        task_queues[task_id] = TaskChannel()
    # 🌟 清空回放历史（2026-11-03 事故根治）：阻塞轮的 stage blocked / end(blocked) 帧留在
    # 历史里会把重连的前端立刻打回 blocked——前端 SSE 对 end 帧一律断连，恢复事件全灭，
    # 横幅永久卡死。清掉后重连客户端只回放 resume 之后的真实事件
    _channel = task_queues.get(task_id)
    _clear_history = getattr(_channel, "clear_history", None)
    if callable(_clear_history):
        _clear_history()

    # 运行态同步置位（不等后台任务）：封死「继续任务」连点造成的双跑窗口
    pb.set_current_pipeline(task_id, True)
    background_tasks.add_task(_run_resume_cleaning_worker, task_id)
    logger.info(f"🔁 [resume] 继续任务已受理: task_id={task_id}, min_rowid={(blocked or {}).get('min_rowid')}")
    return {
        "status": "success",
        "task_id": task_id,
        "message": "继续任务已启动：将重新对遗留的待AI初筛岗位执行 AI 排雷并续推后续链路",
    }


async def _collect_graph_jobs(synced_ids: list[str]) -> list[dict]:
    """把推送成功的飞书记录装配成图流水线 initial_state（字段口径与编排器一致）。

    2026-11-01 搁浅缺口根治的配套：「继续任务」重评通过的岗位在推送后必须能被
    图流水线接手，装配失败只降级打日志，绝不阻断主链路收口。
    """
    import sqlite3

    from app.services.feishu_service import (
        TABLE_ID,
        extract_feishu_text,
        get_job_record_from_feishu,
    )

    def _get_raw_id_mapping():
        with sqlite3.connect(RAW_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT rowid, feishu_record_id, job_link FROM raw_jobs WHERE feishu_record_id IS NOT NULL"
            ).fetchall()
            return {
                r["feishu_record_id"]: (f"raw_{r['rowid']}", r["job_link"] or "")
                for r in rows if r["feishu_record_id"]
            }

    raw_id_map = await asyncio.to_thread(_get_raw_id_mapping)
    jobs = []
    for rid in synced_ids:
        try:
            rec = await asyncio.to_thread(get_job_record_from_feishu, rid, TABLE_ID)
        except Exception as e:
            logger.warning(f"[resume] 拉取飞书记录 {rid} 失败，跳过图装配: {e}")
            continue
        if not rec:
            continue
        f = rec.get("fields", {})
        raw_jid, raw_link = raw_id_map.get(rid, ("", ""))
        jobs.append({
            "job_id": rid,
            "record_id": rid,
            "raw_job_id": raw_jid,
            "job_url": extract_feishu_text(f.get("岗位链接", "")) or raw_link,
            "platform": extract_feishu_text(f.get("招聘平台", "")),
            "company_name": extract_feishu_text(f.get("公司名称", "")),
            "job_name": extract_feishu_text(f.get("岗位名称", "")),
            "jd_text": extract_feishu_text(f.get("岗位详情", "")),
            "salary": extract_feishu_text(f.get("薪资", "")),
            "city": extract_feishu_text(f.get("城市", "")),
            "experience": extract_feishu_text(f.get("经验要求", "")),
            "education": extract_feishu_text(f.get("学历要求", "")),
            "company_scale": extract_feishu_text(f.get("公司规模", "")) or "",
            "feishu_fields": f,
            "_created_time": rec.get("created_time", 0),
        })
    return jobs


async def _run_resume_cleaning_worker(task_id: str):
    """「继续任务」后台体：重洗待AI初筛 → 推飞书 → 按同一规则收口。

    事件全部走原 task 通道；LLM 仍未恢复时按阻塞规则再次置位并 outcome=blocked 收口。
    收口时补发主战报卡片——横幅明文承诺「结束后自动汇报结果」，此前实现整段缺失
    （2026-11-03 事故：恢复轮真实跑完了评估/改写/投递，飞书却一张战报都没有）。
    """
    from app.automation import abort as abort_mod
    from app.automation import pipeline_blocked as pipeline_blocked_mod
    from app.automation import pipeline_broadcast as pb
    from job_processor import step1_rule_filter

    # 重新登记运行任务：resume 期间 /api/automation/abort 可精确终止本轮
    abort_mod.begin_pipeline(task_id)
    resume_started_at = datetime.now()
    min_rowid = 0
    graph_results: list[dict] = []
    synced: list[str] = []
    passed_links: list[str] = []
    try:
        blocked_before = pipeline_blocked_mod.get_blocked_state(task_id)
        min_rowid = int((blocked_before or {}).get("min_rowid") or 0)
        # 🌟 受理即清除陈旧登记：阻塞是否延续由本轮重洗的真实 LLM 结果重新裁决
        # （仍失败会经 report_llm_failure 立即重新置位）。不清的话「遗留岗位已为空、
        # 排雷零调用」时，收口处的 get_blocked_state 会读到陈旧登记误判「LLM 仍未恢复」
        pipeline_blocked_mod.report_llm_success(task_id)

        await pb.emit_stage(task_id, "cleaning", "running")
        await pb.emit_log(task_id, "🔁 继续任务：重新对遗留「待AI初筛」岗位执行 AI 排雷…")

        passed_links = await step1_rule_filter._async_run_ai_scout_only(
            sse_task_id=task_id, min_rowid=min_rowid)

        blocked_now = pipeline_blocked_mod.get_blocked_state(task_id)
        if blocked_now:
            # LLM 仍未恢复：按同一规则置阻塞态收口（不伪装成功）
            await pb.emit_log(
                task_id,
                f"⏸️ LLM 仍不可用（{blocked_now.get('kind')}）：{blocked_now.get('message')}，"
                f"剩余岗位继续保留在待AI初筛",
                "error")
            await pb.emit_stage(
                task_id, "cleaning", "blocked", extra={"blocked": blocked_now})
            await pb.emit_end(task_id, {"outcome": "blocked", "blocked": blocked_now})
            return

        if passed_links and not abort_mod.is_aborted():
            await pb.emit_stage(task_id, "feishu_sync", "running")
            from job_processor import step2_sync_feishu
            synced = await step2_sync_feishu.sync_sqlite_to_feishu_async(
                RAW_DB_PATH, "raw_jobs", task_id, None, target_links=passed_links)
            await pb.emit_stage(task_id, "feishu_sync", "done")

            # 🌟 续链（2026-11-01 搁浅缺口根治）：推送成功的岗位自动注册进图流水线，
            # 评估/改写/投递由本任务继续驱动。此前实现到推送即收口——「继续任务」在
            # 流水线收车后运行时，通过的岗位搁浅在「新线索」50 分钟无人接手。
            graph_jobs: list[dict] = []
            if synced and not abort_mod.is_aborted():
                try:
                    graph_jobs = await _collect_graph_jobs(synced)
                except Exception as e:
                    logger.warning(f"[resume] 图任务装配失败（不阻断收口）: {e}", exc_info=True)

            if graph_jobs and not abort_mod.is_aborted():
                from app.automation.db import get_autopilot_config
                from app.automation.graph_runner import _run_jobs_through_graph
                from app.services.feishu_service import (
                    get_active_resume_from_feishu,
                    get_my_preferences,
                    get_resume_text_by_id,
                )
                config = get_autopilot_config()
                resume_text = await asyncio.to_thread(get_active_resume_from_feishu)
                preferences_text = await asyncio.to_thread(get_my_preferences)
                # 🌟 key 兼容读（第一批 P1-4）——判定收敛在模块级 resolve_mass_resume_id（可单测）
                mass_resume_id = resolve_mass_resume_id(config)
                mass_resume_text = ""
                if mass_resume_id:
                    mass_resume_text = await asyncio.to_thread(get_resume_text_by_id, mass_resume_id)
                if not mass_resume_text:
                    mass_resume_text = resume_text
                batch_limit = int((config or {}).get("batch_limit", 20) or 20)

                await pb.emit_stage(task_id, "evaluating", "running")
                try:
                    # stop_at_review=False：与手动即时模式同语义——C/D 过门禁即自动投递，
                    # A/B 照旧挂精投审批断点等老板细审
                    graph_results = await _run_jobs_through_graph(
                        graph_jobs[:batch_limit], resume_text, preferences_text, task_id,
                        mass_resume_text, stop_at_review=False)
                finally:
                    await pb.emit_stage(task_id, "evaluating", "done")
                await pb.emit_log(
                    task_id, f"✅ 继续任务完成：{len(synced or passed_links)} 个岗位已推送飞书，"
                             f"图流转已接续（评估/投递结果见岗位卡片）")
            elif not abort_mod.is_aborted():
                await pb.emit_log(task_id, f"ℹ️ 继续任务完成：{len(synced or passed_links)} 个岗位已推送飞书")
        elif not abort_mod.is_aborted():
            await pb.emit_log(task_id, "ℹ️ 没有发现遗留的「待AI初筛」岗位，无需重洗")

        # 🌟 继续任务战报（与编排器 _send_task_report 同一实现，2026-11-03 事故根治）：
        # 恢复轮真实跑了重洗/推送/评估/投递，必须给飞书一张战报卡片，不能只发 SSE 日志。
        # 终止轮也如实发（卡片带手动终止横幅）；重洗零产出的空轮不发（避免噪音卡片）
        did_work = bool(synced or graph_results)
        if did_work or abort_mod.is_aborted():
            try:
                from app.automation.db import get_autopilot_config
                if not get_autopilot_config().get("feishu_enable_report", True):
                    await pb.emit_log(task_id, "📮 任务报告推送已在飞书面板关闭，跳过发送")
                else:
                    from app.automation import pipeline_report as pr
                    cleaning_stats = await asyncio.to_thread(
                        pr.collect_cleaning_stats, RAW_DB_PATH, min_rowid)
                    await pb.emit_log(task_id, "📮 正在生成继续任务战报卡片并推送飞书…")
                    card_ok = await pr.send_pipeline_master_card(
                        started_at=resume_started_at,
                        scrape_counts={},
                        cleaning=cleaning_stats,
                        job_results=graph_results,
                        trigger_source="resumed",
                        aborted=abort_mod.is_aborted(),
                    )
                    if not card_ok:
                        text = pr.build_pipeline_report(
                            started_at=resume_started_at,
                            scrape_counts={},
                            disabled_platforms=[],
                            platform_cn={},
                            cleaning=cleaning_stats,
                            synced_count=len(synced or passed_links),
                            job_results=graph_results,
                            aborted=abort_mod.is_aborted(),
                        )
                        await pr.send_pipeline_report(text)
            except Exception as rep_e:
                logger.warning(f"[resume] 继续任务战报发送异常（不阻断收口）: {rep_e}", exc_info=True)

        if abort_mod.is_aborted():
            # 继续任务途中被手动终止：如实按终止收口，不把半途轮次记成 resumed
            await pb.emit_end(task_id, {"reason": "aborted", "resumed_passed": len(passed_links or [])})
            return

        await pb.emit_stage(task_id, "cleaning", "done")
        await pb.emit_stage(task_id, "done", "done")
        await pb.emit_end(task_id, {"outcome": "resumed", "resumed_passed": len(passed_links or [])})
    except Exception as e:
        logger.error(f"🔁 [resume] 继续任务异常: {e}", exc_info=True)
        await pb.emit_log(task_id, f"🚨 继续任务异常: {e}", "error")
        await pb.emit_end(task_id, {"error": str(e)})
    finally:
        pb.set_current_pipeline(task_id, False)
        abort_mod.end_pipeline()


@router.get("/run-snapshot")
async def run_snapshot():
    """本轮各平台真实抓取台账（查库权威值）：刷新页面后前端靠它恢复进度数字。"""
    from app.automation import run_snapshot as rs
    return {"status": "success", "data": rs.compute(RAW_DB_PATH, PLATFORM_CN)}


def resolve_mass_resume_id(config: dict | None) -> str | None:
    """「继续任务」海投简历 key 兼容读（第一批 P1-4；拆分子任务补单测）：
    真实 key mass_apply_resume_id 优先，历史笔误 key mass_resume_id 兜底。"""
    return (config or {}).get("mass_apply_resume_id") or (config or {}).get("mass_resume_id")


def _sync_source_ok(v, fallback):
    """dashboard-sync 子源降级判定（模块级供单测同源调用，CR-B3-R2-P2；
    CR-B3-R3-P0 修正：原版插在 @router.get("/dashboard-sync") 装饰器与
    dashboard_sync 之间，路由被劫持到本函数——线上 dashboard-sync 实测 422）：
    Exception → 告警降级 fallback；CancelledError/KeyboardInterrupt 等重抛。"""
    if isinstance(v, BaseException) and not isinstance(v, Exception):
        raise v
    if isinstance(v, BaseException):
        logger.warning(f"⚠️ [dashboard-sync] 子源异常，降级: {type(v).__name__}: {str(v)[:120]}")
        return fallback
    return v


@router.get("/dashboard-sync")
async def dashboard_sync():
    """指挥中心聚合同步接口：一次往返带回配置状态/当前链路/抓取台账/岗位快照。

    合并前端原本 4 个离散轮询（config-status / current-pipeline /
    run-snapshot / jobs-snapshot），每个子 payload 与原接口响应体完全同构，
    降低轮询对浏览器每主机 6 连接池的挤占（SSE 长连接已占用大半名额）。
    """
    from app.automation import pipeline_broadcast as pb
    from app.automation import run_snapshot as rs
    from app.automation.snapshot_service import build_jobs_snapshot
    from app.pipeline.routes.feishu_status_router import config_status

    def _auto_eval_threshold() -> str:
        try:
            from ai_agents.ai_evaluator import get_auto_eval_threshold
            return str(get_auto_eval_threshold() or "A").upper()
        except Exception as e:
            # 静默回退 A 会让深评/改写分母长期失真且无迹可查
            logger.warning(f"[dashboard-sync] 读取自动化阈值失败，按 A 兜底: {e}")
            return "A"

    # 🚀 Q21 配套：子负载并发执行（此前 jobs_snapshot 之后再串行跑 config/run 两个查库），
    # 墙钟 = 最慢的 jobs_snapshot，而非各项之和。
    # return_exceptions=True（2026-11-02 审计 P2-20）：单源失败此前会让整个聚合 500
    # （违背"单源失败不拖垮聚合"设计注释）。失败子源以 None 落位，下游分支各自降级
    _jobs, _cfg, _run, _thr = await asyncio.gather(
        build_jobs_snapshot(),
        asyncio.to_thread(config_status),
        asyncio.to_thread(rs.compute, RAW_DB_PATH, PLATFORM_CN),
        asyncio.to_thread(_auto_eval_threshold),
        return_exceptions=True,
    )

    jobs_payload = _sync_source_ok(_jobs, None)
    config_modules = _sync_source_ok(_cfg, None)
    run_platforms = _sync_source_ok(_run, None)
    auto_eval_threshold = _sync_source_ok(_thr, None)
    try:
        stage_snapshot = pb.get_stage_snapshot()
    except Exception as e:
        # 阶段快照只是恢复辅助：读取失败不能拖垮 config/jobs/run 三条主链路
        logger.warning(f"[dashboard-sync] stage_snapshot 读取失败，降级为空快照: {e}")
        stage_snapshot = {}
    return {
        "status": "success",
        "data": {
            "config_status": config_modules,
            "current_pipeline": {"status": "success", "data": pb.get_current_pipeline()},
            "run_snapshot": {"status": "success", "data": run_platforms},
            "jobs_snapshot": jobs_payload,
            # 导轨刷新恢复：阶段状态 / 清洗进度 / 各阶段实时运行岗位数（诊断用）
            "stage_snapshot": stage_snapshot,
            # 前端据此判断「哪些评级会进入深评/改写」，不能硬编码 A/B
            "pipeline_settings": {"auto_eval_threshold": auto_eval_threshold},
        },
    }


@router.get("/console-stream")
async def console_stream():
    """后端实时日志流（print + logging），先回放最近 800 行再实时推送。"""
    from app.automation import console_stream as cs

    async def gen():
        # 先订阅后快照（2026-11-02 审计 P2-14）+ seq 去重（CR-B3-R1 修正）：
        # 重叠行以单调 seq 精确跳过（文本去重会误吞分隔线等合法重复行）；
        # subscribe 立即纳入 try/finally——客户端在快照阶段断连也退订，队列不泄漏
        q = cs.subscribe()
        try:
            # 单次 snapshot（CR-B3-R3-P1 修正：两次调用存在 TOCTOU——间隙新日志会被
            # 下发一次且已入队、实时循环再发一次重复）：同一份 snap 同时算水位基线
            # 与遍历下发；subscribe 后立即进入 try/finally，快照阶段断连也退订
            snap = cs.snapshot()
            snapshot_max_seq = max((seq for seq, _ in snap), default=0)
            for _seq, line in snap:
                yield cs.sse_line(line)
            while True:
                try:
                    seq, line = await asyncio.wait_for(q.get(), timeout=15)
                    if seq <= snapshot_max_seq:
                        continue  # 与快照重叠（订阅瞬间已在缓冲），跳过
                    yield cs.sse_line(line)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            cs.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


class CancelJobDeliveryRequest(BaseModel):
    record_id: str


@router.post("/cancel-job-delivery")
async def cancel_job_delivery_endpoint(req: CancelJobDeliveryRequest):
    """
    单岗位自动投递紧急终止接口。
    前置检查岗位是否正处于自动投递中（防非法调用），
    标记取消并触发活跃浏览器破门打断，由工作流收尾释放互斥锁并流转至执行失败。
    """
    from app.automation import abort as abort_mod
    from app.automation import delivery_interrupter
    from app.automation import run_snapshot as rs
    from app.automation.workflow import _DELIVERY_INFLIGHT_RECORD_IDS

    def _inflight_union() -> set[str]:
        """在途岗位全集：状态守卫与撤销复判共用，同源性由代码结构保证。"""
        return rs.get_active_inflight_job_ids() | _DELIVERY_INFLIGHT_RECORD_IDS

    rid = (req.record_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="record_id 不能为空")

    # 1. 幂等性检查：如果已经标记过取消，直接返回成功
    if abort_mod.is_job_delivery_cancelled(rid):
        return {
            "status": "success",
            "message": "该岗位已处于终止处理流程中",
            "record_id": rid,
            "already_cancelled": True,
        }

    # 2. 状态守卫：检查岗位是否正在投递中（仅限真正处于投递中的岗位）
    if rid not in _inflight_union():
        logger.warning(f"⚠️ [cancel-job-delivery] 拒绝终止非在途岗位: {rid}")
        raise HTTPException(
            status_code=400,
            detail=f"岗位 {rid} 当前未处于自动投递进行状态，无法执行终止投递",
        )

    logger.warning(f"🛑 [cancel-job-delivery] 收到用户终止指令，立即刹车并打断岗位 {rid}...")
    # 3. 登记取消标记
    abort_mod.cancel_job_delivery(rid)
    # 4. 触发浏览器活跃打断（若有活跃页面立即破门关闭，放入线程池避免阻塞事件循环）
    interrupted = await asyncio.to_thread(delivery_interrupter.interrupt_active_job, rid)

    # 5. 竞态兜底：登记瞬间岗位可能刚好收尾（守卫检查与登记之间的窗口）。此时标记已无人
    # 消费，留在全局集合里会污染该岗位的下一次重试（首次被误判为用户主动终止而空转）。
    if rid not in _inflight_union():
        abort_mod.clear_job_delivery_cancelled(rid)
        logger.info(f"ℹ️ [cancel-job-delivery] 岗位 {rid} 已在本指令下达时收尾，撤销取消标记")
        return {
            "status": "success",
            "message": "岗位已结束投递，终止标记已撤销",
            "record_id": rid,
            "interrupted": interrupted,
            "already_finished": True,
        }

    return {
        "status": "success",
        "message": "终止指令已下达" + ("并成功打断浏览器等待" if interrupted else "，等待执行器安全退出"),
        "record_id": rid,
        "interrupted": interrupted,
    }
