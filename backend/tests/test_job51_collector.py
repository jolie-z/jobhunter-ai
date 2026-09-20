"""
51job 采集器单元与集成测试 (test_job51_collector.py)
验证从 51job PCResume Vue 结构到前端标准 ResumeData 的字段转换与防覆盖保护
"""

import json
import os
import pytest
import tempfile

from resume_editor.platforms.job51_collector import transform_data, save_data


@pytest.fixture
def sample_vue_resume():
    """模拟 51job 官网 PCResume 组件导出的原始 JSON 数据"""
    return {
        "accountInfo": {
            "cName": "张三",
            "sex": "0",
            "sexString": "男",
            "birthday": "1995-06",
            "mobile": "13800138000",
            "email": "zhangsan@example.com",
            "workYearMonth": "2018-07",
            "workYearString": "6年工作经验",
            "newCurrentSituation": "1",
            "newCurrentSituationString": "离职-随时到岗",
            "area": {"code": "020000", "label": "上海"},
            "household": "上海",
            "politicsStatus": "4",
        },
        "selfIntroduction": {
            "selfIntroduction": "资深全栈工程师，擅长 Python 与 TypeScript。"
        },
        "intentions": [
            {
                "id": "int_01",
                "seekType": "0",
                "expectAreaString": "上海, 杭州",
                "expectArea": "020000, 080200",
                "expectFunctionString": "全栈工程师",
                "expectFunction": "0100",
                "expectIndustryString": "互联网/电子商务",
                "expectIndustry": "01",
                "salaryType": "1",
                "minSalary": 25,
                "maxSalary": 40,
                "salaryMonth": "14",
            }
        ],
        "works": [
            {
                "id": "work_01",
                "companyName": "上海某某科技有限公司",
                "position": "高级全栈工程师",
                "workFunction": "0100",
                "workFunctionString": "全栈工程师",
                "workIndustry": "01",
                "workIndustryString": "互联网/电子商务",
                "workType": "0",
                "workTypeString": "全职",
                "workDescription": "负责核心业务架构设计与微服务开发。",
                "startTime": "2021-03",
                "endTime": "2024-05",
                "startTimeString": "2021.03",
                "endTimeString": "2024.05",
            }
        ],
        "projects": [
            {
                "id": "proj_01",
                "projectName": "智能求职助手平台",
                "companyName": "上海某某科技有限公司",
                "describe": "基于 AI Agent 的自动化求职系统。",
                "startTime": "2023-01",
                "endTime": "2023-12",
                "startTimeString": "2023.01",
                "endTimeString": "2023.12",
            }
        ],
        "educations": [
            {
                "id": "edu_01",
                "schoolName": "同济大学",
                "major": "0809",
                "majorString": "计算机类",
                "majorDescribe": "软件工程",
                "degree": "040",
                "degreeString": "本科",
                "isFullTime": True,
                "isOverseas": False,
                "startTime": "2014-09",
                "endTime": "2018-06",
                "startTimeString": "2014.09",
                "endTimeString": "2018.06",
                "complete": True,
            }
        ],
        "skills": [
            {
                "id": "skill_01",
                "skillType": "python",
                "skillTypeString": "Python",
                "ability": "3",
                "abilityString": "精通",
            }
        ],
        "language": [
            {
                "id": "lang_01",
                "skillType": "english",
                "skillTypeString": "英语",
                "ability": "2",
                "abilityString": "熟练",
            },
            {
                "id": "lang_02",
                "skillType": "japanese",
                "skillTypeString": "日语",
                "ability": "3",
                "abilityString": "精通",
            },
        ],
        "languageCertsByLang": {
            "english": [{"code": "cet6", "value": "大学英语六级(CET-6)"}],
            "japanese": [{"code": "jlpt1", "value": "日语能力一级"}],
        },
        "certifications": [
            {
                "id": "cert_01",
                "cert": "pmp",
                "certString": "PMP项目管理专业人士资格认证",
                "startTime": "2022-09",
            }
        ],
        "avatarUrl": "https://img.51job.com/avatar/123.jpg",
        "topDegreeEducation": {
            "degreeString": "本科"
        },
        "personalSkills": [
            {"function": "0100", "functionString": "全栈开发", "questions": []}
        ]
    }


