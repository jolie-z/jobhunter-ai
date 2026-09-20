# -*- coding: utf-8 -*-
"""
51job 专业技能 (skills) 模块全链路测试套件 (100% 覆盖)
涵盖：
1. 官方 5 大类 81 项标准技能字典完整性与合法性校验
2. 语言类技能 (22xx) 隔离与防御性过滤
3. 简历映射中技能字段构建与对齐
4. 专业技能新增/修改/删除/no-op 载荷构建与规范化
5. 技能互斥与防重复添加逻辑
6. 熟练程度多格式兼容 (0:精通, 1:熟练, 3:良好, 4/2:一般/了解)
7. 大小写与别名归一化模糊匹配
8. 复核验证器 (verify_results) 各种成功与异常分支
9. 全生命周期回写编排与端到端模拟
"""
import os
import json
import pytest
from resume_editor.agent_mapper import (
    _load_job51_it_skills_index,
    _map_51job_skills,
    DATA_DIR,
)
from resume_editor.platforms.job51_write_back import (
    _strip_add_item,
    _build_edit_payload,
    _key_same,
    _match_official,
    plan_writeback,
    verify_results,
)


class TestJob51SkillsOfficialDictionary:
    """51job 官网专业技能字典（5大分类，81项标准IT技能）完整性与合法性校验"""

    def test_official_skills_json_structure(self):
        """测试 51job_skills.json 数据结构严格对齐官网 5 大类 81 项技能"""
        p = os.path.join(DATA_DIR, "51job_skills.json")
        assert os.path.exists(p), "51job_skills.json 必须存在"
        with open(p, "r", encoding="utf-8") as f:
            categories = json.load(f)

        assert len(categories) == 5, f"官网标准分类应为 5 大类，实际为 {len(categories)}"
        cat_map = {c["code"]: c for c in categories}
        assert "0200" in cat_map and cat_map["0200"]["name"] == "大数据类"
        assert "0400" in cat_map and cat_map["0400"]["name"] == "开发编程类"
        assert "1300" in cat_map and cat_map["1300"]["name"] == "多媒体设计类"
        assert "2100" in cat_map and cat_map["2100"]["name"] == "办公应用软件"
        assert "2300" in cat_map and cat_map["2300"]["name"] == "财务管理类"

        # 绝对不应包含语言类 (2200)
        assert "2200" not in cat_map, "专业技能字典严禁包含语言类 (2200)"

        total_skills = sum(len(c["children"]) for c in categories)
        assert total_skills == 81, f"官网标准技能总数应为 81 项，实际为 {total_skills}"

        for cat in categories:
            for item in cat["children"]:
                assert item.get("code") and len(item["code"]) == 4, f"技能代码必须为4位字符: {item}"
                assert item.get("name") and len(item["name"].strip()) > 0, f"技能名称不能为空: {item}"
                # 代码前两位需与分类前两位一致
                assert item["code"][:2] == cat["code"][:2], f"技能代码 {item['code']} 与分类 {cat['code']} 前缀不匹配"

    def test_official_it_skills_json_no_language(self):
        """测试 51job_it_skills.json 已经剔除 2200 语言类"""
        p = os.path.join(DATA_DIR, "51job_it_skills.json")
        with open(p, "r", encoding="utf-8") as f:
            categories = json.load(f)
        codes = [c.get("code") for c in categories]
        assert "2200" not in codes
        assert len(categories) == 5
        total_items = sum(len(c.get("items", [])) for c in categories)
        assert total_items == 81


class TestJob51SkillsDictIndex:
    """51job 官方专业技能字典与别名反查测试"""

    def test_load_skills_index_basic(self):
        idx = _load_job51_it_skills_index()
        assert len(idx) >= 81
        # 核心技能验证
        assert "python" in idx
        assert idx["python"] == ("0413", "Python")
        assert "数据分析" in idx
        assert idx["数据分析"] == ("0202", "数据分析")
        assert "sql" in idx
        assert idx["sql"] == ("0215", "SQL")
        assert "web前端" in idx
        assert idx["web前端"] == ("0416", "Web前端")

    def test_skills_aliases(self):
        idx = _load_job51_it_skills_index()
        # 常见技术别名
        assert idx.get("python3") == ("0413", "Python")
        assert idx.get("js") == ("0410", "JavaScript")
        assert idx.get("excel") == ("2109", "MS Excel")
        assert idx.get("ps") == ("1301", "Photoshop")
        assert idx.get("vue") == ("0416", "Web前端")
        assert idx.get("react") == ("0416", "Web前端")
        assert idx.get("next.js") == ("0416", "Web前端")


