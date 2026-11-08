import os
import tempfile

import pytest
from fastapi.testclient import TestClient
import app.automation.db as adb

def test_save_and_get_autopilot_config(tmp_path, monkeypatch, client: TestClient):
    # 隔离测试数据库，禁止写入生产 autopilot.db
    test_db = str(tmp_path / "autopilot.db")
    monkeypatch.setattr(adb, "DB_PATH", test_db)
    adb.init_autopilot_db()

    # Test data representing all platforms
    payload = {
        "cron_time": "10:30",
        "auto_deliver_grades": ["A", "B"],
        "is_enabled": True,
        "platform_configs": {
            "boss": {"limit": 10, "keyword": "前端", "city": "北京", "salary": "20K-30K"},
            "xiaohongshu": {"limit": 5, "keyword": "产品", "sort_by": "time_descending"},
            "liepin": {"limit": 8, "keyword": "后端", "city": "上海", "salary": "30K-50K"},
            "zhilian": {"limit": 2, "keyword": "测试", "city": "广州", "salary": "10K-15K"},
            "51job": {"limit": 1, "keyword": "运维", "city": "深圳", "salary": "15K-20K"}
        }
    }

    # 1. POST config
    response = client.post("/api/automation/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"

    # 2. GET config to verify persistence
    response = client.get("/api/automation/config")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    
    config = data["data"]
    assert config["cron_time"] == "10:30"
    assert "A" in config["auto_deliver_grades"]
    assert config["is_enabled"] is True
    
    platforms = config["platform_configs"]
    
    # Verify all platforms
    assert platforms["boss"]["salary"] == "20K-30K"
    assert platforms["boss"]["limit"] == 10
    
    assert platforms["xiaohongshu"]["sort_by"] == "time_descending"
    assert platforms["xiaohongshu"]["limit"] == 5
    
    assert platforms["liepin"]["city"] == "上海"
    assert platforms["liepin"]["salary"] == "30K-50K"
    
    assert platforms["zhilian"]["salary"] == "10K-15K"
    assert platforms["zhilian"]["keyword"] == "测试"
    
    assert platforms["51job"]["city"] == "深圳"
    assert platforms["51job"]["limit"] == 1


def test_save_config_partial_preserves_greeting(tmp_path, monkeypatch, client: TestClient):
    """验证 PATCH 防覆盖回归：只传部分字段保存时，未传入的打招呼语与海投白名单绝不得被清空。"""
    test_db = str(tmp_path / "autopilot.db")
    monkeypatch.setattr(adb, "DB_PATH", test_db)
    adb.init_autopilot_db()

    # 1. 预先设置好打招呼语和投递等级
    original_greeting = "您好，这是现有的通用海投打招呼语。"
    adb.update_autopilot_config(
        mass_apply_greeting=original_greeting,
        auto_deliver_grades=["C", "D", "F"],
    )

    # 2. 模拟前端仅更新定时任务，未传 mass_apply_greeting
    partial_payload = {
        "cron_time": "08:30",
        "is_enabled": True,
    }
    resp = client.post("/api/automation/config", json=partial_payload)
    assert resp.status_code == 200

    # 3. 校验打招呼语与投递等级依然完好
    cfg = adb.get_autopilot_config()
    assert cfg["cron_time"] == "08:30"
    assert cfg["mass_apply_greeting"] == original_greeting
    assert cfg["auto_deliver_grades"] == ["C", "D", "F"]



def test_partial_config_patch_keeps_is_enabled(tmp_path, monkeypatch, client):
    """/config 是 PATCH 语义（model_fields_set 判定）：仅显式携带 is_enabled 才写库。

    2026-10-29 schema 默认值 True→False 改动的回归防护：只传 cron_time 的部分更新
    不得把开关悄悄改成 schema 默认 False（否则会把已开启定时的用户误关）。
    """
    test_db = str(tmp_path / "autopilot.db")
    monkeypatch.setattr(adb, "DB_PATH", test_db)
    adb.init_autopilot_db()

    # 先显式开启定时
    r = client.post("/api/automation/config", json={"cron_time": "09:00", "is_enabled": True})
    assert r.status_code == 200, r.text
    assert adb.get_autopilot_config()["is_enabled"] is True

    # 部分更新：只传 cron_time，不携带 is_enabled → 开关必须保持 True
    r = client.post("/api/automation/config", json={"cron_time": "08:00"})
    assert r.status_code == 200, r.text
    cfg = adb.get_autopilot_config()
    assert cfg["is_enabled"] is True
    assert cfg["cron_time"] == "08:00"


def test_schedule_config_requires_explicit_fields(client):
    """schedule-config 必填契约（2026-10-29 复审建议采纳）：缺 is_enabled/cron_time 直接 422，
    不得静默按默认值落库（缺省 False 会误关、缺省 True 会复活）。"""
    r = client.post("/api/automation/schedule-config", json={"cron_time": "08:00"})
    assert r.status_code == 422, r.text  # 缺 is_enabled

    r = client.post("/api/automation/schedule-config", json={"is_enabled": True})
    assert r.status_code == 422, r.text  # 缺 cron_time


def test_scheduler_shutdown_on_client_exit():
    """TestClient 退出后自动化调度器必须已停止（lifespan shutdown 修复的行为级验证）。

    修复前 main.py 引用不存在的 _scheduler 符号，shutdown 静默失效，
    AsyncIOScheduler 单例残留 state=running + 已关闭的事件循环。
    用自建 function 级 TestClient：client fixture 是 module 级（收尾清场在所有
    module 用例之后），断言必须在自己这个 client 的 lifespan 退出后立刻做。
    """
    import sqlite3

    from fastapi.testclient import TestClient

    import app.automation.db as adb_mod
    from app.main import app as main_app

    with tempfile.TemporaryDirectory() as td:
        old_db = adb_mod.DB_PATH
        try:
            # 只换 autopilot 库路径，其余 lifespan 初始化沿用真实环境
            adb_mod.DB_PATH = os.path.join(td, "autopilot.db")
            adb_mod.init_autopilot_db()

            # R6-P2 修正：断言状态迁移而非共享终态——进入前先确保单例为未启动态
            # （module 级 client fixture 可能残留 running），再验证本 client 的
            # lifespan「启动拉起 → 退出停止」的完整迁移。
            from app.automation import scheduler as sch

            if sch.scheduler.running:
                sch.scheduler.shutdown(wait=False)
            sch.scheduler.state = 0
            sch.scheduler._eventloop = None
            sch.scheduler.remove_all_jobs()
            assert sch.scheduler.running is False  # 前置：未启动态

            with TestClient(main_app) as c:
                assert sch.scheduler.running is True  # 本 client 的 lifespan 启动段真实拉起
            # with 退出 = 本 client 的 lifespan shutdown 已执行
            assert sch.scheduler.running is False  # 修复后必须被优雅停止
            assert sch.scheduler.state == 0
        finally:
            adb_mod.DB_PATH = old_db


def test_schedule_config_full_payload_ok(tmp_path, monkeypatch, client):
    """schedule-config 正向契约：前端保存按钮的整包 payload（五字段齐全）→ 200 并落库生效。"""
    monkeypatch.setattr(adb, "DB_PATH", str(tmp_path / "autopilot.db"))
    adb.init_autopilot_db()
    payload = {
        "cron_time": "08:15",
        "is_enabled": True,
        "schedule_start_date": "2026-11-01",
        "schedule_end_date": "",
        "skip_non_workdays": True,
    }
    r = client.post("/api/automation/schedule-config", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert "已生效" in body["message"]
    cfg = adb.get_autopilot_config()
    assert cfg["is_enabled"] is True
    assert cfg["cron_time"] == "08:15"
    assert cfg["schedule_start_date"] == "2026-11-01"
