import os
import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from resume_editor.agent_mapper import (
    load_master_resume,
    flatten_schema,
    get_path,
    set_path,
    _clean_md,
    _rule_map_zhilian,
    map_platform_rules,
    map_platform,
    apply_mapping,
    save_report,
    load_reports,
    DATA_DIR,
)


@pytest.fixture
def zhilian_fields_sample():
    # 固定样例（官网采集格式），不读真实数据文件，避免真实数据结构变化导致测试脆弱
    return {
        "profile": {
            "name": "张三",
            "gender": "2",
            "birthyear": "1990",
            "birthmonth": "11",
            "currentIdentity": "1",
        },
        "selfEvaluation": [
            {
                "selfEvaContent": "旧自我评价内容",
                "selfEvaTitle": "自我介绍"
            }
        ],
        "workExperience": [
            {
                "companyName": "旧公司",
                "jobTitle": "旧职位",
                "workDesc": "旧工作描述",
                "startDate": 1711900800000,
                "startDateFormat": "2024/04/01 00:00:00",
                "endDate": 0,
                "endDateFormat": "至今"
            }
        ],
        "project": [
            {
                "proExpProjectName": "旧项目",
                "proExpProjectDesc": "旧项目描述",
                "proExpStartDate": 1772294400000,
                "proExpStartDateFormat": "2026/03/01 00:00:00",
                "proExpEndDate": 0,
                "proExpEndDateFormat": "至今"
            }
        ],
        "education": [
            {
                "eduSchoolName": "旧学校",
                "eduMajorV": "旧专业",
                "eduStartDate": 1441036800000,
                "eduStartDateFormat": "2015/09/01 00:00:00",
                "eduEndDate": 1561824000000,
                "eduEndDateFormat": "2019/06/30 00:00:00",
                "eduBackground": "4"
            }
        ],
    }


@pytest.fixture
def master_resume_mock():
    real = load_master_resume()
    if real.get("ok") and real.get("data"):
        return real
    return {
        "ok": True,
        "source": "feishu",
        "record_id": "recvrGqr2qWNKv",
        "name": "海投简历",
        "data": {
            "personalInfo": {
                "name": "张三",
                "gender": "女",
                "phone": "13800138000",
                "email": "zhangsan.com",
            },
            "summary": "AI 应用从 0 到 1 落地：独立负责端到端 AI SaaS 系统架构与开发，熟练运用 Python、LangGraph 与 Next.js",
            "workExperience": [
                {
                    "company": "自由职业",
                    "title": "独立 AI 应用开发者",
                    "years": "2024.04-至今",
                    "description": "主导大模型 SaaS 开发与架构落地",
                }
            ],
            "personalProjects": [
                {
                    "name": "求职 SaaS 平台",
                    "years": "2026.02-2026.06",
                    "description": "全链路求职与简历多平台同步中台",
                }
            ],
            "education": [
                {
                    "institution": "云山大学",
                    "major": "电子商务",
                    "years": "2015.09-2019.06",
                    "degree": "本科",
                }
            ]
        }
    }


def test_flatten_schema_zhilian(zhilian_fields_sample):
    schema = flatten_schema(zhilian_fields_sample)
    paths = {s["path"] for s in schema}
    assert "self_evaluation" in paths
    assert "work_experience" in paths
    assert "education" in paths
    assert "projects" in paths or "project" in paths


def test_get_and_set_path_zhilian(zhilian_fields_sample):
    data = json.loads(json.dumps(zhilian_fields_sample))
    
    # 1. self_evaluation
    current_self = get_path(data, "self_evaluation")
    assert current_self is not None
    
    ok = set_path(data, "self_evaluation", "全新自我评价内容测试")
    assert ok is True
    assert data["selfEvaluation"][0]["selfEvaContent"] == "全新自我评价内容测试"
    assert get_path(data, "self_evaluation") == "全新自我评价内容测试"

    # 2. work_experience
    current_we = get_path(data, "work_experience")
    assert isinstance(current_we, list)
    
    new_we = [{"companyName": "新公司测试", "jobTitle": "全栈开发", "workDesc": "新工作经历描述"}]
    ok = set_path(data, "work_experience", new_we)
    assert ok is True
    assert data["workExperience"][0]["companyName"] == "新公司测试"

    # 3. name
    assert get_path(data, "name") == "张三"
    ok = set_path(data, "name", "张三测试")
    assert ok is True
    assert data["profile"]["name"] == "张三测试"


