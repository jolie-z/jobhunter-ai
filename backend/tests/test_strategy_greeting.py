import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app.strategy.routes.ai_router import generate_greeting_and_save_api, GenerateGreetingRequest


@pytest.mark.asyncio
async def test_generate_greeting_missing_active_resume_400():
    """测试当飞书中不存在已激活的母本简历时，准确抛出 400 并引导用户前往配置大盘设置"""
    with patch("app.core.feishu_client.feishu_client.get_record", new=AsyncMock(return_value={"fields": {"岗位名称": "AI工程师"}})), \
         patch("app.strategy.config_service.get_active_resume_text_async", new=AsyncMock(return_value="")):
        with pytest.raises(HTTPException) as exc_info:
            await generate_greeting_and_save_api(GenerateGreetingRequest(job_id="rec_test_1", resume_text=""))
        assert exc_info.value.status_code == 400
        assert "未找到已激活的母本简历" in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_greeting_feishu_unreachable_502():
    """测试当拉取母本简历发生网络或飞书服务故障时，准确抛出 502 Bad Gateway"""
    with patch("app.core.feishu_client.feishu_client.get_record", new=AsyncMock(return_value={"fields": {"岗位名称": "AI工程师"}})), \
         patch("app.strategy.config_service.get_active_resume_text_async", new=AsyncMock(side_effect=Exception("Connection Timeout"))):
        with pytest.raises(HTTPException) as exc_info:
            await generate_greeting_and_save_api(GenerateGreetingRequest(job_id="rec_test_2", resume_text=""))
        assert exc_info.value.status_code == 502
        assert "飞书服务暂时不可达" in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_greeting_feishu_save_failed_502():
    """测试当生成成功但飞书回写失败时，显式抛出 502 而非静默假成功"""
    mock_record = {
        "fields": {
            "岗位名称": "AI工程师",
            "岗位JD": "熟悉Prompt",
            "高杠杆匹配点": "具备全栈经验",
            "AI评估详情": "S级匹配",
        }
    }
    with patch("app.core.feishu_client.feishu_client.get_record", new=AsyncMock(return_value=mock_record)), \
         patch("app.strategy.config_service.get_active_resume_text_async", new=AsyncMock(return_value="我的母本简历")), \
         patch("ai_agents.engine_facade.process_greeting_generation", return_value=("您好，我完全胜任...", {"total_tokens": 100})), \
         patch("app.core.feishu_client.feishu_client.update_record", new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as exc_info:
            await generate_greeting_and_save_api(GenerateGreetingRequest(job_id="rec_test_3", resume_text=""))
        assert exc_info.value.status_code == 502
        assert "回写飞书保存失败" in exc_info.value.detail


@pytest.mark.asyncio
async def test_generate_greeting_happy_path():
    """测试完整成功路径：自动回退母本简历、正确组装 diagnosis_dict、异步线程执行、成功回写飞书"""
    mock_record = {
        "fields": {
            "岗位名称": "AI工程师",
            "岗位JD": "熟悉Prompt",
            "高杠杆匹配点": "具备全栈经验",
            "AI评估详情": "S级匹配",
        }
    }
    with patch("app.core.feishu_client.feishu_client.get_record", new=AsyncMock(return_value=mock_record)), \
         patch("app.strategy.config_service.get_active_resume_text_async", new=AsyncMock(return_value="我的母本简历")), \
         patch("ai_agents.engine_facade.process_greeting_generation", return_value=("打招呼语生成结果", {"total_tokens": 120})), \
         patch("app.core.feishu_client.feishu_client.update_record", new=AsyncMock(return_value=True)):
        res = await generate_greeting_and_save_api(GenerateGreetingRequest(job_id="rec_test_4", resume_text=""))
        assert res["status"] == "success"
        assert res["data"]["greeting"] == "打招呼语生成结果"
        assert res["data"]["usage"]["total_tokens"] == 120
