"""
Phase 4 映射异步化回归测试 (backend/tests/test_agent_map_async.py)

对照任务书 Phase 4 验证目标：
1. 异步启动秒回 task_id，SSE 事件序列 started → platform_start/platform_done ×N → complete
2. 失败载荷闭环：platform_done 携带 success/message/warnings/degraded，complete 携带全量内存 reports
3. retry_wait 事件经 ContextVar on_retry 钩子真实到达（GLM3-P1-1）
4. 取消旗在重试间（cancel_check → TaskCancelledException）与平台边界均生效
5. AGENT_MAP_ASYNC_ENABLED=false 回滚态：/generate 保持同步语义原样可用
6. stream/cancel 端点对未知 task_id 的 404 口径
"""
import asyncio
import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.resume_editor import agent_map_tasks as amt
from app.core.llm_governed import current_llm_context
from app.core.llm_retry import TaskCancelledException
from app.main import app
from resume_editor import agent_mapper as am

# 无 lifespan 的 TestClient（仓库主流约定）：本文件按字母序是全序中最早触达 app 的模块之一，
# 若用 conftest 的 lifespan client 会成为 APScheduler 单例绑定的第一个事件循环，
# 模块结束后循环关闭，后续模块（如 test_automation 的 add_job）将撞 "Event loop is closed"。
client = TestClient(app)

MASTER = {
    "ok": True,
    "source": "feishu",
    "char_count": 100,
    "record_id": "rec-test",
    "name": "测试简历",
    "message": "",
    "data": {"summary": "全栈工程师"},
}


@pytest.fixture(autouse=True)
def _isolate_agent_map_tasks(tmp_path, monkeypatch):
    """任务台账与 DATA_DIR 按用例隔离；业务落盘函数全部替换为记录桩。"""
    amt._AGENT_MAP_TASKS.clear()
    monkeypatch.setattr(amt, "DATA_DIR", str(tmp_path))
    for p in ("boss", "zhilian"):
        (tmp_path / f"{p}_fields.json").write_text("{}", encoding="utf-8")
    saved = []
    selected = []
    monkeypatch.setattr(am, "save_report", lambda platform, report, selected_modules=None: saved.append(platform))
    monkeypatch.setattr(am, "set_selected_master_record", lambda rid: selected.append(rid))
    # 默认打桩 map_platform：任何用例都绝不能让后台 worker 触达真实 LLM（会真实计费）
    monkeypatch.setattr(am, "map_platform", lambda p, f, m, selected_modules=None: _ok_report(p))
    yield {"saved": saved, "selected": selected}
    amt._AGENT_MAP_TASKS.clear()


def _run_task(platforms, map_fn):
    """启动异步任务并等待终态，返回 (task, 事件列表)。"""
    with patch.object(am, "map_platform", map_fn):
        async def main():
            task_id = await amt.start_mapping_task(
                platforms=platforms, master=MASTER, selected_modules=["work_experience"], record_id="rec-test"
            )
            task = amt.get_mapping_task(task_id)
            deadline = time.time() + 5
            while task.status == "running" and time.time() < deadline:
                await asyncio.sleep(0.01)
            events = [json.loads(line.removeprefix("data: ").strip()) for line in task.events]
            return task, events

        return asyncio.run(main())


def _ok_report(platform):
    return {"success": True, "platform": platform, "fields": [], "unfilled": [], "warnings": [], "message": "映射完成"}


def test_async_event_sequence_and_reports(_isolate_agent_map_tasks):
    """【规范】事件序列 + complete 携带全量内存报告 + 成功平台落盘。"""
    iso = _isolate_agent_map_tasks
    task, events = _run_task(["boss", "zhilian"], lambda p, f, m, selected_modules=None: _ok_report(p))

    assert task.status == "completed"
    types = [(e["type"], e.get("platform")) for e in events]
    assert types == [
        ("started", None),
        ("platform_start", "boss"), ("platform_done", "boss"),
        ("platform_start", "zhilian"), ("platform_done", "zhilian"),
        ("complete", None),
    ]
    complete = events[-1]
    assert complete["success"] is True
    assert complete["cancelled"] is False
    assert set(complete["reports"].keys()) == {"boss", "zhilian"}
    assert complete["master"]["record_id"] == "rec-test"
    assert iso["saved"] == ["boss", "zhilian"]  # 仅成功平台落盘
    assert iso["selected"] == ["rec-test"]


