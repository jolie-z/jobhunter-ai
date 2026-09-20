"""非工作日跳过闸门 _check_non_workday 的回归测试。

该闸门同时服务于每日定时采集（trigger_auto_apply_job）与定时发射
（_delivery_guard_ok），开关为 automation_configs.skip_non_workdays。
覆盖：周末跳过、周中法定节假日跳过、调休补班的周六日照常执行、
开关关闭不拦截、chinese-calendar 数据未覆盖当年 / 包缺失时 fail-open。
"""
import datetime
import sys

import app.automation.scheduler as sched


def _freeze_today(monkeypatch, y, m, d):
    """把 scheduler 模块内的 date.today() 钉死到指定日期。"""
    class _FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(y, m, d)
    monkeypatch.setattr(sched, "date", _FrozenDate, raising=False)  # be5e61a 后 date 移入 delivery_tasks，此处打补丁供其 getattr 钩子读取


ON = {"skip_non_workdays": True}
OFF = {"skip_non_workdays": False}


def test_switch_off_always_allows(monkeypatch):
    _freeze_today(monkeypatch, 2026, 10, 1)  # 国庆法定假日
    allow, reason = sched._check_non_workday(OFF)
    assert allow and reason == ""


def test_weekday_holiday_blocked(monkeypatch):
    _freeze_today(monkeypatch, 2026, 10, 1)  # 周四，国庆：只看周末拦不住的日子
    allow, reason = sched._check_non_workday(ON)
    assert not allow and "非工作日" in reason


def test_regular_saturday_blocked(monkeypatch):
    _freeze_today(monkeypatch, 2026, 8, 29)  # 普通周六
    allow, reason = sched._check_non_workday(ON)
    assert not allow and "非工作日" in reason


def test_in_lieu_work_sunday_allowed(monkeypatch):
    _freeze_today(monkeypatch, 2026, 1, 4)  # 调休补班的周日，HR 在岗照常跑
    allow, reason = sched._check_non_workday(ON)
    assert allow and reason == ""


def test_regular_friday_allowed(monkeypatch):
    _freeze_today(monkeypatch, 2026, 8, 28)  # 普通周五
    allow, reason = sched._check_non_workday(ON)
    assert allow and reason == ""


def test_missing_year_fail_open_weekend_still_blocked(monkeypatch):
    _freeze_today(monkeypatch, 2030, 1, 5)  # 2030 安排未发布，周六 → 退化为只跳周末
    allow, reason = sched._check_non_workday(ON)
    assert not allow and "周末" in reason


def test_missing_year_fail_open_weekday_allowed(monkeypatch):
    _freeze_today(monkeypatch, 2030, 1, 7)  # 2030 安排未发布，周一 → 默认放行不断供
    allow, reason = sched._check_non_workday(ON)
    assert allow and reason == ""


def test_package_missing_fail_open(monkeypatch):
    _freeze_today(monkeypatch, 2026, 8, 29)  # 周六但包不可用 → 放行（宁跑勿停）
    monkeypatch.setitem(sys.modules, "chinese_calendar", None)
    allow, reason = sched._check_non_workday(ON)
    assert allow and reason == ""
