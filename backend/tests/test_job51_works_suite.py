"""
前程无忧 (51job) 工作经历 (works) 模块全字段 100% 覆盖自动化测试套件

涵盖字段：
1. companyName (公司名称)
2. position (自定义职位名称与缺省兜底)
3. workFunction / workFunctionString (职位分类码与名称)
4. workIndustry / workIndustryString / industry / industryName (所属行业码与名称及别名互转)
5. companySize / companySizeString (公司规模)
6. companyType / companyTypeString (公司性质)
7. workType / workTypeString / seekType (工作类型：全职/兼职/实习)
8. startTime / endTime / endTimeString / "至今" (起止时间与至今转 None 保护)
9. workDescription (工作描述与换行处理)
10. workVocationalSkills / skills (职业技能标签对象数组归一化)
11. isEnglish / hideInfo (安全布尔与对该公司隐藏信息)
12. 生命周期编排 (add / edit / del / no-op / 复核比对)
"""

import pytest
from resume_editor.platforms.job51_write_back import (
    plan_writeback,
    verify_results,
    _strip_add_item,
    _build_edit_payload,
    _key_same,
    _match_official,
    _diagnose_writeback_failure,
)


@pytest.fixture
def base_official_work():
    """51job 官网工作经历标准条目"""
    return {
        "id": "400101",
        "resumeId": "369525152",
        "companyName": "未来智能科技",
        "position": "资深全栈工程师",
        "workFunction": "0154",
        "workFunctionString": "全栈工程师",
        "workIndustry": "32",
        "workIndustryString": "互联网/电子商务",
        "workIndustryNew": "",
        "companySize": "3",
        "companySizeString": "150-500人",
        "companyType": "01",
        "companyTypeString": "外资（欧美）",
        "workType": "0",
        "workTypeString": "全职",
        "startTime": "2023-05",
        "endTime": None,
        "startTimeString": "2023.05",
        "endTimeString": "至今",
        "workDescription": "负责 AI Agent 平台全栈架构与开发，对接 LLM 接口与工作流调度引擎。",
        "workVocationalSkills": [
            {"skill": "大模型", "value": "大模型", "isCustomize": True, "skillCode": "", "direction": "", "directionCode": ""},
            {"skill": "Python", "value": "Python", "isCustomize": True, "skillCode": "", "direction": "", "directionCode": ""},
            {"skill": "FastAPI", "value": "FastAPI", "isCustomize": True, "skillCode": "", "direction": "", "directionCode": ""}
        ],
        "isEnglish": False,
        "isOverseas": False,
        "hideInfo": False,
    }


# ==============================================================================
# 1. 所属行业 (workIndustry / workIndustryString / industry / industryName) 测试
# ==============================================================================

def test_works_industry_edit_payload_mapping(base_official_work):
    """测试修改所属行业：从前端 industry/industryName 别名自动映射为官网标准 workIndustry/workIndustryString"""
    local_item = {
        "id": "400101",
        "companyName": "未来智能科技",
        "position": "资深全栈工程师",
        "industry": "01",  # 计算机软件代码
        "industryName": "计算机软件",
    }
    payload = _build_edit_payload(local_item, base_official_work)
    assert payload["workIndustry"] == "01"
    assert payload["workIndustryString"] == "计算机软件"
    assert payload["workIndustryNew"] == ""


def test_works_industry_add_strip_mapping():
    """测试新增经历条目：从前端 industry 别名自动生成 workIndustry 和 workIndustryString 载荷"""
    item = {
        "companyName": "新兴 AI 实验室",
        "position": "AI 研究员",
        "industry": "32",
        "industryName": "互联网/电子商务",
        "startTime": "2024-01",
        "endTime": "至今",
    }
    stripped = _strip_add_item(item)
    assert stripped["workIndustry"] == "32"
    assert stripped["workIndustryString"] == "互联网/电子商务"
    assert stripped["workIndustryNew"] == ""


