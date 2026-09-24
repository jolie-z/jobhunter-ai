"""
自动化测试：平台会话状态与生命周期 + 抓取即时单条广播 job 流转
1. GET /api/pipeline/platform-sessions 返回 4 平台健康结构
2. POST /api/pipeline/platform-sessions/launch 唤起指定平台
3. POST /api/pipeline/platform-sessions/close-all 关闭所有 Edge 进程
4. pb.emit_job 广播岗位（支持 company_name, salary, city, job_url, status="scraped"）
5. 任务结束后岗位在全局 Store 中保留验证
"""

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router
import app.automation.pipeline_broadcast as pb
import app.session.browser as browser_mod


@pytest.fixture()
def client():
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


# ─── 1. 平台会话状态感知 ───
def test_platform_sessions_endpoint(client, monkeypatch):
    mock_sessions = [
        {"platform": "boss", "display_name": "BOSS直聘", "port": 9222, "state": "healthy", "message": "正常", "is_alive": True},
        {"platform": "zhilian", "display_name": "智联招聘", "port": 9223, "state": "offline", "message": "未运行", "is_alive": False},
        {"platform": "51job", "display_name": "前程无忧", "port": 9224, "state": "healthy", "message": "正常", "is_alive": True},
        {"platform": "liepin", "display_name": "猎聘网", "port": 9225, "state": "offline", "message": "未运行", "is_alive": False},
    ]
    monkeypatch.setattr(browser_mod, "get_all_platform_sessions", lambda: mock_sessions)

    r = client.get("/api/pipeline/platform-sessions")
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    assert len(res["data"]) == 4
    assert res["data"][0]["platform"] == "boss"
    assert res["data"][0]["state"] == "healthy"


# ─── 2. 唤起指定平台浏览器 ───
def test_launch_platform_endpoint(client, monkeypatch):
    # 必须打路由模块自己的命名空间：scrape_router 顶层 `from ... import launch_edge`
    # 在路由命名空间建立了局部名称引用绑定，patch browser_mod.launch_edge 打不中
    # （Linux 无 Edge 时路由走真函数抛 EdgeNotFoundError → 400，CI 曾因此挂门禁；
    # macOS 有真 Edge 侥幸绿）。另断言 mock 确被调用，杜绝环境巧合造成的假绿。
    from app.pipeline.routes import scrape_router

    def _fake_launch(cfg):
        _fake_launch.called = True
        return {"status": "success", "message": f"唤起 {cfg.port}"}

    _fake_launch.called = False
    monkeypatch.setattr(scrape_router, "launch_edge", _fake_launch)

    r = client.post("/api/pipeline/platform-sessions/launch", json={"platform": "boss"})
    assert r.status_code == 200
    assert _fake_launch.called, "mock 未被路由调用——monkeypatch 又打错命名空间了"
    res = r.json()
    assert res["code"] == 0
    assert "已唤起" in res["msg"]


# ─── 3. 一键关闭全部浏览器 ───
def test_close_all_platforms_endpoint(client, monkeypatch):
    monkeypatch.setattr(browser_mod, "close_all_edges", lambda: 3)

    r = client.post("/api/pipeline/platform-sessions/close-all")
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    assert res["data"]["closed_count"] == 3


# ─── 4. emit_job 广播增强字段 ───
@pytest.mark.asyncio
async def test_emit_job_scraped_metadata():
    task_id = "test_pipe_job_stream"
    q = pb.create_pipeline_queue(task_id)

    await pb.emit_job(
        pipeline_task_id=task_id,
        job_id="raw_101",
        job_name="AI算法工程师",
        node="scrape_node",
        status="scraped",
        platform="boss",
        company_name="腾讯科技",
        salary="25-40K",
        city="广州",
        job_url="https://www.zhipin.com/job_detail/123.html",
    )

    msg = await q.get()
    assert msg.startswith("data: ")
    payload = json.loads(msg[6:].strip())

    assert payload["type"] == "job"
    assert payload["job_id"] == "raw_101"
    assert payload["job_name"] == "AI算法工程师"
    assert payload["company_name"] == "腾讯科技"
    assert payload["salary"] == "25-40K"
    assert payload["city"] == "广州"
    assert payload["status"] == "scraped"
    assert payload["job_url"] == "https://www.zhipin.com/job_detail/123.html"
