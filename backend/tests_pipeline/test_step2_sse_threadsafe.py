"""step2 飞书同步 SSE 跨线程推送回归测试。

背景：主页「推送至飞书」等卡片进度条不实时——step2 全部 push 发生在 asyncio.to_thread
工作线程，旧 _get_main_loop() 在工作线程内必抛 RuntimeError 且被 except 静默吞掉，
phase_progress/log 全丢，只剩主线程 finally 的 end 事件到达前端。
修复：ContextVar 锚定主 loop（sync_sqlite_to_feishu_async 入口 set，to_thread 自动透传），
线程内 push 一律 call_soon_threadsafe 回主 loop；无锚定时告警丢消息，绝不跨线程裸写 queue。

覆盖：
- 主路径：经 async 入口锚定后，工作线程 push_sse_event 消息必达主 loop 的 queue
- 兜底：无锚定的裸线程 push 不崩溃、不写 queue、打印告警
- 边界：锚定 loop 已关闭时同样告警丢消息（MagicMock 注入，不破坏测试宿主 loop）
"""

import asyncio
import json
import threading

import pytest

from job_processor import step2_sync_feishu


@pytest.fixture()
def _queue_env():
    """注册一个干净的 task queue，用完清理。"""
    from app.tasks.state import task_queues
    created = {}
    def make(task_id):
        q = asyncio.Queue()
        task_queues[task_id] = q
        created[task_id] = q
        return q
    yield make
    for tid, q in created.items():
        if task_queues.get(tid) is q:
            task_queues.pop(tid, None)


def test_anchored_thread_push_reaches_main_loop_queue(_queue_env):
    """经 sync_sqlite_to_feishu_async 入口：工作线程内 push 必达主 loop queue。"""
    q = _queue_env("sse_t1")
    seen = {}

    def fake_engine(db_path, table_name="jobs", sse_task_id=None, limit=None, min_rowid=0, target_links=None):  # noqa: ARG001
        # 此处运行在 to_thread 工作线程：模拟真实引擎中途推 phase_progress
        step2_sync_feishu.push_sse_event(sse_task_id, {"type": "phase_progress", "phase": "feishu_sync", "current": 1, "total": 2})
        return ["rec1"]

    original = step2_sync_feishu.sync_sqlite_to_feishu
    step2_sync_feishu.sync_sqlite_to_feishu = fake_engine
    try:
        seen["ids"] = asyncio.run(
            step2_sync_feishu.sync_sqlite_to_feishu_async("fake.db", "raw_jobs", "sse_t1", 10)
        )
    finally:
        step2_sync_feishu.sync_sqlite_to_feishu = original

    assert seen["ids"] == ["rec1"]
    msg = q.get_nowait()
    assert '"type": "phase_progress"' in msg
    assert json.loads(msg[len("data: "):])["current"] == 1


def test_unanchored_bare_thread_push_warns_and_drops(_queue_env, capsys):
    """无锚定的裸线程 push：不崩溃、不写 queue（拒绝非线程安全直写）、打印告警。"""
    q = _queue_env("sse_t2")
    done = threading.Event()

    def worker():
        try:
            step2_sync_feishu.push_sse_event("sse_t2", {"type": "phase_progress", "phase": "feishu_sync", "current": 0, "total": 1})
        finally:
            done.set()

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)
    assert done.is_set(), "push_sse_event 在无锚定线程内不得抛异常"
    assert q.empty(), "无锚定时禁止跨线程裸写 asyncio.Queue"
    assert "无可用主事件循环" in capsys.readouterr().out


def test_closed_anchored_loop_warns_and_drops(_queue_env, capsys):
    """锚定 loop 已关闭（如服务重启残留）：告警丢消息，不崩、不写 queue。"""
    q = _queue_env("sse_t3")

    stale = json.dumps({"type": "log", "message": "stale"}, ensure_ascii=False)
    loop_mock = type("ClosedLoopMock", (), {"is_closed": lambda self: True, "call_soon_threadsafe": lambda *a, **k: pytest.fail("closed loop 不得再调度")})()
    token = step2_sync_feishu._ANCHORED_LOOP.set(loop_mock)
    try:
        step2_sync_feishu.push_sse_message_sync("sse_t3", stale)
    finally:
        step2_sync_feishu._ANCHORED_LOOP.reset(token)

    assert q.empty()
    assert "无可用主事件循环" in capsys.readouterr().out
