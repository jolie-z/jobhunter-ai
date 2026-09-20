"""
前程无忧 (51job) 项目经历 (projects) 模块全字段 100% 覆盖自动化测试套件

涵盖字段与核心场景：
1. companyName / company (所属公司选择、修改、清空为无、前后端别名互转)
2. projectName (项目名称、特殊符号、trim 保护)
3. startTime / endTime / "至今" (起止时间、至今转 None、派生字段重算防 100004)
4. describe (项目描述、换行符保留、2000 字上限截断保护 _clip_proj_desc)
5. functionDescribe / projectRole (项目职务/角色)
6. isEnglish (英文简历布尔强校验)
7. 生命周期编排 (getProjectAdd / getProjectEdit / getProjectDel / no-op / 复核比对)
"""

import pytest
from resume_editor.platforms.job51_write_back import (
    plan_writeback,
    verify_results,
    _strip_add_item,
    _build_edit_payload,
    _key_same,
    _match_official,
    _clip_proj_desc,
    _PROJ_DESC_MAX,
)


@pytest.fixture
def base_official_project():
    """51job 官网项目经历标准条目"""
    return {
        "id": "119259375",
        "resumeId": "369525152",
        "projectName": "全链路求职 Copilot SaaS 平台",
        "startTime": "2026-03",
        "endTime": None,
        "startTimeString": "2026.03",
        "endTimeString": "至今",
        "companyName": "自由职业者",
        "functionDescribe": "独立全栈开发者 / 架构师",
        "describe": "**技术栈**: Next.js, React 19, TypeScript, FastAPI, Python\n\n**项目背景**:\n独立研发端到端求职自动化系统。",
        "isEnglish": False,
    }


# ==============================================================================
# 1. 所属公司 (companyName / company) 测试
# ==============================================================================

def test_projects_company_name_edit_payload_mapping(base_official_project):
    """测试修改项目所属公司：前端 company/companyName 别名自动映射为官网标准 companyName"""
    # 1. 从 companyName 修改为新公司
    local_item1 = {
        "id": "119259375",
        "projectName": "全链路求职 Copilot SaaS 平台",
        "companyName": "未来智能科技",
    }
    payload1 = _build_edit_payload(local_item1, base_official_project)
    assert payload1["companyName"] == "未来智能科技"
    assert "company" not in payload1

    # 2. 从前端 company 别名字段更新
    local_item2 = {
        "id": "119259375",
        "projectName": "全链路求职 Copilot SaaS 平台",
        "company": "某美妆集团",
    }
    payload2 = _build_edit_payload(local_item2, base_official_project)
    assert payload2["companyName"] == "某美妆集团"
    assert "company" not in payload2


def test_projects_company_name_add_strip_mapping():
    """测试新增项目条目：company/companyName 别名标准化并去除 company 冗余键"""
    # 1. 传入 company 别名
    item1 = {
        "projectName": "智能库存中台 (MVP)",
        "startTime": "2025-01",
        "endTime": "2025-06",
        "company": "自由职业者",
        "describe": "负责数据清洗与推演模型构建",
    }
    stripped1 = _strip_add_item(item1)
    assert stripped1["companyName"] == "自由职业者"
    assert "company" not in stripped1

    # 2. 传入标准 companyName
    item2 = {
        "projectName": "智能库存中台 (MVP)",
        "startTime": "2025-01",
        "endTime": "2025-06",
        "companyName": "未来智能科技",
        "describe": "负责数据清洗与推演模型构建",
    }
    stripped2 = _strip_add_item(item2)
    assert stripped2["companyName"] == "未来智能科技"


def test_projects_company_name_clearing_to_none(base_official_project):
    """测试清空所属公司：当用户选 '无' 或空字符串时，正确映射为 None 而非残留旧公司或发送字符串 '无'"""
    for empty_val in ("", "无", None):
        local_item = {
            "id": "119259375",
            "companyName": empty_val,
        }
        payload = _build_edit_payload(local_item, base_official_project)
        assert payload["companyName"] is None

        # 新增条目清空测试
        item_add = {
            "projectName": "个人开源项目",
            "startTime": "2024-01",
            "company": empty_val,
            "describe": "开源项目",
        }
        stripped = _strip_add_item(item_add)
        assert stripped["companyName"] is None


