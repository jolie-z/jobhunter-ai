import pytest
from fastapi.testclient import TestClient
import sys
import json
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from resume_editor.platforms.boss_write_back import (
    plan_writeback,
    verify_results,
    build_baseinfo_payload,
    build_workexp_payload,
    build_expect_payload,
    build_project_payload,
    build_cert_payload,
    build_overseas_payload,
    build_edu_payload,
)

client = TestClient(app)

# Standard mock reference dictionaries for trees
MOCK_COUNTRY_TREE = [
    {"code": 101, "name": "中国香港"},
    {"code": 116, "name": "德国"},
    {"code": 126, "name": "英国"},
]
MOCK_LANG_TREE = [
    {"code": 2, "name": "英语"},
    {"code": 76, "name": "粤语"},
]
MOCK_INDUSTRY_TREE = [
    {"code": 100001, "name": "电子商务"},
    {"code": 100020, "name": "互联网"},
]


class TestBossTabFullIntegration:
    """全面覆盖 BOSS 直聘 Tab 8 大模块的全链路集成测试套件"""

    def test_01_all_8_modules_plan_generation(self):
        """测试 8 大模块全量数据变更时的回写计划生成与字段装配"""
        local_fields = {
            "gender": {
                "label": "性别",
                "type": "string",
                "current_value": "女"
            },
            "job_status": {
                "label": "求职状态",
                "type": "string",
                "current_value": "离职-随时到岗"
            },
            "birth_month": {
                "label": "出生年月",
                "type": "string",
                "current_value": "1990-05"
            },
            "work_start_date": {
                "label": "工作起始时间",
                "type": "string",
                "current_value": "2020-07"
            },
            "personal_advantage": {
                "label": "个人优势",
                "type": "text",
                "current_value": "5年大模型与全栈架构设计沉淀，精通 React/FastAPI。"
            },
            "expectations": {
                "label": "求职期望",
                "type": "array",
                "current_value": [
                    {
                        "position": "全栈工程师",
                        "city": "广州",
                        "salary": "25-35K",
                        "positionType": "全职",
                        "industry": "互联网"
                    }
                ]
            },
            "work_experience": {
                "label": "工作经历",
                "type": "array",
                "current_value": [
                    {
                        "company": "自由职业者",
                        "industry": "互联网",
                        "department": "自主研发",
                        "position": "全栈工程师",
                        "startYear": "2024",
                        "startMonth": "04",
                        "content": "独立研发全链路自动化 SaaS。",
                        "achievement": "交付 5 项涵盖大模型智能体与中台的系统。",
                        "skills": [
                            {"name": "LLM意图路由"},
                            {"name": "Pandas物理校验"},
                            {"name": "双轨制架构"},
                            {"name": "CDP协议"},
                            {"name": "NLP情感分析"},
                            {"name": "全栈研发"}
                        ],
                        "hideResume": True
                    }
                ]
            },
            "projects": {
                "label": "项目经历",
                "type": "array",
                "current_value": [
                    {
                        "project_name": "JobHunter 自动化系统",
                        "project_role": "架构师",
                        "startYear": "2024",
                        "startMonth": "01",
                        "endYear": "2024",
                        "endMonth": "06",
                        "project_description": "自动化投递系统",
                        "achievement": "秒级分发与状态流转",
                        "project_link": "https://github.com/example/jobhunter"
                    }
                ]
            },
            "education": {
                "label": "教育经历",
                "type": "array",
                "current_value": [
                    {
                        "school": "临江大学",
                        "major": "计算机科学与技术",
                        "degree": "本科",
                        "startYear": "2015",
                        "endYear": "2019"
                    }
                ]
            },
            "certificates": {
                "label": "资格证书",
                "type": "array",
                "current_value": ["PMP项目管理专业人士认证", "英语六级"]
            },
            "stayAbroad": {
                "label": "驻外选项",
                "type": "object",
                "current_value": {
                    "countries": ["中国香港", "德国"],
                    "languages": ["英语", "粤语"],
                    "duration": "2年"
                }
            }
        }

        official_zp = {
            "userDesc": "旧优势",
            "expectList": [
                {
                    "id": "exp_001",
                    "position": "1001",
                    "positionType": 1,
                    "lowSalary": 15,
                    "highSalary": 25,
                }
            ],
            "workExpList": [
                {
                    "id": "work_001",
                    "companyName": "自由职业者",
                    "department": "旧部门",
                    "startDateStr": "2024.04",
                    "position": 200101,
                    "customPositionName": "全栈工程师",
                    "emphasis": [],
                    "isPublic": 0,
                }
            ],
            "projectExpList": [
                {
                    "id": "proj_001",
                    "name": "JobHunter 自动化系统",
                    "roleName": "核心开发",
                    "startDateStr": "2024.01",
                    "projectDesc": "旧描述",
                }
            ],
            "educationExpList": [
                {
                    "id": "edu_001",
                    "school": "临江大学",
                    "startYearStr": "2015",
                    "degree": "本科",
                }
            ],
            "certificationList": [{"certName": "旧证书"}],
            "stayAbroad": {},
            "baseInfo": {
                "gender": 1,
                "applyStatus": 1,
                "birthday": "1990-01-01",
                "startWorkDate": "2018-01-01",
            }
        }

        # 生成 8 大模块全量计划
        plan = plan_writeback(
            local_fields,
            official_zp,
            MOCK_COUNTRY_TREE,
            MOCK_LANG_TREE,
            MOCK_INDUSTRY_TREE,
            selected_paths=None,
            skill_tree=None,
        )

        actions = plan.get("actions", [])
        modules_generated = {a["module"] for a in actions}

        # 断言所有配置的模块均生成了对应 action
        assert "personal_advantage" in modules_generated
        assert "expectations" in modules_generated
        assert "work_experience" in modules_generated
        assert "projects" in modules_generated
        assert "education" in modules_generated
        assert "certificates" in modules_generated
        assert "overseas" in modules_generated
        assert "baseinfo" in modules_generated

        # 重点断言工作经历：emphasis 拼接与 isPublic 隐私开关
        work_act = next(a for a in actions if a["module"] == "work_experience")
        wp = work_act["payload"]
        assert wp["id"] == "work_001"
        assert wp["companyName"] == "自由职业者"
        assert wp["department"] == "自主研发"
        assert wp["emphasis"] == "LLM意图路由#&#Pandas物理校验#&#双轨制架构#&#CDP协议#&#NLP情感分析#&#全栈研发"
        assert wp["isPublic"] == 1, "hideResume=True 必须生成 isPublic=1"

        # 重点断言资格证书：全量覆盖格式
        cert_act = next(a for a in actions if a["module"] == "certificates")
        certs = json.loads(cert_act["payload"]["certJson"])
        assert len(certs) == 2
        assert {c["name"] for c in certs} == {"PMP项目管理专业人士认证", "英语六级"}

        # 重点断言驻外选项：代码映射
        overseas_act = next(a for a in actions if a["module"] == "overseas")
        op = overseas_act["payload"]
        assert "101" in op["country"] and "116" in op["country"]
        assert "2" in op["language"] and "76" in op["language"]

    def test_02_verify_results_engine_comprehensive(self):
        """测试 verify_results 对账校验引擎对 8 大模块回写结果的判定能力"""
        saved_actions = [
            {
                "module": "work_experience",
                "ok": True,
                "payload": {
                    "id": "work_001",
                    "companyName": "自由职业者",
                    "workContent": "自动化 SaaS 研发",
                    "workPerformance": "5项数据产品",
                    "emphasis": "LLM意图路由#&#Pandas物理校验",
                    "isPublic": 1,
                }
            },
            {
                "module": "personal_advantage",
                "ok": True,
                "payload": {"advantage": "全新优势内容"}
            },
            {
                "module": "certificates",
                "ok": True,
                "payload": {"certJson": json.dumps([{"name": "PMP"}, {"name": "CET6"}])}
            }
        ]

        # 官网回读对账数据（完全对齐）
        verify_zp_match = {
            "userDesc": "全新优势内容",
            "workExpList": [
                {
                    "id": "work_001",
                    "workContent": "自动化 SaaS 研发",
                    "workPerformance": "5项数据产品",
                    "emphasis": ["LLM意图路由", "Pandas物理校验"],
                    "isPublic": 1,
                }
            ],
            "certificationList": [{"certName": "PMP"}, {"certName": "CET6"}]
        }

        report_match = verify_results(verify_zp_match, saved_actions)
        assert len(report_match) == 3
        for item in report_match:
            assert item["match"] is True, f"模块 {item['module']} 应判定为对账成功"

        # 官网回读对账数据（技能不匹配场景）
        verify_zp_mismatch = {
            "userDesc": "全新优势内容",
            "workExpList": [
                {
                    "id": "work_001",
                    "workContent": "自动化 SaaS 研发",
                    "workPerformance": "5项数据产品",
                    "emphasis": [],  # 官网技能为空
                    "isPublic": 1,
                }
            ],
            "certificationList": [{"certName": "PMP"}, {"certName": "CET6"}]
        }
        report_mismatch = verify_results(verify_zp_mismatch, saved_actions)
        work_res = next(r for r in report_mismatch if r["module"] == "work_experience")
        assert work_res["match"] is False, "当官网技能未同步成功时，对账必须判定为 False"

    def test_03_api_endpoints_integration(self):
        """测试 FastAPI 后端对 BOSS 简历保存、快照生成及回写调度的接口级集成"""
        # 1. 测试保存字段 /api/resume-editor/save/boss
        mock_payload = {
            "personal_advantage": {
                "label": "个人优势",
                "current_value": "接口集成测试优势内容"
            }
        }
        res_save = client.post("/api/resume-editor/save/boss", json=mock_payload)
        assert res_save.status_code == 200
        assert res_save.json()["success"] is True

        # 2. 测试固化快照 /api/agent-map/writeback-save
        res_wb_save = client.post("/api/agent-map/writeback-save", json={"platform": "boss"})
        assert res_wb_save.status_code == 200
        assert res_wb_save.json()["success"] is True
        assert "快照" in res_wb_save.json()["message"] or "ok" in res_wb_save.json()["message"]

        # 3. 测试调度回写 /api/agent-map/write-back (Dry-Run)
        res_wb = client.post("/api/agent-map/write-back", json={
            "platform": "boss",
            "dry_run": True,
            "paths": ["personal_advantage", "work_experience"]
        })
        assert res_wb.status_code in (200, 500)
        data = res_wb.json()
        assert "success" in data
        if not data["success"]:
            assert "全部与官网一致" not in data.get("message", "")
