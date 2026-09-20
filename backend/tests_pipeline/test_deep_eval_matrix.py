"""
自动化测试：深度评估全量规则与轻量化架构
1. GET /api/pipeline/deep-eval-config 接口完整性与 6 大诊断模块校验
2. deep_evaluate_resume 极简 Prompt 上下文验证（确认剔除初筛偏好与初评分数）
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pipeline.router import router
from ai_agents.ai_scorer import deep_evaluate_resume


@pytest.fixture()
def client():
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_get_deep_eval_config_endpoint(client):
    r = client.get("/api/pipeline/deep-eval-config")
    assert r.status_code == 200
    res = r.json()
    assert res["code"] == 0
    data = res["data"]
    assert "model_name" in data
    assert "temperature" in data
    assert "active_resume" in data
    assert "modules" in data
    assert len(data["modules"]) == 6
    
    # 验证 6 大核心模块
    module_keys = [m["key"] for m in data["modules"]]
    for expected_key in [
        "ats_ability_analysis",
        "resume_audit",
        "dream_picture",
        "strong_fit_assessment",
        "risk_red_flags",
        "deep_action_plan",
    ]:
        assert expected_key in module_keys

    # 验证防编造铁律
    assert "anti_hallucination_rules" in data
    assert len(data["anti_hallucination_rules"]) >= 4


def test_deep_evaluate_resume_slimming_context():
    """验证 deep_evaluate_resume 调用时上下文已彻底精简（不含冗余初筛偏好与初评分数）"""
    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"extracted_skills": ["Python", "LangChain"]}'
    mock_response.choices = [mock_choice]
    mock_response.usage = None
    mock_openai.chat.completions.create.return_value = mock_response

    with patch("ai_agents.ai_scorer.get_openai_client", return_value=mock_openai):
        res, usage = deep_evaluate_resume(
            resume_text="精通 Python 与 FastAPI 开发",
            jd_text="招聘资深 AI 应用工程师，熟悉 LangChain",
        )
        assert res.get("extracted_skills") == ["Python", "LangChain"]

        # 检查传入大模型的 messages
        call_args = mock_openai.chat.completions.create.call_args[1]
        messages = call_args["messages"]
        system_msg = messages[0]["content"]
        user_msg = messages[1]["content"]

        # 1. 确认系统提示词不包含客套长文与旧版初筛偏好
        assert "资深猎头与职业规划专家" not in system_msg
        assert "严谨资深的技术面试官与简历合规审计专家" in system_msg

        # 2. 确认用户提示词只包含 JD 和 简历，不含初评分数 dump
        assert "【目标岗位 JD】" in user_msg
        assert ("【候选人简历】" in user_msg) or ("【候选人全局不可变简历档案】" in user_msg)
        assert "【第一阶段10维度评估结果" not in user_msg


def test_activate_resume_endpoint(client):
    with patch("app.strategy.service.activate_target_resume", return_value=None), \
         patch("app.services.feishu_service.get_active_resume_meta", return_value={"record_id": "rec_test_123", "title": "测试算法专家简历", "word_count": 3000, "status": "启用"}), \
         patch("app.services.feishu_service.get_all_resumes_meta", return_value=[{"record_id": "rec_test_123", "title": "测试算法专家简历", "word_count": 3000, "status": "启用"}]):
        r = client.post("/api/pipeline/activate-resume", json={"record_id": "rec_test_123"})
        assert r.status_code == 200
        res = r.json()
        assert res["code"] == 0
        assert res["data"]["active_resume"]["title"] == "测试算法专家简历"
        assert len(res["data"]["all_resumes"]) == 1

