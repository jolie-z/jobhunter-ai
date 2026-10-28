"""
BOSS 平台确定性规则映射与降级兜底专项测试 (backend/tests/test_boss_rule_map.py)

验证目标（依据任务书 5.1 版 Phase 3 规范）：
1. 模块独立 import 与双向无序 import 零循环依赖自检 (GLM-P1-1)
2. 基础文本、个人优势、三大经历正常规则映射覆盖
3. 空数组不产出条目且记入 unfilled 断言 (GLM-P1-4)
4. 脏数据条目安全降级进 unfilled 断言 (GLM2-P2-3)
5. 主简历经历多于模板条目时未匹配项进 warnings 断言 (GLM2-P2-2)
6. 全部 path 合法性符合 flatten_schema 约束
7. 选项类字段全量归入 unfilled
8. selected_modules 模块过滤生效
9. BOSS 回写干跑兼容性：消费规则映射报告零 KeyError
10. map_platform 在 LLM 持续 429 下平滑降级至规则映射 (success=True)
11. BOSS_RULE_FALLBACK_ENABLED=false 时完整回滚至 LLM-only 硬失败
12. 路由级 POST /api/agent-map/generate 在 429 时 boss success=True 并落盘保存
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from unittest.mock import patch, MagicMock

import pytest

from resume_editor.agent_mapper import (
    map_platform,
    map_platform_rules,
    flatten_schema,
    is_boss_rule_fallback_enabled,
)
from resume_editor.rule_map_boss import rule_map_boss
from tests.helpers.fake_llm_gateway import FakeLLMClient


@pytest.fixture
def boss_gold_fields():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "boss_fields_sample.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def master_resume_fixture():
    return {
        "ok": True,
        "source": "feishu",
        "char_count": 1000,
        "record_id": "rec_test_001",
        "message": "读取成功",
        "name": "李四",
        "phone": "13900139000",
        "email": "lisi@example.com",
        "wechat": "wx_lisi",
        "summary": "资深全栈研发工程师，10年后端架构与大模型治理经验。",
        "experiences": [
            {
                "company": "字节跳动",
                "role": "首席后端架构师",
                "start": "2021-06",
                "end": "至今",
                "desc": "主导全仓 LLM 限流网关与分布式调度系统研发。",
            },
            {
                "company": "阿里巴巴",
                "role": "高级后端工程师",
                "start": "2018-07",
                "end": "2021-05",
                "desc": "负责电商交易核心系统高可用架构。",
            },
            {
                "company": "腾讯",
                "role": "后端开发工程师",
                "start": "2015-07",
                "end": "2018-06",
                "desc": "负责微信支付后台基础服务开发。",
            },
        ],
        "projects": [
            {
                "name": "多平台简历同步中心",
                "role": "架构师",
                "start": "2022-01",
                "end": "2022-12",
                "desc": "实现了四大招聘平台字段映射与自动化回写链路。",
            },
            {
                "name": "分布式流控网关",
                "role": "核心设计者",
                "start": "2023-01",
                "end": "至今",
                "desc": "基于令牌桶与滑动窗口的并发控制组件。",
            },
        ],
        "education": [
            {
                "school": "清华大学",
                "major": "软件工程",
                "degree": "硕士",
                "start": "2012-09",
                "end": "2015-07",
            },
            {
                "school": "浙江大学",
                "major": "计算机科学与技术",
                "degree": "学士",
                "start": "2008-09",
                "end": "2012-07",
            },
        ],
    }


def test_boss_rule_map_no_cyclic_import():
    """【GLM-P1-1 验证】独立子进程双向无序 import 零循环依赖自检。"""
    cmd1 = [sys.executable, "-c", "import resume_editor.rule_map_boss; import resume_editor.agent_mapper; print('OK1')"]
    out1 = subprocess.check_output(cmd1, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."))
    assert "OK1" in out1

    cmd2 = [sys.executable, "-c", "import resume_editor.agent_mapper; import resume_editor.rule_map_boss; print('OK2')"]
    out2 = subprocess.check_output(cmd2, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."))
    assert "OK2" in out2


def test_boss_rule_map_normal_coverage(boss_gold_fields, master_resume_fixture):
    """【基础功能验证】验证个人优势、基本信息、三大经历正常规则映射覆盖与报告结构。"""
    report = rule_map_boss(boss_gold_fields, master_resume_fixture, llm_error="429 RateLimit")
    assert report["success"] is True
    assert report["platform"] == "boss"
    assert any("降级为确定性规则映射" in w for w in report.get("warnings", []))

    field_map = {f["path"]: f for f in report["fields"]}

    # 1. 优势亮点
    assert "personal_advantage" in field_map
    assert field_map["personal_advantage"]["value"] == master_resume_fixture["summary"]

    # 2. 基本信息
    assert field_map["name"]["value"] == master_resume_fixture["name"]
    assert field_map["phone"]["value"] == master_resume_fixture["phone"]
    assert field_map["email"]["value"] == master_resume_fixture["email"]

    # 3. 工作经历
    assert "work_experience" in field_map
    we_items = field_map["work_experience"]["value"]
    assert isinstance(we_items, list) and len(we_items) == 1
    assert we_items[0]["company"] == "字节跳动"
    assert we_items[0]["position"] == "首席后端架构师"
    assert we_items[0]["startYear"] == "2021"
    assert we_items[0]["startMonth"] == "6"
    assert we_items[0]["endYear"] == ""

    # 4. 项目经历
    assert "projects" in field_map
    pj_items = field_map["projects"]["value"]
    assert isinstance(pj_items, list) and len(pj_items) == 1
    assert pj_items[0]["project_name"] == "多平台简历同步中心"
    assert pj_items[0]["startYear"] == "2022"

    # 5. 教育经历
    assert "education" in field_map
    edu_items = field_map["education"]["value"]
    assert isinstance(edu_items, list) and len(edu_items) == 1
    assert edu_items[0]["school"] == "清华大学"
    assert edu_items[0]["major"] == "软件工程"


def test_boss_rule_map_empty_array_boundary(boss_gold_fields, master_resume_fixture):
    """【GLM-P1-4 核心验证】空数组边界防御：current_value 为 [] 时绝不产出伪造条目，直接记入 unfilled。"""
    fields_data = copy.deepcopy(boss_gold_fields)
    fields_data["work_experience"]["current_value"] = []
    fields_data["projects"]["current_value"] = []

    report = rule_map_boss(fields_data, master_resume_fixture, llm_error="429 RateLimit")
    unfilled_map = {u["path"]: u for u in report["unfilled"]}

    # 必须在 unfilled 中明确提示人工在官网添加初始记录以生成模板
    assert "work_experience" in unfilled_map
    assert "需人工在官网首次添加至少一条记录以生成字段模板" in unfilled_map["work_experience"]["reason"]
    assert "projects" in unfilled_map
    assert "需人工在官网首次添加至少一条记录以生成字段模板" in unfilled_map["projects"]["reason"]

    # 严禁向 fields 注入伪造的条目（条目数必为 0，且绝无 high 置信度规则映射）
    assert not any(f["path"] == "work_experience" and f.get("confidence") == "high" for f in report["fields"])
    assert not any(f["path"] == "projects" and f.get("confidence") == "high" for f in report["fields"])
    we_f = next((f for f in report["fields"] if f["path"] == "work_experience"), None)
    if we_f:
        assert we_f.get("value") == []


def test_boss_rule_map_dirty_data_defense(boss_gold_fields, master_resume_fixture):
    """【GLM2-P2-3 核心验证】脏数据防御：current_value 包含非 dict 元素时不抛异常，安全降级至 unfilled。"""
    fields_data = copy.deepcopy(boss_gold_fields)
    fields_data["work_experience"]["current_value"] = ["非字典脏字符串数据"]
    fields_data["education"]["current_value"] = [12345]

    report = rule_map_boss(fields_data, master_resume_fixture, llm_error="429 RateLimit")
    unfilled_map = {u["path"]: u for u in report["unfilled"]}

    assert "work_experience" in unfilled_map
    assert "无法安全投影" in unfilled_map["work_experience"]["reason"]
    assert "education" in unfilled_map
    assert "无法安全投影" in unfilled_map["education"]["reason"]

    # 绝不能生成 high 置信度规则映射
    assert not any(f["path"] in ("work_experience", "education") and f.get("confidence") == "high" for f in report["fields"])



def test_boss_rule_map_length_mismatch_warning(boss_gold_fields, master_resume_fixture):
    """【GLM2-P2-2 核心验证】条目数量不对等：主简历经历多于模板条目时，按模板截断，未匹配项进 warnings。"""
    fields_data = copy.deepcopy(boss_gold_fields)
    # 模板只有 1 条，但主简历有 3 段工作经历、2 段项目、2 段教育
    assert len(fields_data["work_experience"]["current_value"]) == 1
    assert len(master_resume_fixture["experiences"]) == 3

    report = rule_map_boss(fields_data, master_resume_fixture, llm_error="429 RateLimit")

    warnings_text = "\n".join(report.get("warnings", []))
    assert "工作经历：主简历包含 3 段经历，官网模板仅 1 段，已匹配投影 1 段，未匹配经历请人工在官网补充" in warnings_text
    assert "项目经历：主简历包含 2 段经历，官网模板仅 1 段，已匹配投影 1 段，未匹配经历请人工在官网补充" in warnings_text
    assert "教育经历：主简历包含 2 段经历，官网模板仅 1 段，已匹配投影 1 段，未匹配经历请人工在官网补充" in warnings_text


def test_boss_rule_map_schema_validity(boss_gold_fields, master_resume_fixture):
    """【Schema 约束】验证映射输出的所有 fields 与 unfilled 路径全部在 flatten_schema 范围内。"""
    report = rule_map_boss(boss_gold_fields, master_resume_fixture, llm_error="test")
    valid_paths = {f["path"] for f in flatten_schema(boss_gold_fields)}
    valid_paths.update(boss_gold_fields.keys())

    for f in report.get("fields", []):
        assert f["path"] in valid_paths, f"字段路径 {f['path']} 必须在合法 schema 范围内"
    for u in report.get("unfilled", []):
        assert u["path"] in valid_paths, f"未填路径 {u['path']} 必须在合法 schema 范围内"


def test_boss_rule_map_options_unfilled(boss_gold_fields, master_resume_fixture):
    """【选项类隔离】验证求职期望、驻外选项、资格证书、性别等选项/复合字段统一归入 unfilled。"""
    report = rule_map_boss(boss_gold_fields, master_resume_fixture, llm_error="test")
    unfilled_paths = {u["path"]: u for u in report.get("unfilled", [])}

    assert "expectations" in unfilled_paths
    assert "certificates" in unfilled_paths
    assert "overseas" in unfilled_paths
    assert "job_status" in unfilled_paths
    assert "gender" in unfilled_paths
    for p in ("expectations", "certificates", "overseas", "job_status"):
        assert "需人工在官网" in unfilled_paths[p]["reason"]


def test_boss_rule_map_selected_modules_filter(boss_gold_fields, master_resume_fixture):
    """【模块过滤】验证传入 selected_modules 时仅输出指定模块的字段与 unfilled 项。"""
    report = rule_map_boss(
        boss_gold_fields,
        master_resume_fixture,
        llm_error="test",
        selected_modules=["work_experience"],
    )
    assert report["selected_modules"] == ["work_experience"]
    for f in report["fields"]:
        assert f["path"] == "work_experience"
    for u in report["unfilled"]:
        assert u["path"] == "work_experience"


def test_boss_writeback_compatibility(boss_gold_fields, master_resume_fixture):
    """【回写干跑兼容性】验证规则映射输出的工作经历与项目经历与 boss_write_back 消费契约完全兼容。"""
    from resume_editor.platforms import boss_write_back

    report = rule_map_boss(boss_gold_fields, master_resume_fixture, llm_error="test")
    field_map = {f["path"]: f["value"] for f in report["fields"]}

    # 1. 模拟回写工作经历匹配
    local_work = field_map.get("work_experience")
    official_work = [
        {"company": "字节跳动", "startDate": "2021-06-01", "startDateStr": "2021-06"}
    ]
    pairs, unmatched = boss_write_back.match_work_items(local_work, official_work)
    assert len(pairs) == 1
    assert pairs[0] == (0, 0)
    assert len(unmatched) == 0

    # 2. 模拟回写项目经历匹配
    local_projects = field_map.get("projects")
    official_projects = [
        {"name": "多平台简历同步中心", "startDate": "2022-01-01", "startDateStr": "2022-01"}
    ]
    p_pairs, p_unmatched = boss_write_back.match_project_items(local_projects, official_projects)
    assert len(p_pairs) == 1
    assert p_pairs[0] == (0, 0)
    assert len(p_unmatched) == 0


def test_map_platform_boss_degrades_on_429(boss_gold_fields, master_resume_fixture):
    """【集成断言】验证 map_platform('boss') 在持续遭遇 429 限流时平滑降级至规则映射 (success=True)。"""
    fake_client = FakeLLMClient(mode="rate_limit", retry_after=1.0)
    with patch("openai.OpenAI", return_value=fake_client), patch("time.sleep"):
        res = map_platform(
            "boss",
            boss_gold_fields,
            master_resume_fixture,
            cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "gpt-4o-mini"},
        )

    assert res["success"] is True, "BOSS 平台遇到 429 时应当平滑降级成功"
    assert res["platform"] == "boss"
    assert any("降级" in w or "规则" in w for w in res.get("warnings", []))
    field_paths = {f["path"] for f in res["fields"]}
    assert "personal_advantage" in field_paths
    assert "work_experience" in field_paths


def test_boss_rule_fallback_rollback_switch(boss_gold_fields, master_resume_fixture):
    """【回滚开关断言】验证 BOSS_RULE_FALLBACK_ENABLED=false 时回滚至 LLM-only 硬失败。"""
    # 1. 验证开关判断函数
    with patch("common.config.get_configured_value", return_value="false"):
        assert is_boss_rule_fallback_enabled() is False

    with patch("common.config.get_configured_value", return_value=""):
        with patch.dict(os.environ, {"BOSS_RULE_FALLBACK_ENABLED": "false"}):
            assert is_boss_rule_fallback_enabled() is False

    with patch("common.config.get_configured_value", return_value=""):
        with patch.dict(os.environ, {}, clear=True):
            assert is_boss_rule_fallback_enabled() is True

    # 2. 验证 map_platform 在开关关闭时硬失败
    fake_client = FakeLLMClient(mode="rate_limit", retry_after=1.0)
    with patch("resume_editor.agent_mapper.is_boss_rule_fallback_enabled", return_value=False):
        with patch("openai.OpenAI", return_value=fake_client), patch("time.sleep"):
            res = map_platform(
                "boss",
                boss_gold_fields,
                master_resume_fixture,
                cfg={"OPENAI_API_KEY": "test_key", "OPENAI_MODEL": "gpt-4o-mini"},
            )

    assert res["success"] is False, "回滚开关关闭时 BOSS 应当维持 LLM 硬失败"
    assert "BOSS 平台映射依赖 AI 模型" in res["message"]


def test_route_generate_boss_degrades_and_saves_report(boss_gold_fields, master_resume_fixture, tmp_path):
    """【路由级验证】验证 POST /api/agent-map/generate 在 BOSS 遭遇 429 限流时聚合返回 success=True 且落盘。"""
    from fastapi.testclient import TestClient
    from app.main import app
    import resume_editor.agent_mapper as am

    client = TestClient(app)

    saved_reports = {}

    def fake_save_report(platform, report, selected_modules=None):
        saved_reports[platform] = report

    fake_client = FakeLLMClient(mode="rate_limit", retry_after=1.0)

    with patch("openai.OpenAI", return_value=fake_client), \
         patch("time.sleep"), \
         patch("resume_editor.agent_mapper.load_master_resume", return_value=master_resume_fixture), \
         patch("resume_editor.agent_mapper.save_report", side_effect=fake_save_report):

        # 临时将 boss_fields.json 写入 DATA_DIR 确保路由存在该平台数据
        boss_path = os.path.join(am.DATA_DIR, "boss_fields.json")
        orig_data = None
        if os.path.exists(boss_path):
            with open(boss_path, "r", encoding="utf-8") as f:
                orig_data = f.read()

        try:
            with open(boss_path, "w", encoding="utf-8") as f:
                json.dump(boss_gold_fields, f, ensure_ascii=False)

            # Phase 4 后默认异步；本用例验证同步聚合契约，显式 mode=sync（保留一个版本周期）
            resp = client.post("/api/agent-map/generate", json={"platforms": ["boss"], "mode": "sync"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True, "全量平台成功或平滑降级时，顶层聚合 success 应当为 True"
            assert "boss" in data["reports"]
            assert data["reports"]["boss"]["success"] is True
            assert "boss" in saved_reports, "平滑降级成功的 BOSS 报告必须被 save_report 落盘"
        finally:
            if orig_data is not None:
                with open(boss_path, "w", encoding="utf-8") as f:
                    f.write(orig_data)
            elif os.path.exists(boss_path):
                os.remove(boss_path)


def test_boss_rule_map_education_preserves_non_fulltime(boss_gold_fields, master_resume_fixture):
    """【P1-1 验证】验证官网模板为非全日制时，规则映射 100% 保持非全日制性质，严禁捏造全日制前缀。"""
    fields_data = copy.deepcopy(boss_gold_fields)
    fields_data["education"]["current_value"] = [
        {
            "degree": "大专 / 非全日制",
            "degreeName": "非全日制大专",
            "eduType": "非全日制",
            "school": "某成人高校",
            "major": "工商管理",
            "startYear": "2016",
            "endYear": "2019",
        }
    ]

    report = rule_map_boss(fields_data, master_resume_fixture, llm_error="test")
    edu_field = next(f for f in report["fields"] if f["path"] == "education")
    item = edu_field["value"][0]

    assert item["school"] == "清华大学"
    assert item["major"] == "软件工程"
    assert "非全日制" in item["degree"], "非全日制模板必须保持非全日制性质"
    assert item["degree"] == "硕士 / 非全日制"
    assert item["degreeName"] == "非全日制硕士", "严禁将非全日制改写为全日制硕士"