def test_failure_payload_closed_loop(_isolate_agent_map_tasks):
    """【规范】失败载荷闭环：platform_done 带失败详情，降级判定，complete 顶层 success=False。"""
    def map_fn(platform, _fields, _master, **_kw):
        if platform == "zhilian":
            return {"success": False, "platform": platform, "fields": [], "unfilled": [],
                    "warnings": [], "message": "AI 模型触发速率限制，已退避重试 3 次仍失败"}
        return {"success": True, "platform": platform, "fields": [], "unfilled": [],
                "warnings": ["⚠️ 已降级为确定性规则映射（LLM 不可用：429），仅覆盖文本/日期字段"], "message": "映射完成"}

    task, events = _run_task(["boss", "zhilian"], map_fn)

    done = {e["platform"]: e for e in events if e["type"] == "platform_done"}
    assert done["zhilian"]["success"] is False
    assert "速率限制" in done["zhilian"]["message"]
    assert done["boss"]["degraded"] is True  # 警告含「降级」→ 降级标记
    assert done["zhilian"]["degraded"] is False

    complete = events[-1]
    assert complete["success"] is False
    assert complete["reports"]["zhilian"]["success"] is False  # 失败平台也在内存报告中
    assert _isolate_agent_map_tasks["saved"] == ["boss"]  # 失败平台不落盘


def test_retry_wait_event_arrives_via_contextvar_hook():
    """【GLM3-P1-1】底层治理层经 ContextVar on_retry 钩子上抛 retry_wait 事件。"""
    def map_fn(platform, _fields, _master, **_kw):
        ctx = current_llm_context.get() or {}
        on_retry = ctx.get("on_retry")
        assert ctx.get("platform") == platform, "钩子上下文必须携带当前平台"
        assert ctx.get("task_id"), "钩子上下文必须携带 task_id"
        if on_retry:
            on_retry("agent_map", 1, 2.5, ctx)  # 模拟 govern 层重试回调
        return _ok_report(platform)

    task, events = _run_task(["boss"], map_fn)

    retry_events = [e for e in events if e["type"] == "retry_wait"]
    assert len(retry_events) == 1
    assert retry_events[0]["platform"] == "boss"
    assert retry_events[0]["seconds"] == 2.5
    assert retry_events[0]["attempt"] == 1
    assert task.status == "completed"


def test_cancel_takes_effect_between_platforms():
    """【规范】取消旗在平台边界生效：boss 完成后取消，zhilian 不再执行。"""
    def map_fn(platform, _fields, _master, **_kw):
        if platform == "boss":
            ctx = current_llm_context.get() or {}
            amt.cancel_mapping_task(ctx["task_id"])  # 用户在 boss 运行期间点了取消
        return _ok_report(platform)

    task, events = _run_task(["boss", "zhilian"], map_fn)

    assert task.status == "cancelled"
    assert any(e["type"] == "cancel_requested" for e in events)
    assert set(task.reports.keys()) == {"boss"}  # zhilian 未执行
    complete = events[-1]
    assert complete["cancelled"] is True
    assert complete["success"] is False


def test_cancel_takes_effect_between_retries():
    """【GLM3-P1-1】取消旗在重试间生效：cancel_check 为 True 时 TaskCancelledException 上抛即终止。"""
    def map_fn(platform, _fields, _master, **_kw):
        ctx = current_llm_context.get() or {}
        amt.cancel_mapping_task(ctx["task_id"])
        if ctx["cancel_check"](ctx):
            raise TaskCancelledException("LLM task cancelled after sleep in attempt 1")
        return _ok_report(platform)

    task, events = _run_task(["boss", "zhilian"], map_fn)

    assert task.status == "cancelled"
    assert task.reports == {}  # boss 自身也未完成
    assert events[-1]["type"] == "complete" and events[-1]["cancelled"] is True


