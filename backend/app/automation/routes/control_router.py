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

from fastapi import APIRouter, HTTPException
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
async def trigger_autopilot_manual(req: TriggerRequest):
    """手动立即触发一轮【全自动链路】(抓取→清洗→飞书→评估→投递)。

    必须携带 {"confirm": true}：防脚本/预检/误碰空参直启真实链路（Q17 守卫）。
    """
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="缺少确认参数：请携带 {\"confirm\": true} 启动全链路（防误触发守卫）",
        )
    try:
        from app.automation.full_auto import run_full_auto_pipeline
        pipeline_task_id = await run_full_auto_pipeline()
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
    """终止当前运行中的全自动链路（优雅终止）。"""
    from app.api.routes.crawlers import stop_platform
    from app.automation import abort as abort_mod
    ok = abort_mod.request_abort(req.task_id)
    if not ok:
        return {"status": "success", "message": "终止指令与当前任务不匹配，已忽略", "aborted": False}
    for p in abort_mod.KNOWN_PLATFORMS:
        stop_platform(p)
        abort_mod.request_platform_abort(p)
    return {"status": "success", "message": "终止指令已下达，链路将在安全点收尾", "aborted": True}


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


@router.get("/run-snapshot")
async def run_snapshot():
    """本轮各平台真实抓取台账（查库权威值）：刷新页面后前端靠它恢复进度数字。"""
    from app.automation import run_snapshot as rs
    return {"status": "success", "data": rs.compute(RAW_DB_PATH, PLATFORM_CN)}


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

    # 🚀 Q21 配套：三个子负载并发执行（此前 jobs_snapshot 之后再串行跑 config/run 两个查库），
    # 墙钟 = 最慢的 jobs_snapshot，而非三者之和。
    jobs_payload, config_modules, run_platforms = await asyncio.gather(
        build_jobs_snapshot(),
        asyncio.to_thread(config_status),
        asyncio.to_thread(rs.compute, RAW_DB_PATH, PLATFORM_CN),
    )
    return {
        "status": "success",
        "data": {
            "config_status": config_modules,
            "current_pipeline": {"status": "success", "data": pb.get_current_pipeline()},
            "run_snapshot": {"status": "success", "data": run_platforms},
            "jobs_snapshot": jobs_payload,
        },
    }


@router.get("/console-stream")
async def console_stream():
    """后端实时日志流（print + logging），先回放最近 800 行再实时推送。"""
    from app.automation import console_stream as cs

    async def gen():
        for line in cs.snapshot():
            yield cs.sse_line(line)
        q = cs.subscribe()
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15)
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
    inflight_jobs = rs.get_active_inflight_job_ids() | _DELIVERY_INFLIGHT_RECORD_IDS
    if rid not in inflight_jobs:
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

    return {
        "status": "success",
        "message": "终止指令已下达" + ("并成功打断浏览器等待" if interrupted else "，等待执行器安全退出"),
        "record_id": rid,
        "interrupted": interrupted,
    }
