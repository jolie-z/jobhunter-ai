"""
猎聘 (Liepin) 全模块、全字段单元测试、集成测试与端到端测试套件
涵盖猎聘 10 大核心模块及全部字段：
  1. basic_info (基本信息 22 个子字段)
  2. self_assessment (优势亮点 / 自我评价)
  3. expectations (求职期望 / 薪资 / 城市 / 行业)
  4. work_experience (工作经历 / 至今 / 职位三级码 / 屏蔽公司)
  5. projects (项目经历 / 描述-职责-业绩三段互斥)
  6. education (教育经历 / 学历码 / 统招标记)
  7. certificates (资格证书 / 证书码字典)
  8. skill_tags (技能标签 / 官网上限 10 个)
  9. languages (语言能力 / 掌握程度 / 等级证书)
  10. additional_info (附加信息)
"""

import json
import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# 引入 backend 目录
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from resume_editor.platforms.liepin_collector import build_liepin_fields
from resume_editor.platforms.liepin_pusher import (
    LiepinPusher,
    load_dicts,
    fuzzy_find,
    norm_ym,
    norm_ymd,
    DEGREE_MAP,
    WORK_STATUS_MAP,
    STUDENT_STATUS_MAP,
    POLITICAL_MAP,
    ALL_MODULES,
)

client = TestClient(app)
DATA_DIR = os.path.join(BACKEND_DIR, "resume_editor", "data")


# ============================================================================
# 1. 单元测试：字典加载、日期归一与工具函数
# ============================================================================

class TestLiepinUnitHelpers:
    """测试字典加载与辅助转换函数"""

    def test_01_load_dicts(self):
        cities, industries, jobs, langs, certs = load_dicts()
        assert len(cities) > 100, "城市字典应包含大量城市数据"
        assert "广州" in cities or "050020" in cities.values()
        assert len(industries) > 10, "行业字典应包含行业类别"
        assert len(jobs) > 100, "职位字典应包含丰富职位分类"
        assert "11" in langs, "语言字典应包含英语(11)"
        assert len(certs) > 10, "证书字典应包含证书映射"

    def test_02_norm_ym_variations(self):
        assert norm_ym("2026-02") == "202602"
        assert norm_ym("2026/06") == "202606"
        assert norm_ym("2026.03") == "202603"
        assert norm_ym("202601") == "202601"
        assert norm_ym("2026年5月") == "202605"
        assert norm_ym("至今") == "999999"
        assert norm_ym("现在") == "999999"
        assert norm_ym("") is None
        assert norm_ym(None) is None

    def test_02b_norm_ymd_variations(self):
        """测试 8 位出生日期格式化（必须输出 YYYYMMDD）"""
        assert norm_ymd("1990年07月") == "19900701"
        assert norm_ymd("1990年7月") == "19900701"
        assert norm_ymd("1990-07") == "19900701"
        assert norm_ymd("1990.11") == "19901101"
        assert norm_ymd("1990/07/15") == "19900715"
        assert norm_ymd("1990年11月5日") == "19901105"
        assert norm_ymd("19901101") == "19901101"
        assert norm_ymd("") is None
        assert norm_ymd(None) is None

    def test_03_fuzzy_find(self):
        cities, industries, jobs, _, _ = load_dicts()
        # 精确或模糊匹配城市
        assert fuzzy_find("深圳", cities) is not None
        assert fuzzy_find("北京", cities) is not None
        # 模糊匹配职位
        assert fuzzy_find("全栈研发", jobs) is not None or fuzzy_find("软件工程师", jobs) is not None


# ============================================================================
# 2. 单元测试：10 大模块 Payload 构造器 (LiepinPusher Converter)
# ============================================================================

