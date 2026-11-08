"""autopilot 配置持久化：greeting_platforms 读写 + schema 覆盖保护 + preflight 环境变量

背景：
- 打招呼生成平台开关（greeting_platforms）持久化到 automation_configs；
- /api/automation/config 是整体覆盖式接口，旧客户端不带新字段时必须保留库里已有值
  （靠 pydantic model_fields_set 判定）；
- 登录态预检等待窗口由 PIPELINE_LOGIN_WAIT_S / PIPELINE_LOGIN_POLL_S 控制。
"""
import pytest

import app.automation.db as adb
from app.automation.schemas import AutopilotConfigSchema
from app.session import preflight


def test_greeting_platforms_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()

    cfg = adb.get_autopilot_config()
    assert cfg["greeting_platforms"] == {"boss": True, "liepin": True, "zhilian": True, "51job": False}

    new_gp = {"boss": False, "liepin": True, "51job": True, "zhilian": False}
    ok = adb.update_autopilot_config(
        "09:30", ["C", "D"], ["boss"], True, {},
        20, "", "", 1000, "", new_gp,
    )
    assert ok
    cfg2 = adb.get_autopilot_config()
    assert cfg2["greeting_platforms"] == new_gp
    assert cfg2["cron_time"] == "09:30"
    assert cfg2["auto_deliver_grades"] == ["C", "D"]


def test_schema_fields_set_guard():
    """旧客户端请求不带 greeting_platforms 时，model_fields_set 不含该字段（防覆盖判定依据）"""
    req = AutopilotConfigSchema.model_validate({"cron_time": "08:00"})
    assert "greeting_platforms" not in req.model_fields_set

    req2 = AutopilotConfigSchema.model_validate({"greeting_platforms": {"boss": False}})
    assert "greeting_platforms" in req2.model_fields_set
    assert req2.greeting_platforms == {"boss": False}


def test_preflight_env_parsing(monkeypatch):
    monkeypatch.setenv("PIPELINE_LOGIN_WAIT_S", "60")
    monkeypatch.setenv("PIPELINE_LOGIN_POLL_S", "5")
    assert preflight._wait_seconds() == 60
    assert preflight._poll_seconds() == 5

    # 非法值回退默认
    monkeypatch.setenv("PIPELINE_LOGIN_WAIT_S", "abc")
    assert preflight._wait_seconds() == 300
    monkeypatch.delenv("PIPELINE_LOGIN_WAIT_S", raising=False)
    monkeypatch.delenv("PIPELINE_LOGIN_POLL_S", raising=False)
    assert preflight._wait_seconds() == 300
    assert preflight._poll_seconds() == 10


def _reset_apscheduler_singleton(monkeypatch):
    """重置模块级 AsyncIOScheduler 单例的事件循环绑定。

    既有路由测试经 TestClient 真实 start 过调度器，会把 _eventloop 绑到已关闭的
    应用循环；本文件打桩跳过 start() 后 _eventloop 不会重绑，add_job → wakeup()
    会打到死循环上报 RuntimeError(Event loop is closed)。启动前先清状态，
    add_job 在未启动调度器上只登记不唤醒（与我们「只验证注册结果」的语义一致）。
    """
    from app.automation import scheduler as sch
    monkeypatch.setattr(sch.scheduler, "start", lambda: None)  # 不真起调度线程
    monkeypatch.setattr(sch.scheduler, "_eventloop", None, raising=False)
    monkeypatch.setattr(sch.scheduler, "state", 0, raising=False)
    return sch


def test_fresh_install_default_schedule_disabled(monkeypatch, tmp_path):
    """2026-10-29 默认关修复的行为级验证：全新库 init 后总开关为关，
    start_scheduler 不注册 daily_scout_task（其余运维任务照常注册形成对照）。"""
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()
    assert adb.get_autopilot_config()["is_enabled"] is False

    sch = _reset_apscheduler_singleton(monkeypatch)
    try:
        sch.start_scheduler()
        assert sch.scheduler.get_job("daily_scout_task") is None
        # 对照组：无条件注册的运维任务仍在
        assert sch.scheduler.get_job("session_health_check") is not None
    finally:
        sch.scheduler.remove_all_jobs()