def test_transform_data_all_modules(sample_vue_resume):
    """验证 transform_data 能够正确转换 10 大核心模块"""
    transformed = transform_data(sample_vue_resume)

    assert "basic_info" in transformed
    assert "self_introduction" in transformed
    assert "intentions" in transformed
    assert "works" in transformed
    assert "projects" in transformed
    assert "educations" in transformed
    assert "language" in transformed
    assert "skills" in transformed
    assert "certifications" in transformed
    assert "personalSkills" in transformed

    # 1. 基本信息
    bi = transformed["basic_info"]["current_value"]
    assert bi["cName"] == "张三"
    assert bi["avatarUrl"] == "https://img.51job.com/avatar/123.jpg"
    assert bi["topDegreeString"] == "本科"

    # 2. 自我介绍
    si = transformed["self_introduction"]["current_value"]
    assert "资深全栈工程师" in si["selfIntroduction"]

    # 3. 求职意向
    intentions = transformed["intentions"]["current_value"]
    assert len(intentions) == 1
    assert intentions[0]["expectAreaNames"] == "上海, 杭州"
    assert intentions[0]["expectFunctionName"] == "全栈工程师"
    assert intentions[0]["industryNames"] == "互联网/电子商务"
    assert intentions[0]["salaryMonth"] == 14

    # 4. 工作经历
    works = transformed["works"]["current_value"]
    assert len(works) == 1
    assert works[0]["companyName"] == "上海某某科技有限公司"
    assert works[0]["seekType"] == "0"
    assert works[0]["industry"] == "01"
    assert works[0]["industryName"] == "互联网/电子商务"

    # 5. 项目经历
    projects = transformed["projects"]["current_value"]
    assert len(projects) == 1
    assert projects[0]["projectName"] == "智能求职助手平台"
    assert projects[0]["company"] == "上海某某科技有限公司"

    # 6. 教育经历
    educations = transformed["educations"]["current_value"]
    assert len(educations) == 1
    assert educations[0]["schoolName"] == "同济大学"
    assert educations[0]["majorName"] == "软件工程"
    assert educations[0]["studyType"] == "全日制"

    # 7. 语言能力与证书合并（按语种分桶，不交叉污染）
    langs = transformed["language"]["current_value"]
    assert len(langs) == 2
    assert langs[0]["certifications"] == ["cet6"]
    assert langs[0]["certificationDetails"][0]["code"] == "cet6"
    assert langs[1]["certifications"] == ["jlpt1"]

    # 8. 专业技能
    skills = transformed["skills"]["current_value"]
    assert len(skills) == 1
    assert skills[0]["skillName"] == "Python"

    # 9. 证书
    certs = transformed["certifications"]["current_value"]
    assert len(certs) == 1
    assert certs[0]["certString"] == "PMP项目管理专业人士资格认证"


def test_transform_data_empty_fallbacks():
    """验证空数据与非全日制教育经历的容错处理"""
    empty_raw = {
        "accountInfo": {},
        "selfIntroduction": None,
        "intentions": [],
        "works": [],
        "projects": [],
        "educations": [
            {
                "schoolName": "某培训学校",
                "isFullTime": False,
                "complete": True,
                "majorString": "计算机网络",
            },
            {
                "complete": False,  # 未完成且无校名的脏条目应该被过滤
                "schoolName": "",
            }
        ],
    }
    transformed = transform_data(empty_raw)
    assert transformed["self_introduction"]["current_value"] == {"selfIntroduction": ""}
    assert transformed["intentions"]["current_value"] == []
    edus = transformed["educations"]["current_value"]
    assert len(edus) == 1
    assert edus[0]["studyType"] == "非全日制"
    assert edus[0]["majorName"] == "计算机网络"


def test_save_data_rejects_empty_and_backs_up(monkeypatch, tmp_path):
    """统一安全落盘：空数据拒绝写入、正常数据覆盖前自动备份、原子替换"""
    import pytest as _pytest
    from resume_editor.platforms.browser_common import save_fields_json

    test_file = tmp_path / "51job_fields.json"
    monkeypatch.setattr("resume_editor.platforms.job51_collector.OUTPUT_PATH", str(test_file))
    monkeypatch.setattr("resume_editor.platforms.job51_collector.DATA_DIR", str(tmp_path))

    # 1. 空数据（全空模块）在首次写入时即被拒绝
    empty_data = {
        f"mod_{i}": {"label": f"Module {i}", "current_value": ""}
        for i in range(6)
    }
    with _pytest.raises(RuntimeError, match="近乎为空"):
        save_data(empty_data)
    assert not test_file.exists(), "空数据不应产生文件"

    # 2. 正常数据写入成功
    full_data = {
        f"mod_{i}": {"label": f"Module {i}", "current_value": {"k": f"v{i}"}}
        for i in range(8)
    }
    save_data(full_data)
    with open(test_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert len(saved) == 8

    # 3. 再次写入（模拟官网数据更新）：覆盖为官网现状，旧数据自动备份
    new_data = {
        f"mod_{i}": {"label": f"Module {i}", "current_value": {"k": f"new_v{i}"}}
        for i in range(8)
    }
    save_data(new_data)
    with open(test_file, "r", encoding="utf-8") as f:
        replaced = json.load(f)
    assert replaced["mod_0"]["current_value"]["k"] == "new_v0"

    snapshots = list((tmp_path / "snapshots").glob("51job_collect_*.bak.json"))
    assert len(snapshots) == 1, "覆盖前应自动备份一份旧数据"
    with open(snapshots[0], "r", encoding="utf-8") as f:
        bak = json.load(f)
    assert bak["mod_0"]["current_value"]["k"] == "v0", "备份内容应为覆盖前的旧数据"

    # 4. 二次采集后的空数据同样被拦截，且好数据不被破坏
    with _pytest.raises(RuntimeError, match="近乎为空"):
        save_data(empty_data)
    with open(test_file, "r", encoding="utf-8") as f:
        intact = json.load(f)
    assert intact["mod_0"]["current_value"]["k"] == "new_v0", "空数据拦截后本地数据保持完好"