class TestLiepinModuleConverters:
    """针对猎聘 10 大模块与每一个字段的转换器单独进行全覆盖单元测试"""

    @pytest.fixture
    def pusher(self):
        p = LiepinPusher(ALL_MODULES)
        p.res_id = "test_encry_res_id_123456"
        p.detail = {
            "resId": "test_encry_res_id_123456",
            "workExperiences": [{"id": "w1", "dqName": "深圳", "dqCode": "050090", "industryName": "互联网", "industryCode": "010", "jobtitleName": "全栈工程师", "jobtitleCode": "N000101"}],
            "projectExperiences": [{"id": "p1", "projectName": "测试项目"}],
            "eduExperiences": [{"id": "e1", "school": "某财经类大学"}],
            "jobWants": [{"id": "j1"}],
            "languages": [{"name": "英语", "code": "11"}],
        }
        return p

    def test_01_basic_info_all_22_subfields(self, pusher):
        fields = {
            "basic_info": {
                "current_value": {
                    "name": "张三",
                    "gender": "男",
                    "age": "28",
                    "work_years": "5",
                    "city": "深圳",
                    "job_status": "离职，正在找工作",
                    "political_status": "群众",
                    "phone": "13800000000",
                    "email": "test@example.com",
                    "wechat": "wx_zhangsan",
                    "birth": "1998-05",
                    "work_start_date": "2021/07",
                    "identity": "职场人",
                    "show_gender_suffix": True,
                    "current_salary_month": "25000",
                    "current_salary_months": "14",
                    "salary_confidential": True,
                    "education_degree": "本科",
                    "current_company": "测试科技",
                    "current_title": "资深工程师",
                    "current_industry": "计算机软件",
                    "household": "广东广州",
                    "nationality": "中国",
                }
            }
        }
        form = pusher._bi(fields)
        assert form["encryResId"] == "test_encry_res_id_123456"
        assert form["realName"] == "张三"
        assert form["sex"] == "男"
        assert form["birthday"] == "19980501"
        assert form["startJobYear"] == "2021"
        assert form["startJobMonth"] == "07"
        assert form["nowSalary"] == "25000"
        assert form["nowSalaryMonths"] == "14"
        assert form["nowSalarySecret"] == "1"
        assert form["namePrivacy"] == "1"
        assert form["wechat"] == "wx_zhangsan"

    def test_02_self_assessment_module(self, pusher):
        fields = {
            "self_assessment": {
                "current_value": "具备 5 年大型互联网全栈架构经验，主导高并发系统重构。"
            }
        }
        text = fields["self_assessment"]["current_value"]
        assert len(text) <= 1000
        assert text.startswith("具备")

    def test_03_expectations_multi_items_and_fields_full_coverage(self, pusher):
        """测试 3 条求职期望全量生成、职位/城市/行业/薪资全字段解析与 ID 绑定机制"""
        fields = {
            "expectations": {
                "current_value": [
                    {
                        "position": "数据标注/AI训练师",
                        "city": "广州",
                        "other_cities": ["深圳"],
                        "industries": ["不限"],
                        "salary_min": "15k",
                        "salary_max": "25k",
                        "salary_months": 14,
                    },
                    {
                        "position": "AI产品经理",
                        "city": "广州",
                        "other_cities": ["深圳"],
                        "industries": ["全部行业"],
                        "salary_min": "15000",
                        "salary_max": "25000",
                        "salary_months": 14,
                    },
                    {
                        "position": "全栈",
                        "city": "广州",
                        "other_cities": ["深圳"],
                        "industries": ["智能硬件/消费电子", "电子商务"],
                        "salary_min": "1.5万",
                        "salary_max": "2.5万",
                        "salary_months": 14,
                    },
                ]
            }
        }
        payloads = pusher._expectations(fields)
        # 必须全量输出 3 个 Payload，严禁截断为 1 个
        assert len(payloads) == 3, f"应生成 3 条期望 payload，实际为 {len(payloads)}"

        # 第 1 条期望（对齐已有 ID 进行更新）
        p1 = payloads[0]
        assert p1["encryResId"] == "test_encry_res_id_123456"
        assert p1.get("id") == "j1", "已有第 1 条应携带 id 进行更新"
        assert p1["jobtitleCode"] == "N002007"
        assert p1["dqCode"] == "050020"
        assert p1["otherExpectDqCodes"] == ["050090"]
        assert p1["industryCodes"] == "000", "'不限' 应映射为 '000'"
        assert p1["wantSalaryLow"] == 15000
        assert p1["wantSalaryHigh"] == 25000
        assert p1["wantSalaryMonths"] == 14

        # 第 2 条期望（超出已有条数作为新增条目，不带 id）
        p2 = payloads[1]
        assert p2["encryResId"] == "test_encry_res_id_123456"
        assert "id" not in p2, "超出官网已有条数应作为新增（不带 id）"
        assert p2["jobtitleCode"] == "N002271"
        assert p2["industryCodes"] == "000", "'全部行业' 应映射为 '000'"
        assert p2["wantSalaryLow"] == 15000
        assert p2["wantSalaryHigh"] == 25000

        # 第 3 条期望（全栈职位、多行业拼接、万级薪资格式）
        p3 = payloads[2]
        assert p3["encryResId"] == "test_encry_res_id_123456"
        assert "id" not in p3
        assert p3["jobtitleCode"] == "N000027", "'全栈' 职位码应精确映射为 N000027"
        assert "H0015" in p3["industryCodes"] or "H0002" in p3["industryCodes"]
        assert p3["wantSalaryLow"] == 15000
        assert p3["wantSalaryHigh"] == 25000

    def test_03b_expectations_salary_and_industry_edge_cases(self, pusher):
        """测试期望薪资多形态 (k, 万, 纯数字) 与多行业去重容错"""
        fields = {
            "expectations": {
                "current_value": [
                    {
                        "position": "软件工程师",
                        "city": "北京",
                        "other_cities": ["上海", "深圳", "深圳"],  # 重复城市
                        "industries": ["电子商务", "电子商务", "全部行业"],  # 重复行业
                        "salary_min": "18k+",
                        "salary_max": "3.5万",
                        "salary_months": 16,
                    }
                ]
            }
        }
        payloads = pusher._expectations(fields)
        assert len(payloads) == 1
        p = payloads[0]
        assert p["wantSalaryLow"] == 18000
        assert p["wantSalaryHigh"] == 35000
        assert p["wantSalaryMonths"] == 16
        assert len(p["otherExpectDqCodes"]) == 2, "重复城市应去重"

    def test_03c_expectations_delete_redundant_when_local_less_than_official(self, pusher):
        """测试当官网有 3 条而本地只有 1 条时，多余的 2 条被识别出清理"""
        pusher.detail = {
            "resId": "test_encry_res_id_123456",
            "jobWants": [{"id": "jw_1"}, {"id": "jw_2"}, {"id": "jw_3"}],
        }
        fields = {
            "expectations": {
                "current_value": [
                    {"position": "全栈", "city": "广州"}
                ]
            }
        }
        payloads = pusher._expectations(fields)
        assert len(payloads) == 1
        assert payloads[0]["id"] == "jw_1"
        existing = pusher.detail["jobWants"]
        redundant = existing[len(payloads):]
        assert len(redundant) == 2
        assert redundant[0]["id"] == "jw_2"
        assert redundant[1]["id"] == "jw_3"

    def test_04a_work_all_standard_fields_and_types(self, pusher):
        """测试工作经历所有 13 个字段的标准映射与类型规范"""
        fields = {
            "work_experience": {
                "current_value": [
                    {
                        "company": "某美妆集团有限公司",
                        "position": "独立 AI 应用开发者 / 全栈研发",
                        "job_category": "全栈",
                        "department": "技术研发部",
                        "start_date": "2024/04",
                        "end_date": "至今",
                        "responsibilities": "负责核心业务系统微服务架构设计与性能调优，实现端到端高并发交付",
                        "industry": "电子商务",
                        "work_city": "广州",
                        "is_internship": True,
                        "hide_resume": True,
                        "salary_amount": "14000",
                        "salary_months": "14",
                        "report_to": "技术总监",
                        "team_size": "5",
                    }
                ]
            }
        }
        payloads = pusher._work(fields)
        assert len(payloads) == 1
        w = payloads[0]
        assert w["compName"] == "某美妆集团有限公司"
        assert w["title"] == "独立 AI 应用开发者 / 全栈研发"
        assert w["startDate"] == "202404"
        assert w["endDate"] == "999999", "至今必须映射为 999999"
        assert w["workType"] == 2, "实习经历必须映射为 workType: 2"
        assert w["shieldComp"] is True, "屏蔽简历必须显式传递 True"
        assert w["dept"] == "技术研发部"
        assert w["report2"] == "技术总监"
        assert w["subordinate"] == "5"
        assert w["salmonths"] == "14"
        assert w["salary"] == "14000"
        assert w["nowSalary"] == "14000"
        assert w["dq"] == "050020"
        assert w["industry"] == "H0002"
        assert w["jobtitle"] == "N000027"
        assert w["duty"].startswith("负责核心业务系统")

    def test_04b_work_internship_and_shield_boolean_toggles(self, pusher):
        """测试实习经历 (workType: 1 vs 2) 与屏蔽公司 (shieldComp: True vs False) 布尔切换"""
        fields = {
            "work_experience": {
                "current_value": [
                    {
                        "company": "全职公司A",
                        "position": "电商运营",
                        "is_internship": False,
                        "hide_resume": False,
                    },
                    {
                        "company": "实习公司B",
                        "position": "产品实习生",
                        "is_internship": "true",
                        "hide_resume": "1",
                    }
                ]
            }
        }
        payloads = pusher._work(fields)
        assert len(payloads) == 2
        # 条目 1: 全职且不屏蔽
        assert payloads[0]["workType"] == 1
        assert payloads[0]["shieldComp"] is False
        # 条目 2: 实习且屏蔽
        assert payloads[1]["workType"] == 2
        assert payloads[1]["shieldComp"] is True

    def test_04c_work_salary_variations_and_months(self, pusher):
        """测试目前薪资多形态 (14000 / 14k / 1.4万 / 14k+) 与月数解析"""
        fields = {
            "work_experience": {
                "current_value": [
                    {
                        "company": "测试公司A",
                        "position": "软件工程师",
                        "salary_amount": "1.4万",
                        "salary_months": "15薪",
                    },
                    {
                        "company": "测试公司B",
                        "position": "前端开发",
                        "salary_amount": "20k+",
                        "salary_months": 16,
                    }
                ]
            }
        }
        payloads = pusher._work(fields)
        assert len(payloads) == 2
        assert payloads[0]["salary"] == "14000"
        assert payloads[0]["salmonths"] == "15"
        assert payloads[1]["salary"] == "20000"
        assert payloads[1]["salmonths"] == "16"

    def test_04d_work_unlisted_industry_job_and_city_fallbacks(self, pusher):
        """测试不在字典中的生僻行业、生僻职位与生僻城市智能推导与兜底机制"""
        # 场景 A: 存在官网现有记录，继承官网已有记录编码
        fields_inherit = {
            "work_experience": {
                "current_value": [
                    {
                        "company": "未来星际探索机构",
                        "position": "火星探索总指挥研发官",
                        "industry": "xyz未知生僻概念领域",
                        "work_city": "生僻未知开发区",
                    }
                ]
            }
        }
        payloads_inherit = pusher._work(fields_inherit)
        assert len(payloads_inherit) == 1
        # 职位推导为研发 N000027，行业继承现有记录 010，城市继承现有记录 050090/050020
        assert payloads_inherit[0]["jobtitle"] == "N000027"
        assert payloads_inherit[0]["industry"] in ("010", "H0001", "H0002")
        assert payloads_inherit[0]["dq"] in ("050090", "050020")

        # 场景 B: 无任何官网旧记录，触发终极智能推导与默认兜底
        pusher.detail = {}
        fields_fresh = {
            "work_experience": {
                "current_value": [
                    {
                        "company": "完全独立新公司A",
                        "position": "火星探索总指挥研发官",  # 包含'研发'推导为技术码 N000027
                        "industry": "xyz未知生僻概念领域",    # 完全未收录 -> 通用兜底 H0001
                        "work_city": "生僻未知开发区",       # 未收录城市 -> 兜底广州 050020
                    },
                    {
                        "company": "美妆新零售工坊",
                        "position": "全域私域用户增长店长",  # 包含'店长/私域' -> 运营码 N000174
                        "industry": "跨境美妆选品贸易",      # 包含'美妆/贸易' -> 电商行业 H0002
                        "work_city": "格陵兰岛",
                    }
                ]
            }
        }
        payloads_fresh = pusher._work(fields_fresh)
        assert len(payloads_fresh) == 2
        # 条目 1: 智能推导为技术码 N000027、科技/IT通用兜底行业 H0001、广州兜底 050020
        assert payloads_fresh[0]["jobtitle"] == "N000027"
        assert payloads_fresh[0]["industry"] == "H0001"
        assert payloads_fresh[0]["dq"] == "050020"
        # 条目 2: 智能推导为运营码 N000174、电商行业 H0002
        assert payloads_fresh[1]["jobtitle"] == "N000174"
        assert payloads_fresh[1]["industry"] == "H0002"

    def test_04e_work_character_limits_and_truncation_full_boundary(self, pusher):
        """测试全字段超长字数安全截断 (100字/50字/1000字/10字) 与不足 10 字职责补齐"""
        long_150 = "超长测试字符串" * 22  # >150 字
        long_2500 = "职责业绩详细展开测试内容描述，包含大量项目细节与指标落地结果。" * 80  # >2500 字
        fields = {
            "work_experience": {
                "current_value": [
                    {
                        "company": long_150,
                        "position": long_150,
                        "department": long_150,
                        "report_to": long_150,
                        "team_size": "12345678901234567890",  # >20 字符
                        "responsibilities": long_2500,
                        "start_date": "2023年09月",
                        "end_date": "2024-03",
                    },
                    {
                        "company": "合规公司B",
                        "position": "合规职位B",
                        "responsibilities": "微调优化",  # 仅 4 个字，不足 10 字
                    }
                ]
            }
        }
        payloads = pusher._work(fields)
        assert len(payloads) == 2
        w1 = payloads[0]
        assert len(w1["compName"]) <= 100, f"公司名称超长应截断为 <= 100 字，实际 {len(w1['compName'])}"
        assert len(w1["title"]) <= 100, f"职位名称超长应截断为 <= 100 字，实际 {len(w1['title'])}"
        assert len(w1["dept"]) <= 100, f"部门超长应截断为 <= 100 字，实际 {len(w1['dept'])}"
        assert len(w1["report2"]) <= 50, f"汇报对象超长应截断为 <= 50 字，实际 {len(w1['report2'])}"
        assert len(w1["duty"]) <= 1000, f"职责业绩超长应截断为 <= 1000 字，实际 {len(w1['duty'])}"
        assert len(w1["subordinate"]) <= 10, f"下属人数超长应截断为 <= 10 字符，实际 {len(w1['subordinate'])}"
        assert w1["startDate"] == "202309"
        assert w1["endDate"] == "202403"

        w2 = payloads[1]
        assert len(w2["duty"]) >= 10, f"过短职责业绩应安全补齐至 >= 10 字，实际 {len(w2['duty'])}"

    def test_05_projects_tripartite_split_and_boundaries(self, pusher):
        fields = {
            "projects": {
                "current_value": [
                    {
                        "project_name": "AI 自动化求职中台",
                        "company": "某某科技",
                        "role": "架构负责人",
                        "start_date": "2026/02",
                        "end_date": "2026/06",
                        "description": "Next.js、FastAPI、ChromaDB 技术栈与背景",
                        "responsibilities": "核心贡献：设计全局流控并发锁，彻底解决 429 报错",
                        "achievements": "业务成果：处理耗时由 4 小时压缩至秒级，提效显著",
                    }
                ]
            }
        }
        payloads = pusher._projects(fields)
        assert len(payloads) == 1
        pj = payloads[0]
        assert pj["name"] == "AI 自动化求职中台"
        assert pj["compName"] == "某某科技"
        assert pj["title"] == "架构负责人"
        assert pj["startDate"] == "202602"
        assert pj["endDate"] == "202606"
        assert pj["desc"] == "Next.js、FastAPI、ChromaDB 技术栈与背景"
        assert pj["duty"] == "核心贡献：设计全局流控并发锁，彻底解决 429 报错"
        assert pj["achievement"] == "业务成果：处理耗时由 4 小时压缩至秒级，提效显著"
        # 严格验证三段互斥不重叠
        assert pj["duty"] not in pj["desc"]
        assert pj["achievement"] not in pj["desc"]

    def test_06_education_module_and_tongzhao(self, pusher):
        fields = {
            "education": {
                "current_value": [
                    {
                        "school": "某财经类大学",
                        "degree": "本科",
                        "major": "软件工程",
                        "start_date": "2015/09",
                        "end_date": "2019/07",
                        "is_tongzhao": True,
                        "campus_experience": "在校期间主修软件工程专业核心课程，多次获得校级奖学金与优秀学生干部荣誉。",
                    }
                ]
            }
        }
        payloads = pusher._education(fields)
        assert len(payloads) == 1
        edu = payloads[0]
        assert edu["school"] == "某财经类大学"
        assert edu["degree"] == "040", "本科 degreeCode 应为 040"
        assert edu["special"] == "软件工程"
        assert edu["startDate"] == "201509"
        assert edu["endDate"] == "201907"
        assert edu["tz"] == "1", "统招应映射为 '1'"
        assert "experience" in edu
        assert len(edu["experience"]) >= 10 and len(edu["experience"]) <= 1000

    def test_06b_education_multi_items_and_campus_experience_boundaries(self, pusher):
        """测试多条教育经历、短在校经历安全补齐、超长截断与 ID 就地更新"""
        pusher.detail = {
            "eduExperiences": [
                {"id": 200179041576, "school": "某财经类大学", "degree": "040"}
            ]
        }
        fields = {
            "education": {
                "current_value": [
                    {
                        "school": "某财经类大学",
                        "degree": "本科",
                        "major": "社会工作",
                        "start_date": "2015/07",
                        "end_date": "2019/07",
                        "is_tongzhao": True,
                        "campus_experience": "数据分析",  # 仅 4 字，不足 10 字
                    },
                    {
                        "school": "某财经类大学",
                        "degree": "硕士",
                        "major": "社会工作",
                        "start_date": "2020年07月",
                        "end_date": "2023年06月",
                        "is_tongzhao": True,
                        "campus_experience": "超长在校经历" * 200,  # > 1000 字超长
                    },
                ]
            }
        }
        payloads = pusher._education(fields)
        assert len(payloads) == 2

        # 第 1 条经历：就地对齐官网原有 ID，短文本安全补齐至 >= 10 字
        e1 = payloads[0]
        assert e1["id"] == 200179041576, "第1条应携带官网已有 ID 就地更新"
        assert e1["degree"] == "040"
        assert e1["startDate"] == "201507"
        assert e1["endDate"] == "201907"
        assert len(e1["experience"]) >= 10, f"短在校经历必须合规补齐至 >= 10 字符，实际 {len(e1['experience'])}"
        assert "数据分析" in e1["experience"]

        # 第 2 条经历：新增无 ID，超长文本安全截断至 <= 1000 字
        e2 = payloads[1]
        assert "id" not in e2, "超出官网条数的新增教育经历不应携带 id"
        assert e2["degree"] == "030", "硕士应映射为 030"
        assert e2["startDate"] == "202007"
        assert e2["endDate"] == "202306"
        assert len(e2["experience"]) <= 1000, f"超长在校经历必须截断为 <= 1000 字符，实际 {len(e2['experience'])}"

    def test_06c_education_push_and_redundancy_cleanup(self, pusher):
        """测试教育经历回传时精准就地更新与多余条目定向清理（不误删已有记录）"""
        pusher.detail = {
            "eduExperiences": [
                {"id": 101, "school": "学校A"},
                {"id": 102, "school": "学校B"},
                {"id": 103, "school": "学校C"},  # 官网多出第3条
            ]
        }
        # 本地只有 2 条教育经历
        fields = {
            "education": {
                "current_value": [
                    {"school": "新学校A", "degree": "本科", "start_date": "2015-09", "end_date": "2019-06"},
                    {"school": "新学校B", "degree": "硕士", "start_date": "2019-09", "end_date": "2022-06"},
                ]
            }
        }

        saved_payloads = []
        deleted_records = []

        def mock_post_json(url, body):
            saved_payloads.append(body.get("data", {}))
            return '{"flag": 1, "data": {}}'

        def mock_delete_records(url, records):
            deleted_records.extend(records)
            return len(records)

        pusher.post_json = mock_post_json
        pusher.delete_records = mock_delete_records

        pusher._push_education(fields)

        # 验证前 2 条带 ID 就地更新且空在校经历显式传递 ""
        assert len(saved_payloads) == 2
        assert saved_payloads[0]["id"] == 101
        assert saved_payloads[0]["experience"] == "", "未填在校经历必须显式传空字符串清空官网"
        assert saved_payloads[1]["id"] == 102
        assert saved_payloads[1]["experience"] == "", "未填在校经历必须显式传空字符串清空官网"

        # 验证仅删除了第 3 条多余记录（id 103），绝对没有误删前两条已更新记录
        assert len(deleted_records) == 1
        assert deleted_records[0]["id"] == 103
        assert pusher.results["education"]["success"] is True

    def test_07_certificates_module(self, pusher):
        fields = {
            "certificates": {
                "current_value": ["大学英语六级", "BEC剑桥商务英语中级", "C1驾驶证"]
            }
        }
        payload, unmapped = pusher._certificates(fields)
        assert payload is not None, f"全部证书应可映射，未命中: {unmapped}"
        assert unmapped == []
        assert payload["encryResId"] == "test_encry_res_id_123456"
        assert "C0002" in payload["credentialCodes"], "CET6 对应 C0002"

    def test_07b_certificates_unmapped_returns_none(self, pusher):
        """存在字典外证书时返回 None + 未映射清单（调用方跳过整表替换，防止官网证书被静默删减）"""
        fields = {
            "certificates": {
                "current_value": ["大学英语六级", "自定义神秘证书ABC"]
            }
        }
        payload, unmapped = pusher._certificates(fields)
        assert payload is None
        assert "自定义神秘证书ABC" in unmapped

    def test_08_skill_tags_max_10_boundary(self, pusher):
        fields = {
            "skill_tags": {
                "current_value": [
                    "Python",
                    "Prompt Engineering",  # 18 字符超长，必须截断为 15 字符 Prompt Engineer
                    "FastAPI",
                    "Next.js",
                    "React",
                    "TypeScript",
                    "LangGraph",
                    "ChromaDB",
                    "SQL",
                    "Tableau",
                    "Docker",
                    "超出第11个标签",
                ]
            }
        }
        payload = pusher._skill_tags(fields)
        assert payload is not None
        assert len(payload["labels"]) == 10, "官网限制最多 10 个技能标签，必须自动截断"
        assert payload["labels"][0] == {"label": "Python", "type": 1}
        assert payload["labels"][1] == {"label": "Prompt Engineer", "type": 1}, "超长标签必须自动安全截断为 <= 15 字符"
        for item in payload["labels"]:
            assert len(item["label"]) <= 15, f"每个标签长度不得超过 15 字符，实际: {item['label']} ({len(item['label'])})"
            assert item["type"] == 1

    def test_09_languages_module(self, pusher):
        fields = {
            "languages": {
                "current_value": [
                    {
                        "language": "英语",
                        "proficiency": "工作应用",
                        "certificate": "CET6",
                    },
                    {
                        "language": "普通话",
                        "proficiency": "商务洽谈",
                        "certificate": "一级甲等",
                    }
                ]
            }
        }
        payloads = pusher._languages(fields)
        assert len(payloads) == 2
        p0 = payloads[0]
        assert p0["code"] == "11"
        assert p0["degreeCode"] == "1112"
        assert p0["levelCode"] == "1104"
        assert p0.get("originalCode") == "11"

    def test_10_additional_info_module(self, pusher):
        fields = {
            "additional_info": {
                "current_value": "持有 CET-6 证书与 C1 驾照，具备良好的英文技术文档阅读能力。"
            }
        }
        v = fields["additional_info"]["current_value"]
        assert len(v) <= 1000
        assert "CET-6" in v


