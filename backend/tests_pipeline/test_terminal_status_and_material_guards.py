import pytest
import time
from unittest.mock import AsyncMock, patch
from app.core.feishu_utils import is_terminal_or_post_delivery_status
from app.jobs.router import update_job_resume, UpdateJobResumeRequest
from app.jobs.action_service import save_manual_resume_action
from app.jobs.schemas import SaveManualResumeRequest
from app.automation.materials import _render_mass_resume_materials, _MASS_MATERIALS_CACHE
from app.automation.workflow import delivery_node


def test_is_terminal_or_post_delivery_status():
    """测试终态与投递后状态判定"""
    # 终态 / 投递后状态
    assert is_terminal_or_post_delivery_status("已投递") is True
    assert is_terminal_or_post_delivery_status("已放弃投递") is True
    assert is_terminal_or_post_delivery_status("清洗淘汰") is True
    assert is_terminal_or_post_delivery_status("已拒绝") is True
    assert is_terminal_or_post_delivery_status("一面") is True
    assert is_terminal_or_post_delivery_status("HR面") is True
    assert is_terminal_or_post_delivery_status("Offer") is True

    # 待处理 / 可流转阶段
    assert is_terminal_or_post_delivery_status("新线索") is False
    assert is_terminal_or_post_delivery_status("待复核") is False
    assert is_terminal_or_post_delivery_status("海投人工复核") is False
    assert is_terminal_or_post_delivery_status("") is False
    assert is_terminal_or_post_delivery_status(None) is False


@pytest.mark.asyncio
async def test_update_job_resume_protects_terminal_status():
    """测试 update_job_resume 在岗位处于终态（如已投递）时不倒流跟进状态"""
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = {"status": "success"}

        # 1. 终态岗位：传入 current_status="已投递"
        payload_terminal = UpdateJobResumeRequest(
            job_id="rec_delivered_001",
            resume_data="{'summary': '已投递岗位微调'}",
            current_status="已投递"
        )
        await update_job_resume(payload_terminal)

        # 验证只更新了 AI改写JSON，绝对没有写入 跟进状态
        assert mock_update.called
        call_args = mock_update.call_args[0]
        assert call_args[0] == "rec_delivered_001"
        assert "AI改写JSON" in call_args[1]
        assert "跟进状态" not in call_args[1]

        mock_update.reset_mock()

        # 2. 非终态岗位：传入 current_status="待复核"
        payload_normal = UpdateJobResumeRequest(
            job_id="rec_pending_002",
            resume_data="{'summary': '正常待审岗位改写'}",
            current_status="待复核"
        )
        await update_job_resume(payload_normal)

        call_args = mock_update.call_args[0]
        assert call_args[0] == "rec_pending_002"
        assert "AI改写JSON" in call_args[1]
        assert call_args[1]["跟进状态"] == "简历人工复核"


@pytest.mark.asyncio
async def test_save_manual_resume_action_protects_terminal_status():
    """测试 action_service.save_manual_resume_action 终态防倒流"""
    with patch("app.core.feishu_client.feishu_client.update_record", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = True

        payload = SaveManualResumeRequest(
            job_id="rec_abandoned_003",
            resume_text="{'title': '已放弃岗位的简历'}",
            current_status="已放弃投递"
        )
        res = await save_manual_resume_action(payload)
        assert res["status"] == "success"

        call_kwargs = mock_update.call_args.kwargs
        assert "AI改写JSON" in call_kwargs["fields"]
        assert "跟进状态" not in call_kwargs["fields"]


@pytest.mark.asyncio
async def test_mass_materials_cache_avoids_repeated_render():
    """测试海投通用简历物料在内存中复用，杜绝重复渲染与上传"""
    resume_id = "rec_mass_template_001"
    _MASS_MATERIALS_CACHE.clear()

    # 预置缓存：key 带 need_image 维度，_render_mass_resume_materials 默认 need_image=True
    fake_mats = {"pdf_token": "token_pdf_1", "img_token": "token_img_1", "name": "海投简历"}
    _MASS_MATERIALS_CACHE[(resume_id, True)] = (time.time(), fake_mats)

    res = await _render_mass_resume_materials(resume_id)
    assert res == fake_mats
    # 再次调用，依然从缓存返回
    res2 = await _render_mass_resume_materials(resume_id)
    assert res2 == fake_mats


@pytest.mark.asyncio
async def test_delivery_node_graceful_fallback_when_feishu_fails():
    """测试发射前当飞书查询失败时，快照完整时可用性降级并拦截缺失物料"""
    state = {
        "record_id": "rec_test_degrade_001",
        "company_name": "星云科技",
        "job_name": "AI产品经理",
        "platform": "智联招聘",
        "greeting": "您好！",
        "final_markdown": "# 个人总结\n定制改写简历内容",
        "feishu_fields": {
            "岗位链接": {"link": "https://jobs.zhaopin.com/123.htm"},
            "PDF备份": [],  # 物料缺失
            "打招呼语": "您好！"
        }
    }

    # 模拟飞书 API 报错（网络抖动）
    with patch("app.services.feishu_service.get_job_record_from_feishu", side_effect=Exception("Feishu Timeout")):
        res = await delivery_node(state)
        # 降级沿用快照，未被网络报错一票否决，而是精准进入物料缺失拦截
        assert "error" in res
        assert "缺少 PDF 简历附件" in res["error"]
