"""
Unit tests for Pure Python Resume HTML Builder (aligned with frontend ResumeClassic / ResumeColor).
"""
import pytest
from app.core.resume_html_builder import build_resume_html, _markdown_to_html_snippet

def test_markdown_to_html_snippet():
    text = "**5年电商运营专家**：主导 **3CE** 店铺\n- 解决率提升 75%\n- [项目链接](https://github.com/demo-user)"
    html = _markdown_to_html_snippet(text)
    assert "<strong>5年电商运营专家</strong>" in html
    assert "<strong>3CE</strong>" in html
    assert "<li>解决率提升 75%</li>" in html
    assert '<a href="https://github.com/demo-user" target="_blank">项目链接</a>' in html
    assert '<ul class="resume-ul">' in html


def test_build_resume_html_classic_with_avatar():
    data = {
        "personalInfo": {
            "name": "张三",
            "phone": "138-0000-8888",
            "email": "zhangsan.com",
            "GitHub主页": "https://github.com/demo-user",
            "city": "广州",
            "avatar_url": "http://127.0.0.1:8000/api/strategy/avatar/tok123"
        },
        "summary": "- **AI全栈开发者**：独立交付5项企业级AI产品",
        "workExperience": [
            {
                "company": "某美妆集团",
                "title": "AI业务运营",
                "years": "2019.07-2023.08",
                "description": ["- 主导智能客服系统0-1建设", "- 机器解决率达75%+"]
            }
        ],
        "personalProjects": [
            {
                "name": "Auto-JobHunter",
                "role": "独立开发者",
                "years": "2026.02-至今",
                "description": ["- 全链路自动求职 Copilot SaaS"]
            }
        ],
        "education": [
            {
                "school": "某财经类大学",
                "major": "社会工作",
                "degree": "全日制本科",
                "years": "2015.07-2019.07"
            }
        ],
        "additional": {
            "technicalSkills": ["- **大模型与Agent**：熟练掌握 LangGraph, Prompt Engineering"],
            "languages": ["英语 CET-6"],
            "certificationsTraining": []
        }
    }

    html = build_resume_html(data, skin="classic")
    
    # 1. 验证中文姓名自动空格排版
    assert "张 三" in html
    # 2. 验证证件照头像节点与避让样式
    assert 'class="resume-avatar"' in html
    assert 'http://127.0.0.1:8000/api/strategy/avatar/tok123' in html
    assert 'has-avatar' in html
    # 3. 验证去 Emoji 后的纯净竖线分隔
    assert "138-0000-8888" in html
    assert "zhangsan.com" in html
    assert "meta-sep" in html
    assert "📞" not in html
    assert "✉️" not in html
    # 4. 验证三栏水平对齐网格结构
    assert "item-grid" in html
    assert "col-left" in html
    assert "col-center" in html
    assert "col-right" in html
    assert "某美妆集团" in html
    assert "AI业务运营" in html
    assert "2019.07-2023.08" in html
    # 5. 验证经典普通模版色彩
    assert "--accent: #000000;" in html


def test_build_resume_html_multi_skin():
    data = {
        "personalInfo": {"name": "张三", "phone": "13800000000"},
        "summary": "资深数据分析师"
    }

    html_v1 = build_resume_html(data, skin="color_v1")
    assert "--accent: #1d4ed8;" in html_v1

    html_v2 = build_resume_html(data, skin="color_v2")
    assert "--accent: #1e40af;" in html_v2


def test_strip_confidence_tags():
    data = {
        "personalInfo": {"name": "张三", "phone": "13800000000"},
        "summary": "针对单条JD设计代码级前置过滤引擎 [稳]",
        "workExperience": [
            {
                "company": "测试科技",
                "title": "工程师",
                "years": "2020-2022",
                "description": [
                    "负责核心爬虫抓取系统，突破反爬策略 [需补证]",
                    "搭建微服务架构与自动化发布流水线 [补证后可用]"
                ]
            }
        ]
    }
    html = build_resume_html(data, skin="classic")
    assert "[稳]" not in html
    assert "[需补证]" not in html
    assert "[补证后可用]" not in html
    assert "突破反爬策略" in html
    assert "搭建微服务架构" in html
