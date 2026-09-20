# app/services/report_scheduler.py
"""
飞书战报 APScheduler 调度器 - 定时发送日报/周报/月报。
从 job_goals 表读取用户配置的推送时间，支持热更新。
"""
import logging

logger = logging.getLogger(__name__)
_scheduler = None


def _get_schedule():
    """从 job_goals 表读取报告调度配置。"""
    try:
        from app.services.goal_service import get_current_goals
        goals = get_current_goals()
        if goals:
            return {
                "daily_time": goals.get("report_time_daily", "21:00"),
                "weekly_time": goals.get("report_time_weekly", "09:00"),
                "monthly_time": goals.get("report_time_monthly", "09:00"),
                "daily_enabled": bool(goals.get("report_enabled_daily", 1)),
                "weekly_enabled": bool(goals.get("report_enabled_weekly", 1)),
                "monthly_enabled": bool(goals.get("report_enabled_monthly", 1)),
            }
    except Exception:
        pass
    return {
        "daily_time": "21:00", "weekly_time": "09:00", "monthly_time": "09:00",
        "daily_enabled": True, "weekly_enabled": True, "monthly_enabled": True,
    }


async def _run_daily():
    try:
        from app.services.report_feishu import send_daily_report
        logger.info("[report_scheduler] 触发日报发送...")
        await send_daily_report()
    except Exception as e:
        logger.warning(f"[report_scheduler] 日报发送失败: {e}")


async def _run_weekly():
    try:
        from app.services.report_feishu import send_weekly_report
        logger.info("[report_scheduler] 触发周报发送...")
        await send_weekly_report()
    except Exception as e:
        logger.warning(f"[report_scheduler] 周报发送失败: {e}")


async def _run_monthly():
    try:
        from app.services.report_feishu import send_monthly_report
        logger.info("[report_scheduler] 触发月报发送...")
        await send_monthly_report()
    except Exception as e:
        logger.warning(f"[report_scheduler] 月报发送失败: {e}")


def start_report_scheduler():
    """启动战报定时调度器。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return  # 幂等守卫：已在运行则直接返回，防止 lifespan 与手动刷新叠加导致战报双发
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = AsyncIOScheduler()
        schedule = _get_schedule()

        if schedule["daily_enabled"]:
            h, m = schedule["daily_time"].split(":")
            _scheduler.add_job(_run_daily, CronTrigger(hour=int(h), minute=int(m)), id="daily_report", replace_existing=True)
            logger.info(f"[report_scheduler] 日报已注册: 每日 {schedule['daily_time']}")

        if schedule["weekly_enabled"]:
            h, m = schedule["weekly_time"].split(":")
            _scheduler.add_job(_run_weekly, CronTrigger(day_of_week="mon", hour=int(h), minute=int(m)), id="weekly_report", replace_existing=True)
            logger.info(f"[report_scheduler] 周报已注册: 每周一 {schedule['weekly_time']}")

        if schedule["monthly_enabled"]:
            h, m = schedule["monthly_time"].split(":")
            _scheduler.add_job(_run_monthly, CronTrigger(day=1, hour=int(h), minute=int(m)), id="monthly_report", replace_existing=True)
            logger.info(f"[report_scheduler] 月报已注册: 每月1号 {schedule['monthly_time']}")

        _scheduler.start()
        logger.info("[report_scheduler] 战报调度器已启动")
    except ImportError:
        logger.warning("[report_scheduler] APScheduler 未安装，跳过定时战报")
    except Exception as e:
        logger.warning(f"[report_scheduler] 启动失败: {e}")


def stop_report_scheduler():
    """停止调度器。"""
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
            # AsyncIOScheduler.shutdown 经 call_soon_threadsafe 异步生效，running 短暂滞后；
            # 必须置空引用，否则紧随其后的 start 会因守卫误判"仍在运行"而拒绝重建
            _scheduler = None
            logger.info("[report_scheduler] 已停止")
        except Exception as e:
            logger.warning(f"[report_scheduler] 停止失败: {e}")


def refresh_scheduler():
    """目标更新后重新加载调度配置。"""
    stop_report_scheduler()
    start_report_scheduler()