def test_rule_map_zhilian(zhilian_fields_sample, master_resume_mock):
    report = map_platform_rules("zhilian", zhilian_fields_sample, master_resume_mock)
    assert report["success"] is True
    assert report["platform"] == "zhilian"
    assert len(report["fields"]) > 0

    field_paths = {f["path"]: f for f in report["fields"]}
    assert "self_evaluation" in field_paths
    assert "work_experience" in field_paths
    assert "education" in field_paths
    assert "name" in field_paths

    # Check that self_evaluation content matches summary
    summary_expected = _clean_md(master_resume_mock["data"]["summary"])
    assert field_paths["self_evaluation"]["value"] in summary_expected or summary_expected in field_paths["self_evaluation"]["value"]


def test_apply_mapping_zhilian(zhilian_fields_sample, master_resume_mock):
    data = json.loads(json.dumps(zhilian_fields_sample))
    report = map_platform_rules("zhilian", data, master_resume_mock)
    entries = [{"path": f["path"], "value": f["value"]} for f in report["fields"]]

    res = apply_mapping(data, entries)
    assert len(res["skipped"]) == 0
    assert "self_evaluation" in res["applied"]
    assert "work_experience" in res["applied"]

    # Verify that data was updated in-place
    assert len(data["selfEvaluation"]) > 0
    assert len(data["selfEvaluation"][0]["selfEvaContent"]) > 0
    assert len(data["workExperience"]) > 0


def test_agent_map_apply_endpoint():
    client = TestClient(app)
    # Test apply endpoint
    test_entries = [
        {"path": "self_evaluation", "value": "测试应用个人优势"},
        {"path": "name", "value": "张三"}
    ]
    resp = client.post("/api/agent-map/apply", json={"platform": "zhilian", "entries": test_entries})
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["success"] is True
    assert "self_evaluation" in res_json["applied"]


def test_normalize_zhilian_work_skills():
    from resume_editor.agent_mapper import _normalize_zhilian_work_skills
    report = {
        "platform": "zhilian",
        "fields": [
            {
                "path": "work_experience",
                "value": [
                    {
                        "companyName": "科技公司",
                        "wnewJobSubType": "9000300290000",
                        "skillTagList": ["Python", "MySQL", "FastAPI", "LangGraph", "Docker", "SaaS开发"],
                    }
                ]
            }
        ]
    }
    res = _normalize_zhilian_work_skills(report)
    items = res["fields"][0]["value"]
    tag_list = items[0]["skillTagList"]
    assert len(tag_list) > 0
    # Every item must have a valid string/int skillId != "0" and != 0
    for s in tag_list:
        assert isinstance(s, dict)
        assert s["skillId"] not in ("0", 0, None, "")
        assert int(s["skillId"]) > 0
        assert len(s["name"]) > 0

    # Custom skills must be capped at 3
    custom_skills = [s for s in tag_list if s.get("customize")]
    assert len(custom_skills) <= 3
    assert items[0]["skillTagsTranslation"] == ",".join(s["name"] for s in tag_list)


def test_check_field_length_limits():
    from resume_editor.agent_mapper import _check_field_length_limits
    report = {
        "platform": "zhilian",
        "fields": [
            {
                "path": "self_evaluation",
                "value": "x" * 600,  # 上限 500
                "type": "textarea"
            },
            {
                "path": "projects",
                "type": "array",
                "value": [
                    {
                        "proExpProjectName": "智能美妆自动化",
                        "proExpProjectDesc": "y" * 3224,  # 上限 2000，超出 1224 字
                    }
                ]
            }
        ],
        "warnings": []
    }
    checked = _check_field_length_limits(report, "zhilian")
    # 1. 标量字段
    self_field = checked["fields"][0]
    assert self_field.get("over_limit") is True
    assert self_field.get("current_len") == 600
    assert self_field.get("max_limit") == 500
    assert self_field.get("overflow") == 100
    assert "⚠️ 字数超限" in self_field.get("note", "")

    # 2. 数组字段
    proj_field = checked["fields"][1]
    assert proj_field.get("has_over_limit_items") is True
    item = proj_field["value"][0]
    assert "_over_limit" in item
    assert "proExpProjectDesc" in item["_over_limit"]
    assert item["_over_limit"]["proExpProjectDesc"]["current"] == 3224
    assert item["_over_limit"]["proExpProjectDesc"]["overflow"] == 1224

    # 3. 报告 Warnings
    assert any("超出" in w and "1224" in w for w in checked["warnings"])