class TestJob51SkillsMapping:
    """51job 简历映射中技能字段构建与对齐测试"""

    def test_map_51job_skills_normalizes_existing_items(self):
        report = {
            "fields": [
                {
                    "path": "skills",
                    "value": [
                        {"skillName": "Python", "ability": "0"},
                        {"skill": "数据分析", "level": "1"},
                        {"skillName": "Web前端", "ability": "3"},
                    ]
                }
            ]
        }
        master = {"data": {}}
        res = _map_51job_skills(report, master)
        skills = next(f["value"] for f in res["fields"] if f["path"] == "skills")
        assert len(skills) == 3
        # Python
        assert skills[0]["skillType"] == "0413"
        assert skills[0]["skillName"] == "Python"
        assert skills[0]["ability"] == "0"
        assert skills[0]["abilityString"] == "精通"
        assert skills[0]["isEnglish"] is False
        # 数据分析
        assert skills[1]["skillType"] == "0202"
        assert skills[1]["skillName"] == "数据分析"
        assert skills[1]["ability"] == "1"
        assert skills[1]["abilityString"] == "熟练"
        assert skills[1]["isEnglish"] is False
        # Web前端
        assert skills[2]["skillType"] == "0416"
        assert skills[2]["skillName"] == "Web前端"
        assert skills[2]["ability"] == "3"
        assert skills[2]["abilityString"] == "良好"

    def test_map_51job_skills_filters_invalid_headers_and_non_whitelist(self):
        report = {
            "fields": [
                {
                    "path": "skills",
                    "value": [
                        {"skillName": "大模型与 AI 工程", "ability": ""},
                        {"skillName": "全栈开发与架构", "ability": ""},
                        {"skillName": "Python", "ability": "0"},
                        {"skillName": "SQL", "ability": "1"},
                        {"skillName": "SomeRandomUnknownTech", "ability": ""},
                    ]
                }
            ]
        }
        master = {"data": {}}
        res = _map_51job_skills(report, master)
        skills = next(f["value"] for f in res["fields"] if f["path"] == "skills")
        names = [s["skillName"] for s in skills]
        # 确保大标题和非白名单词被彻底过滤
        assert "大模型与 AI 工程" not in names
        assert "全栈开发与架构" not in names
        assert "SomeRandomUnknownTech" not in names
        # 确保官方标准技能被正确保留并补齐结构
        assert "Python" in names
        assert "SQL" in names
        assert all(s["skillType"] for s in skills)
        assert all(s["ability"] in ("0", "1", "3", "2") for s in skills)
        assert all(s["isEnglish"] is False for s in skills)


class TestJob51SkillsWriteBackPayload:
    """51job 专业技能新增与编辑载荷构建测试"""

    def test_strip_add_item_skills(self):
        item = {
            "skillName": "Python",
            "skillType": "0413",
            "ability": 1,
            "abilityString": "熟练",
        }
        res = _strip_add_item(item)
        assert res["skillType"] == "0413"
        assert res["skillName"] == "Python"
        assert res["ability"] == "1"
        assert res["isEnglish"] is False

    def test_build_edit_payload_skills(self):
        official = {
            "id": "214371185",
            "resumeId": "369525152",
            "skillType": "0413",
            "skillName": "Python",
            "ability": "3",
            "isEnglish": False,
        }
        local_edit = {
            "skillType": "0413",
            "skillName": "Python",
            "ability": "0",  # 改为精通
        }
        res = _build_edit_payload(local_edit, official)
        assert res["id"] == "214371185"
        assert res["skillType"] == "0413"
        assert res["skillName"] == "Python"
        assert res["ability"] == "0"
        assert res["isEnglish"] is False


