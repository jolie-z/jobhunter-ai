"""按平台终止（问题 C 修复）行为测试。

覆盖：
- abort 模块平台级登记纯函数（置位/查询/清理/未知平台忽略）
- TestClient 调 /api/automation/abort 后各平台 controller 急刹 flag 全部置位
- TestClient 调 /api/automation/abort/platform/{platform} 仅对应平台 flag 置位、非法平台 400
- _platform_worker 循环条件含平台级检查（静态断言）
- 回归：/api/v1/crawlers/cancel/{task_id} 重构后行为不变
"""
import importlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.automation import abort as abort_mod
import app.api.routes.crawlers as crawlers

ALL_PLATFORMS = ["boss", "liepin", "51job", "zhilian", "xiaohongshu"]


def _load_controller(platform: str):
    """以与生产相同的 sys.path hack 载入控制器（sys.modules 同一对象，flag 互通）。"""
    subdir, mod_name = crawlers._PLATFORM_STOP_MODULES[platform]
    mod_dir = f"{crawlers.PROJECT_ROOT}/{subdir}"
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)
    return importlib.import_module(mod_name)


def _flag_of(platform: str) -> bool:
    mod = _load_controller(platform)
    return getattr(mod, "GLOBAL_STOP_FLAG", getattr(mod, "_stop_flag", False))


def _reset_all_flags():
    for p in ALL_PLATFORMS:
        _load_controller(p).set_stop_flag(False)


@pytest.fixture()
def pipeline_ctx():
    """模拟一轮链路运行，结束后清理全局/平台级标记。"""
    abort_mod.begin_pipeline("pipeline_abort_test")
    yield
    abort_mod.end_pipeline()
    abort_mod.begin_pipeline("pipeline_cleanup")
    abort_mod.end_pipeline()
    _reset_all_flags()


@pytest.fixture()
def auto_client():
    from app.automation.router import router as automation_router
    api = FastAPI()
    api.include_router(automation_router, prefix="/api/automation")
    return TestClient(api)


@pytest.fixture()
def crawler_client():
    api = FastAPI()
    api.include_router(crawlers.router, prefix="/api/v1/crawlers")
    return TestClient(api)


# ── 平台级登记纯函数 ──

def test_platform_abort_registration_roundtrip():
    abort_mod.begin_pipeline("pipeline_p1")
    assert abort_mod.request_platform_abort("boss") is True
    assert abort_mod.is_platform_aborted("boss")
    assert not abort_mod.is_platform_aborted("zhilian")
    assert abort_mod.get_aborted_platforms() == ["boss"]

    abort_mod.request_platform_abort("zhilian")
    assert sorted(abort_mod.get_aborted_platforms()) == ["boss", "zhilian"]

    # begin_pipeline 清理平台级标记
    abort_mod.begin_pipeline("pipeline_p2")
    assert abort_mod.get_aborted_platforms() == []
    assert not abort_mod.is_platform_aborted("boss")
    abort_mod.end_pipeline()
    abort_mod.begin_pipeline("pipeline_cleanup")
    abort_mod.end_pipeline()


def test_platform_abort_unknown_ignored():
    abort_mod.begin_pipeline("pipeline_p3")
    assert abort_mod.request_platform_abort("taobao") is False
    assert not abort_mod.is_platform_aborted("taobao")
    assert abort_mod.get_aborted_platforms() == []
    abort_mod.end_pipeline()
    abort_mod.begin_pipeline("pipeline_cleanup")
    abort_mod.end_pipeline()


def test_stop_platform_unknown_returns_false():
    assert crawlers.stop_platform("taobao") is False


# ── 全局终止：一次指令刹住全部平台 ──

