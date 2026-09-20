# -*- coding: utf-8 -*-
"""
51job 语言能力 (language) 模块全链路测试套件
涵盖：证书归一化、新增/编辑载荷规范化(isEnglish防100004)、键比对、匹配器、回写规划与结果复核
"""
import pytest
from resume_editor.platforms.job51_write_back import (
    _norm_lang_certs,
    _strip_add_item,
    _build_edit_payload,
    _key_same,
    _match_official,
    plan_writeback,
    verify_results,
)


class TestJob51LanguageCertsNorm:
    """语言能力证书与字段归一化测试"""

    def test_norm_lang_certs_empty(self):
        assert _norm_lang_certs(None) == []
        assert _norm_lang_certs([]) == []
        assert _norm_lang_certs("") == []

    def test_norm_lang_certs_str_codes(self):
        codes = ["0117", "0108"]
        res = _norm_lang_certs(codes)
        assert len(res) == 2
        assert res[0] == {"cert": "0117", "certString": ""}
        assert res[1] == {"cert": "0108", "certString": ""}

    def test_norm_lang_certs_dict_objects(self):
        certs = [
            {"code": "0117", "value": "大学英语六级"},
            {"cert": "0108", "certString": "剑桥商务英语中级"},
        ]
        res = _norm_lang_certs(certs)
        assert len(res) == 2
        assert res[0] == {"cert": "0117", "certString": "大学英语六级"}
        assert res[1] == {"cert": "0108", "certString": "剑桥商务英语中级"}

    def test_norm_lang_certs_preserves_existing_queries(self):
        queries = [{"cert": "0116", "certString": "大学英语四级"}]
        res = _norm_lang_certs([], cert_queries=queries)
        assert res == queries


class TestJob51LanguagePayloadBuilding:
    """语言能力新增与编辑载荷构建测试"""

    def test_strip_add_item_language(self):
        item = {
            "skill": "2201",
            "skillString": "英语",
            "ability": 6,
            "abilityString": "听说读写流利",
            "certifications": ["0117", "0108"],
        }
        res = _strip_add_item(item)
        # 必须转为官方规范字段
        assert res["skillType"] == "2201"
        assert res["skillName"] == "英语"
        assert res["ability"] == "6"
        assert res["isEnglish"] is False  # 官方必填，缺失即报 100004
        assert len(res["skillCertificationQueries"]) == 2
        assert "skill" not in res
        assert "skillString" not in res
        assert "certifications" not in res

    def test_build_edit_payload_language(self):
        official = {
            "id": "217654821",
            "resumeId": "369525152",
            "skillType": "2201",
            "skillName": "英语",
            "ability": "5",
            "abilityString": "熟练",
            "isEnglish": False,
        }
        local_edit = {
            "skill": "2201",
            "skillName": "英语",
            "ability": "6",
            "certifications": ["0117"],
        }
        res = _build_edit_payload(local_edit, official)
        assert res["id"] == "217654821"
        assert res["skillType"] == "2201"
        assert res["skillName"] == "英语"
        assert res["ability"] == "6"
        assert res["isEnglish"] is False
        assert len(res["skillCertificationQueries"]) == 1
        assert res["skillCertificationQueries"][0]["cert"] == "0117"


class TestJob51LanguageKeySameAndMatching:
    """语言能力比对与配对测试"""

    def test_key_same_skill_type(self):
        local = {"skill": "2201", "ability": "6"}
        official = {"skillType": "2201", "ability": "6"}
        assert _key_same("skillType", local, official) is True
        assert _key_same("ability", local, official) is True

    def test_key_same_different_ability(self):
        local = {"skillType": "2201", "ability": "6"}
        official = {"skillType": "2201", "ability": "5"}
        assert _key_same("skillType", local, official) is True
        assert _key_same("ability", local, official) is False

    def test_match_official_language(self):
        off_items = [
            {"id": "101", "skillType": "2201", "skillName": "英语", "ability": "6"},
            {"id": "102", "skillType": "2210", "skillName": "普通话", "ability": "6"},
        ]
        # 本地条目（无 id，skill 键）
        item_mandarin = {"skill": "2210", "skillString": "普通话", "ability": "6"}
        matched = _match_official(item_mandarin, off_items, set(), "language")
        assert matched is not None
        assert matched["id"] == "102"


class TestJob51LanguagePlanAndVerify:
    """语言能力回写规划与复核测试"""

    def test_plan_writeback_language_noop(self):
        local = {
            "language": [
                {"id": "101", "skillType": "2201", "ability": "6"},
                {"id": "102", "skillType": "2210", "ability": "6"},
            ]
        }
        official = {
            "language": [
                {"id": "101", "skillType": "2201", "ability": "6"},
                {"id": "102", "skillType": "2210", "ability": "6"},
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["language"])
        assert len(plan["actions"]) == 0
        assert len(plan["skipped"]) == 1

    def test_plan_writeback_language_add_and_edit_and_del(self):
        local = {
            "language": [
                {"id": "101", "skill": "2201", "ability": "6"},       # edit: ability 5 -> 6
                {"skill": "2213", "skillString": "粤语", "ability": "6"}, # add: 粤语
            ]
        }
        official = {
            "language": [
                {"id": "101", "skillType": "2201", "ability": "5"},
                {"id": "102", "skillType": "2210", "ability": "6"},   # del: 普通话
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["language"])
        actions = plan["actions"]
        assert len(actions) == 3

        ops = {a["op"]: a for a in actions}
        assert "edit" in ops
        assert ops["edit"]["method"] == "languageEdit"
        assert ops["edit"]["args"][1] == "101"
        assert ops["edit"]["args"][2]["ability"] == "6"

        assert "add" in ops
        assert ops["add"]["method"] == "languageAdd"
        assert ops["add"]["args"][1]["skillType"] == "2213"
        assert ops["add"]["args"][1]["isEnglish"] is False

        assert "del" in ops
        assert ops["del"]["method"] == "languageDel"
        assert ops["del"]["args"][1] == "102"

    def test_verify_results_language(self):
        local = {
            "language": [
                {"id": "101", "skillType": "2201", "ability": "6", "certifications": ["0117"]},
                {"id": "102", "skillType": "2210", "ability": "6", "certifications": ["0185"]},
                {"id": "103", "skillType": "2213", "ability": "6", "certifications": []},
            ]
        }
        official = {
            "language": [
                {"id": "101", "skillType": "2201", "ability": "6", "certifications": ["0117"]},
                {"id": "102", "skillType": "2210", "ability": "6", "certifications": ["0185"]},
                {"id": "103", "skillType": "2213", "ability": "6", "certifications": []},
            ]
        }
        res = verify_results(official, local, {"actions": [{"module": "language"}]})
        assert len(res) == 1
        assert res[0]["module"] == "language"
        assert res[0]["match"] is True
        assert res[0]["note"] == "3 条已生效"

    def test_plan_writeback_language_certs_diff_triggers_edit(self):
        local = {
            "language": [
                {"id": "101", "skillType": "2201", "ability": "6", "certifications": ["0117", "0108"]},
            ]
        }
        official = {
            "language": [
                {"id": "101", "skillType": "2201", "ability": "6", "certifications": ["0117"]},
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["language"])
        assert len(plan["actions"]) == 1
        assert plan["actions"][0]["op"] == "edit"
        assert plan["actions"][0]["method"] == "languageEdit"
        payload = plan["actions"][0]["args"][2]
        assert len(payload["skillCertificationQueries"]) == 2