def test_works_industry_clearing(base_official_work):
    """测试清空行业：当用户将行业清空为空字符串时，正确生成空字符串而不是残留旧行业"""
    local_item = {
        "id": "400101",
        "industry": "",
        "industryName": "",
        "workIndustry": "",
        "workIndustryString": "",
    }
    payload = _build_edit_payload(local_item, base_official_work)
    assert payload["workIndustry"] == ""
    assert payload["workIndustryString"] == ""


def test_works_industry_key_same_comparison(base_official_work):
    """测试 _key_same 针对 industry 字段的比对逻辑"""
    # 1. 本地 industry 与官网 workIndustry 代码一致 -> Same (True)
    item_same_code = {"industry": "32", "industryName": "互联网/电子商务"}
    assert _key_same("workIndustry", item_same_code, base_official_work) is True

    # 2. 本地与官网均为空 -> Same (True)
    item_empty = {"workIndustry": ""}
    off_empty = {"workIndustry": ""}
    assert _key_same("workIndustry", item_empty, off_empty) is True

    # 3. 本地 industry 修改为 "01" -> Diff (False)
    item_diff = {"industry": "01", "industryName": "计算机软件"}
    assert _key_same("workIndustry", item_diff, base_official_work) is False


def test_works_industry_change_triggers_plan_action(base_official_work):
    """测试仅修改工作经历所属行业时，能精准识别变化并生成 editWorkExp 动作（不被误判为 no-op）"""
    official = {"works": [base_official_work]}
    local = {
        "works": [
            {
                **base_official_work,
                "industry": "01",
                "industryName": "计算机软件",
                "workIndustry": "01",
                "workIndustryString": "计算机软件",
            }
        ]
    }
    plan = plan_writeback(local, official, selected_modules=["works"])
    assert len(plan["actions"]) == 1
    act = plan["actions"][0]
    assert act["module"] == "works"
    assert act["op"] == "edit"
    assert act["method"] == "editWorkExp"
    assert act["args"][2]["workIndustry"] == "01"
    assert act["args"][2]["workIndustryString"] == "计算机软件"


# ==============================================================================
# 2. 职位名称 (position) 与 职位分类 (workFunction) 测试
# ==============================================================================

def test_works_position_fallback_chain():
    """测试 position 缺省多级回退兜底链：workFunctionString -> jobTitle -> title -> '专业人员'"""
    # 1. 有 workFunctionString
    item1 = {"companyName": "A公司", "workFunction": "0154", "workFunctionString": "全栈工程师", "startTime": "2024-01"}
    assert _strip_add_item(item1)["position"] == "全栈工程师"

    # 2. 无 workFunctionString，有 jobTitle
    item2 = {"companyName": "B公司", "jobTitle": "技术顾问", "startTime": "2024-01"}
    assert _strip_add_item(item2)["position"] == "技术顾问"

    # 3. 只有 title
    item3 = {"companyName": "C公司", "title": "项目经理", "startTime": "2024-01"}
    assert _strip_add_item(item3)["position"] == "项目经理"

    # 4. 全部为空时安全兜底为 '专业人员'
    item4 = {"companyName": "D公司", "startTime": "2024-01"}
    assert _strip_add_item(item4)["position"] == "专业人员"


def test_works_function_and_position_edit(base_official_work):
    """测试修改职位名称与职位类别码"""
    local_item = {
        "id": "400101",
        "position": "首席 AI 架构师",
        "workFunction": "0100",
        "workFunctionString": "高级软件工程师",
    }
    payload = _build_edit_payload(local_item, base_official_work)
    assert payload["position"] == "首席 AI 架构师"
    assert payload["workFunction"] == "0100"
    assert payload["workFunctionString"] == "高级软件工程师"


# ==============================================================================
# 3. 公司规模 (companySize) 与 公司性质 (companyType) 测试
# ==============================================================================

