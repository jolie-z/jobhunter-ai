"""Skill 改写实时推演事件流测试（2026-10-09 看板静止报修）。

三层覆盖：
1. 官方单文件剧本路径 run_skill_based_rewrite 的生命周期事件埋点（此前零事件，
   看板从建连到结束全程静止）；
2. 跨线程事件投递原语：引擎跑在 asyncio.to_thread 工作线程，事件必须经
   call_soon_threadsafe 入队（直接 put_nowait 非线程安全）；
3. 异步任务 API 的 init 事件即时入队冒烟。

注：全链路 API 编排（POST 创建 worker → SSE 消费到 complete）无法在 TestClient 下
断言——POST 请求作用域结束即取消 create_task 的 worker（生产 uvicorn 单常驻循环无
此问题），已实证，故拆分为以上三层各自可断言的单元。
"""
import asyncio
import time
from types import SimpleNamespace

import pytest

import ai_agents.skill_rewrite as skill_rewrite
from app.jobs.task_manager import task_event_manager
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _fake_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, reasoning_content=""))],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_tokens_details=None,
        ),
    )


class _FakeLLMClient:
    def __init__(self, content: str):
        self._content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return _fake_llm_response(self._content)


@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setattr(
        skill_rewrite, "get_openai_client", lambda: _FakeLLMClient(
            "<THINKING>内部推演</THINKING>\n<FINAL_RESUME>\n# 定稿简历\n- 精通 Python\n</FINAL_RESUME>"
        )
    )


def test_run_skill_based_rewrite_emits_lifecycle_events(fake_llm):
    """官方剧本路径必须在关键阶段发事件，且顺序稳定（看板「动起来」的底线）"""
    events: list[tuple[str, dict]] = []
    final_md, usage = skill_rewrite.run_skill_based_rewrite(
        original_resume="# 母本简历",
        jd_text="招聘精通 Python 与大模型的工程师",
        diagnosis_dict={},
        job_name="测试工程师",
        skill_id="resume_rewrite",
        on_event=lambda t, d: events.append((t, d)),
    )

    assert not final_md.startswith("❌")
    assert "定稿简历" in final_md
    assert usage["total_tokens"] == 15

    types = [t for t, _ in events]
    # 生命周期骨架：启动 → 装载剧本 → 提示词装配 → 大模型推演 → 响应萃取 → 安全阀 → token 上抛
    assert types == [
        "agent_start",
        "step_start",   # step 1 装载剧本
        "thinking",     # 提示词装配完成
        "step_start",   # step 2 大模型推演
        "thinking",     # 响应完成
        "tool_call",    # truth_boundary_check
        "usage",        # 单轮 token 上抛（usage_dict 已可用，看板计数不等 complete）
    ]
    assert events[0][1]["message"].startswith("📜")
    assert events[1][1]["step"] == 1
    assert events[3][1]["step"] == 2
    assert events[5][1]["tool"] == "truth_boundary_check"
    # 阶段事件必须携带 max_turns，前端进度条靠它算百分比
    assert events[1][1]["max_turns"] == 4
    assert "耗时" in events[4][1]["message"]
    # usage 事件与返回的 usage_dict 同值（2026-10-16 前该事件因先用后定义从未发出）
    assert events[6][1]["prompt_tokens"] == 10
    assert events[6][1]["total_tokens"] == 15
    assert events[6][1]["cached_tokens"] == 0


def test_run_skill_based_rewrite_on_event_exception_never_breaks_rewrite(fake_llm):
    """埋点回调抛异常必须被吞掉——事件系统永不阻断改写主流程"""

    def _bomb(event_type, data):
        raise RuntimeError("回调爆炸")

    final_md, usage = skill_rewrite.run_skill_based_rewrite(
        original_resume="# 母本简历",
        jd_text="JD",
        diagnosis_dict={},
        skill_id="resume_rewrite",
        on_event=_bomb,
    )
    assert "定稿简历" in final_md
    assert usage["total_tokens"] == 15


def test_thread_events_reach_queue_via_call_soon_threadsafe():
    """引擎在工作线程里发事件，必须全部有序抵达 SSE 队列（含 None 终止符）"""
    task_id = "skill_task_test_threadsafe"

    async def scenario():
        queue = task_event_manager.register_task(task_id)
        loop = asyncio.get_running_loop()

        def push_event(event: dict):
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def engine_thread():
            # 模拟 to_thread 工作线程内的 on_event 回调链
            for i in range(3):
                push_event({"type": "thinking", "message": f"m{i}", "ts": time.time()})
            push_event(None)

        await asyncio.to_thread(engine_thread)

        got = []
        while True:
            ev = await asyncio.wait_for(queue.get(), timeout=5)
            got.append(ev)
            if ev is None:
                break
        return got

    try:
        got = asyncio.run(scenario())
    finally:
        task_event_manager.remove_task(task_id)

    assert [e["message"] for e in got[:3]] == ["m0", "m1", "m2"]
    assert got[-1] is None


def test_skill_rewrite_async_api_init_event_enqueued_immediately():
    """异步任务创建即返回 task_id，init 事件同步入队（前端建连前不空窗）"""
    resp = client.post(
        "/api/strategy/skill_rewrite_async",
        json={"job_id": "", "jd_text": "JD", "job_name": "岗位", "skill_id": ""},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    task_id = body["task_id"]
    assert task_id.startswith("skill_task_")

    queue = task_event_manager.get_queue(task_id)
    assert queue is not None
    first = queue.get_nowait()
    assert first["type"] == "init"
    assert first["task_id"] == task_id
    task_event_manager.remove_task(task_id)
