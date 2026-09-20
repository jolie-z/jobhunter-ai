"""
51job 主简历智能与规则映射单元测试 (test_job51_agent_mapping.py)
验证 51job 的确定性规则映射、单时间点项目对齐、职位类目反查与字数安全截断机制
"""

import pytest
from resume_editor.agent_mapper import (
    _rule_map_51job,
    _enforce_51job_single_project_end,
    _map_51job_work_function,
)


@pytest.fixture
def sample_master_resume():
    """主简历数据结构"""
    return {
        "ok": True,
        "source": "feishu",
        "data": {
            "summary": "资深全栈技术专家，具备10年大型互联网高并发架构设计与团队管理经验。" + ("深入研究云原生与AI Agent架构。" * 30),  # 超长文本测试
            "workExperience": [
                {
                    "company": "字节跳动科技",
                    "title": "后端架构师",
                    "years": "2020.06 - 至今",
                    "description": "负责核心推荐系统架构重构与性能优化。" + ("支持十亿级日流量并发处理。" * 100),  # 超长文本测试
                },
                {
                    "company": "阿里巴巴集团",
                    "title": "高级研发工程师",
                    "years": "2016.07 - 2020.05",
                    "description": "负责电商交易链路与风控网关建设。",
                }
            ],
            "personalProjects": [
                {
                    "name": "智能多Agent协作求职中枢",
                    "years": "2026.03",  # 单时间点测试
                    "description": "基于大模型与多工具协同的自动化求职机器人。" + ("实现真机无损回写。" * 100),  # 超长文本测试
                },
                {
                    "name": "企业级数据分析湖仓",
                    "years": "2021.01 - 2021.12",
                    "description": "基于 Spark 与 Flink 的实时数仓系统。",
                }
            ],
            "education": [
                {
                    "institution": "浙江大学",
                    "major": "计算机科学与技术",
                    "degree": "硕士",
                    "years": "2013.09 - 2016.06",
                }
            ]
        }
    }


@pytest.fixture
def sample_51job_fields():
    """51job 现有平台数据结构（带官网选项代码）"""
    return {
        "basic_info": {"current_value": {"cName": "李四"}},
        "self_introduction": {"current_value": {"selfIntroduction": "旧自我介绍"}},
        "intentions": {"current_value": [{"seekType": "0", "expectArea": "020000"}]},
        "works": {
            "current_value": [
                {
                    "id": "w1",
                    "companyName": "旧公司A",
                    "position": "旧职位",
                    "workFunction": "0100",
                    "workFunctionString": "软件工程师",
                    "workIndustry": "01",
                    "workDescription": "旧工作描述",
                    "startTime": "2020-06",
                    "endTime": "至今",
                },
                {
                    "id": "w2",
                    "companyName": "旧公司B",
                    "position": "旧职位",
                    "workFunction": "0200",
                    "workFunctionString": "开发工程师",
                    "workIndustry": "01",
                    "workDescription": "旧工作描述",
                    "startTime": "2016-07",
                    "endTime": "2020-05",
                }
            ]
        },
        "projects": {
            "current_value": [
                {
                    "id": "p1",
                    "projectName": "旧项目1",
                    "describe": "旧描述",
                    "startTime": "2026-03",
                    "endTime": "至今",
                },
                {
                    "id": "p2",
                    "projectName": "旧项目2",
                    "describe": "旧描述",
                    "startTime": "2021-01",
                    "endTime": "2021-12",
                }
            ]
        },
        "educations": {
            "current_value": [
                {
                    "id": "e1",
                    "schoolName": "旧大学",
                    "major": "旧专业",
                    "degree": "030",  # 硕士码
                    "degreeString": "硕士",
                    "startTime": "2013-09",
                    "endTime": "2016-06",
                }
            ]
        }
    }


def test_rule_map_51job_text_and_truncation(sample_51job_fields, sample_master_resume):
    """验证规则映射的字段覆写与字数截断保护机制"""
    report = _rule_map_51job(sample_51job_fields, sample_master_resume)

    assert report["success"] is True
    assert report["platform"] == "51job"
    fields_by_path = {f["path"]: f["value"] for f in report["fields"]}

    # 1. 自我介绍：500 字上限截断保护
    si_val = fields_by_path["self_introduction.selfIntroduction"]
    assert len(si_val) <= 500
    assert "资深全栈技术专家" in si_val

    # 2. 工作经历：2000 字上限截断保护，覆写 companyName 与 position
    works_val = fields_by_path["works"]
    assert len(works_val) == 2
    assert works_val[0]["companyName"] == "字节跳动科技"
    assert works_val[0]["position"] == "后端架构师"
    assert len(works_val[0]["workDescription"]) <= 2000
    assert "核心推荐系统架构重构" in works_val[0]["workDescription"]

    # 3. 项目经历：单时间点规则与 2000 字截断
    proj_val = fields_by_path["projects"]
    assert len(proj_val) == 2
    assert proj_val[0]["projectName"] == "智能多Agent协作求职中枢"
    assert proj_val[0]["startTime"] == "2026-03"
    assert proj_val[0]["endTime"] == "2026-03"  # 必须是同月结束，绝不能为至今
    assert len(proj_val[0]["describe"]) <= 2000

    # 4. 教育经历：校名与专业覆盖，保留 degree 选项码
    edu_val = fields_by_path["educations"]
    assert len(edu_val) == 1
    assert edu_val[0]["schoolName"] == "浙江大学"
    assert edu_val[0]["major"] == "计算机科学与技术"
    assert edu_val[0]["degree"] == "030"


