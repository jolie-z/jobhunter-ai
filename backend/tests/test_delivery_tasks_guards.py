"""delivery_tasks 守卫与工具函数覆盖补强（质检 2.2/2.4，Q10 同批）。

补测对象为覆盖率实测弱项（53%→目标 70%+）：
- _get_active_func / _call_guard / _call_resume（测试打桩解析与签名兼容）
- _check_schedule_date_range（定时日期范围四象限）
- _check_non_workday（skip 开关/工作日/周末/节假日/数据未覆盖 fail-open 五分支）
- _is_51job_platform / _prioritize_51job_mass（51job 排头兵规则）
- get_pipeline_app / set_pipeline_app（依赖注入与 scheduler 穿透）
"""
import sys
from datetime import date, datetime
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 桩函数的未用参数（label/job_id/pipeline_app/mock_scheduler_date）是「签名兼容契约」的被测对象本身，
# 非意外遗漏；fixture 注入后未在断言中直接引用亦属正常。故文件级豁免 ARG001。
# ruff: noqa: ARG001
from app.automation import delivery_tasks as dt

# ---------------- 依赖注入与打桩解析 ----------------

def test_get_pipeline_app_explicit_priority(monkeypatch):
    """显式 set_pipeline_app 优先于 scheduler 穿透（scheduler 未预加载时注入替身，消除顺序依赖）。"""
    monkeypatch.setattr(dt, "pipeline_app", None, raising=False)
    sched = sys.modules.get("app.automation.scheduler") or ModuleType("app.automation.scheduler")
    monkeypatch.setitem(sys.modules, "app.automation.scheduler", sched)
    sentinel = object()
    monkeypatch.setattr(sched, "pipeline_app", sentinel, raising=False)
    assert dt.get_pipeline_app() is sentinel  # 穿透路径
    mine = object()
    dt.set_pipeline_app(mine)
    assert dt.get_pipeline_app() is mine  # 显式优先
    dt.set_pipeline_app(None)


def test_get_active_func_prefers_scheduler_stub(monkeypatch):
    """scheduler 上存在同名打桩（且不是默认函数本体）时优先采用；否则回退默认。"""
    default_fn = dt._check_non_workday
    assert dt._get_active_func("_check_non_workday", default_fn) is default_fn

    sched = ModuleType("app.automation.scheduler")
    stub = lambda *a, **k: True  # noqa: E731
    monkeypatch.setitem(sys.modules, "app.automation.scheduler", sched)
    # 未打桩：回退默认
    assert dt._get_active_func("_check_non_workday", default_fn) is default_fn
    # 打桩后：优先打桩
    monkeypatch.setattr(sched, "_check_non_workday", stub, raising=False)
    assert dt._get_active_func("_check_non_workday", default_fn) is stub
    # 打桩值恰好等于默认本体：仍回退默认（避免误把本体当打桩）
    monkeypatch.setattr(sched, "_check_non_workday", default_fn, raising=False)
    assert dt._get_active_func("_check_non_workday", default_fn) is default_fn


def test_call_guard_signature_compat():
    """守卫调用自动兼容 (label, pipeline_app=) 双参与仅 label 单参两种打桩。"""
    calls = []

    def two_args(label, pipeline_app=None):
        calls.append("two")
        return True

    def one_arg(label):
        calls.append("one")
        return False

    assert dt._call_guard(two_args, "test_guard_label", pipeline_app=object()) is True
    assert dt._call_guard(one_arg, "test_guard_label", pipeline_app=object()) is False
    assert calls == ["two", "one"]


@pytest.mark.asyncio
async def test_call_resume_signature_compat():
    """恢复调用自动兼容 (job_id, pipeline_app=) 双参与仅 job_id 单参两种打桩协程。"""

    async def two_args(job_id, pipeline_app=None):
        return True, "双参"

    async def one_arg(job_id):
        return False, "单参"

    assert await dt._call_resume(two_args, "rec1", pipeline_app=object()) == (True, "双参")
    # 单参桩 + 显式 pipeline_app：生产方始终携带上下文调用时 TypeError 回退的完整路径
    assert await dt._call_resume(one_arg, "rec1", pipeline_app=object()) == (False, "单参")


# ---------------- 定时日期范围（四象限） ----------------

def test_schedule_date_range_quadrants(monkeypatch):
    monkeypatch.setattr(dt, "datetime", type(
        "FakeDT", (), {"now": staticmethod(lambda: datetime(2026, 9, 19, 10, 0, 0))}))

    # 未配置：不限
    assert dt._check_schedule_date_range({}) == (True, "")
    # 在范围内
    ok = dt._check_schedule_date_range({"schedule_start_date": "2026-09-01", "schedule_end_date": "2026-09-30"})
    assert ok == (True, "")
    # 早于开始
    early = dt._check_schedule_date_range({"schedule_start_date": "2026-10-01"})
    assert early[0] is False and "早于" in early[1]
    # 晚于结束
    late = dt._check_schedule_date_range({"schedule_end_date": "2026-09-01"})
    assert late[0] is False and "已过" in late[1]


