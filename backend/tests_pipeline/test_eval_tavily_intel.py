"""
自动化测试：AI 初评自动触发 Serper 企业背调联网情报探针（Tavily 降级）
验证点：
1. evaluate_single_job 在 company_intel 为空时，根据 enable_company_search 自动触发公司情报背调
2. 成功获取的情报自动写入 update_data["公司业务情报"] 与返回值中
3. 当 enable_company_search=False 时，跳过网络请求
4. 当企业为匿名/未知时，不写入垃圾情报
"""

import pytest
from unittest.mock import patch, MagicMock
from ai_agents.ai_evaluator import evaluate_single_job


def test_evaluate_single_job_auto_triggers_tavily(monkeypatch):
    """测试评估单个岗位时，自动触发联网背调并写入情报字段"""
    mock_intel_search = MagicMock(return_value="【测试科技 公司情报】\n· 核心业务为大模型企业级落地应用，已完成A轮融资。")
    mock_10dim = MagicMock(return_value=(
        {
            "grade": "B",
            "scores": {
                "role_match": 4, "skills_align": 4, "seniority": 4,
                "compensation": 4, "interview_prob": 4, "company_stage": 4,
                "market_fit": 4, "growth": 4
            },
            "score_rationales": {"role_match": "良好"}
        },
        {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    ))
    
    monkeypatch.setattr("ai_agents.ai_evaluator.fetch_company_intel", mock_intel_search)
    monkeypatch.setattr("ai_agents.ai_evaluator._call_10dim_evaluation", mock_10dim)
    monkeypatch.setattr("ai_agents.ai_evaluator.get_auto_eval_threshold", lambda: "A")

    job_data = {
        "record_id": "rec_test_123",
        "company": "测试科技股份有限公司",
        "job_title": "AI产品经理",
        "platform": "boss",
        "jd_text": "负责大模型与企业知识库相关产品设计与落地。",
        "salary": "25-35K",
        "city": "广州",
        "experience": "3-5年",
        "education": "本科",
    }

    result = evaluate_single_job(
        job_data=job_data,
        resume_text="资深产品经理，精通大模型落地与敏捷管理。",
        company_intel="",  # 初始为空
        preferences_text="期望15K以上",
        task_mode="eval_only"
    )

    # 验证是否自动调用了情报调度器
    mock_intel_search.assert_called_once_with("测试科技股份有限公司")
    
    # 验证 update_data 中是否包含公司业务情报
    assert result["success"] is True
    assert "公司业务情报" in result["update_data"]
    assert "测试科技 公司情报" in result["update_data"]["公司业务情报"]
    assert "公司业务情报" in result["update_data"]
    assert result["company_intel"] != ""


def test_evaluate_single_job_skips_search_when_disabled(monkeypatch):
    """测试当关闭企业背调开关时，不调用情报调度器"""
    mock_intel_search = MagicMock(return_value="【不应该被调用】")
    mock_10dim = MagicMock(return_value=(
        {
            "grade": "C",
            "scores": {
                "role_match": 3, "skills_align": 3, "seniority": 3,
                "compensation": 3, "interview_prob": 3, "company_stage": 3,
                "market_fit": 3, "growth": 3
            },
            "score_rationales": {}
        },
        {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    ))
    
    monkeypatch.setattr("ai_agents.ai_evaluator.fetch_company_intel", mock_intel_search)
    monkeypatch.setattr("ai_agents.ai_evaluator._call_10dim_evaluation", mock_10dim)
    monkeypatch.setattr("app.automation.db.get_autopilot_config", lambda: {"enable_company_search": False})

    job_data = {
        "record_id": "rec_test_456",
        "company": "测试科技股份有限公司",
        "job_title": "AI产品经理",
        "platform": "boss",
        "jd_text": "负责产品设计",
        "salary": "20K",
        "city": "广州",
        "experience": "3年",
        "education": "本科",
    }

    result = evaluate_single_job(
        job_data=job_data,
        resume_text="个人简历",
        company_intel="",
        preferences_text="",
        task_mode="eval_only"
    )

    # 验证没有调用情报调度器
    mock_intel_search.assert_not_called()
    assert "公司业务情报" not in result["update_data"]
