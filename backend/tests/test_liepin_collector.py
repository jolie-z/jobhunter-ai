import pytest
import os
import sys
import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from resume_editor.platforms.liepin_collector import (
    build_liepin_fields,
    save_data,
    OUTPUT_PATH,
    DATA_DIR,
    PORT,
)
from app.session.health_checker import probe_port, _no_proxy_opener

client = TestClient(app)

FIXTURE_PATH = os.path.join(DATA_DIR, "liepin_detail_fixture.json")


class TestLiepinParser:
    """猎聘简历 API 数据解析与结构化映射测试集"""

    @pytest.fixture
    def real_fixture_data(self):
        """加载猎聘真实 web-resume-detail 响应 fixture"""
        if os.path.exists(FIXTURE_PATH):
            with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
                content = json.load(f)
                return content.get("data", {})
        return {}

    def test_01_parse_real_fixture_all_10_modules(self, real_fixture_data):
        """使用真实官网抓包 Fixture 验证 10 大模块全部完整解析"""
        if not real_fixture_data:
            pytest.skip("Fixture liepin_detail_fixture.json 不存在")

        fields = build_liepin_fields(real_fixture_data)
        assert isinstance(fields, dict)

        # 1. 验证 10 大核心字段全部存在
        expected_modules = [
            "basic_info",
            "self_assessment",
            "expectations",
            "work_experience",
            "projects",
            "education",
            "certificates",
            "skill_tags",
            "languages",
            "additional_info",
        ]
        for mod in expected_modules:
            assert mod in fields, f"缺失模块: {mod}"
            assert "current_value" in fields[mod]
            assert "label" in fields[mod]

        # 2. 验证基本信息具体字段
        bi = fields["basic_info"]["current_value"]
        assert bi["name"] == "张三" or bi["name"] == "张女士"
        assert bi["gender"] == "女"
        assert bi["phone"] == "138****8000"
        assert bi["city"] == "广州"
        assert bi["identity"] == "职场人"
        assert bi["show_gender_suffix"] is True
        assert bi["salary_confidential"] is True
        assert bi["current_salary_month"] == "11700"
        assert bi["current_salary_months"] == "14"

        # 3. 验证优势亮点
        sa = fields["self_assessment"]["current_value"]
        assert "全英文跨国沟通" in sa
        assert "全栈研发与大模型生态" in sa

        # 4. 验证求职期望
        exp = fields["expectations"]["current_value"]
        assert len(exp) >= 1
        assert exp[0]["position"] == "数据标注/AI训练师"
        assert exp[0]["city"] == "广州"
        assert "深圳" in exp[0]["other_cities"]
        assert exp[0]["salary_min"] == "15k"
        assert exp[0]["salary_max"] == "25k"
        assert exp[0]["salary_months"] == 14

        # 5. 验证工作经历
        work = fields["work_experience"]["current_value"]
        assert len(work) == 2
        assert work[0]["company"] == "广州青梧美妆网络科技有限公司"
        assert work[0]["position"] == "电商副店长（统筹运营）"
        assert work[0]["start_date"] == "2023/09"
        assert work[0]["end_date"] == "2024/03"
        assert work[0]["hide_resume"] is False
        assert work[0]["is_internship"] is False
        assert "虚拟组套" in work[0]["responsibilities"]

        assert work[1]["position"] == "AI 业务运营 / 智能客服训练师"
        assert work[1]["start_date"] == "2019/07"
        assert work[1]["end_date"] == "2023/08"
        assert work[1]["team_size"] == "3"

        # 6. 验证项目经历（包含“至今”与 9999 年月解析）
        proj = fields["projects"]["current_value"]
        assert len(proj) == 5
        assert proj[0]["project_name"] == "基于大模型的全自动岗位抓取与深度评估系统"
        assert proj[0]["end_date"] == "至今"  # 9999/99 正确映射为至今
        assert "开源方案集成" in proj[0]["responsibilities"]

        # 7. 验证教育经历
        edu = fields["education"]["current_value"]
        assert len(edu) == 1
        assert edu[0]["school"] == "某财经类大学"
        assert edu[0]["degree"] == "本科"
        assert edu[0]["major"] == "社会工作"
        assert edu[0]["is_tongzhao"] is True

        # 8. 验证资格证书
        certs = fields["certificates"]["current_value"]
        assert "大学英语六级" in certs

        # 9. 验证技能标签
        skills = fields["skill_tags"]["current_value"]
        assert "智能客服知识库建设" in skills
        assert "AIGC技术落地与应用" in skills

        # 10. 验证语言能力
        langs = fields["languages"]["current_value"]
        assert len(langs) == 3
        assert langs[0]["language"] == "英语"
        assert langs[0]["proficiency"] == "商务洽谈"
        assert langs[0]["certificate"] == "CET6"

        # 11. 验证附加信息
        add_info = fields["additional_info"]["current_value"]
        assert "BEC商务英语中级" in add_info

    def test_02_empty_and_minimal_payload(self):
        """测试空/残缺报文下的防御能力，确保不抛异常并给出默认结构"""
        fields = build_liepin_fields({})
        assert isinstance(fields, dict)
        assert fields["basic_info"]["current_value"]["name"] == ""
        assert fields["basic_info"]["current_value"]["identity"] == "职场人"
        assert fields["self_assessment"]["current_value"] == ""
        assert fields["expectations"]["current_value"] == []
        assert fields["work_experience"]["current_value"] == []
        assert fields["projects"]["current_value"] == []
        assert fields["education"]["current_value"] == []
        assert fields["certificates"]["current_value"] == []
        assert fields["skill_tags"]["current_value"] == []
        assert fields["languages"]["current_value"] == []
        assert fields["additional_info"]["current_value"] == ""

    def test_03_student_identity_and_suffix_boundary(self):
        """测试学生身份、女士后缀与薪资保密等边界条件"""
        resume = {
            "baseInfo": {
                "showName": "张同学",
                "realName": "张三",
                "fromStudent": True,
                "nowSalarySecret": 0,
                "nowSalary": 8000,
                "nowSalaryMonths": 12,
            },
            "labels": ["Python", "FastAPI", "React"],  # 字符串列表模式
        }
        fields = build_liepin_fields(resume)
        bi = fields["basic_info"]["current_value"]
        assert bi["identity"] == "学生"
        assert bi["show_gender_suffix"] is False
        assert bi["salary_confidential"] is False
        assert bi["current_salary_month"] == "8000"

        # 技能标签字符串列表正确解析
        assert fields["skill_tags"]["current_value"] == ["Python", "FastAPI", "React"]

    def test_04_work_experience_ongoing_to_date_mapping(self):
        """测试工作经历在职时间（9999/99、999999、空值）精准映射为“至今”"""
        resume = {
            "workExperiences": [
                {
                    "compName": "自由职业者",
                    "title": "AI应用开发者",
                    "startYear": "2024",
                    "startMonth": "04",
                    "endYear": "9999",
                    "endMonth": "99",
                    "end": 999999,
                },
                {
                    "compName": "前公司A",
                    "title": "运营经理",
                    "startYear": "2023",
                    "startMonth": "09",
                    "endYear": "",
                    "endMonth": "",
                },
                {
                    "compName": "前公司B",
                    "title": "项目主管",
                    "startYear": "2019",
                    "startMonth": "07",
                    "endYear": "2023",
                    "endMonth": "08",
                    "end": 202308,
                }
            ]
        }
        fields = build_liepin_fields(resume)
        works = fields["work_experience"]["current_value"]
        assert len(works) == 3
        # 1. 9999/99 -> 至今
        assert works[0]["end_date"] == "至今"
        assert works[0]["start_date"] == "2024/04"
        # 2. 空 endYear -> 至今
        assert works[1]["end_date"] == "至今"
        # 3. 正常离职时间 -> 2023/08
        assert works[2]["end_date"] == "2023/08"

    def test_05_languages_mandarin_and_level_mapping(self):
        """测试语言能力（包括普通话及等级、掌握程度）的解析与字典对齐"""
        resume = {
            "languages": [
                {
                    "name": "普通话",
                    "degreeName": "商务洽谈",
                    "degreeCode": "1409",
                    "levelName": "一级甲等",
                    "levelCode": "1401",
                    "code": "14",
                },
                {
                    "name": "英语",
                    "degreeName": "工作应用",
                    "degreeCode": "1112",
                    "levelName": "CET6",
                    "levelCode": "1104",
                    "code": "11",
                },
                {
                    "name": "粤语",
                    "degreeName": "基础沟通",
                    "degreeCode": "1501",
                    "code": "15",
                }
            ]
        }
        fields = build_liepin_fields(resume)
        langs = fields["languages"]["current_value"]
        assert len(langs) == 3

        # 1. 普通话字段
        assert langs[0]["language"] == "普通话"
        assert langs[0]["proficiency"] == "商务洽谈"
        assert langs[0]["level"] == "一级甲等"
        assert langs[0]["levelCode"] == "1401"
        assert langs[0]["degreeCode"] == "1409"

        # 2. 英语字段
        assert langs[1]["language"] == "英语"
        assert langs[1]["proficiency"] == "工作应用"
        assert langs[1]["certificate"] == "CET6"
        assert langs[1]["level"] == "CET6"

        # 3. 粤语字段（无语言等级）
        assert langs[2]["language"] == "粤语"
        assert langs[2]["proficiency"] == "基础沟通"
        assert langs[2]["level"] == ""