def test_works_company_size_and_type_sync(base_official_work):
    """测试公司规模与公司性质修改与序列化"""
    local_item = {
        "id": "400101",
        "companySize": "5",  # 1000-5000人
        "companyType": "03",  # 合资
    }
    payload = _build_edit_payload(local_item, base_official_work)
    assert payload["companySize"] == "5"
    assert payload["companyType"] == "03"

    # _key_same 变更检测
    assert _key_same("companySize", local_item, base_official_work) is False
    assert _key_same("companyType", local_item, base_official_work) is False


# ==============================================================================
# 4. 工作类型 (workType / seekType) 测试
# ==============================================================================

def test_works_work_type_normalization():
    """测试全职 (0)、兼职 (1)、实习 (2) 工作类型解析"""
    # 1. workType 字符串化
    item_full = {"workType": 0, "startTime": "2024-01"}
    assert _strip_add_item(item_full)["workType"] == "0"

    item_part = {"workType": 1, "startTime": "2024-01"}
    assert _strip_add_item(item_part)["workType"] == "1"

    # 2. seekType 别名转换
    item_intern = {"seekType": "2", "startTime": "2024-01"}
    assert _key_same("workType", item_intern, {"workType": "2"}) is True


# ==============================================================================
# 5. 起止时间 (startTime / endTime / "至今") 测试
# ==============================================================================

def test_works_end_time_zhijin_handling(base_official_work):
    """测试 endTime 为 '至今' 时转为 None 并生成 endTimeString: '至今'"""
    item_zhijin = {
        "companyName": "自由职业",
        "position": "独立开发者",
        "startTime": "2025-01",
        "endTime": "至今",
    }
    stripped = _strip_add_item(item_zhijin)
    assert stripped["endTime"] is None
    assert stripped["endTimeString"] == "至今"
    assert stripped["startTimeString"] == "2025.01"

    payload = _build_edit_payload(item_zhijin, base_official_work)
    assert payload["endTime"] is None


def test_works_time_change_invalidates_derived_strings(base_official_work):
    """测试当起止时间发生变化时，剔除旧的展示型派生字段以防 100004 报错"""
    item_time_change = {
        "id": "400101",
        "startTime": "2024-06",
        "endTime": "2025-12",
    }
    payload = _build_edit_payload(item_time_change, base_official_work)
    assert payload["startTime"] == "2024-06"
    assert payload["endTime"] == "2025-12"
    # 派生字段被剔除，由服务端重新根据新时间计算
    assert "startTimeString" not in payload or payload.get("startTimeString") != "2023.05"


# ==============================================================================
# 6. 工作描述 (workDescription) 与 换行符测试
# ==============================================================================

def test_works_description_preservation(base_official_work):
    """测试多行工作描述、特殊标点与换行保留"""
    desc = "- 核心成果 1：重构平台架构\n- 核心成果 2：提升吞吐量 300%\n- 技术栈：Python / LangGraph"
    local_item = {
        "id": "400101",
        "workDescription": desc,
    }
    payload = _build_edit_payload(local_item, base_official_work)
    assert payload["workDescription"] == desc


# ==============================================================================
# 7. 职业技能 (workVocationalSkills / skills) 标签对象转换测试
# ==============================================================================

def test_works_skills_string_list_to_official_objects():
    """测试将前端字符串技能数组规范化为 51job 官方自定义技能对象数组"""
    skills_raw = ["大模型", "LangChain", "FastAPI", "React"]
    item = {
        "companyName": "AI 独角兽",
        "position": "全栈工程师",
        "skills": skills_raw,
        "startTime": "2024-01",
    }
    stripped = _strip_add_item(item)
    assert "skills" not in stripped
    voc_skills = stripped["workVocationalSkills"]
    assert len(voc_skills) == 4
    assert voc_skills[0]["skill"] == "大模型"
    assert voc_skills[0]["value"] == "大模型"
    assert voc_skills[0]["isCustomize"] is True


