"""存活检测分批执行器测试。

覆盖：批量启动与防重、判定分发（在招/死链/无法判定）、处置语义（飞书标已下架+SQLite标记，绝不删除）、
四道防风控闸（登录态失效熔断/连续异常熔断/条间休息）、进度状态。

外部边界（真浏览器、飞书写入、SQLite、检测脚本）全部 Mock；批次/熔断/处置逻辑真实执行。
"""
import asyncio
import json

import pytest

from app.services import job_table_hygiene as hyg


def _job(rid, company="测试公司", title="AI产品经理", platform="BOSS直聘", link="https://x/1"):
    return {"record_id": rid, "company_name": company, "job_name": title,
            "follow_status": "新线索", "platform": platform, "job_link": link,
            "ai_rewrite_json": "", "fetch_time": ""}


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    hyg._liveness_state.update(
        running=False, platform="", total=0, done=0, alive=0, dead=0,
        unknown=0, aborted="", started_epoch=0.0, finished_epoch=0.0, log=[])
    monkeypatch.setattr(hyg.asyncio, "sleep", _nosleep)
    monkeypatch.setattr(hyg, "_mark_sqlite_dead", lambda rid: 1)
    yield
    hyg._liveness_state.update(running=False)


def _nosleep(*a, **k):
    async def _f():
        return None
    return _f()


def _run(coro):
    return asyncio.run(coro)


def _fake_script(verdicts_reasons):
    """构造判定脚本替身：check 函数按序返回预设结果。"""
    class _Mod:
        pass

    seq = iter(verdicts_reasons)

    def _check(browser, link):
        return next(seq)

    _Mod.check_zhilian_link = _check
    _Mod.check_liepin_link = _check
    _Mod.get_platform_browser = lambda platform: object()
    return _Mod


async def _drain():
    """等后台 worker 真正跑完（join 句柄），避免任务逃出测试。"""
    task = hyg._liveness_state.get("task")
    if task:
        await asyncio.wait_for(asyncio.shield(task), timeout=15)
    for _ in range(20):
        await asyncio.sleep(0)


def test_batch_disposes_dead_via_status_not_delete(monkeypatch):
    """死链处置 = 飞书改「已下架」+ SQLite 标记；绝无删除调用；在招/无法判定不动。"""
    from app.core import feishu_client as fcm

    written, deleted = [], []

    async def fake_update(table_id, record_id, fields):
        written.append((record_id, fields))

    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)
    monkeypatch.setattr(fcm.feishu_client, "batch_delete_records",
                        lambda *a, **k: deleted.append(a) or (_ for _ in ()).throw(AssertionError("绝不删除")))
    monkeypatch.setattr(fcm.feishu_client, "delete_record",
                        lambda *a, **k: deleted.append(a) or (_ for _ in ()).throw(AssertionError("绝不删除")))

    async def fake_candidates(platform, limit):
        return [_job("recA"), _job("recB"), _job("recC")]

    monkeypatch.setattr(hyg, "_stale_jobs_for_platform", fake_candidates)
    monkeypatch.setattr(hyg, "_liveness_script",
                        lambda: _fake_script(iter([(True, ""), (False, "页面提示：职位已失效"), (None, "无已知标志（保守不判）")])))

    async def scenario():
        out = await hyg.start_liveness_batch(platform="zhilian")
        await _drain()
        return out, hyg.liveness_progress()

    out, prog = _run(scenario())

    assert out["started"] is True and out["total"] == 3
    assert prog["running"] is False and prog["done"] == 3
    assert (prog["alive"], prog["dead"], prog["unknown"]) == (1, 1, 1)
    assert prog["aborted"] == ""
    assert (rec for rec, _ in written) and written[0] == ("recB", {"跟进状态": "已下架"}), "死链应标已下架"
    assert not deleted, "全程不得有删除调用"


def test_circuit_breaks_on_session_failure(monkeypatch):
    """连续 2 条登录态失效 → 熔断停手，后续岗位不再检测，飞书零写入。"""
    from app.core import feishu_client as fcm

    written = []

    async def fake_update(table_id, record_id, fields):
        written.append(record_id)

    monkeypatch.setattr(fcm.feishu_client, "update_record", fake_update)

    async def fake_candidates(platform, limit):
        return [_job("rec1"), _job("rec2"), _job("rec3")]

    monkeypatch.setattr(hyg, "_stale_jobs_for_platform", fake_candidates)
    monkeypatch.setattr(hyg, "_liveness_script",
                        lambda: _fake_script(iter([(None, "登录态失效"), (None, "登录态失效"), (False, "页面提示：职位已失效")])))

    async def scenario():
        await hyg.start_liveness_batch(platform="zhilian")
        await _drain()
        return hyg.liveness_progress()

    prog = _run(scenario())

    assert "熔断" in prog["aborted"]
    assert prog["done"] == 2, "熔断后剩余岗位不再检测"
    assert written == [], "登录态失效不算死链，绝不能标已下架"


def test_duplicate_start_rejected(monkeypatch):
    """批次进行中再次启动 → 拒绝（防重）。"""
    import threading

    release = threading.Event()

    class _Mod:
        pass

    def _check(browser, link):
        release.wait(timeout=5)  # 模拟耗时检测：卡住保证批次确实在跑
        return True, ""

    _Mod.check_zhilian_link = _check
    _Mod.check_liepin_link = _check
    _Mod.get_platform_browser = lambda platform: object()

    async def fake_candidates(platform, limit):
        return [_job("recA"), _job("recB")]

    monkeypatch.setattr(hyg, "_stale_jobs_for_platform", fake_candidates)
    monkeypatch.setattr(hyg, "_liveness_script", lambda: _Mod)

    async def scenario():
        first = await hyg.start_liveness_batch(platform="zhilian")
        second = await hyg.start_liveness_batch(platform="zhilian")
        release.set()
        task = hyg._liveness_state.get("task")
        if task:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        return first, second

    first, second = _run(scenario())
    assert first["started"] is True
    assert second["started"] is False and "在跑" in second["reason"]


def test_platform_51job_rejected():
    out = _run(hyg.start_liveness_batch(platform="51job"))
    assert out["started"] is False
    assert "51job" in out["reason"] and "排除" in out["reason"]


def test_progress_tool_shape_before_any_run():
    prog = hyg.liveness_progress()
    assert prog["running"] is False and prog["total"] == 0 and "elapsed_seconds" in prog
