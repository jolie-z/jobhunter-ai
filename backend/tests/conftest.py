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

from app.main import app

# 真机用例白名单开关：默认（不设 RUN_LIVE_E2E）全量回归不收集这两个文件
_LIVE_E2E_FILES = ("test_boss_e2e_live.py", "test_boss_work_exp_integration.py")
collect_ignore = [] if os.environ.get("RUN_LIVE_E2E") else list(_LIVE_E2E_FILES)


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


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