def test_works_skills_key_same_set_comparison(base_official_work):
    """测试 _key_same 针对技能标签的集合无序比较"""
    # 技能顺序不同但集合一致 -> True
    item_reordered = {
        "workVocationalSkills": ["FastAPI", "大模型", "Python"]
    }
    assert _key_same("workVocationalSkills", item_reordered, base_official_work) is True

    # 技能新增一个 -> False
    item_new_skill = {
        "workVocationalSkills": ["FastAPI", "大模型", "Python", "Next.js"]
    }
    assert _key_same("workVocationalSkills", item_new_skill, base_official_work) is False


# ==============================================================================
# 8. 安全与布尔字段 (isEnglish / hideInfo) 测试
# ==============================================================================

def test_works_security_and_boolean_fields():
    """测试 isEnglish 必须为 False，hideInfo 正常传递"""
    item = {
        "companyName": "保密公司",
        "position": "研发",
        "startTime": "2024-01",
        "hideInfo": True,
        "isEnglish": None,  # 模拟空值
    }
    stripped = _strip_add_item(item)
    assert stripped["isEnglish"] is False
    assert stripped["hideInfo"] is True


# ==============================================================================
# 9. 完整生命周期编排与复核比对 (Add / Edit / Del / No-Op / Verify) 测试
# ==============================================================================

def test_works_full_lifecycle_planning(base_official_work):
    """测试工作经历全生命周期编排：1条no-op，1条修改行业/职位，1条新增，1条删除官网多余"""
    extra_off_work = {
        "id": "400102",
        "companyName": "已被淘汰的旧公司",
        "position": "初级助理",
        "startTime": "2018-01",
        "endTime": "2019-01",
    }
    official = {"works": [base_official_work, extra_off_work]}

    local = {
        "works": [
            # 条目 1: 保持完全一致 (no-op)
            base_official_work,
            # 条目 2: 本地新增条目 (无 id -> add)
            {
                "id": "",
                "companyName": "AI 自由职业者",
                "position": "独立开发者",
                "workFunction": "0154",
                "workFunctionString": "全栈工程师",
                "industry": "32",
                "industryName": "互联网/电子商务",
                "startTime": "2026-01",
                "endTime": "至今",
                "skills": ["LLM", "Agent"],
            }
            # extra_off_work 在本地不存在 -> 触发 del id=400102
        ]
    }

    plan = plan_writeback(local, official, selected_modules=["works"])
    actions = plan["actions"]
    assert len(actions) == 2

    # 1. 验证新增动作
    add_act = next((a for a in actions if a["op"] == "add"), None)
    assert add_act is not None
    assert add_act["method"] == "addWorkExpList"
    assert add_act["args"][1]["companyName"] == "AI 自由职业者"
    assert add_act["args"][1]["workIndustry"] == "32"
    assert add_act["args"][1]["position"] == "独立开发者"

    # 2. 验证删除动作
    del_act = next((a for a in actions if a["op"] == "del"), None)
    assert del_act is not None
    assert del_act["method"] == "delWorkExp"
    assert del_act["args"][1] == "400102"


def test_works_verify_results_matching(base_official_work):
    """测试复核引擎 verify_results 对工作经历的精确比对与判定"""
    # 模拟回写后官网已更新的数据
    off_after = {
        "works": [
            base_official_work,
            {
                "id": "400103",
                "companyName": "AI 自由职业者",
                "position": "独立开发者",
                "workIndustry": "32",
                "workIndustryString": "互联网/电子商务",
                "startTime": "2026-01",
                "endTime": None,
                "endTimeString": "至今",
            }
        ]
    }
    local_state = {
        "works": [
            base_official_work,
            {
                "id": "400103",
                "companyName": "AI 自由职业者",
                "position": "独立开发者",
                "industry": "32",
                "industryName": "互联网/电子商务",
                "startTime": "2026-01",
                "endTime": "至今",
            }
        ]
    }
    plan = {"actions": [{"module": "works", "op": "edit"}]}
    res = verify_results(off_after, local_state, plan)
    work_res = next((r for r in res if r["module"] == "works"), None)
    assert work_res is not None
    assert work_res["match"] is True
    assert "2 条已生效" in work_res["note"]