def test_explicit_enable_registers_daily_task(monkeypatch, tmp_path):
    """显式开启走 PATCH 持久化 + 热注册；关闭则移除任务并持久化为关。"""
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()

    sch = _reset_apscheduler_singleton(monkeypatch)

    assert adb.update_autopilot_config(cron_time="09:00", is_enabled=True)
    assert adb.get_autopilot_config()["is_enabled"] is True

    try:
        sch.update_scheduler_cron("09:00", True)
        job = sch.scheduler.get_job("daily_scout_task")
        assert job is not None
        assert "hour='9'" in str(job.trigger)  # CronTrigger(hour=9, minute=0)

        sch.update_scheduler_cron("09:00", False)
        assert sch.scheduler.get_job("daily_scout_task") is None

        assert adb.update_autopilot_config(is_enabled=False)
        assert adb.get_autopilot_config()["is_enabled"] is False
    finally:
        sch.scheduler.remove_all_jobs()


def test_existing_v040_db_upgrade_preserves_row(monkeypatch, tmp_path):
    """存量 0.4.0 旧库（旧 DDL DEFAULT 1 + 旧行）升级不迁移：行为级验证。

    用 0.4.0 的旧 DDL 建表 + 旧行，跑 init_autopilot_db（幂等：表已存在不重建、
    id=1 行已存在不 INSERT，仅补新列）后断言行未被改写；start_scheduler 仍注册
    daily_scout_task（与升级前行为一致）；再走 0.4.1 提示的手动关闭路径确认可移除。
    """
    import sqlite3

    db_file = tmp_path / "autopilot.db"
    conn = sqlite3.connect(db_file)
    conn.execute('''
        CREATE TABLE automation_configs (
            id INTEGER PRIMARY KEY DEFAULT 1,
            cron_time TEXT NOT NULL,
            auto_deliver_grades TEXT NOT NULL,
            auto_deliver_platforms TEXT NOT NULL DEFAULT '["boss", "liepin", "51job", "zhilian"]',
            is_enabled BOOLEAN NOT NULL DEFAULT 1,
            platform_configs TEXT DEFAULT '{}'
        )
    ''')
    conn.execute(
        "INSERT INTO automation_configs (id, cron_time, auto_deliver_grades, auto_deliver_platforms, is_enabled, platform_configs) "
        "VALUES (1, '09:00', '[\"C\", \"D\", \"F\"]', '[\"boss\", \"liepin\", \"51job\", \"zhilian\"]', 1, '{}')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(adb, "DB_PATH", str(db_file))
    adb.init_autopilot_db()

    cfg = adb.get_autopilot_config()
    assert cfg["is_enabled"] is True  # 旧行未被改写（不迁移）
    assert cfg["cron_time"] == "09:00"

    sch = _reset_apscheduler_singleton(monkeypatch)
    try:
        sch.start_scheduler()
        assert sch.scheduler.get_job("daily_scout_task") is not None  # 存量行为与升级前一致

        # 用户按 0.4.1 更新日志「老用户提示」手动关闭
        assert adb.update_autopilot_config(is_enabled=False)
        sch.update_scheduler_cron("09:00", False)
        assert sch.scheduler.get_job("daily_scout_task") is None
    finally:
        sch.scheduler.remove_all_jobs()


@pytest.mark.asyncio
async def test_manual_trigger_does_not_check_is_enabled(monkeypatch, tmp_path):
    """手动全链路 /trigger 不受每日定时开关影响（行为级验证）。

    control_router.py 的 handler 直接调用 run_full_auto_pipeline(trigger_source="manual")，
    不经过 cron 入口 trigger_auto_apply_job、无 is_enabled 检查——新装默认关后，
    手动启动链路必须照常（这是「默认关只关无人值守定时」结论的核心支撑）。
    """
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()
    assert adb.get_autopilot_config()["is_enabled"] is False  # 新装默认关

    import app.automation.full_auto as full_auto

    captured: dict = {}

    async def fake_run_full_auto_pipeline(*args, **kwargs):
        captured.update(kwargs)
        return "pipeline_test_manual"

    monkeypatch.setattr(full_auto, "run_full_auto_pipeline", fake_run_full_auto_pipeline)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        # 缺 confirm 被防误触发守卫拦截（与开关无关的前置闸门）
        r = client.post("/api/automation/trigger", json={})
        assert r.status_code == 400
        # 显式 confirm=true：手动链路照常启动（若 handler 读 is_enabled 并跳过，这里会失败）
        r = client.post("/api/automation/trigger", json={"confirm": True})
        assert r.status_code == 200, r.text
        assert r.json()["pipeline_task_id"] == "pipeline_test_manual"
    assert captured.get("trigger_source") == "manual"


def test_delivery_guard_blocks_wave_when_disabled(monkeypatch, tmp_path):
    """波次闸门语义锁定：is_enabled=False（新装默认）时 _delivery_guard_ok 不放行定时发射。

    这是「每日定时开关管整条无人值守链路（采集+发射波次）」的契约锚点——
    防止后续把闸门改掉而让关闭态下波次继续发射。手动审批投递不走此闸门。
    冻结日期与并发检查：断言真值只随 is_enabled 变化（周末/节假日跑测试不假红）。
    """
    from datetime import date as real_date

    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()  # 新装默认 is_enabled=False

    from app.automation import delivery_tasks as dt

    monkeypatch.setattr(dt, "pipeline_app", object())  # 打桩管线已初始化（隔离「未初始化」分支）

    # 冻结日期为周一（FakeDate 子类覆写 today：R6-P1 修正——直接 setattr 实例时
    # date.today() classmethod 仍绑定真实类型返回真实今天，冻结无效）；
    # 打桩无并发管道运行。断言真值只随 is_enabled 变化。
    class FakeDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 2)  # 周一

    monkeypatch.setattr(dt, "date", FakeDate)
    # datetime.now 用于日期范围检查：范围字段本用例为空，不受影响，无需冻结
    import app.automation.pipeline_broadcast as pb
    monkeypatch.setattr(pb, "get_current_pipeline", lambda: {"running": False})

    assert dt._delivery_guard_ok("定时投递·测试") is False  # 开关关闭 → 波次不放行

    assert adb.update_autopilot_config(is_enabled=True)
    # 开启后本闸门放行（日期范围内 + 工作日 + 无并发管道均已冻结为通过态）
    assert dt._delivery_guard_ok("定时投递·测试") is True

    # 对照（R6-P1 要求的「证明日期确实被替换」）：把冻结日改成周六，工作日闸门必须拦截
    # ——若 monkeypatch 没生效（today 仍返回真实今天），工作日下本断言将假红暴露
    class FakeSaturday(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 7)  # 周六

    monkeypatch.setattr(dt, "date", FakeSaturday)
    assert dt._delivery_guard_ok("定时投递·测试") is False  # 周六 HR 不在岗，即使开关开启也不放行


