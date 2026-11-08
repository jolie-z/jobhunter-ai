"""测试库隔离阀门哨兵（2026-11-06 智联 Edge 自动拉起/台账污染事故根治）。

事故：测试逃逸链路（_spawn_tracked 后台任务在 patch 撤除后执行真 _execute_pipeline）
把「终止看门狗强制收尾」failed 行、「全自动链路启动: k / c」行直写生产 backend/autopilot.db。

根治：backend/conftest.py 顶部（任何 app import 之前）设 AUTOPILOT_DB_PATH /
JOBHUNTER_DB_PATH 指向临时目录，import 期固化的模块常量（app.automation.db.DB_PATH、
platform_guard.DB_PATH、full_auto.RAW_DB_PATH）全部命中测试库。本文件锁定该契约：
任何回归（conftest 阀门被删、writable_path 优先级被改）都会在此红灯，而不是在生产
台账里留下幽灵记录后才被发现。
"""
from pathlib import Path

import app.automation.db as adb
import app.automation.full_auto as full_auto
import app.automation.platform_guard as pg

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REAL_AUTOPILOT_DB = (_BACKEND_ROOT / "autopilot.db").resolve()
_REAL_MAIN_DB = (_BACKEND_ROOT / "data" / "job_hunter.db").resolve()


def test_autopilot_db_constant_routes_to_test_valve():
    assert Path(adb.DB_PATH).resolve() != _REAL_AUTOPILOT_DB, (
        f"automation.db.DB_PATH 指向生产库 {_REAL_AUTOPILOT_DB}！"
        "root conftest 的 AUTOPILOT_DB_PATH 测试阀门失效，测试逃逸会污染真实台账"
    )


def test_platform_guard_db_constant_routes_to_test_valve():
    assert Path(pg.DB_PATH).resolve() != _REAL_AUTOPILOT_DB, (
        f"platform_guard.DB_PATH 指向生产库 {_REAL_AUTOPILOT_DB}！（模块级 from-import 绑定）"
    )


def test_raw_db_path_routes_to_test_valve():
    assert Path(full_auto.RAW_DB_PATH).resolve() != _REAL_MAIN_DB, (
        f"full_auto.RAW_DB_PATH 指向生产主库 {_REAL_MAIN_DB}！"
        "逃逸链路会把抓取结果写进真实 raw_jobs"
    )