class TestLiepinDataSaveAndMerge:
    """猎聘数据保存与防覆盖保护测试"""

    def test_01_save_data_creates_file_and_preserves_structure(self, monkeypatch, tmp_path):
        """测试保存数据并验证字段完整性"""
        test_file = str(tmp_path / "liepin_test.json")
        monkeypatch.setattr("resume_editor.platforms.liepin_collector.OUTPUT_PATH", test_file)
        monkeypatch.setattr("resume_editor.platforms.liepin_collector.DATA_DIR", str(tmp_path))

        # 3 个非空模块：满足统一落盘的空数据拦截阈值（min_non_empty=3）
        test_data = {
            "basic_info": {"label": "基本信息", "current_value": {"name": "测试员"}},
            "self_assessment": {"label": "优势亮点", "current_value": "优势文本"},
            "work_experience": {"label": "工作经历", "current_value": [{"company": "测试公司"}]},
        }
        save_data(test_data)

        assert os.path.exists(test_file)
        with open(test_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["basic_info"]["current_value"]["name"] == "测试员"
        assert saved["self_assessment"]["current_value"] == "优势文本"


class TestLiepinCollectorApiEndpoints:
    """FastAPI 路由接口集成测试 (/api/resume-editor)"""

    @pytest.fixture(autouse=True)
    def backup_restore_data(self):
        """自动备份与还原 liepin_fields.json，保证测试隔离性"""
        backup_content = None
        if os.path.exists(OUTPUT_PATH):
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                backup_content = f.read()
        yield
        if backup_content is not None:
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                f.write(backup_content)

    def test_01_get_liepin_fields(self):
        """测试 GET /api/resume-editor/liepin 能够正确返回 10 大模块结构"""
        res = client.get("/api/resume-editor/liepin")
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") is True
        fields = data.get("data", {})
        assert isinstance(fields, dict)
        assert "work_experience" in fields
        assert "education" in fields
        assert "basic_info" in fields
        assert len(fields) >= 10

    def test_02_save_liepin_fields_snapshot(self):
        """测试 POST /api/resume-editor/save/liepin 能够正确更新保存快照"""
        res_get = client.get("/api/resume-editor/liepin")
        fields = res_get.json().get("data", {})

        # 尝试更新附加信息
        if "additional_info" in fields:
            orig_val = fields["additional_info"].get("current_value", "")
            fields["additional_info"]["current_value"] = f"{orig_val} [test_token]"

        res_save = client.post("/api/resume-editor/save/liepin", json=fields)
        assert res_save.status_code == 200
        assert res_save.json().get("success") is True

        # 验证读取出的最新值确实包含更新
        res_check = client.get("/api/resume-editor/liepin")
        updated_fields = res_check.json().get("data", {})
        if "additional_info" in updated_fields:
            assert "[test_token]" in updated_fields["additional_info"]["current_value"]

    def test_03_collect_liepin_dispatch(self, monkeypatch):
        """测试 POST /api/unified/collect 调度猎聘采集脚本"""
        # Mock subprocess.run to verify proper command line invocation
        import subprocess

        called_cmd = []

        def mock_run(cmd, *args, **kwargs):
            called_cmd.extend(cmd)
            class MockResult:
                returncode = 0
                stdout = "[OK] 数据已保存: liepin_fields.json\n[OK] 共 10 个字段"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)
        # 端点在调度脚本前有浏览器端口预检（probe_port），测试环境猎聘 Edge 离线必须 mock 掉
        monkeypatch.setattr("app.api.resume_editor.unified_routes.probe_port", lambda *a, **k: True)

        res = client.post("/api/unified/collect", json={"platforms": ["liepin"]})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert any("liepin_collector.py" in str(arg) for arg in called_cmd)


class TestLiepinLivePortE2E:
    """猎聘 Edge 浏览器 9226 端口真机连通性与采集自适应测试"""

    def test_01_live_port_status_check(self):
        """自适应探测 9226 端口连通性"""
        port_open = probe_port(PORT)
        if not port_open:
            pytest.skip(f"猎聘 Edge 浏览器 (端口 {PORT}) 未启动，跳过真机 CDP 探查")

        # 端口若开放，则断言 CDP /json 接口必须能在 1.5s 内返回有效 Tab 列表
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/json")
        with _no_proxy_opener.open(req, timeout=1.5) as resp:
            assert resp.status == 200
            tabs = json.loads(resp.read().decode())
            assert isinstance(tabs, list)
