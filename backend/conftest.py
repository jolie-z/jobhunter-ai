import os
os.environ["JOBHUNTER_TESTING"] = "1"

# ===== autopilot.db 测试隔离阀门（2026-11-06 事故根治）=====
# 事故：测试逃逸链路把「终止看门狗强制收尾」failed 行、「全自动链路启动: k / c」行
# 直写生产 backend/autopilot.db（台账永久污染，且排障时与真实运行记录混淆）。
# 修法：在根 conftest 顶部（任何 app import 之前）设 AUTOPILOT_DB_PATH 指向临时目录。
# app.automation.db.DB_PATH 经 writable_path 解析时单文件 env 优先级最高，import 期
# 即固化到临时库；platform_guard 等模块级 `from app.automation.db import DB_PATH`
# 的下游绑定也一并命中，无需逐用例 patch。需要真机验证时显式 RUN_LIVE_E2E=1 解禁。
# RUN_LIVE_E2E=1 时用户自行保证 AUTOPILOT_DB_PATH 指向真实库（保持真机读写语义）。
if not os.environ.get("RUN_LIVE_E2E"):
    import atexit as _atexit
    import shutil as _shutil
    import tempfile as _tempfile

    _TEST_AUTOPILOT_DIR = _tempfile.mkdtemp(prefix="jobhunter_test_autopilot_")
    os.environ["AUTOPILOT_DB_PATH"] = os.path.join(_TEST_AUTOPILOT_DIR, "autopilot.db")
    # 主库 job_hunter.db 同源隔离：逃逸链路会经 scrape_runner 写 raw_jobs、经
    # run_snapshot 写快照表。tests_pipeline 已有 _isolate_run_snapshot_db（模块级
    # patch），这里在 import 期把 job_hunter_db_path 阀门一并指到临时库，双保险。
    # JOBHUNTER_TEST_DB_DIR 是子 conftest（tests/conftest.py）的识别哨兵：它 pop
    # 宿主残留后会按本目录重设 JOBHUNTER_DB_PATH（宿主不会有此变量，语义不冲突）。
    os.environ["JOBHUNTER_DB_PATH"] = os.path.join(_TEST_AUTOPILOT_DIR, "job_hunter.db")
    os.environ["JOBHUNTER_TEST_DB_DIR"] = _TEST_AUTOPILOT_DIR
    # 会话结束清理临时库（agy round1 P2）：排障窗口内仍可打开目录核对（不立即删），
    # 进程退出后自动回收，避免长期运行残留堆积。
    _atexit.register(_shutil.rmtree, _TEST_AUTOPILOT_DIR, True)

"""backend 根级测试配置：对 resume_editor/data/ 平台数据文件做会话级备份/还原。

事故背景（2026-08-31 / 2026-09-02）：多个目录下的测试（tests/、resume_editor/、
tests_pipeline/）会经由真实 API 或 healer 直写 boss_fields.json 等生产数据文件，
曾把完整采集数据覆盖成一行测试残留文字。本守卫在会话开始前备份、结束后原样还原；
测试期间的读写行为不受影响，所有子目录的测试统一被覆盖。
"""
import os
import shutil
import threading
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session", autouse=True)
def _protect_real_resume_data(tmp_path_factory):
    data_dir = _BACKEND_ROOT / "resume_editor" / "data"
    if not data_dir.exists():
        yield
        return
    patterns = ("*_fields.json", "*_writeback.json", "unified_resume.json", "total_fields.json")
    protected = [p for pat in patterns for p in data_dir.glob(pat)]
    backup_dir = tmp_path_factory.mktemp("real_data_backup")
    for f in protected:
        shutil.copy2(f, backup_dir / f.name)
    yield
    for f in protected:
        bak = backup_dir / f.name
        if bak.exists():
            shutil.copy2(bak, f)


_EXIT_STATUS = {"code": 0}


def pytest_sessionfinish(session, exitstatus):
    _EXIT_STATUS["code"] = int(exitstatus)


def pytest_unconfigure(config):
    if os.environ.get("RUN_LIVE_E2E"):
        return  # 真机调试场景保持正常退出语义，便于交互式排查

    lingering = [
        t
        for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon and t.is_alive()
    ]
    if not lingering:
        return
    names = ", ".join(f"{t.name}(ident={t.ident})" for t in lingering)
    print(
        f"\n⚠️ [root conftest] 检测到 {len(lingering)} 个残留非 daemon 线程会阻塞解释器退出: {names}\n"
        f"⚠️ [root conftest] 携带真实退出码 {_EXIT_STATUS['code']} 强制结束进程，避免全量回归假死（CI 超时）"
    )
    os._exit(_EXIT_STATUS["code"])