def test_delivery_guard_blocks_running_pipeline(monkeypatch, tmp_path):
    """并发互斥分支自证（R6-P2）：pb.get_current_pipeline 打桩必须被真实消费——
    stub 返回 running=True 时闸门必须 False（证明打桩绑定有效，非 no-op）。"""
    from datetime import date as real_date

    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()

    from app.automation import delivery_tasks as dt

    monkeypatch.setattr(dt, "pipeline_app", object())
    assert adb.update_autopilot_config(is_enabled=True)  # 打开开关，隔离其他分支

    class FakeDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 2)  # 周一

    monkeypatch.setattr(dt, "date", FakeDate)

    import app.automation.pipeline_broadcast as pb
    # _delivery_guard_ok 内部 `from ... import pipeline_broadcast as pb` 后以模块属性调用，
    # monkeypatch 模块属性即生效（此处用行为断言自证，而非依赖绑定方式推断）
    monkeypatch.setattr(pb, "get_current_pipeline", lambda: {"running": True})
    assert dt._delivery_guard_ok("定时投递·测试") is False  # 全链路正在运行 → 跳过波次

    monkeypatch.setattr(pb, "get_current_pipeline", lambda: {"running": False})
    assert dt._delivery_guard_ok("定时投递·测试") is True  # 同环境解除并发 → 放行
