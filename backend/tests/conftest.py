"""全局测试配置。

1. 真机 E2E 用例默认排除出全量回归：test_boss_e2e_live / test_boss_work_exp_integration
   依赖真实 Edge 浏览器（CDP 19222），端口在线时会自动执行并等待人工扫码/拖滑块，
   混在全量回归里必然假死。需要真机验证时显式运行：
       RUN_LIVE_E2E=1 pytest tests/test_boss_e2e_live.py -v
2. 修复全量回归「跑完 100% 后进程不退出」：测试链路会拉起 Playwright driver 等
   原生子线程，残留的非 daemon 线程会阻塞解释器 shutdown（表现为永远假死，
   CI 超时）。pytest_unconfigure 里检测残留线程并携带真实退出码强退。
"""
import os
import threading
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

# import 期清空主库路径阀门（agy P2 复审建议采纳）：app.main 导入链会把
# goal_service.DB_PATH / config_status_service.DB_PATH 等按 import 时 env 固化为
# 模块常量，宿主 shell 残留的 JOBHUNTER_DATA_DIR 会让整条导入链与用例内断言永久
# 错位（2026-10-28 实测假阳性红灯）。仓库惯例是隔离全部在 conftest 内做（tmp_path
# 重定向），不依赖宿主 env 注入，故这里放心清空；下方 autouse fixture 再逐用例兜底。
for _db_env_var in ("JOBHUNTER_DATA_DIR", "JOBHUNTER_DB_PATH", "ANALYTICS_DB_PATH", "MAIN_PROJECT_DB"):
    os.environ.pop(_db_env_var, None)

# 根 conftest 测试库隔离阀门（2026-11-06 事故）：JOBHUNTER_TEST_DB_DIR 只可能由
# backend/conftest.py 顶部设置（宿主不会有）。上面 pop 掉宿主残留后，把主库
# JOBHUNTER_DB_PATH 重设回测试临时目录——app.main 导入链里 job_hunter_db_path
# 固化的模块常量即命中临时库，逃逸链路（后台任务在 patch 退出后执行真
# _execute_pipeline）对 raw_jobs/快照的读写全部落在测试库，不再污染生产库。
_TEST_DB_DIR = os.environ.get("JOBHUNTER_TEST_DB_DIR", "")


def _valve_main_db_env() -> None:
    """按测试库阀门重设主库 JOBHUNTER_DB_PATH（顶部 import 期与逐用例 fixture 共用，
    agy round1 P2 重复逻辑收口）。RUN_LIVE_E2E=1 真机场景不注入。"""
    if _TEST_DB_DIR and not os.environ.get("RUN_LIVE_E2E"):
        os.environ["JOBHUNTER_DB_PATH"] = os.path.join(_TEST_DB_DIR, "job_hunter.db")


if _TEST_DB_DIR:
    _valve_main_db_env()

from app.main import app  # noqa: E402

# 真机用例白名单开关：默认（不设 RUN_LIVE_E2E）全量回归不收集这两个文件
_LIVE_E2E_FILES = ("test_boss_e2e_live.py", "test_boss_work_exp_integration.py")
collect_ignore = [] if os.environ.get("RUN_LIVE_E2E") else list(_LIVE_E2E_FILES)


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c
    # main.py lifespan 的 shutdown 修复（单例 shutdown）是主修；此处兜底复位是为
    # 防其他入口残留 running 态：AsyncIOScheduler.shutdown 会经 @run_in_event_loop
    # 派回已关闭的循环再次炸——改为不动事件循环的强制复位（未启动态 add_job 只登记不唤醒）。
    try:
        from app.automation import scheduler as _sch
        _sch.scheduler.state = 0
        _sch.scheduler._eventloop = None
        _sch.scheduler.remove_all_jobs()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_db_path_env(monkeypatch):
    """主库路径阀门 env 逐用例隔离（agy P2 复审建议采纳，2026-10-28 实测踩坑）。

    开发机 shell 残留的 JOBHUNTER_DATA_DIR / JOBHUNTER_DB_PATH 会让 db_bootstrap
    的路径断言假阳性红灯；这里逐用例删净四个路径阀门，用例如需 env 行为自行
    monkeypatch.setenv（autouse 先删、用例内后设，顺序天然正确）。
    JOBHUNTER_DB_PATH 删后按根 conftest 的测试隔离阀门重设（2026-11-06 事故，
    与顶部 import 期共用 _valve_main_db_env 收口）：测试进程内运行期读阀门的代码
    （scrape_runner._get_raw_db_path 等）必须落测试库，不得回落到生产 job_hunter.db。
    """
    for _var in ("JOBHUNTER_DATA_DIR", "JOBHUNTER_DB_PATH", "ANALYTICS_DB_PATH", "MAIN_PROJECT_DB"):
        monkeypatch.delenv(_var, raising=False)
    _valve_main_db_env()
    yield


