"""全链路看板子任务事件转发回归（2026-10-30 真机事故）。

事故链：BOSS 采集器环境守卫误杀 → 子任务队列发 type=error → 转发协程原样推进
主队列 → pipeline-store 的 "error" 分支把整条链路置为失败，但猎聘/智联 worker
仍在继续抓取并进入 AI 评估。修复：单平台 error 降级为 warning，全局终态只由
编排器自己的 emit_end 决定。
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.routes import crawlers  # noqa: E402
from app.tasks.state import TaskChannel, task_queues  # noqa: E402


class _DoneTask:
    """子任务已结束：转发协程走 get_nowait 排空分支。"""

    def done(self) -> bool:
        return True


def _parse(raw: str) -> dict:
    return json.loads(raw.replace("data: ", "", 1).strip())


def test_subtask_error_is_downgraded_to_warning(monkeypatch, caplog):
    monkeypatch.setattr("app.automation.abort.is_aborted", lambda: False)
    master = TaskChannel()
    sub = TaskChannel()
    task_queues["pipeline_test_master"] = master
    task_queues["spider_test_sub"] = sub
    try:
        sub.put_nowait('data: {"type": "error", "message": "BOSS爬虫异常崩溃: boom"}\n\n')
        sub.put_nowait('data: {"type": "end"}\n\n')

        with caplog.at_level(logging.WARNING, logger=crawlers.__name__):
            reason = asyncio.run(
                crawlers._forward_subtask_events(
                    "spider_test_sub", "boss", "pipeline_test_master", sub_task=_DoneTask()
                )
            )

        assert reason == "complete"
        event = _parse(master.get_nowait())
        assert event["type"] == "warning"  # 绝不透传 error
        assert event["platform"] == "boss"
        assert event["stage"] == "scraping"
        assert event["platform_error"] is True
        assert "BOSS爬虫异常崩溃: boom" in event["message"]
        assert "其他平台与后续阶段继续执行" in event["message"]
        assert master.empty()  # end 帧不转发，主队列只收到这一条
        # 规范第 4 条：降级分支必须留服务端白盒日志
        assert any(
            "降级为 warning" in rec.getMessage() and "boss" in rec.getMessage()
            for rec in caplog.records
        ), [rec.getMessage() for rec in caplog.records]
    finally:
        task_queues.pop("pipeline_test_master", None)
        task_queues.pop("spider_test_sub", None)


def test_subtask_progress_still_forwarded(monkeypatch):
    monkeypatch.setattr("app.automation.abort.is_aborted", lambda: False)
    master = TaskChannel()
    sub = TaskChannel()
    task_queues["pipeline_test_master"] = master
    task_queues["spider_test_sub"] = sub
    try:
        sub.put_nowait(
            'data: {"type": "progress", "current": 2, "total": 3, "platform": "boss"}\n\n'
        )
        sub.put_nowait('data: {"type": "heartbeat"}\n\n')
        sub.put_nowait('data: {"type": "end"}\n\n')

        reason = asyncio.run(
            crawlers._forward_subtask_events(
                "spider_test_sub", "boss", "pipeline_test_master", sub_task=_DoneTask()
            )
        )

        assert reason == "complete"
        event = _parse(master.get_nowait())
        assert event["type"] == "progress"
        assert event["stage"] == "scraping"
        assert event["platform"] == "boss"  # 平台标签会被转发层覆盖为权威值
        assert master.empty()  # heartbeat 与 end 都不进主队列
    finally:
        task_queues.pop("pipeline_test_master", None)
        task_queues.pop("spider_test_sub", None)
