"""平台抓取失败通知测试（2026-10-31 智联薪资筛选中止事故后续）。

覆盖 crawlers._run_and_track 的统一失败通知行为：
- result.success=False 且带 fail_reason → master 队列收到 platform_failure 事件 + 飞书被调用
- fail_reason 缺省（手动急刹 GLOBAL_STOP）→ 不通知
- success=True 正常收尾 → 不通知
- 投递闸门跳过（_SCRAPE_SKIPPED）→ 不通知
- runner 异常上抛 → 以异常文本通知
"""
import asyncio
import json
from unittest.mock import patch

import pytest

from app.api.routes import crawlers
from app.tasks.state import task_queues


@pytest.fixture(autouse=True)
def _mock_side_effects(monkeypatch):
    """隔离外部副作用：台账回写落库与飞书真实发送。"""
    monkeypatch.setattr(
        "app.session.scrape_sessions.update_last_page",
        lambda *a, **k: None,
    )
    sent: list[str] = []

    async def _fake_send(text: str) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr("app.automation.pipeline_report.send_pipeline_report", _fake_send)
    return sent


def _drain(task_id: str) -> list[dict]:
    q = task_queues[task_id]
    events = []
    while not q.empty():
        raw = q.get_nowait()
        if raw.startswith("data: "):
            events.append(json.loads(raw[len("data: "):].strip()))
    return events


def test_failure_with_reason_emits_event_and_feishu(_mock_side_effects):
    master_id = "pipeline_test_master"
    task_queues[master_id] = asyncio.Queue()

    async def _fail_round():
        return {"inserted": 0, "success": False,
                "fail_reason": "薪资筛选失败中止（下拉选项未渲染，宁缺毋滥防越档岗位灌库）"}

    asyncio.new_event_loop().run_until_complete(
        crawlers._run_and_track(
            _fail_round(), "spider_zhilian_x", "智能客服", "广州", "15K-25K",
            "zhilian", 1, master_task_id=master_id,
        )
    )

    events = _drain(master_id)
    failures = [e for e in events if e.get("type") == "platform_failure"]
    assert len(failures) == 1
    ev = failures[0]
    assert ev["platform"] == "zhilian"
    assert ev["platform_name"] == "智联招聘"
    assert "薪资筛选失败中止" in ev["reason"]
    assert ev["keyword"] == "智能客服" and ev["city"] == "广州" and ev["salary"] == "15K-25K"
    # ts（发射时刻毫秒）：前端按它去重 TaskChannel 重连回放的重复投递
    assert isinstance(ev.get("ts"), int) and ev["ts"] > 0
    # 飞书同步通知（文本含平台名与原因）
    assert _mock_side_effects and "智联招聘抓取任务失败" in _mock_side_effects[0]
    assert "薪资筛选失败中止" in _mock_side_effects[0]
    task_queues.pop(master_id, None)


def test_success_and_manual_stop_do_not_notify(_mock_side_effects):
    master_id = "pipeline_test_master2"
    task_queues[master_id] = asyncio.Queue()

    async def _ok_round():
        return {"inserted": 3, "success": True, "last_page": 1}

    async def _manual_stop_round():
        # 手动急刹：success=False 但不带 fail_reason（控制器约定）
        return {"inserted": 0, "success": False, "last_page": 1}

    loop = asyncio.new_event_loop()
    loop.run_until_complete(crawlers._run_and_track(
        _ok_round(), "spider_boss_x", "AI产品", "广州", "15-20K", "boss", 1, master_task_id=master_id))
    loop.run_until_complete(crawlers._run_and_track(
        _manual_stop_round(), "spider_boss_y", "AI产品", "广州", "15-20K", "boss", 1, master_task_id=master_id))

    events = _drain(master_id)
    assert not [e for e in events if e.get("type") == "platform_failure"]
    assert _mock_side_effects == []
    task_queues.pop(master_id, None)


def test_skipped_round_does_not_notify(_mock_side_effects):
    master_id = "pipeline_test_master3"
    task_queues[master_id] = asyncio.Queue()

    async def _skipped():
        return crawlers._SCRAPE_SKIPPED

    asyncio.new_event_loop().run_until_complete(
        crawlers._run_and_track(
            _skipped(), "spider_boss_z", "AI产品", "广州", "15-20K", "boss", 1,
            master_task_id=master_id,
        )
    )
    assert _drain(master_id) == []
    assert _mock_side_effects == []
    task_queues.pop(master_id, None)


def test_runner_exception_notifies_with_error_text(_mock_side_effects):
    master_id = "pipeline_test_master4"
    task_queues[master_id] = asyncio.Queue()

    async def _boom():
        raise RuntimeError("浏览器拉起失败")

    asyncio.new_event_loop().run_until_complete(
        crawlers._run_and_track(
            _boom(), "spider_51job_x", "AI产品", "广州", "15-20K", "51job", 1,
            master_task_id=master_id,
        )
    )
    failures = [e for e in _drain(master_id) if e.get("type") == "platform_failure"]
    assert len(failures) == 1
    assert failures[0]["platform_name"] == "前程无忧"
    assert "浏览器拉起失败" in failures[0]["reason"]
    assert _mock_side_effects and "前程无忧抓取任务失败" in _mock_side_effects[0]
    task_queues.pop(master_id, None)
