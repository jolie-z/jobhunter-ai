import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest

from app.core.cache import JobCache
from app.tasks.executor import _handle_approve, run_batch_ai_task


@pytest.fixture(autouse=True)
def _isolate_job_cache_snapshot(monkeypatch, tmp_path):
    """全局隔离 JobCache 磁盘快照与内存态，杜绝任何用例踩踏生产快照 job_cache_snapshot.json。"""
    monkeypatch.setattr(JobCache, "_snapshot_path", tmp_path / "job_cache_snapshot_test.json")
    saved = (JobCache._data, JobCache._timestamp, JobCache._dirty, JobCache._last_disk_write)
    yield
    JobCache._data, JobCache._timestamp, JobCache._dirty, JobCache._last_disk_write = saved


@pytest.mark.asyncio
async def test_handle_approve_emits_progress_and_enqueues():
    """测试 _handle_approve 发射 4 阶段 progress SSE 并成功归档至待投递"""
    queue = asyncio.Queue()
    fields = {
        "公司名称": "广州恒熠达知识产权有限公司",
        "岗位名称": "AI项目经理",
        "招聘平台": "智联招聘",
        "AI改写JSON": json.dumps({"name": "定制简历测试", "summary": "项目经历丰富"}),
        "PDF备份": [],
        "图片保存": [],
        "打招呼语": "您好，关注到贵司正在招聘AI项目经理！",
    }

    with patch("app.automation.materials._render_custom_resume_materials", new_callable=AsyncMock) as mock_render, \
         patch("app.tasks.executor.update_feishu_record") as mock_update, \
         patch("app.automation.routes.delivery_router._mark_approved_guarded"):

        mock_render.return_value = {
            "pdf_token": "pdf_token_123",
            "img_token": "img_token_123",
            "name": "广州恒熠达知识产权有限公司_AI项目经理.pdf",
        }

        result = await _handle_approve(
            record_id="recApprove1",
            platform="智联招聘",
            fields=fields,
            queue=queue,
            job_id="zhilian--recApprove1",
        )

        assert result["status"] == "success"
        assert result["followStatus"] == "待投递"
        mock_update.assert_called_once()
        patch_data = mock_update.call_args[0][1]
        assert patch_data["跟进状态"] == "待投递"
        assert patch_data["PDF备份"][0]["file_token"] == "pdf_token_123"

        # 检查发出的 SSE 消息中包含 4 阶段微进度
        events = []
        while not queue.empty():
            msg = await queue.get()
            if isinstance(msg, str) and msg.startswith("data: "):
                payload = json.loads(msg[6:].strip())
                events.append(payload)

        stages = [e.get("stage_title") for e in events if e.get("type") == "progress"]
        assert "物料校验" in stages
        assert "高清渲染" in stages
        assert "飞书归档" in stages
        assert "放行待投" in stages


@pytest.mark.asyncio
async def test_run_batch_ai_task_approve_stream():
    """测试通过 run_batch_ai_task 派发 approve 任务的端到端事件推流"""
    queue = asyncio.Queue()
    fake_record = {
        "fields": {
            "公司名称": "广州翰特网络科技有限公司",
            "岗位名称": "数字化产品经理",
            "招聘平台": "智联招聘",
            "AI改写JSON": json.dumps({"name": "定制简历"}),
            "PDF备份": [{"file_token": "existing_pdf", "name": "广州翰特网络科技有限公司_数字化产品经理.pdf"}],
            "图片保存": [{"file_token": "existing_img", "name": "广州翰特网络科技有限公司_数字化产品经理-长图.jpg"}],
            "打招呼语": "您好！",
        }
    }

    with patch("app.tasks.executor.get_job_record_from_feishu", return_value=fake_record), \
         patch("app.tasks.executor.update_feishu_record"), \
         patch("app.automation.routes.delivery_router._mark_approved_guarded"):

        await run_batch_ai_task(
            task_id="test_approve_task_id",
            task_type="approve",
            job_ids=["zhilian--recApprove2"],
            queue=queue,
        )

        events = []
        while not queue.empty():
            msg = await queue.get()
            if isinstance(msg, str) and msg.startswith("data: "):
                events.append(json.loads(msg[6:].strip()))

        types = [e.get("type") for e in events]
        assert "start" in types
        assert "progress" in types
        assert "wave_status" in types
        assert "success" in types
        assert "complete" in types

        # 验证 success 事件携带 followStatus 热更新
        success_event = next(e for e in events if e.get("type") == "success")
        assert success_event.get("job_updates", {}).get("followStatus") == "待投递"


def test_job_cache_patch_record_fields():
    """验证 JobCache.patch_record_fields 能够就地更新内存中岗位的 follow_status"""
    dummy_data = [
        {"record_id": "rec_001", "job_name": "AI应用产品经理", "follow_status": "简历人工复核"},
        {"record_id": "rec_002", "job_name": "AI智能体应用工程师", "follow_status": "简历人工复核"},
    ]
    JobCache.set(dummy_data)

    # 1. 正常补丁命中
    patched = JobCache.patch_record_fields("rec_001", {"follow_status": "待投递"})
    assert patched is True
    cached = JobCache.get()
    assert cached is not None
    assert cached[0]["follow_status"] == "待投递"
    assert cached[1]["follow_status"] == "简历人工复核"

    # 2. 未命中返回 False
    not_found = JobCache.patch_record_fields("rec_non_exist", {"follow_status": "待投递"})
    assert not_found is False