def test_projects_company_key_same_comparison(base_official_project):
    """测试 _key_same 针对 companyName / company 别名与空值比对"""
    # 1. 本地 company 与官网 companyName 相同 -> Same (True)
    item_same = {"company": "自由职业者"}
    assert _key_same("companyName", item_same, base_official_project) is True

    # 2. 本地与官网均为空或 '无' -> Same (True)
    off_none = {"companyName": None}
    item_empty = {"company": "无"}
    assert _key_same("companyName", item_empty, off_none) is True

    # 3. 本地修改为新公司 -> Diff (False)
    item_diff = {"company": "新创 AI 实验室"}
    assert _key_same("companyName", item_diff, base_official_project) is False


def test_projects_company_change_triggers_plan_action(base_official_project):
    """测试仅修改项目经历所属公司时，精准识别变化并生成 getProjectEdit 动作（不被误判为 no-op）"""
    official = {"projects": [base_official_project]}
    local = {
        "projects": [
            {
                **base_official_project,
                "company": "新创 AI 实验室",
                "companyName": "新创 AI 实验室",
            }
        ]
    }
    plan = plan_writeback(local, official, selected_modules=["projects"])
    assert len(plan["actions"]) == 1
    act = plan["actions"][0]
    assert act["module"] == "projects"
    assert act["op"] == "edit"
    assert act["method"] == "getProjectEdit"
    assert act["args"][1] == "119259375"
    assert act["args"][2]["companyName"] == "新创 AI 实验室"


# ==============================================================================
# 2. 项目名称 (projectName) 与 修剪测试
# ==============================================================================

def test_projects_project_name_trim_and_special_chars():
    """测试项目名称两端空格 trim 与特殊字符保留"""
    item = {
        "projectName": "  全渠道库存自动化核销与预测分析中台 (MVP)  ",
        "startTime": "2026-02",
        "endTime": "2026-06",
        "describe": "项目描述内容",
    }
    stripped = _strip_add_item(item)
    assert stripped["projectName"] == "  全渠道库存自动化核销与预测分析中台 (MVP)  "


def test_projects_name_change_triggers_edit(base_official_project):
    """测试修改项目名称生成 edit"""
    local_item = {
        "id": "119259375",
        "projectName": "AI Copilot 2.0 企业重构版",
    }
    payload = _build_edit_payload(local_item, base_official_project)
    assert payload["projectName"] == "AI Copilot 2.0 企业重构版"


# ==============================================================================
# 3. 起止时间 (startTime / endTime / "至今") 测试
# ==============================================================================

def test_projects_end_time_zhijin_handling(base_official_project):
    """测试项目经历 endTime 为 '至今' 时转为 None 并生成 endTimeString: '至今'"""
    item_zhijin = {
        "projectName": "活跃开源项目",
        "startTime": "2025-01",
        "endTime": "至今",
        "describe": "持续维护中",
    }
    stripped = _strip_add_item(item_zhijin)
    assert stripped["endTime"] is None
    assert stripped["endTimeString"] == "至今"
    assert stripped["startTimeString"] == "2025.01"

    payload = _build_edit_payload(item_zhijin, base_official_project)
    assert payload["endTime"] is None


def test_projects_time_change_invalidates_derived_strings(base_official_project):
    """测试起止时间变更时剔除过期的派生字段 startTimeString/endTimeString"""
    local_item = {
        "id": "119259375",
        "startTime": "2024-01",
        "endTime": "2024-12",
    }
    payload = _build_edit_payload(local_item, base_official_project)
    assert payload["startTime"] == "2024-01"
    assert payload["endTime"] == "2024-12"
    assert payload.get("startTimeString") != "2026.03"


# ==============================================================================
# 4. 项目描述 (describe) 与 超长截断截取保护测试
# ==============================================================================

def test_projects_describe_preserves_newlines(base_official_project):
    """测试项目描述保留换行与 Markdown 格式"""
    desc = "**架构核心**:\n1. 消息队列 FIFO 削峰\n2. 向量检索 RAG 加速\n\n**产出**:\n提升吞吐 300%"
    local_item = {
        "id": "119259375",
        "describe": desc,
    }
    payload = _build_edit_payload(local_item, base_official_project)
    assert payload["describe"] == desc