# ---------------- 非工作日守卫（五分支） ----------------

class _FakeDate(date):
    """可注入 today() 的日期替身（delivery_tasks 经 scheduler.date 穿透获取）。"""

    @classmethod
    def today(cls):  # noqa: D102
        return cls(2026, 9, 19)  # 周六


def _with_fake_chinese_calendar(monkeypatch, impl):
    mod = ModuleType("chinese_calendar")
    mod.is_workday = impl
    monkeypatch.setitem(sys.modules, "chinese_calendar", mod)


def test_non_workday_switch_off(monkeypatch):
    """skip_non_workdays 未开启：任何日期直接放行。"""
    monkeypatch.setitem(sys.modules, "app.automation.scheduler", ModuleType("app.automation.scheduler"))
    allow, reason = dt._check_non_workday({})
    assert (allow, reason) == (True, "")


@pytest.fixture
def mock_scheduler_date(monkeypatch):
    """注入 scheduler 模块替身并将 date 穿透指向 _FakeDate（2026-09-19 周六）。"""
    sched = ModuleType("app.automation.scheduler")
    monkeypatch.setitem(sys.modules, "app.automation.scheduler", sched)
    monkeypatch.setattr(sched, "date", _FakeDate, raising=False)
    return sched


def test_non_workday_workday_pass(monkeypatch, mock_scheduler_date):
    _with_fake_chinese_calendar(monkeypatch, lambda d: True)  # 周六但调休补班
    allow, reason = dt._check_non_workday({"skip_non_workdays": True})
    assert (allow, reason) == (True, "")


def test_non_workday_holiday_block(monkeypatch, mock_scheduler_date):
    _with_fake_chinese_calendar(monkeypatch, lambda d: False)  # 法定节假日
    allow, reason = dt._check_non_workday({"skip_non_workdays": True})
    assert allow is False and "非工作日" in reason


def test_non_workday_data_gap_weekend_block(monkeypatch, mock_scheduler_date):
    """chinese-calendar 未覆盖当年（NotImplementedError）：周末按周末跳过。"""

    def impl(d):
        raise NotImplementedError("no data")

    _with_fake_chinese_calendar(monkeypatch, impl)
    allow, reason = dt._check_non_workday({"skip_non_workdays": True})
    assert allow is False and "周末" in reason


def test_non_workday_data_gap_weekday_fail_open(monkeypatch):
    """数据未覆盖但落在周中：fail-open 放行（避免工作日静默断供）。"""
    class _Wed(_FakeDate):
        @classmethod
        def today(cls):
            return cls(2026, 9, 23)  # 周三

    monkeypatch.setitem(sys.modules, "app.automation.scheduler", ModuleType("app.automation.scheduler"))
    monkeypatch.setattr(sys.modules["app.automation.scheduler"], "date", _Wed, raising=False)

    def impl(d):
        raise NotImplementedError("no data")

    _with_fake_chinese_calendar(monkeypatch, impl)
    allow, reason = dt._check_non_workday({"skip_non_workdays": True})
    assert (allow, reason) == (True, "")


def test_non_workday_package_missing_fail_open(monkeypatch, mock_scheduler_date):
    """未安装 chinese-calendar：直接放行并告警。"""
    monkeypatch.setitem(sys.modules, "chinese_calendar", None)  # import 触发 ImportError
    allow, reason = dt._check_non_workday({"skip_non_workdays": True})
    assert (allow, reason) == (True, "")


# ---------------- 51job 排头兵 ----------------

def test_is_51job_platform_variants():
    assert dt._is_51job_platform("51job") is True
    assert dt._is_51job_platform("前程无忧") is True
    assert dt._is_51job_platform("boss") is False
    assert dt._is_51job_platform(None) is False
    assert dt._is_51job_platform("") is False


def test_prioritize_51job_mass_ordering():
    """51job 精投稳定后移（海投先拿当日配额），其余岗位相对顺序不变（稳定排序）。"""
    targets = [
        {"platform": "前程无忧", "job_id": "j2", "is_custom": True},
        {"platform": "boss", "job_id": "b1"},
        {"platform": "51job", "job_id": "j3", "is_custom": True},
        {"platform": "51job", "job_id": "j1", "is_custom": False},
        {"platform": "猎聘", "job_id": "l1"},
    ]
    ordered = dt._prioritize_51job_mass(targets)
    ids = [t["job_id"] for t in ordered]
    # 51job/前程无忧的精投岗（j2/j3）即便在输入头部也必须被后移；其余保持原相对顺序
    assert ids == ["b1", "j1", "l1", "j2", "j3"]