def test_stream_replays_history_and_terminates_on_complete():
    """SSE 流生成器：先回放历史再实时分发，complete 后收尾退订。"""
    task, _ = _run_task(["boss"], lambda p, f, m, selected_modules=None: _ok_report(p))

    # 任务已结束但台账未清理（TTL 内）——重连订阅应一次性回放全部历史并终止
    async def consume():
        out = []
        async for line in amt.stream_mapping_events(task.task_id):
            out.append(line)
        return out

    chunks = asyncio.run(consume())
    types = [json.loads(c.removeprefix("data: ").strip())["type"] for c in chunks]
    assert types[0] == "started"
    assert types[-1] == "complete"
    assert task.subscribers == set()


def test_cancel_during_last_platform_marks_cancelled():
    """【P1 验证】唯一平台执行期间取消：平台报告保留，任务终态必须 cancelled=True 而非「完成」。"""
    def map_fn(platform, _fields, _master, **_kw):
        ctx = current_llm_context.get() or {}
        amt.cancel_mapping_task(ctx["task_id"])  # 平台跑完前用户点了取消
        return _ok_report(platform)

    task, events = _run_task(["boss"], map_fn)

    assert task.status == "cancelled"
    assert task.reports["boss"]["success"] is True  # 已完成平台照常保留并落盘
    complete = events[-1]
    assert complete["type"] == "complete"
    assert complete["cancelled"] is True
    assert complete["success"] is False


def test_cancel_unknown_task_returns_404_message():
    ok, msg = amt.cancel_mapping_task("nonexistent")
    assert ok is False
    assert "不存在" in msg


class TestAgentMapRoutes:
    """路由级：异步默认、同步回滚态、404 口径。"""

    def test_generate_async_default_returns_task_id(self, monkeypatch):
        monkeypatch.setattr(am, "load_master_resume", lambda record_id=None: dict(MASTER))
        res = client.post("/api/agent-map/generate", json={"platforms": ["boss"]})
        body = res.json()
        assert res.status_code == 200
        assert body["mode"] == "async" and body["task_id"]
        assert amt.get_mapping_task(body["task_id"]) is not None

    def test_mode_async_cannot_override_disabled_switch(self, monkeypatch):
        """【P1 验证】AGENT_MAP_ASYNC_ENABLED=false 时显式 mode=async 也必须回落同步（熔断开关否决权）。"""
        monkeypatch.setenv("AGENT_MAP_ASYNC_ENABLED", "false")
        monkeypatch.setattr(am, "load_master_resume", lambda record_id=None: dict(MASTER))

        res = client.post("/api/agent-map/generate", json={"platforms": ["boss"], "mode": "async"})
        body = res.json()
        assert body.get("task_id") is None  # 未启动异步任务
        assert body["success"] is True and body["reports"]["boss"]["success"] is True

    def test_generate_sync_mode_when_disabled(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAP_ASYNC_ENABLED", "false")
        monkeypatch.setattr(am, "load_master_resume", lambda record_id=None: dict(MASTER))

        res = client.post("/api/agent-map/generate", json={"platforms": ["boss"]})
        body = res.json()
        assert body.get("mode") is None  # 同步响应：无 mode/task_id，直接携带 reports
        assert body["success"] is True
        assert body["reports"]["boss"]["success"] is True

    def test_stream_unknown_task_404(self):
        assert client.get("/api/agent-map/generate/stream/nope").status_code == 404

    def test_cancel_unknown_task_404(self):
        res = client.post("/api/agent-map/generate/cancel", json={"task_id": "nope"})
        assert res.status_code == 404
