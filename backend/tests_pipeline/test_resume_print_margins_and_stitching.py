"""
测试简历 HTML 渲染与 PDF 边距加固
===================================
1. 验证专业技能列表破碎单字智能清洗与聚合（无破折号空 bullet）
2. 验证缺失 personalInfo 时自动兜底姓名与联系方式，杜绝 "- 个人简历"
3. 验证 render_html_to_pdf 默认应用标准打印安全边距，杜绝 0 留白
"""
import pytest
from app.core.resume_html_builder import (
    build_resume_html,
    _consolidate_technical_skills,
    _markdown_to_html_snippet,
)
from app.core.pdf_renderer import _resolve_pdf_margins


def test_consolidate_technical_skills_removes_empty_and_merges():
    raw_skills = [
        "- 大模型应用开发（OpenAI API）",
        "- **LangGraph**智能体架构",
        "",
        "**RAG**",
        "",
        "**RPA (GUI自动化)**",
        "",
        "**数据治理**",
        "- Python",
        "- SQL",
        "**FastAPI**",
        "**Next.js**"
    ]
    consolidated = _consolidate_technical_skills(raw_skills)
    assert len(consolidated) < len(raw_skills)
    assert not any(s == "" for s in consolidated)
    assert not any(s == "-" for s in consolidated)

    # 验证 markdown 转换后无空 <li></li>
    html = _markdown_to_html_snippet(consolidated)
    assert "<li></li>" not in html
    assert "<li>-</li>" not in html


def test_build_resume_html_auto_stitches_missing_personal_info(monkeypatch):
    # 断掉飞书 token：测试不依赖本机飞书配置，确定性走中性兜底
    monkeypatch.setattr(
        "app.services.feishu_service.get_tenant_access_token", lambda: None
    )
    data = {
        "personalInfo": {},
        "summary": "资深 AI 产品经理",
        "workExperience": [],
        "personalProjects": [],
        "education": [],
        "additional": {}
    }
    html = build_resume_html(data, skin="classic")
    # 验证姓名与标题栏正常，绝不出现 "- 个人简历"
    assert "<title>张 三 - 个人简历</title>" in html
    assert "张 三" in html
    # 中性兜底不注入任何联系方式：竖线分隔的 meta 行仅在存在联系方式时渲染
    assert "丨" not in html


def test_pdf_renderer_margins_have_proper_whitespace():
    # 验证未指定 margins 时默认返回安全留白边距
    default_margins = _resolve_pdf_margins(None)
    assert default_margins["top"] == "10mm"
    assert default_margins["right"] == "10mm"
    assert default_margins["bottom"] == "10mm"
    assert default_margins["left"] == "10mm"
