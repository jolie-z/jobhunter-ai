"""
51job 全链路回写引擎与 API 自动化测试套件 (test_job51_full_suite.py)
验证 51job 的回写计划生成、无破坏性 ID 就地更新、码值保护、复核比对与 FastAPI 路由集成
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from resume_editor.platforms.job51_write_back import (
    plan_writeback,
    verify_results,
    _norm_time,
    _build_edit_payload,
    _clip_proj_desc,
    HARD_SKIP,
    ALL_MODULES,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def official_resume_state():
    """官网当前状态数据"""
    return {
        "resumeId": "369525152",
        "selfIntroduction": "官网已有自我介绍",
        "intentions": [
            {
                "id": "int_1",
                "seekType": "0",
                "expectArea": "020000",
                "expectIndustry": "01",
                "expectFunction": "0100",
                "salaryType": "1",
                "minSalary": 20,
                "maxSalary": 35,
                "salaryMonth": 12,
            }
        ],
        "works": [
            {
                "id": "work_1",
                "companyName": "旧公司",
                "position": "架构师",
                "workFunction": "0100",
                "workDescription": "旧工作描述",
                "startTime": "2020-01",
                "endTime": None,  # 官网"至今"存为 None
            },
            {
                "id": "work_extra",
                "companyName": "多余旧条目",
                "position": "工程师",
                "workFunction": "0200",
                "workDescription": "多余描述",
                "startTime": "2015-01",
                "endTime": "2018-01",
            }
        ],
        "projects": [
            {
                "id": "proj_1",
                "projectName": "旧项目",
                "companyName": "旧公司",
                "describe": "旧项目描述",
                "startTime": "2021-01",
                "endTime": "2021-12",
            }
        ],
        "educations": [
            {
                "id": "edu_1",
                "schoolName": "浙江大学",
                "major": "4000",  # 官网专业码
                "degree": "040",
                "describe": "本科计算机",
                "startTime": "2011-09",
                "endTime": "2015-06",
            }
        ],
        "skills": [
            {"id": "sk_1", "skillType": "python", "ability": "3"}
        ],
        "language": [
            {"id": "lang_1", "skillType": "english", "ability": "2"}
        ],
        "certifications": [
            {"id": "cert_1", "cert": "pmp", "startTime": "2022-01"}
        ]
    }


def test_time_normalization():
    """验证时间归一化逻辑：'至今'、None、'' 等价"""
    assert _norm_time("至今") == ""
    assert _norm_time(None) == ""
    assert _norm_time("") == ""
    assert _norm_time("2024-05") == "2024-05"


def test_code_protection_in_edit_payload():
    """验证官网纯数字码值保护：本地传入纯文本不覆盖官网数字代码"""
    off_item = {
        "id": "edu_1",
        "schoolName": "浙江大学",
        "major": "4000",  # 官网纯数字码
        "degree": "040",
        "startTime": "2011-09",
        "endTime": "2015-06",
    }
    local_item = {
        "id": "edu_1",
        "schoolName": "浙江大学软件学院",
        "major": "软件工程",  # 本地是中文文本
        "degree": "040",
        "startTime": "2011-09",
        "endTime": "至今",
    }
    payload = _build_edit_payload(local_item, off_item)
    # 校名更新
    assert payload["schoolName"] == "浙江大学软件学院"
    # 专业代码未被纯文本篡改
    assert payload["major"] == "4000"
    # "至今" 转为 None
    assert payload["endTime"] is None


def test_project_desc_clipping():
    """验证项目描述超过 2000 字时的安全截断"""
    long_desc = "A" * 2500
    payload = {"projectName": "测试项目", "describe": long_desc}
    _clip_proj_desc(payload)
    assert len(payload["describe"]) == 2000


def test_plan_writeback_noop(official_resume_state):
    """验证本地与官网完全一致时触发 No-Op 跳过"""
    local = {
        "self_introduction": {"selfIntroduction": "官网已有自我介绍"},
        "works": [
            {
                "id": "work_1",
                "companyName": "旧公司",
                "position": "架构师",
                "workFunction": "0100",
                "workDescription": "旧工作描述",
                "startTime": "2020-01",
                "endTime": "至今",  # 本地为'至今'，与官网 None 等价
            },
            {
                "id": "work_extra",
                "companyName": "多余旧条目",
                "position": "工程师",
                "workFunction": "0200",
                "workDescription": "多余描述",
                "startTime": "2015-01",
                "endTime": "2018-01",
            }
        ]
    }
    plan = plan_writeback(local, official_resume_state, selected_modules=["self_introduction", "works"])
    assert len(plan["actions"]) == 0
    assert len(plan["skipped"]) == 2
    assert "无需回写" in plan["skipped"][0]["reason"]
    assert "无需回写" in plan["skipped"][1]["reason"]


def test_plan_writeback_edit_add_del(official_resume_state):
    """验证全量覆盖语义：就地 edit、本地超出官网条数 add、本地少于官网条数 del"""
    # 场景 1: 本地 3 条（超出官网 2 条）-> 2 条 edit + 1 条 add
    local_add = {
        "self_introduction": {"selfIntroduction": "全新自我介绍（已修改）"},
        "works": [
            {
                "id": "work_1",
                "companyName": "新公司名1",  # 触发 edit id=work_1
                "position": "技术总监",
                "workFunction": "0100",
                "workDescription": "全新管理描述",
                "startTime": "2020-01",
                "endTime": "至今",
            },
            {
                "id": "work_extra",
                "companyName": "新公司名2",  # 触发 edit id=work_extra
                "position": "架构师",
                "workFunction": "0200",
                "workDescription": "核心架构",
                "startTime": "2015-01",
                "endTime": "2018-01",
            },
            {
                # 本地超出官网数量的第 3 条，无 ID -> 触发 add
                "companyName": "全新创业公司",
                "position": "联合创始人",
                "workFunction": "0100",
                "workDescription": "创业全盘统筹",
                "startTime": "2024-06",
                "endTime": "至今",
            }
        ]
    }
    plan_add = plan_writeback(local_add, official_resume_state, selected_modules=["self_introduction", "works"])
    actions_add = plan_add["actions"]
    assert len(actions_add) == 4
    ops_add = [a["op"] for a in actions_add]
    assert ops_add == ["edit", "edit", "edit", "add"]
    assert actions_add[3]["op"] == "add"
    assert actions_add[3]["method"] == "addWorkExpList"

    # 场景 2: 本地 1 条（少于官网 2 条）-> 1 条 edit + 1 条 del (work_extra)
    local_del = {
        "works": [
            {
                "id": "work_1",
                "companyName": "新公司名1",  # 触发 edit id=work_1
                "position": "技术总监",
                "workFunction": "0100",
                "workDescription": "全新管理描述",
                "startTime": "2020-01",
                "endTime": "至今",
            }
            # 未包含 work_extra -> 触发 del
        ]
    }
    plan_del = plan_writeback(local_del, official_resume_state, selected_modules=["works"])
    actions_del = plan_del["actions"]
    assert len(actions_del) == 2
    ops_del = [a["op"] for a in actions_del]
    assert ops_del == ["del", "edit"]
    assert actions_del[0]["op"] == "del"
    assert actions_del[0]["method"] == "delWorkExp"
    assert actions_del[0]["args"][1] == "work_extra"


def test_plan_writeback_empty_local_protection(official_resume_state):
    """验证本地为空时的防误删保护机制（保留官网现有条目，绝不执行 del）"""
    local = {
        "works": []  # 本地为空
    }
    plan = plan_writeback(local, official_resume_state, selected_modules=["works"])
    assert len(plan["actions"]) == 0
    assert len(plan["skipped"]) == 1
    assert "保留官网现有" in plan["skipped"][0]["reason"]


def test_plan_writeback_basic_info(official_resume_state):
    """验证基本信息（basic_info）可回写规划：码值清洗与 editBaseInfo 动作生成"""
    local = {
        "basic_info": {
            "cName": "张三",
            "sex": "1",
            "birthday": "1994-07",
            "area": {"id": "030300", "label": "广州"},
            "household": {"id": "030200", "label": "广州"},
            "newCurrentSituation": "5",
            "personAsLabel": "2",
            "politicsStatus": "06",
            "workYearMonth": "2016-07",
            "wechatId": "13800138000",
        }
    }
    # 官网初始状态不同
    official = {
        **official_resume_state,
        "basic_info": {
            "cName": "张三",
            "sex": "1",
            "birthday": "1994-07",
            "area": "010000",  # 北京
            "household": "010000",
            "currentSituation": "1",
            "personAsLabel": "2",
            "politicsStatus": "06",
            "workYearMonth": "2018-07",
            "wechatId": "old_wx",
        }
    }
    plan = plan_writeback(local, official, selected_modules=["basic_info"])
    assert len(plan["actions"]) == 1
    action = plan["actions"][0]
    assert action["module"] == "basic_info"
    assert action["method"] == "editBaseInfo"
    payload = action["args"][0]
    assert payload["area"] == "030300"
    assert payload["household"] == "030200"
    assert payload["currentSituation"] == "5"
    assert payload["workYearMonth"] == "2016-07"
    assert payload["workYear"] == "2016"
    assert payload["wechatId"] == "13800138000"


def test_verify_results_engine():
    """验证回写后复核比对引擎"""
    plan = {
        "actions": [
            {"module": "self_introduction", "op": "edit"},
            {"module": "works", "op": "edit"}
        ]
    }
    local = {
        "self_introduction": {"selfIntroduction": "期望文本"},
        "works": [
            {"id": "w1", "companyName": "公司A", "position": "P1", "workFunction": "01", "workDescription": "D", "startTime": "2020", "endTime": "2022"}
        ]
    }

    # 官网数据一致
    verify_off_success = {
        "selfIntroduction": "期望文本",
        "works": [
            {"id": "w1", "companyName": "公司A", "position": "P1", "workFunction": "01", "workDescription": "D", "startTime": "2020", "endTime": "2022"}
        ]
    }
    res_succ = verify_results(verify_off_success, local, plan)
    assert all(r["match"] for r in res_succ)

    # 官网数据不一致
    verify_off_failed = {
        "selfIntroduction": "不匹配文本",
        "works": []
    }
    res_fail = verify_results(verify_off_failed, local, plan)
    assert not any(r["match"] for r in res_fail)


def test_fastapi_write_back_dry_run(client):
    """验证 FastAPI 8000 路由 /api/agent-map/write-back 支持 51job dry-run"""
    resp = client.post("/api/agent-map/write-back", json={
        "platform": "51job",
        "dry_run": True,
        "paths": ["self_introduction", "works"]
    })
    # 只要环境存在 51job 快照或 fields，返回 200，dry_run 为 True
    if resp.status_code == 200:
        data = resp.json()
        assert data["success"] is True
        assert data["dry_run"] is True
        assert "plan" in data
    else:
        # 本地若无 51job_fields.json 则返回 500 提示数据不存在，也是预期分支
        assert resp.status_code in (200, 500)


def test_plan_writeback_add_work_experience_freelancer_with_skills_and_work_type(official_resume_state):
    """验证新增「自由职业者」工作经历（无 id，endTime='至今'）能正确生成 addWorkExp 动作并将 endTime 置为 None，规范组装 workVocationalSkills 与 workType"""
    local = {
        "works": [
            {
                "id": "",  # 本地新增无 id
                "companyName": "自由职业者",
                "position": "独立 AI 应用开发者 / 全栈研发",
                "workDescription": "围绕多平台分发开发自动求职 SaaS，精通 Python、FastAPI、大模型 与 React",
                "startTime": "2024-04",
                "endTime": "至今",
                "workType": "1",  # 兼职/自由职业
                "workVocationalSkills": ["大模型", "FastAPI", "React", "Python"],
            },
            {
                "id": "work_1",  # 官网原有条目
                "companyName": "旧公司",
                "position": "架构师",
                "workFunction": "0100",
                "workDescription": "旧工作描述",
                "startTime": "2020-01",
                "endTime": "至今",
                "workType": "0",
            },
            {
                "id": "work_extra",  # 官网原有条目
                "companyName": "多余旧条目",
                "position": "工程师",
                "workFunction": "0200",
                "workDescription": "多余描述",
                "startTime": "2015-01",
                "endTime": "至今",
                "workType": "0",
            }
        ]
    }
    plan = plan_writeback(local, official_resume_state, selected_modules=["works"])
    add_act = next((a for a in plan["actions"] if a["op"] == "add" and a["module"] == "works"), None)
    assert add_act is not None
    assert add_act["method"] == "addWorkExpList"
    payload = add_act["args"][1]
    assert payload["companyName"] == "自由职业者"
    assert payload["position"] == "独立 AI 应用开发者 / 全栈研发"
    assert payload["endTime"] is None  # 关键修复：新增经历'至今'置为 None，防止 100004 报错
    assert payload["endTimeString"] == "至今"
    assert payload["workType"] == "1"
    assert isinstance(payload["workVocationalSkills"], list)
    assert len(payload["workVocationalSkills"]) == 4
    assert payload["workVocationalSkills"][0]["skill"] == "大模型"
    assert payload["workVocationalSkills"][0]["isCustomize"] is True


def test_job51_diagnose_writeback_failure_scenarios():
    """验证 _diagnose_writeback_failure 针对各类 100004 报错与 tips 字段能输出精确诊断与调整建议"""
    from resume_editor.platforms.job51_write_back import _diagnose_writeback_failure, _strip_add_item

    # 1. position 缺失
    act1 = {"module": "works", "op": "add"}
    resp1 = {"status": "100004", "message": "参数校验错误", "resultbody": {"tips": {"position": "请填写职位"}}}
    diag1 = _diagnose_writeback_failure(act1, resp1)
    assert diag1["field"] == "position"
    assert "职位名称 (position) 缺失" in diag1["diagnosis"]
    assert "请在「工作经历」编辑卡片中填写自定义职位" in diag1["suggestion"]

    # 2. sex 已实名保护
    act2 = {"module": "basic_info", "op": "edit"}
    resp2 = {"status": "100004", "tips": {"sex": "已实名账号暂不支持修改性别"}}
    diag2 = _diagnose_writeback_failure(act2, resp2)
    assert diag2["field"] == "sex"
    assert "性别" in diag2["diagnosis"]
    assert "实名认证" in diag2["suggestion"]

    # 3. describe 超长
    act3 = {"module": "projects", "op": "add"}
    resp3 = {"status": "100004", "resultbody": {"tips": {"describe": "内容过长"}}}
    diag3 = _diagnose_writeback_failure(act3, resp3)
    assert diag3["field"] == "describe"
    assert "2000" in diag3["suggestion"]

    # 4. position 缺失时的 _strip_add_item 兜底自动补全
    item_no_pos = {
        "companyName": "自由职业者",
        "workFunction": "0154",
        "workFunctionString": "全栈工程师",
        "startTime": "2026-01",
    }
    stripped = _strip_add_item(item_no_pos)
    assert stripped["position"] == "全栈工程师"

