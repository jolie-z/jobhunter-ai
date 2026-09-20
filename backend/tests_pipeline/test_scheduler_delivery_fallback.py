import pytest
from unittest.mock import AsyncMock, patch
from app.automation.scheduler import _resume_job_delivery, custom_delivery_task


@pytest.mark.asyncio
async def test_resume_job_delivery_with_checkpoint(monkeypatch):
    """测试当存在 LangGraph 审批断点时，通过 astream 恢复状态机执行"""
    mock_pipeline = AsyncMock()
    
    # 模拟 aget_state 处于 manual_review_node 断点
    mock_state = AsyncMock()
    mock_state.next = ["manual_review_node"]
    
    mock_final_state = AsyncMock()
    mock_final_state.values = {"status": "已投递"}
    
    mock_pipeline.aget_state = AsyncMock(side_effect=[mock_state, mock_final_state])
    
    async def mock_astream(cmd, config):
        yield {"delivery_node": {"status": "已投递"}}
        
    mock_pipeline.astream = mock_astream
    
    monkeypatch.setattr("app.automation.scheduler.pipeline_app", mock_pipeline)
    
    ok, msg = await _resume_job_delivery("rec_test_1")
    assert ok is True
    assert msg == "已投递"


@pytest.mark.asyncio
async def test_resume_job_delivery_fallback_direct_delivery(monkeypatch):
    """测试当 LangGraph 无断点时，自动触发双轨保底从飞书读取并直接调用 delivery_node"""
    mock_pipeline = AsyncMock()
    mock_state = AsyncMock()
    mock_state.next = []  # 无断点
    mock_pipeline.aget_state = AsyncMock(return_value=mock_state)
    
    monkeypatch.setattr("app.automation.scheduler.pipeline_app", mock_pipeline)
    
    # 模拟飞书记录
    monkeypatch.setattr(
        "app.services.feishu_service.get_job_record_from_feishu",
        lambda record_id, table_id: {
            "fields": {
                "招聘平台": "zhilian",
                "公司名称": "测试科技有限公司",
                "岗位名称": "Python后端开发",
                "打招呼语": "您好，期待沟通",
                "综合等级": "B",
            }
        }
    )
    
    # 模拟 delivery_node 投递成功
    mock_delivery_node = AsyncMock(return_value={"status": "已投递"})
    monkeypatch.setattr("app.automation.workflow.delivery_node", mock_delivery_node)
    
    ok, msg = await _resume_job_delivery("rec_test_fallback")
    assert ok is True
    assert msg == "已投递"
    assert mock_delivery_node.called


@pytest.mark.asyncio
async def test_morning_and_afternoon_scheduled_delivery_tasks(monkeypatch):
    """测试上午波次 (mass_delivery_task) 与下午波次 (custom_delivery_task) 统一扫描待投递队列"""
    from app.automation.scheduler import mass_delivery_task, custom_delivery_task

    # 模拟闸门通过
    monkeypatch.setattr("app.automation.scheduler._delivery_guard_ok", lambda label: True)
    
    # 模拟飞书返回 2 个待投递岗位
    monkeypatch.setattr(
        "app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu",
        lambda *args, **kwargs: [
            {"job_id": "rec_job_1", "job_name": "AI工程师", "company_name": "A公司", "platform": "zhilian"},
            {"job_id": "rec_job_2", "job_name": "产品经理", "company_name": "B公司", "platform": "boss"},
        ]
    )

    delivered = []
    async def mock_resume(thread_id):
        delivered.append(thread_id)
        return True, "已投递"

    monkeypatch.setattr("app.automation.scheduler._resume_job_delivery", mock_resume)
    mock_notifier = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.delivery_card_notifier.send_delivery_round_report", mock_notifier)

    # 触发上午波次
    await mass_delivery_task()
    assert delivered == ["rec_job_1", "rec_job_2"]

    # 触发下午波次
    delivered.clear()
    await custom_delivery_task()
    assert delivered == ["rec_job_1", "rec_job_2"]
    assert mock_notifier.await_count == 2


@pytest.mark.asyncio
async def test_scheduled_delivery_skips_unallowed_platforms(monkeypatch):
    """测试当某平台在目标投递平台白名单中被取消勾选时，定时发射自动跳过该平台岗位"""
    from app.automation.scheduler import scheduled_delivery_batch_task

    monkeypatch.setattr("app.automation.scheduler._delivery_guard_ok", lambda label: True)
    # 模拟仅勾选了 boss，未勾选 zhilian 和 51job
    monkeypatch.setattr("app.automation.scheduler.get_autopilot_config", lambda: {
        "auto_deliver_platforms": ["boss"]
    })
    
    monkeypatch.setattr(
        "app.services.feishu_service.get_scheduled_delivery_jobs_from_feishu",
        lambda *args, **kwargs: [
            {"job_id": "rec_zhilian_1", "job_name": "测试岗位1", "company_name": "A公司", "platform": "zhilian"},
            {"job_id": "rec_boss_2", "job_name": "测试岗位2", "company_name": "B公司", "platform": "boss"},
        ]
    )

    delivered = []
    async def mock_resume(thread_id):
        delivered.append(thread_id)
        return True, "已投递"

    monkeypatch.setattr("app.automation.scheduler._resume_job_delivery", mock_resume)
    mock_notifier = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.delivery_card_notifier.send_delivery_round_report", mock_notifier)

    await scheduled_delivery_batch_task("测试波次")
    # 仅 boss 岗位被发射，zhilian 岗位被安全跳过
    assert delivered == ["rec_boss_2"]
    mock_notifier.assert_awaited_once()