@pytest.fixture(autouse=True)
def _isolate_cdp_lock_dir(tmp_path, monkeypatch):
    """跨进程端口锁目录逐用例隔离：测试不得锁住真实 ~/.jobhunter-cdp-locks。"""
    monkeypatch.setenv("JOBHUNTER_CDP_LOCK_DIR", str(tmp_path / "cdp-locks"))
    yield


@pytest.fixture(autouse=True)
def _isolate_llm_gate():
    """每次测试前后重置 LLM 限流闸门单例，防止跨用例冷却窗或槽位泄漏。"""
    try:
        from app.core.llm_gate import reset_llm_gate
        reset_llm_gate()
        yield
        reset_llm_gate()
    except Exception:
        yield


@pytest.fixture(autouse=True)
def _isolate_51job_upload_quota(tmp_path, monkeypatch):
    """51job 日上传配额状态文件按测试隔离，避免波次/编排用例读到生产状态文件。"""
    from app.automation import upload_quota

    monkeypatch.setattr(upload_quota, "QUOTA_STATE_FILE", str(tmp_path / "51job_upload_quota.json"))
    yield


@pytest.fixture(autouse=True)
def _isolate_job_cache_snapshot(tmp_path, monkeypatch):
    """岗位列表缓存（JobCache）的磁盘快照重定向到临时目录，并清空测试进程内存态。

    事故背景（2026-09-24）：test_m9_qa_fixes 的 kick_background_refresh 用例把 mock 数据
    [{"record_id": "x"}] 经 JobCache.set() 持久化进生产 data/job_cache_snapshot.json，
    后端重启后按快照恢复 1 条空壳岗位，主页列表只剩一条「未知公司/未知职位」。
    凡触发 JobCache.set()/clear() 的用例都不得读写生产快照文件。
    """
    from app.core.cache import JobCache

    monkeypatch.setattr(JobCache, "_snapshot_path", tmp_path / "job_cache_snapshot.json")
    JobCache._reset_for_tests()
    yield
    JobCache._reset_for_tests()


@pytest.fixture(scope="session", autouse=True)
def _isolate_run_snapshot_db(tmp_path_factory):
    """run_snapshot 底层数据库重定向到临时测试库，防止测试写入污染生产库 job_hunter.db。

    事故背景（质检 Q13 2026-09-18）：tests/ 侧曾缺此隔离（tests_pipeline/ 已有），
    delivery_node 失败分支在测试进程内真实调用 record_delivery_failure → _save_to_db，
    把内存台账（含其他失败测试泄漏的测试数据）持久化进生产 pipeline_latest_run 表，
    导致 _load_from_db 回灌后 test_snapshot_evaluating_triage 确定性失败、
    生产执行失败 Tab 显示测试岗位。
    """
    from app.automation import run_snapshot as rs
    temp_dir = tmp_path_factory.mktemp("test_run_snapshot")
    temp_db = temp_dir / "test_snapshot.db"
    orig_db = rs._DB_PATH
    rs._DB_PATH = temp_db
    # conftest 顶部导入 app.main 时生产库已回灌过内存台账，重定向后必须清空，
    # 彻底切断导入期回灌敞口（岗哨3 R2 P2 建议采纳）
    rs._delivery_failures.clear()
    yield
    rs._DB_PATH = orig_db
    # 测试结束后恢复生产库的干净权威状态
    rs._load_from_db()


@pytest.fixture(scope="session", autouse=True)
def _isolate_inflight_registry(tmp_path_factory):
    """进行中评估登记表重定向到临时文件，防止任何测试写生产 data/inflight_pipelines.json。"""
    from app.automation import inflight_registry as reg
    temp = tmp_path_factory.mktemp("test_inflight_registry") / "inflight_pipelines.json"
    reg.reset_for_test(temp)
    yield
    reg.reset_for_test()
