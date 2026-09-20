import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.automation.checkpoint_gc import run_scheduled_gc_async
from app.automation.db import (
    get_autopilot_config,
    init_autopilot_db,
)
from app.automation.db_backup import run_scheduled_backup_async
from app.automation.delivery_tasks import (  # noqa: F401
    _auto_diagnose,
    _check_non_workday,
    _check_schedule_date_range,
    _delivery_guard_ok,
    _resume_job_delivery,
    custom_delivery_task,
    get_pipeline_app,
    mass_delivery_task,
    run_pipeline_for_job,
    run_scraper_with_rate_limit,
    scheduled_delivery_batch_task,
    set_pipeline_app,
    trigger_auto_apply_job,
    trigger_auto_apply_job_with_guard,
)
from app.automation.workflow import build_pipeline_graph

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = AsyncIOScheduler()
# 全局图执行器实例
pipeline_app = None

__all__ = [
    "scheduler",
    "pipeline_app",
    "init_automation_pipeline",
    "start_scheduler",
    "update_delivery_schedules",
    "update_scheduler_cron",
    "trigger_auto_apply_job",
    "scheduled_delivery_batch_task",
    "mass_delivery_task",
    "custom_delivery_task",
    "trigger_auto_apply_job_with_guard",
    "_resume_job_delivery",
    "_delivery_guard_ok",
    "_check_schedule_date_range",
    "_check_non_workday",
    "_auto_diagnose",
    "run_scraper_with_rate_limit",
    "run_pipeline_for_job",
    "get_pipeline_app",
    "set_pipeline_app",
]


async def init_automation_pipeline(db_path: str = ""):
    """
    初始化自动化流水线，在 FastAPI 启动时调用。
    """
    global pipeline_app

    if not db_path or db_path == "checkpoints.db":
        from pathlib import Path
        db_path = str(Path(__file__).resolve().parents[2] / "langgraph_checkpoints.db")

    logger.info(f"⚙️ 正在初始化 LangGraph 状态机与持久化存储 [db_path={db_path}]...")

    # 初始化底层的 SQLite 连接并保持长连接
    # 注意：工作流通过 astream 异步执行，必须用 AsyncSqliteSaver（同步 SqliteSaver 会抛
    # NotImplementedError: The SqliteSaver does not support async methods）。
    # 用 aiosqlite 建立长连接并直接传入构造器，使其全局存活（不能用 async with，退出会关连接）。
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    conn = await aiosqlite.connect(db_path)
    memory = AsyncSqliteSaver(conn)
    await memory.setup()

    # 编译带断点的执行图
    pipeline_app = build_pipeline_graph().compile(
        checkpointer=memory,
        # 拦截发往 manual_review_node 的边，这就是我们的 "老板审核断点"
        interrupt_before=["manual_review_node"],
    )
    set_pipeline_app(pipeline_app)

    # 初始化自动化数据库表
    init_autopilot_db()

    logger.info("✅ 自动化流水线引擎 (LangGraph) 初始化完成！")
    return pipeline_app


async def _run_session_health_check():
    """定时会话健康检查：探测所有平台登录态，状态变迁时触发预警"""
    # 顺手巡检飞书聊天会话：超 48h 无活动的沉寂（is_active=0 并清内存缓存）
    from app.core.session_manager import get_session_manager
    from app.session.alerter import session_alerter
    from app.session.manager import session_manager

    swept = get_session_manager().sweep_stale_sessions(max_idle_hours=48)
    if swept:
        logger.info(f"💤 已沉寂 {swept} 个超期飞书聊天会话")

    session_manager.check_all(force=True)
    transitions = session_manager.get_state_transitions()
    if transitions:
        logger.warning(f"🚨 检测到 {len(transitions)} 个平台会话过期: {[t['platform'] for t in transitions]}")
        await session_alerter.alert_if_needed(transitions)
    else:
        logger.debug("🩺 会话健康检查完成，所有平台状态正常。")


async def _run_session_renewal():
    """定时会话续期心跳：静默访问各平台首页，续期 BOSS/智联的 7 天滑动登录 cookie"""
    from app.session.renewal import renew_all_sessions

    await asyncio.get_running_loop().run_in_executor(None, renew_all_sessions)


