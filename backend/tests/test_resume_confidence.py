"""resume_confidence 打分规则测试。"""

from app.core.resume_confidence import score_resume_confidence


def test_missing_and_thin_modules_marked_low():
    structured = {
        "summary": "",  # 空 → low
        "workExperience": [
            {"company": "A", "description": "负责核心业务，支撑日均千万级请求的微服务架构设计与落地"}
        ],
        "personalProjects": [],  # 空列表 → low
        "education": None,  # 缺失 → low
        "additional": "熟悉英语",  # 过短 → low
    }
    result = score_resume_confidence(structured)
    assert result["summary"] == "low"
    assert result["workExperience"] == "high"
    assert result["personalProjects"] == "low"
    assert result["education"] == "low"
    assert result["additional"] == "low"


def test_normal_modules_marked_high():
    structured = {
        "summary": "五年电商与 AI 应用全栈经验，主导过多个从 0 到 1 的业务级 SaaS 产品交付",
        "workExperience": [
            {"company": "A", "description": "负责核心微服务架构"},
            {"company": "B", "description": "带领 3 人小组交付数据中台"},
        ],
    }
    result = score_resume_confidence(structured)
    assert result["summary"] == "high"
    assert result["workExperience"] == "high"


def test_entries_without_substantive_content_marked_low():
    # 有条目但字段几乎全空 → low
    structured = {
        "workExperience": [
            {"company": "A", "description": ""},
            {"company": "B", "description": "短"},
        ],
    }
    result = score_resume_confidence(structured)
    assert result["workExperience"] == "low"


def test_custom_modules_scored_per_key():
    # 前端规范：customModules = Record<moduleKey, ExperienceV2[]>（R1 P1 对齐）
    structured = {
        "customModules": {
            "custom_skills": [
                {"title": "技能", "description": "Python、SQL、Tableau 等数据分析全栈技能，多年实战经验积累"},
            ],
            "custom_empty": [
                {"title": "空模块", "description": ""},
            ],
        },
    }
    result = score_resume_confidence(structured)
    assert result["custom_skills"] == "high"
    assert result["custom_empty"] == "low"


def test_non_dict_input_returns_empty():
    assert score_resume_confidence(None) == {}  # type: ignore[arg-type]
    assert score_resume_confidence("not a dict") == {}  # type: ignore[arg-type]