def test_global_abort_sets_all_controller_flags(auto_client, pipeline_ctx):
    _reset_all_flags()
    r = auto_client.post("/api/automation/abort", json={"task_id": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["aborted"] is True
    assert abort_mod.is_aborted()
    # 全部平台登记 + 各 controller 急刹 flag 置位
    assert sorted(abort_mod.get_aborted_platforms()) == sorted(ALL_PLATFORMS)
    for p in ALL_PLATFORMS:
        assert _flag_of(p), f"{p} 急刹 flag 未置位"


# ── 按平台终止：只刹目标平台 ──

def test_platform_endpoint_only_stops_target(auto_client, pipeline_ctx):
    _reset_all_flags()
    r = auto_client.post("/api/automation/abort/platform/zhilian")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["platform"] == "zhilian"

    assert abort_mod.is_platform_aborted("zhilian")
    assert not abort_mod.is_platform_aborted("boss")
    assert _flag_of("zhilian")
    assert not _flag_of("boss")
    assert not _flag_of("liepin")
    assert not abort_mod.is_aborted()  # 不触发全局终止


def test_platform_endpoint_invalid_400(auto_client, pipeline_ctx):
    r = auto_client.post("/api/automation/abort/platform/taobao")
    assert r.status_code == 400
    assert not abort_mod.is_platform_aborted("taobao")


# ── 编排层：_platform_worker 循环条件含平台级检查 ──

def test_platform_worker_loop_checks_platform_abort():
    import app.automation.full_auto as fa
    src = open(fa.__file__, encoding="utf-8").read()
    assert "not abort_mod.is_platform_aborted(p)" in src
    assert "已按指令终止" in src


# ── 回归：调试面板 cancel 端点重构后行为不变 ──

def test_cancel_crawler_regression(crawler_client):
    _reset_all_flags()
    r = crawler_client.post("/api/v1/crawlers/cancel/spider_boss_abcd1234")
    assert r.status_code == 200
    assert r.json()["status"] == "success"
    assert _flag_of("boss")
    assert not _flag_of("liepin")

    r2 = crawler_client.post("/api/v1/crawlers/cancel/spider_liepin_efgh5678")
    assert r2.status_code == 200
    assert _flag_of("liepin")
    _reset_all_flags()

    # 🌟 回归验证：对全平台清洗任务执行取消，不得误杀 BOSS 爬虫
    from job_processor import step1_rule_filter, xhs_vision_cleaner
    step1_rule_filter.set_stop_flag(False)
    xhs_vision_cleaner.set_stop_flag(False)
    
    r_clean = crawler_client.post("/api/v1/crawlers/cancel/clean_global_12345678")
    assert r_clean.status_code == 200
    assert r_clean.json()["status"] == "success"
    assert not _flag_of("boss") # 严禁误杀 BOSS！
    assert step1_rule_filter.get_stop_flag() # 清洗急刹必须生效

    r_xhs = crawler_client.post("/api/v1/crawlers/cancel/clean_xhs_12345678")
    assert r_xhs.status_code == 200
    assert not _flag_of("boss") # 严禁误杀 BOSS！
    assert xhs_vision_cleaner.get_stop_flag() # 小红书清洗急刹必须生效

    step1_rule_filter.set_stop_flag(False)
    xhs_vision_cleaner.set_stop_flag(False)
    _reset_all_flags()


def test_crawler_platform_concurrency_lock_returns_409(crawler_client):
    """测试同平台并发互斥：已有同平台任务在执行时，再次触发必须返回 409 Conflict"""
    import app.api.routes.crawlers as crawlers_mod
    crawlers_mod._platform_running_tasks.clear()

    # 1. 模拟 boss 平台已有任务在运行
    crawlers_mod._platform_running_tasks["boss"] = "spider_boss_running123"

    # 2. 再次请求启动 boss 爬虫，必须命中 409 拦截
    resp = crawler_client.post("/api/v1/crawlers/run", json={
        "platform": "boss",
        "keyword": "AI产品经理",
        "city": "北京"
    })
    assert resp.status_code == 409
    assert "已有抓取任务在执行中" in resp.json()["detail"]

    # 3. 任务释放后，再次触发可正常放行（或进入调度）
    crawlers_mod._platform_running_tasks.clear()


@pytest.mark.asyncio
async def test_task_channel_fifo_semantics():
    """测试 TaskChannel 单消费者 FIFO 出队语义：连发 3 条消息，必须严格按顺序出队，绝不死循环重复返回第 1 条"""
    from app.tasks.state import TaskChannel
    channel = TaskChannel()

    # 发送 3 条不同的消息
    await channel.put("msg_1")
    await channel.put("msg_2")
    await channel.put("msg_3")

    # 单消费者逐个读取，必须严格先进先出
    item1 = await channel.get()
    item2 = await channel.get()
    item3 = await channel.get()

    assert item1 == "msg_1"
    assert item2 == "msg_2"
    assert item3 == "msg_3"


def test_dispatch_conflict_platforms_returns_409(crawler_client):
    """测试统一分发互斥：勾选的平台若已有运行中任务，必须返回 409 Conflict 拦截"""
    import app.api.routes.crawlers as crawlers_mod
    crawlers_mod._platform_running_tasks.clear()

    # 模拟 liepin 平台正在执行
    crawlers_mod._platform_running_tasks["liepin"] = "spider_liepin_running999"

    resp = crawler_client.post("/api/v1/crawlers/dispatch", json={
        "keyword": "前端",
        "city": "上海",
        "platforms": ["boss", "liepin"]
    })

    assert resp.status_code == 409
    assert "LIEPIN" in resp.json()["detail"]

    crawlers_mod._platform_running_tasks.clear()


def test_global_clean_lock_defined():
    """验证 step1_rule_filter 模块中定义了 GLOBAL_CLEAN_LOCK 并已就绪"""
    import job_processor.step1_rule_filter as s1
    import asyncio
    assert hasattr(s1, "GLOBAL_CLEAN_LOCK")
    assert isinstance(s1.GLOBAL_CLEAN_LOCK, asyncio.Lock)