def start_scheduler():
    """启动全局调度器"""
    config = get_autopilot_config()
    if config["is_enabled"]:
        time_parts = config["cron_time"].split(":")
        hour = int(time_parts[0]) if len(time_parts) > 0 else 9
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0

        scheduler.add_job(
            trigger_auto_apply_job,
            CronTrigger(hour=hour, minute=minute),
            id="daily_scout_task",
            replace_existing=True,
        )
        logger.info(f"⏰ APScheduler 调度中心已启动，配置了每日 {config['cron_time']} 的自动化任务。")
    else:
        logger.info("⏸️ APScheduler 自动化开关未开启。")

    # 会话健康检查：每 30 分钟探测所有平台登录态，过期时触发飞书预警
    scheduler.add_job(
        _run_session_health_check,
        CronTrigger(minute="*/30"),
        id="session_health_check",
        replace_existing=True,
    )
    logger.info("🩺 会话健康检查已注册（每 30 分钟）")

    # 会话续期心跳：每 2 天静默访问一次各平台首页，续期 BOSS/智联等 7 天滑动登录 cookie；
    # 任一平台浏览器活跃时自动整轮跳过，不打扰运行中的任务/用户操作
    scheduler.add_job(
        _run_session_renewal,
        CronTrigger(hour=7, minute=40, day="*/2"),
        id="session_renewal_heartbeat",
        replace_existing=True,
    )
    logger.info("🔄 会话续期心跳已注册（每 2 天 07:40）")

    # SQLite 核心库每日热备：04:00 VACUUM INTO 快照（先于 04:30 的 GC，
    # 天然形成 GC 前还原点）；保留最近 7 份，结果落 automation_logs
    scheduler.add_job(
        run_scheduled_backup_async,
        CronTrigger(hour=4, minute=0),
        id="daily_db_backup",
        replace_existing=True,
    )
    logger.info("📦 核心库每日热备已注册（每天 04:00，保留 7 份）")

    # checkpoint 垃圾回收：每天 04:30 清理超期 LangGraph 断点并 VACUUM 瘦身；
    # 流水线运行中自动整轮跳过，待审批岗位强制保护（详见 app/automation/checkpoint_gc.py）
    scheduler.add_job(
        run_scheduled_gc_async,
        CronTrigger(hour=4, minute=30),
        id="checkpoint_gc",
        replace_existing=True,
    )
    logger.info("🧹 checkpoint 垃圾回收已注册（每天 04:30）")

    # T2 每日海投发射 + T3 每日精投发射（时间来自投递配置，保存后热更新）
    update_delivery_schedules()
    logger.info("🚀 海投/精投每日发射任务已注册（时间以投递配置为准）")

    scheduler.start()


def _register_daily_job(job_id: str, func, hhmm) -> bool:
    """按 HH:MM 注册每日任务；时间非法/为空则移除该任务。返回是否注册成功。"""
    try:
        parts = str(hhmm or "").split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logger.info(f"⏸️ 已移除定时任务 {job_id}（时间非法: {hhmm!r}）")
        return False
    scheduler.add_job(
        func,
        CronTrigger(hour=hour, minute=minute),
        id=job_id,
        replace_existing=True,
    )
    return True


def update_delivery_schedules():
    """投递配置保存后热更新每日双时段发射任务（mass_deliver_time: 上午波次 / custom_deliver_time: 下午波次）。"""
    config = get_autopilot_config()
    time_morning = config.get("mass_deliver_time") or "10:00"
    time_afternoon = config.get("custom_deliver_time") or "14:30"
    if _register_daily_job("mass_delivery_task", mass_delivery_task, time_morning):
        logger.info(f"🚀 上午定时发射任务已注册：每天 {time_morning}")
    if _register_daily_job("custom_delivery_task", custom_delivery_task, time_afternoon):
        logger.info(f"🚀 下午定时发射任务已注册：每天 {time_afternoon}")


def update_scheduler_cron(cron_time: str, is_enabled: bool):
    """动态更新或移除 Cron 任务"""
    if not is_enabled:
        if scheduler.get_job("daily_scout_task"):
            scheduler.remove_job("daily_scout_task")
            logger.info("⏸️ 已移除每日自动投递任务 (总开关关闭)。")
        return

    time_parts = cron_time.split(":")
    hour = int(time_parts[0]) if len(time_parts) > 0 else 9
    minute = int(time_parts[1]) if len(time_parts) > 1 else 0

    scheduler.add_job(
        trigger_auto_apply_job,
        CronTrigger(hour=hour, minute=minute),
        id="daily_scout_task",
        replace_existing=True,
    )
    logger.info(f"⏰ 成功将自动化任务时间重置为每天 {cron_time}。")
