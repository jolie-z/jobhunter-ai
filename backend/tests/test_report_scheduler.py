"""
飞书战报调度器生命周期回归测试。
背景：调度器此前仅由前端「保存时间表」接口拉起，应用重启即失联（21:00 静默不推送）；
现已挂载 FastAPI lifespan，本测试锁定「启动即注册、重复启动幂等、开关生效、刷新重建、关闭即停」行为。
注意：AsyncIOScheduler.shutdown 经 call_soon_threadsafe 异步生效，本模块约定 stop 后引用置 None。
"""
from app.services import report_scheduler


def _fixed_schedule():
    return {
        "daily_time": "21:00",
        "weekly_time": "09:00",
        "monthly_time": "09:00",
        "daily_enabled": True,
        "weekly_enabled": True,
        "monthly_enabled": True,
    }


async def test_start_registers_enabled_jobs(monkeypatch):
    monkeypatch.setattr(report_scheduler, "_get_schedule", _fixed_schedule)
    report_scheduler.stop_report_scheduler()
    try:
        report_scheduler.start_report_scheduler()
        assert report_scheduler._scheduler is not None
        assert report_scheduler._scheduler.running
        job_ids = {job.id for job in report_scheduler._scheduler.get_jobs()}
        assert {"daily_report", "weekly_report", "monthly_report"} <= job_ids
    finally:
        report_scheduler.stop_report_scheduler()
    assert report_scheduler._scheduler is None


async def test_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(report_scheduler, "_get_schedule", _fixed_schedule)
    report_scheduler.stop_report_scheduler()
    try:
        report_scheduler.start_report_scheduler()
        first = report_scheduler._scheduler
        report_scheduler.start_report_scheduler()  # 模拟 lifespan 与手动路径叠加调用
        assert report_scheduler._scheduler is first  # 第二次调用不替换实例（无双发）
        assert first.running
    finally:
        report_scheduler.stop_report_scheduler()


async def test_disabled_jobs_not_registered(monkeypatch):
    schedule = _fixed_schedule()
    schedule["weekly_enabled"] = False
    schedule["monthly_enabled"] = False
    monkeypatch.setattr(report_scheduler, "_get_schedule", lambda: schedule)
    report_scheduler.stop_report_scheduler()
    try:
        report_scheduler.start_report_scheduler()
        job_ids = {job.id for job in report_scheduler._scheduler.get_jobs()}
        assert job_ids == {"daily_report"}
    finally:
        report_scheduler.stop_report_scheduler()


async def test_refresh_rebuilds_scheduler(monkeypatch):
    """手动保存路径（refresh = stop + start）必须能重建调度器，不受异步 shutdown 滞后影响。"""
    monkeypatch.setattr(report_scheduler, "_get_schedule", _fixed_schedule)
    report_scheduler.stop_report_scheduler()
    try:
        report_scheduler.start_report_scheduler()
        old = report_scheduler._scheduler
        report_scheduler.refresh_scheduler()
        assert report_scheduler._scheduler is not old
        assert report_scheduler._scheduler.running
        assert len(report_scheduler._scheduler.get_jobs()) == 3
    finally:
        report_scheduler.stop_report_scheduler()
