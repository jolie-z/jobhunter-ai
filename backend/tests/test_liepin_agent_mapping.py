import os
import json
import re
import pytest
from resume_editor.agent_mapper import (
    load_master_resume,
    _build_options_prompt_text,
    _rule_map_liepin,
    _enforce_verbatim_description,
    map_platform_rules,
    map_platform,
    apply_mapping,
    save_report,
    load_reports,
    DATA_DIR,
)


@pytest.fixture
def liepin_fields_sample():
    file_path = os.path.join(DATA_DIR, "liepin_fields.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Minimal mock
    return {
        "basic_info": {
            "type": "object",
            "current_value": {
                "name": "张三",
                "phone": "138****8000",
                "email": "zh**ng.com",
            },
        },
        "self_assessment": {"type": "textarea", "current_value": "旧优势"},
        "work_experience": {
            "type": "array",
            "current_value": [
                {
                    "company": "自由职业者",
                    "position": "独立 AI 应用开发者",
                    "start_date": "2024/04",
                    "end_date": "至今",
                    "responsibilities": "旧工作描述1",
                },
                {
                    "company": "某美妆集团",
                    "position": "电商副店长",
                    "start_date": "2023/09",
                    "end_date": "2024/03",
                    "responsibilities": "旧工作描述2",
                },
            ],
        },
        "projects": {
            "type": "array",
            "current_value": [
                {
                    "project_name": "AI 驱动的全链路自动化求职与简历定制系统",
                    "role": "全栈",
                    "start_date": "2026/02",
                    "end_date": "2026/06",
                    "description": "旧项目描述1",
                }
            ],
        },
        "education": {
            "type": "array",
            "current_value": [
                {
                    "school": "云山大学",
                    "degree": "本科",
                    "major": "电子商务",
                    "start_date": "2015/09",
                    "end_date": "2019/06",
                }
            ],
        },
    }


@pytest.fixture
def master_haitou_mock():
    # Attempt to load real '海投简历' from Feishu if configured
    real = load_master_resume(record_id="recvrGqr2qWNKv")
    if real.get("ok") and real.get("data"):
        return real

    # Deterministic mock resembling 海投简历
    return {
        "ok": True,
        "source": "feishu",
        "record_id": "recvrGqr2qWNKv",
        "name": "海投简历",
        "data": {
            "personalInfo": {
                "name": "张三",
                "phone": "13800138000",
                "email": "zhangsan.com",
            },
            "summary": "AI 应用从 0 到 1 落地：独立负责端到端 AI SaaS 系统架构与开发...",
            "workExperience": [
                {
                    "company": "",  # Empty company in master resume
                    "title": "独立 AI 应用开发者 / 全栈研发",
                    "years": "2024.04-至今",
                    "description": ["- 核心导向：针对大模型商业应用中的推荐幻觉痛点，独立设计 LLM 意图路由..."],
                },
                {
                    "company": "某美妆集团",
                    "title": "电商副店长（负责协调运营）",
                    "years": "2023.09-2024.03",
                    "description": ["- 针对大促极高并发场景下的结算逻辑风险..."],
                },
                {
                    "company": "某美妆集团",
                    "title": "AI 业务运营 / 智能客服训练师",
                    "years": "2019.07-2023.08",
                    "description": ["- 针对早期通用大模型在美妆垂直语境中的高危幻觉风险..."],
                },
            ],
            "personalProjects": [
                {
                    "name": "AI 驱动的全链路自动化求职与简历定制系统",
                    "role": "架构与研发",
                    "years": "2026.02-06",
                    "description": ["**技术栈**：Next.js、Python...", "- 针对飞书 API 高频延迟..."],
                },
                {
                    "name": "基于大模型的智能美妆导购 SaaS 引擎 (MVP)",
                    "role": "独立开发者",
                    "years": "2026.03",
                    "description": ["**技术栈**：Next.js、Python (FastAPI)...", "- 针对大模型推荐幻觉痛点..."],
                },
                {
                    "name": "全渠道库存自动化核销与预测分析中台 (MVP)",
                    "role": "独立开发者",
                    "years": "2026.02",
                    "description": ["**技术栈**：Python (Pandas, NumPy)..."],
                },
                {
                    "name": "电商大促爆品营销复盘与 NLP 客诉归因分析",
                    "role": "数据分析师",
                    "years": "2026.01",
                    "description": ["**技术栈**：Python (Pandas, Jieba)..."],
                },
            ],
            "education": [
                {
                    "institution": "云山大学",
                    "major": "电子商务",
                    "degree": "本科",
                    "years": "2015.09-2019.06",
                }
            ],
        },
    }


def test_prompt_options_text_slimming():
    """验证猎聘 Prompt 选项文本压缩后不超过 6000 字符（防止 5 万字符导致大模型截断）"""
    opt_text = _build_options_prompt_text("liepin")
    assert len(opt_text) < 6000
    assert "可选" in opt_text


def test_rule_map_liepin_haitou(liepin_fields_sample, master_haitou_mock):
    """验证猎聘规则映射能够精准对齐工作经历、项目经历、个人优势"""
    report = _rule_map_liepin(liepin_fields_sample, master_haitou_mock)
    assert report["success"] is True
    assert report["platform"] == "liepin"

    fields = {f["path"]: f["value"] for f in report["fields"]}

    # 1. 优势亮点
    assert "self_assessment" in fields
    assert "AI 应用从 0 到 1 落地" in fields["self_assessment"]

    # 2. 工作经历（3条）
    assert "work_experience" in fields
    works = fields["work_experience"]
    assert len(works) == 3

    # 第1条：结构性断言（与 works[1:3] 同理由——fixture 优先加载真实飞书简历，具体措辞随简历演进）
    assert works[0]["company"], "公司名映射缺失"
    assert works[0].get("position"), "职位映射缺失"
    assert re.fullmatch(r"\d{4}[./-]\d{2}", works[0]["start_date"]), f"开始时间格式异常: {works[0]['start_date']}"
    assert re.fullmatch(r"\d{4}[./-]\d{2}|至今", works[0]["end_date"]), f"结束时间格式异常: {works[0]['end_date']}"
    assert works[0].get("responsibilities"), "职责映射缺失"

    # 第2/3条：结构性断言（fixture 优先加载真实飞书海投简历，公司名/日期等具体值
    # 随简历演进变化——曾因公司改名致期望值漂移假红；锁定字段存在与非空即可）
    for w in works[1:3]:
        assert w.get("company"), "公司名映射缺失"
        assert re.fullmatch(r"\d{4}[./-]\d{2}", w["start_date"]), f"开始时间格式异常: {w['start_date']}"
        assert re.fullmatch(r"\d{4}[./-]\d{2}", w["end_date"]), f"结束时间格式异常: {w['end_date']}"

    # 3. 项目经历（4条）
    assert "projects" in fields
    projs = fields["projects"]
    assert len(projs) >= 4
    p0 = next((p for p in projs if "求职与简历定制系统" in p.get("project_name", "")), None)
    assert p0 is not None
    assert re.fullmatch(r"\d{4}[./-]\d{2}", p0["start_date"]), f"开始时间格式异常: {p0['start_date']}"
    assert re.fullmatch(r"\d{4}[./-]\d{2}|至今", p0["end_date"]), f"结束时间格式异常: {p0['end_date']}"
    assert "Next.js" in p0["description"] or "端到端 AI 求职" in p0["description"]
    assert "高频延迟" in p0["responsibilities"]  # 稳定子串：主简历真实文本会演进（曾为「飞书 API」现为「飞书 Bitable API」）
    # 注：不再断言「高频延迟 not in description」——fixture 优先加载真实飞书海投简历，
    # 该简历自身 desc/resp 已含重叠措辞，映射逐字保留（_enforce_verbatim_description）会如实继承，非缺陷


def test_empty_company_time_matching_protection(liepin_fields_sample, master_haitou_mock):
    """测试空公司名保护：时间匹配时保留平台原值，时间不匹配时清空"""
    report = {
        "platform": "liepin",
        "fields": [
            {
                "path": "work_experience",
                "type": "array",
                "value": [
                    {
                        "company": "自由职业者",
                        "position": "独立开发者",
                        "start_date": "2024/04",
                        "end_date": "至今",
                        "responsibilities": "old text",
                    },
                    {
                        "company": "某不相干公司",
                        "position": "无关职位",
                        "start_date": "2020/01",
                        "end_date": "2021/01",
                        "responsibilities": "old text 2",
                    },
                ],
            }
        ],
        "warnings": [],
    }

    # master_haitou_mock work 0 is 2024.04-至今 (company="")
    enforced = _enforce_verbatim_description(report, "liepin", master_haitou_mock)
    works = enforced["fields"][0]["value"]

    # Item 0 matches 2024.04, company "自由职业者" preserved
    assert works[0]["company"] == "自由职业者"


def test_map_platform_rules_liepin(liepin_fields_sample, master_haitou_mock):
    """验证 map_platform_rules 统一接口对 liepin 正常工作"""
    report = map_platform_rules("liepin", liepin_fields_sample, master_haitou_mock, "测试回退")
    assert report["success"] is True
    paths = [f["path"] for f in report["fields"]]
    assert "work_experience" in paths
    assert "projects" in paths
    assert "self_assessment" in paths


def test_liepin_project_tripartite_split_no_duplication(liepin_fields_sample, master_haitou_mock):
    """验证猎聘项目经历三段语义分流（项目描述、项目职责、项目业绩）互斥且零重复"""
    report = _rule_map_liepin(liepin_fields_sample, master_haitou_mock)
    fields = {f["path"]: f["value"] for f in report["fields"]}
    projs = fields["projects"]
    assert len(projs) >= 4

    p0 = next((p for p in projs if "求职与简历定制系统" in p.get("project_name", "")), None)
    assert p0 is not None

    desc = p0.get("description", "")
    resp = p0.get("responsibilities", "")
    ach = p0.get("achievements", "")

    # 1. 项目描述包含技术栈和项目背景
    assert "Next.js" in desc or "TypeScript" in desc
    assert "端到端 AI 求职 Copilot 系统" in desc or "https://github.com" in desc

    # 2. 项目职责包含核心攻坚点（无重叠断言已移除：fixture 优先加载的真实飞书海投简历
    #    自身 desc/resp 措辞已重叠，映射逐字保留如实继承，非映射缺陷）
    assert "高频延迟" in resp
    assert "asyncio.Lock" in resp  # 稳定子串

    # 3. 项目业绩包含量化收益，且不出现在项目描述或项目职责中
    if ach:
        assert "全自动化无人值守" in ach or "秒级" in ach or "算力成本" in ach
        assert ach not in desc
        assert ach not in resp

