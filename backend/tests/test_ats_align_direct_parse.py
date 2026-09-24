"""ats_align 底稿 JSON 直解析（跳过 LLM 调用#1）回归测试。

对应方案：docs/reports/2026-09-19_ATS靶向改写提速方案_底稿JSON直解析.md
量化依据：LLM#1 parse_resume_to_json 占端到端 53%，而底稿主路径恒为 JSON 串。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.strategy.ai_diagnosis_service import ats_align_experience_service
from app.strategy.schemas import AtsAlignRequest

VALID_RESUME_JSON = json.dumps(
    {
        "summary": "测试总结",
        "workExperience": [
            {"title": "后端工程师", "company": "测试公司", "years": "2020.01-2024.01", "description": ["做了A", "做了B"]}
        ],
        "personalProjects": [
            {"name": "测试项目", "role": "owner", "years": "2024.01-至今", "description": ["开发C"]}
        ],
        "moduleOrder": ["summary", "workExperience", "personalProjects"],
        "moduleTitles": {"summary": "个人总结", "workExperience": "工作经历", "personalProjects": "项目经历"},
    },
    ensure_ascii=False,
)

# 手写期望值（非实现输出）：ResumeData.model_dump 的同构形态
EXPECTED_DIRECT_PARSE = {
    "personalInfo": {"name": "", "title": "", "email": "", "phone": "", "location": "", "website": None},
    "summary": "测试总结",
    "workExperience": [
        {"title": "后端工程师", "company": "测试公司", "location": None, "years": "2020.01-2024.01", "description": ["做了A", "做了B"]}
    ],
    "education": [],
    "personalProjects": [
        {"name": "测试项目", "role": "owner", "years": "2024.01-至今", "description": ["开发C"]}
    ],
    # skillOverview 为 185acf1 新增字段（AdditionalInfo 默认空串），model_dump 必带此键
    "additional": {"skillOverview": "", "technicalSkills": [], "languages": [], "certificationsTraining": []},
    "moduleOrder": ["summary", "workExperience", "personalProjects"],
    "moduleTitles": {"summary": "个人总结", "workExperience": "工作经历", "personalProjects": "项目经历"},
    "customModules": {},
}

# LLM#2（靶向改写）返回的最小合法 JSON：is_modified=False 走最短路径
LLM2_OK = json.dumps(
    {"is_modified": False, "blocks": [], "injected_keywords": [], "surgeon_rationale": ""},
    ensure_ascii=False,
)

FALLBACK_PARSE_RESULT = {
    "workExperience": [{"title": "回退岗位", "company": "回退公司", "years": "2019.01-2020.01", "description": ["回退条目"]}],
    "personalProjects": [],
}


def _make_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices[0].message.content = content
    return resp


def _make_client_mock(content: str):
    client = MagicMock()
    client.chat.completions.create.return_value = _make_llm_response(content)
    return client


def _payload(full_resume_context) -> AtsAlignRequest:
    return AtsAlignRequest(
        original_experience="测试目标经历",
        jd_report_context="测试JD画像",
        full_resume_context=full_resume_context,
    )


@pytest.mark.asyncio
async def test_valid_json_resume_skips_llm_parse_and_feeds_prompt():
    """底稿为合法 JSON：本地直解析、parse_resume_to_json 零调用、产物进 user prompt 且与手写 fixture 同构"""
    client = _make_client_mock(LLM2_OK)
    captured = {}

    def _capture_create(**kwargs):
        captured.update(kwargs)
        return _make_llm_response(LLM2_OK)

    client.chat.completions.create.side_effect = _capture_create
    mock_parse = AsyncMock(return_value=FALLBACK_PARSE_RESULT)

    with patch("app.strategy.ai_diagnosis_service._get_client", return_value=client), \
         patch("app.strategy.ai_diagnosis_service.parse_resume_to_json", new=mock_parse):
        result = await ats_align_experience_service(_payload(VALID_RESUME_JSON))

    mock_parse.assert_not_called()
    client.chat.completions.create.assert_called_once()  # 全链只剩 LLM#2，零多余 LLM 调用
    # 从 user prompt 中切出简历 AST 片段，按结构（而非键序/文本）与手写 fixture 同构比对
    user_content = captured["messages"][1]["content"]
    ast_start = user_content.index("{", user_content.index("【全局完整简历结构"))
    ast_end = user_content.index("【请仅对以下目标经历")
    ast_in_prompt = json.loads(user_content[ast_start:ast_end].strip())
    assert ast_in_prompt == EXPECTED_DIRECT_PARSE
    assert "后端工程师" in user_content
    assert result["is_modified"] is False


@pytest.mark.asyncio
async def test_markdown_resume_falls_back_to_llm_parse():
    """底稿为 Markdown（非 JSON）：回退走 parse_resume_to_json，LLM 产物进 user prompt"""
    client = _make_client_mock(LLM2_OK)
    mock_parse = AsyncMock(return_value=FALLBACK_PARSE_RESULT)

    with patch("app.strategy.ai_diagnosis_service._get_client", return_value=client), \
         patch("app.strategy.ai_diagnosis_service.parse_resume_to_json", new=mock_parse):
        result = await ats_align_experience_service(_payload("# 我的简历\n- 手写条目"))

    mock_parse.assert_awaited_once()
    assert result["is_modified"] is False


@pytest.mark.asyncio
async def test_schema_broken_json_falls_back_to_llm_parse():
    """底稿是合法 JSON 但 schema 不合规（description 应为数组）：ValidationError 触发回退 LLM"""
    broken_json = json.dumps(
        {"workExperience": [{"title": "岗位", "company": "公司", "years": "2020.01-2024.01", "description": "不是数组"}]},
        ensure_ascii=False,
    )
    client = _make_client_mock(LLM2_OK)
    mock_parse = AsyncMock(return_value=FALLBACK_PARSE_RESULT)

    with patch("app.strategy.ai_diagnosis_service._get_client", return_value=client), \
         patch("app.strategy.ai_diagnosis_service.parse_resume_to_json", new=mock_parse):
        result = await ats_align_experience_service(_payload(broken_json))

    mock_parse.assert_awaited_once()
    assert result["is_modified"] is False


@pytest.mark.asyncio
async def test_empty_resume_skips_both_paths():
    """空底稿：resume_json 为空 dict，LLM 解析与直解析皆不触发，user prompt 中简历结构为空对象"""
    client = _make_client_mock(LLM2_OK)
    captured = {}

    def _capture_create(**kwargs):
        captured.update(kwargs)
        return _make_llm_response(LLM2_OK)

    client.chat.completions.create.side_effect = _capture_create
    mock_parse = AsyncMock(return_value=FALLBACK_PARSE_RESULT)

    with patch("app.strategy.ai_diagnosis_service._get_client", return_value=client), \
         patch("app.strategy.ai_diagnosis_service.parse_resume_to_json", new=mock_parse), \
         patch("app.strategy.ai_diagnosis_service.get_active_resume_text_async", new=AsyncMock(return_value="")):
        result = await ats_align_experience_service(_payload(""))

    mock_parse.assert_not_called()
    assert "{}" in captured["messages"][1]["content"]
    assert result["is_modified"] is False