# ============================================================================
# 3. 集成测试：真实 live dump 解析与 Fast API 8000 路由联动
# ============================================================================

class TestLiepinIntegrationWithFastAPI:
    """测试真实猎聘数据解析以及与主后端 FastAPI 8000 端口各路由的完整闭环"""

    def test_01_parse_live_api_dump_and_reconvert(self):
        live_dump_path = os.path.join(DATA_DIR, "liepin_live_api_dump.json")
        if not os.path.exists(live_dump_path):
            pytest.skip("liepin_live_api_dump.json 不存在")

        with open(live_dump_path, "r", encoding="utf-8") as f:
            live_resume = json.load(f)

        # 1) 使用采集器解析 live dump
        fields = build_liepin_fields(live_resume)
        assert "basic_info" in fields
        assert "work_experience" in fields
        assert "projects" in fields
        assert "education" in fields

        # 2) 使用推送转换器将 fields 重新转化为回写 payload
        pusher = LiepinPusher(ALL_MODULES)
        pusher.res_id = live_resume.get("resId", "mock_res_id")
        pusher.detail = live_resume

        bi_form = pusher._bi(fields)
        assert bi_form["encryResId"] == pusher.res_id
        assert "realName" in bi_form or "sex" in bi_form

        work_payloads = pusher._work(fields)
        assert isinstance(work_payloads, list)
        for w in work_payloads:
            assert "compName" in w
            assert "title" in w

        pj_payloads = pusher._projects(fields)
        assert isinstance(pj_payloads, list)
        for pj in pj_payloads:
            assert "name" in pj
            assert "desc" in pj
            assert "duty" in pj
            assert "achievement" in pj

    def test_02_fastapi_get_and_save_liepin_endpoints(self):
        # GET 猎聘数据
        resp = client.get("/api/resume-editor/liepin")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        fields = data.get("data", {})
        assert "basic_info" in fields
        assert "work_experience" in fields
        assert "projects" in fields

        # 保存快照写回源
        resp_wb = client.post("/api/agent-map/writeback-save", json={"platform": "liepin"})
        assert resp_wb.status_code == 200
        assert resp_wb.json().get("success") is True

        # 验证 liepin_writeback.json 已成功创建
        wb_path = os.path.join(DATA_DIR, "liepin_writeback.json")
        assert os.path.exists(wb_path)
        with open(wb_path, "r", encoding="utf-8") as f:
            wb_data = json.load(f)
        assert "fields" in wb_data
        assert "meta" in wb_data


# ============================================================================
# 4. 端到端测试 (E2E)：DrissionPage 连通与真机环境探查
# ============================================================================

class TestLiepinDrissionPageE2E:
    """通过 DrissionPage 连接真机 9226 端口探查猎聘登录态与 DOM/API"""

    def test_01_drissionpage_port_9226_live_check(self):
        from app.session.health_checker import probe_port
        is_alive = probe_port(9226)
        if not is_alive:
            pytest.skip("猎聘 Edge 浏览器 (端口 9226) 未启动")

        from DrissionPage import ChromiumPage, ChromiumOptions
        co = ChromiumOptions()
        co.set_local_port(9226)
        page = ChromiumPage(co)
        assert page is not None
        assert "liepin" in page.url or "c.liepin.com" in page.url or "passport" in page.url
        print(f"\n[E2E] Connected to Liepin browser at {page.url}")