def test_enforce_51job_single_project_end():
    """验证单时间点项目经历结束时间自动对齐同月（非至今）"""
    mock_master = {
        "data": {
            "personalProjects": [
                {"name": "独立创新项目", "years": "2026.04", "description": "测试单月"}
            ]
        }
    }
    mock_report = {
        "fields": [
            {
                "path": "projects",
                "type": "array",
                "value": [
                    {"projectName": "独立创新项目", "startTime": "2026-04", "endTime": "至今"}
                ]
            }
        ],
        "warnings": []
    }

    result = _enforce_51job_single_project_end(mock_report, mock_master)
    proj = result["fields"][0]["value"][0]
    assert proj["endTime"] == "2026-04"
    assert any("单个时间" in w or "单时间" in w for w in result["warnings"])


def test_map_51job_work_function_exact_match():
    """验证职位类目与 51job 官方树形字典的精确匹配"""
    mock_master = {
        "data": {
            "workExperience": [
                {"title": "软件工程师", "company": "某公司", "years": "2020 - 2022"}
            ]
        }
    }
    mock_report = {
        "fields": [
            {
                "path": "works",
                "type": "array",
                "value": [
                    {"companyName": "某公司", "position": "软件工程师", "workFunction": "old_code"}
                ]
            }
        ],
        "warnings": []
    }

    result = _map_51job_work_function(mock_report, mock_master)
    assert len(result["fields"][0]["value"]) == 1
    # 只要字典存在，若精确匹配成功则更新 workFunction，若无精确匹配则保留原值并提示
    assert len(result["warnings"]) > 0
    assert "工作类型" in result["warnings"][0]


def test_rule_map_51job_adds_extra_work_experiences_and_skills(sample_51job_fields):
    """验证主简历有 3 条经历（含自由职业者）而平台仅 2 条时，自动追加第 3 条新增项，并提取技能和推断工作类型"""
    master = {
        "ok": True,
        "data": {
            "summary": "AI 开发者",
            "workExperience": [
                {
                    "company": "自由职业者",
                    "title": "独立 AI 应用开发者 / 全栈研发",
                    "years": "2024.04 - 至今",
                    "description": "围绕多平台分发开发自动求职 SaaS，使用 Python、FastAPI、React 与大模型 Agent 架构",
                },
                {
                    "company": "旧公司A",
                    "title": "后端架构师",
                    "years": "2020.06 - 2024.03",
                    "description": "负责 Java、Spring Boot 与 Redis 高并发系统重构",
                },
                {
                    "company": "旧公司B",
                    "title": "研发实习生",
                    "years": "2016.07 - 2020.05",
                    "description": "负责 MySQL 数据清洗与自动化脚本编写",
                }
            ]
        }
    }
    report = _rule_map_51job(sample_51job_fields, master)
    assert report["success"] is True
    works_field = next(f for f in report["fields"] if f["path"] == "works")
    works = works_field["value"]
    # 必须完整生成 3 条工作经历（第 3 条自动追加，不再遗漏！）
    assert len(works) == 3

    # 验证第 1 条（自由职业者）：工作类型自动识别为兼职/自由职业 ("1")，技能自动提取
    w_freelance = next(w for w in works if w.get("companyName") == "自由职业者")
    assert w_freelance["position"] == "独立 AI 应用开发者 / 全栈研发"
    assert w_freelance["workType"] == "1"
    assert w_freelance["endTime"] == "至今"
    assert any("大模型" in s for s in w_freelance["workVocationalSkills"])
    assert any("Python" in s or "FastAPI" in s for s in w_freelance["workVocationalSkills"])

    # 验证实习生：工作类型自动识别为实习 ("2")
    w_intern = next(w for w in works if "实习" in w.get("position", "") or "旧公司B" in w.get("companyName", ""))
    assert w_intern["workType"] == "2"
