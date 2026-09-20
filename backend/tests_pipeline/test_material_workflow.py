import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.automation.workflow import rewrite_node, quick_greeting_node, delivery_node

@pytest.mark.asyncio
async def test_rewrite_node_official_skill_auto_renders_custom_pdf():
    """测试官方技能下，A/B 级改写会自动渲染专属定制 PDF 并挂载到飞书附件"""
    state = {
        "record_id": "rec_test_ab_001",
        "company_name": "星云科技有限公司",
        "job_name": "AI产品经理",
        "jd_text": "负责 AI 智能体产品设计",
        "resume_text": "# 个人总结\n熟悉 Python 与 AI 产品",
        "diagnosis_dict": {"grade": "A", "score": 92},
        "feishu_fields": {"PDF备份": [{"file_token": "old_generic_token"}]},
    }

    mock_parsed_json = {
        "personalInfo": {"name": "张三", "phone": "13800000000"},
        "summary": "资深 AI 产品经理",
        "workExperience": [],
        "education": [],
        "additional": {"technicalSkills": ["LangChain", "FastAPI"]}
    }

    mock_tool = MagicMock()
    mock_tool.ainvoke = AsyncMock(return_value={"status": "ok"})

    with patch("app.automation.workflow.process_resume_rewrite", return_value=("# 个人总结\n资深 AI 产品经理", {})), \
         patch("app.automation.workflow.process_greeting_generation", return_value=("您好，我对该岗位非常感兴趣！", {})), \
         patch("app.automation.workflow.get_autopilot_config", return_value={"rewrite_skill_id": "official"}), \
         patch("ai_agents.markdown_to_json.parse_markdown_to_json", return_value=mock_parsed_json), \
         patch("app.automation.materials._render_custom_resume_materials", new_callable=AsyncMock) as mock_render, \
         patch("app.automation.workflow.update_feishu_status", mock_tool):
        
        mock_render.return_value = {
            "pdf_token": "token_custom_pdf_123",
            "img_token": "token_custom_img_123",
            "name": "星云科技有限公司_AI产品经理"
        }

        res = await rewrite_node(state)
        
        assert res["status"] == "简历人工复核"
        assert res["final_markdown"] == "# 个人总结\n资深 AI 产品经理"
        assert mock_render.called
        
        # 验证 Feishu 更新中挂载了定制 PDF
        call_args = mock_tool.ainvoke.call_args[0][0]
        assert call_args["record_id"] == "rec_test_ab_001"
        updates = call_args["updates"]
        assert len(updates["PDF备份"]) == 1
        assert updates["PDF备份"][0]["file_token"] == "token_custom_pdf_123"
        assert updates["PDF备份"][0]["name"] == "星云科技有限公司_AI产品经理.pdf"


@pytest.mark.asyncio
async def test_rewrite_node_custom_skill_clears_materials_for_safety():
    """测试自定义多产物技能下，系统主动清空通用物料防呆，等待用户进入面板确认"""
    state = {
        "record_id": "rec_test_custom_skill_002",
        "company_name": "星云科技有限公司",
        "job_name": "高级架构师",
        "jd_text": "负责系统架构",
        "resume_text": "# 原简历",
        "diagnosis_dict": {"grade": "B", "score": 85},
        "feishu_fields": {"PDF备份": [{"file_token": "old_generic_token"}]},
    }

    mock_tool = MagicMock()
    mock_tool.ainvoke = AsyncMock(return_value={"status": "ok"})

    with patch("app.automation.workflow.process_resume_rewrite", return_value=("自定义多产物输出...", {})), \
         patch("app.automation.workflow.process_greeting_generation", return_value=("您好", {})), \
         patch("app.automation.workflow.get_autopilot_config", return_value={"rewrite_skill_id": "my_custom_package_skill"}), \
         patch("ai_agents.markdown_to_json.parse_markdown_to_json", return_value={}), \
         patch("app.automation.workflow.update_feishu_status", mock_tool):

        res = await rewrite_node(state)
        
        assert res["status"] == "简历人工复核"
        call_args = mock_tool.ainvoke.call_args[0][0]
        updates = call_args["updates"]
        # 验证物料被清空置为 []
        assert updates["PDF备份"] == []
        assert updates["图片保存"] == []


@pytest.mark.asyncio
async def test_delivery_node_blocks_when_materials_missing():
    """测试投递网关拦截：当改写岗缺少 PDF 物料时，坚决拦截并给出明确提示"""
    state = {
        "record_id": "rec_test_ab_missing_mat",
        "company_name": "星云科技",
        "job_name": "AI产品经理",
        "platform": "智联招聘",
        "greeting": "您好！",
        "final_markdown": "# 个人总结\n定制改写简历内容",
        "feishu_fields": {
            "岗位链接": {"link": "https://jobs.zhaopin.com/123.htm"},
            "PDF备份": [], # 物料为空
            "打招呼语": "您好！"
        }
    }

    res = await delivery_node(state)
    assert "error" in res
    assert "缺少 PDF 简历附件" in res["error"]
    assert "定制面板" in res["error"]