class TestJob51SkillsMatchingAndDiff:
    """51job 专业技能比对与配对测试"""

    def test_key_same_skills(self):
        local = {"skillType": "0413", "skillName": "Python", "ability": "1"}
        official = {"skillType": "0413", "skillName": "Python", "ability": "1"}
        assert _key_same("skillType", local, official) is True
        assert _key_same("skillName", local, official) is True
        assert _key_same("ability", local, official) is True

    def test_key_same_different_ability(self):
        local = {"skillType": "0413", "ability": "0"}
        official = {"skillType": "0413", "ability": "1"}
        assert _key_same("ability", local, official) is False

    def test_match_official_skills(self):
        off_items = [
            {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
            {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
        ]
        # 本地条目（无 id）
        item = {"skill": "0413", "skillName": "Python", "ability": "0"}
        matched = _match_official(item, off_items, set(), "skills")
        assert matched is not None
        assert matched["id"] == "201"

    def test_match_official_skills_case_insensitive(self):
        off_items = [
            {"id": "201", "skillType": "0416", "skillName": "Web前端", "ability": "3"},
        ]
        item = {"skillName": "web前端", "ability": "3"}
        matched = _match_official(item, off_items, set(), "skills")
        assert matched is not None
        assert matched["id"] == "201"


class TestJob51SkillsPlanAndVerify:
    """51job 专业技能回写规划与复核测试"""

    def test_plan_writeback_skills_noop(self):
        local = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"id": "203", "skillType": "0416", "skillName": "Web前端", "ability": "3"},
            ]
        }
        official = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"id": "203", "skillType": "0416", "skillName": "Web前端", "ability": "3"},
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["skills"])
        assert len(plan["actions"]) == 0
        assert len(plan["skipped"]) == 1
        assert "3 条 no-op" in plan["skipped"][0]["reason"]

    def test_plan_writeback_skills_add_and_edit_and_del(self):
        local = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "0"},  # edit: 1 -> 0
                {"skillType": "0202", "skillName": "数据分析", "ability": "1"},             # add: 数据分析
            ]
        }
        official = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},     # del: SQL
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["skills"])
        actions = plan["actions"]
        assert len(actions) == 3

        ops = {a["op"]: a for a in actions}
        assert ops["edit"]["method"] == "getSkillItEdit"
        assert ops["edit"]["args"][1] == "201"
        assert ops["edit"]["args"][2]["ability"] == "0"

        assert ops["add"]["method"] == "getSkillItAdd"
        assert ops["add"]["args"][1]["skillType"] == "0202"
        assert ops["add"]["args"][1]["isEnglish"] is False

        assert ops["del"]["method"] == "getSkillItDel"
        assert ops["del"]["args"][1] == "202"

    def test_plan_writeback_skills_filters_language_skills(self):
        """测试专业技能规划时自动过滤属于语言类的条目（如 2201 英语、2213 粤语），防止错位回写"""
        local = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "3"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"skillType": "2201", "skillName": "英语", "skillCategory": "语言类", "ability": "0"},
                {"skillType": "2213", "skillName": "粤语", "skillCategory": "语言类", "ability": "0"},
            ]
        }
        official = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "3"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["skills"])
        # 语言类被过滤后，剩余 2 项与官网完全一致，无需发送任何 add/edit
        assert len(plan["actions"]) == 0
        assert len(plan["skipped"]) == 1
        assert "2 条 no-op" in plan["skipped"][0]["reason"]

    def test_plan_writeback_skills_deduplicates_duplicate_local_entries(self):
        """测试当本地数据出现重复填写的技能（如多次添加 SQL/Python 但熟练度不同）时，自动互斥去重，避免重复 add/edit 冲突"""
        local = {
            "skills": [
                {"id": "201", "skillType": "0215", "skillName": "SQL", "ability": "1"},       # 熟练
                {"id": "202", "skillType": "0413", "skillName": "Python", "ability": "3"},    # 良好
                {"skillType": "0215", "skillName": "SQL", "ability": "3"},                    # 重复添加 SQL
                {"skillType": "0413", "skillName": "Python", "ability": "1"},                 # 重复添加 Python
            ]
        }
        official = {
            "skills": [
                {"id": "201", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"id": "202", "skillType": "0413", "skillName": "Python", "ability": "3"},
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["skills"])
        # 去重后，两条与官网完全一致，不应产生重复的 add/edit 操作
        assert len(plan["actions"]) == 0
        assert len(plan["skipped"]) == 1
        assert "与官网一致（2 条 no-op）" in plan["skipped"][0]["reason"]

    def test_verify_results_skills_success(self):
        local = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"id": "203", "skillType": "0416", "skillName": "Web前端", "ability": "3"},
            ]
        }
        official = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"id": "203", "skillType": "0416", "skillName": "Web前端", "ability": "3"},
            ]
        }
        res = verify_results(official, local, {"actions": [{"module": "skills"}]})
        assert len(res) == 1
        assert res[0]["module"] == "skills"
        assert res[0]["match"] is True
        assert res[0]["note"] == "3 条已生效"

    def test_verify_results_skills_count_mismatch(self):
        """测试当官网技能条数与本地不一致时，精准报警"""
        local = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"skillType": "0416", "skillName": "Web前端", "ability": "3"},
                {"skillType": "2201", "skillName": "英语", "ability": "0"},
                {"skillType": "2213", "skillName": "粤语", "ability": "0"},
            ]
        }
        official = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},
                {"id": "202", "skillType": "0215", "skillName": "SQL", "ability": "1"},
                {"id": "203", "skillType": "0416", "skillName": "Web前端", "ability": "3"},
            ]
        }
        res = verify_results(official, local, {"actions": [{"module": "skills"}]})
        assert len(res) == 1
        assert res[0]["module"] == "skills"
        assert res[0]["match"] is False
        assert "条数不一致 官网3 vs 本地5" in res[0]["note"]

    def test_verify_results_skills_ability_mismatch(self):
        """测试当技能熟练度属性不一致时，精准报警"""
        local = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "0"},  # 本地精通
            ]
        }
        official = {
            "skills": [
                {"id": "201", "skillType": "0413", "skillName": "Python", "ability": "1"},  # 官网熟练
            ]
        }
        res = verify_results(official, local, {"actions": [{"module": "skills"}]})
        assert len(res) == 1
        assert res[0]["module"] == "skills"
        assert res[0]["match"] is False
        assert "ability" in res[0]["note"]