def test_zhilian_writeback_check_length_violations():
    from resume_editor.platforms.zhilian_write_back import check_length_violations
    local_data = {
        "selfEvaluation": [{"selfEvaContent": "a" * 550}],
        "project": [
            {"proExpProjectName": "大模型系统", "proExpProjectDesc": "b" * 3224}
        ]
    }
    violations = check_length_violations(local_data, ["self_evaluation", "projects"])
    assert len(violations) == 2
    desc_v = next(v for v in violations if "项目描述" in v["field_label"])
    assert desc_v["current_len"] == 3224
    assert desc_v["overflow"] == 1224
    assert "3224" in desc_v["reason"]
    assert "2000" in desc_v["suggestion"]


def test_zhilian_proskill_usetime_cleanup_and_plan():
    from resume_editor.platforms.zhilian_write_back import _items_same, _build_skill_values, plan_writeback
    # 1. 验证 _items_same 能精准识别 "5" vs "5年" 不一致
    local_skill = {"proskillName": "Python", "proskillLevel": "熟练", "proskillUseTime": "5"}
    off_skill_nan = {"proskillName": "Python", "proskillLevel": "熟练", "proskillUseTime": "5年", "path": "Resume[3].ProfessionalSkill[13]"}
    off_skill_clean = {"proskillName": "Python", "proskillLevel": "熟练", "proskillUseTime": "5", "path": "Resume[3].ProfessionalSkill[13]"}

    assert not _items_same(local_skill, off_skill_nan, ["proskillName", "proskillLevel", "proskillUseTime"])
    assert _items_same(local_skill, off_skill_clean, ["proskillName", "proskillLevel", "proskillUseTime"])

    # 2. 验证 _build_skill_values 将 proskillUseTime 净化为纯数字串 "5"
    built = _build_skill_values({"proskillName": "Python", "proskillUseTime": "5个月"}, off_skill_nan)
    assert built["proskillUseTime"] == "5"

    # 3. 验证 plan_writeback 对脏数据 "5年" 生成 edit 回写动作
    local = {"professionalSkills": [local_skill]}
    official = {"ProfessionalSkill": [off_skill_nan]}
    plan = plan_writeback(local, official, ["skill_tags"])
    assert len(plan["actions"]) == 1
    assert plan["actions"][0]["op"] == "edit"
    assert plan["actions"][0]["values"]["proskillUseTime"] == "5"


def test_zhilian_verify_results_plan_structure():
    from resume_editor.platforms.zhilian_write_back import verify_results
    local = {
        "work_experience": [
            {
                "companyName": "科技有限公司",
                "jobTitle": "大模型工程师",
                "workDesc": "负责大模型应用开发",
                "startDate": 1711900800000,
                "startDateFormat": "2024/04/01 00:00:00",
                "endDate": 0,
                "endDateFormat": "至今"
            }
        ]
    }
    verify_off = {
        "WorkExperience": [
            {
                "path": "Resume[3].WorkExperience[0]",
                "companyName": "科技有限公司",
                "jobTitle": "大模型工程师",
                "workDesc": "负责大模型应用开发",
                "startDate": 1711900800000,
                "startDateFormat": "2024/04/01 00:00:00",
                "endDate": 0,
                "endDateFormat": "至今"
            }
        ]
    }
    plan = {
        "actions": [{"module": "work_experience", "op": "edit", "node": "WorkExperience"}],
        "skipped": []
    }
    # 验证 verify_results 不依赖 plan["modules"]，正常返回复核结果
    res = verify_results(verify_off, local, plan)
    assert len(res) == 1
    assert res[0]["module"] == "work_experience"
    assert res[0]["match"] is True