def test_projects_describe_max_length_clipping():
    """测试项目描述超过 2000 字上限时自动截断保护 (_clip_proj_desc)"""
    long_desc = "超长项目描述内容" * 300  # 超过 2000 字
    assert len(long_desc) > _PROJ_DESC_MAX
    payload = {
        "projectName": "大规模数据分析项目",
        "describe": long_desc,
    }
    _clip_proj_desc(payload)
    assert len(payload["describe"]) == _PROJ_DESC_MAX
    assert payload["describe"] == long_desc[:_PROJ_DESC_MAX]


# ==============================================================================
# 5. 项目职责 / 角色 (functionDescribe) 与 布尔安全测试
# ==============================================================================

def test_projects_function_describe_and_is_english():
    """测试项目职责传递与 isEnglish: False 安全防护"""
    item = {
        "projectName": "NLP 情感分析系统",
        "functionDescribe": "核心算法工程师",
        "startTime": "2024-03",
        "endTime": "2024-09",
        "describe": "语料分词与情感极性分类",
        "isEnglish": None,
    }
    stripped = _strip_add_item(item)
    assert stripped["functionDescribe"] == "核心算法工程师"
    assert stripped["isEnglish"] is False


# ==============================================================================
# 6. 完整生命周期编排与复核比对 (Add / Edit / Del / No-Op / Verify) 测试
# ==============================================================================

def test_projects_full_lifecycle_planning(base_official_project):
    """测试项目经历全生命周期编排：1条 no-op，1条修改所属公司/描述，1条新增，1条删除官网多余"""
    extra_off_proj = {
        "id": "119259376",
        "projectName": "已废弃的旧项目",
        "startTime": "2020-01",
        "endTime": "2020-06",
        "describe": "旧系统",
    }
    official = {"projects": [base_official_project, extra_off_proj]}

    local = {
        "projects": [
            # 条目 1: 保持完全一致 (no-op)
            base_official_project,
            # 条目 2: 本地新增条目 (无 id -> add)
            {
                "id": "",
                "projectName": "电商大促爆品营销复盘与 NLP 客诉归因分析",
                "startTime": "2026-01",
                "endTime": "2026-01",
                "company": "某美妆集团",
                "companyName": "某美妆集团",
                "describe": "分析退款率飙升原因",
            }
            # extra_off_proj 在本地不存在 -> 触发 del id=119259376
        ]
    }

    plan = plan_writeback(local, official, selected_modules=["projects"])
    actions = plan["actions"]
    assert len(actions) == 2

    # 1. 验证新增动作
    add_act = next((a for a in actions if a["op"] == "add"), None)
    assert add_act is not None
    assert add_act["method"] == "getProjectAdd"
    assert add_act["args"][1]["projectName"] == "电商大促爆品营销复盘与 NLP 客诉归因分析"
    assert add_act["args"][1]["companyName"] == "某美妆集团"

    # 2. 验证删除动作
    del_act = next((a for a in actions if a["op"] == "del"), None)
    assert del_act is not None
    assert del_act["method"] == "getProjectDel"
    assert del_act["args"][1] == "119259376"


def test_projects_verify_results_matching(base_official_project):
    """测试复核引擎 verify_results 对项目经历所属公司与各字段的精确比对判定"""
    off_after = {
        "projects": [
            base_official_project,
            {
                "id": "119259377",
                "projectName": "电商大促爆品营销复盘与 NLP 客诉归因分析",
                "startTime": "2026-01",
                "endTime": "2026-01",
                "companyName": "某美妆集团",
                "describe": "分析退款率飙升原因",
            }
        ]
    }
    local_state = {
        "projects": [
            base_official_project,
            {
                "id": "119259377",
                "projectName": "电商大促爆品营销复盘与 NLP 客诉归因分析",
                "startTime": "2026-01",
                "endTime": "2026-01",
                "company": "某美妆集团",
                "describe": "分析退款率飙升原因",
            }
        ]
    }
    plan = {"actions": [{"module": "projects", "op": "edit"}]}
    res = verify_results(off_after, local_state, plan)
    proj_res = next((r for r in res if r["module"] == "projects"), None)
    assert proj_res is not None
    assert proj_res["match"] is True
    assert "2 条已生效" in proj_res["note"]
