import pytest
import os
import json
from resume_editor.platforms.job51_write_back import (
    _norm_cert_items,
    _match_official,
    _key_same,
    _diagnose_writeback_failure,
    plan_writeback,
    verify_results,
    LIST_MODULES,
)


class TestJob51CertificationsNormalization:
    def test_norm_cert_items_from_string_list(self):
        raw = ["0815", "0108", "0117", "0110", "0154"]
        normed = _norm_cert_items(raw)
        assert len(normed) == 5
        assert normed[0]["cert"] == "0815"
        assert normed[0]["isEnglish"] is False
        assert normed[2]["cert"] == "0117"

    def test_norm_cert_items_from_dict_list(self):
        raw = [
            {"id": "101", "cert": "0815", "certString": "C1驾照", "startTime": "2018-07"},
            {"code": "0108", "name": "剑桥商务英语中级"},
        ]
        normed = _norm_cert_items(raw)
        assert len(normed) == 2
        assert normed[0]["id"] == "101"
        assert normed[0]["cert"] == "0815"
        assert normed[0]["certName"] == "C1驾照"
        assert normed[0]["startTime"] == "2018-07"
        assert normed[1]["cert"] == "0108"
        assert normed[1]["certName"] == "剑桥商务英语中级"

    def test_norm_cert_items_deduplication(self):
        raw = ["0815", "0815", {"cert": "0815", "certName": "C1驾照"}, "0108"]
        normed = _norm_cert_items(raw)
        assert len(normed) == 2
        assert normed[0]["cert"] == "0815"
        assert normed[1]["cert"] == "0108"

    def test_norm_cert_items_empty_and_invalid(self):
        assert _norm_cert_items([]) == []
        assert _norm_cert_items(None) == []
        assert _norm_cert_items(["", None, {}]) == []


class TestJob51CertificationsMatchingAndDiff:
    def test_match_official_cert_by_code(self):
        off_items = [
            {"id": "1001", "cert": "0815", "certString": "C1驾照"},
            {"id": "1002", "cert": "0108", "certString": "剑桥商务英语中级"},
        ]
        item = {"cert": "0815", "certName": ""}
        matched = _match_official(item, off_items, set(), "certifications")
        assert matched is not None
        assert matched["id"] == "1001"

    def test_match_official_cert_by_name(self):
        off_items = [
            {"id": "1001", "cert": "0815", "certString": "C1驾照"},
            {"id": "1002", "cert": "0108", "certString": "剑桥商务英语中级"},
        ]
        item = {"cert": "", "certName": "剑桥商务英语中级"}
        matched = _match_official(item, off_items, set(), "certifications")
        assert matched is not None
        assert matched["id"] == "1002"

    def test_key_same_cert(self):
        assert _key_same("cert", {"cert": "0815"}, {"cert": "0815"}) is True
        assert _key_same("cert", {"code": "0815"}, {"cert": "0815"}) is True
        assert _key_same("cert", "0815", {"cert": "0815"}) is True
        assert _key_same("cert", {"cert": "0815"}, {"cert": "0108"}) is False

    def test_plan_writeback_all_match_noop(self):
        official = {
            "resumeId": "369525152",
            "certifications": [
                {"id": "1", "cert": "0815", "certString": "C1驾照"},
                {"id": "2", "cert": "0108", "certString": "剑桥商务英语中级"},
            ]
        }
        local = {
            "certifications": ["0815", "0108"]
        }
        plan = plan_writeback(local, official, ["certifications"])
        assert len(plan["actions"]) == 0
        assert any("无需回写" in s["reason"] for s in plan["skipped"])

    def test_plan_writeback_add_and_del_priority(self):
        """核心防护：验证 del 动作严格排在 add 动作之前，防止触碰 20 条证书上限"""
        official = {
            "resumeId": "369525152",
            "certifications": [
                {"id": "1", "cert": "0815", "certString": "C1驾照"},
                {"id": "2", "cert": "0199", "certString": "日语高级笔译"},
            ]
        }
        local = {
            "certifications": ["0815", "0117"]  # Add 0117, Del 0199 (id=2), 0815 no-op
        }
        plan = plan_writeback(local, official, ["certifications"])
        actions = plan["actions"]
        assert len(actions) == 2

        # 检查动作顺序：del 必须在 add 之前！
        assert actions[0]["op"] == "del"
        assert actions[0]["method"] == "getCertificateDel"
        assert actions[0]["args"][1] == "2"

        assert actions[1]["op"] == "add"
        assert actions[1]["method"] == "getCertificatedd"
        assert actions[1]["args"][1]["cert"] == "0117"

    def test_plan_writeback_20_certificates_roundtrip(self):
        """模拟用户 20 条全量证书从 7 条存量（包含 2 条多余项）回写的编排顺序"""
        user_20_codes = [
            '0815', '0108', '0117', '0507', '0513', '1006', '1005', '1009', '1004', '0903',
            '0907', '0906', '0902', '0914', '0305', '0378', '0308', '0331', '0321', '0368'
        ]
        official = {
            "resumeId": "369525152",
            "certifications": [
                {"id": "101", "cert": "0815", "certString": "C1驾照"},
                {"id": "102", "cert": "0108", "certString": "剑桥商务英语中级"},
                {"id": "103", "cert": "0117", "certString": "大学英语六级"},
                {"id": "104", "cert": "0116", "certString": "大学英语四级"},  # surplus
                {"id": "105", "cert": "0132", "certString": "英语专业四级"},  # surplus
            ]
        }
        local = {"certifications": user_20_codes}
        plan = plan_writeback(local, official, ["certifications"])
        actions = plan["actions"]

        # 应该先生成 2 个 del，然后生成 17 个 add，共 19 个动作（3 个已存在走 no-op）
        dels = [a for a in actions if a["op"] == "del"]
        adds = [a for a in actions if a["op"] == "add"]
        assert len(dels) == 2
        assert len(adds) == 17

        # 检查所有 del 操作的索引都在 add 之前
        del_indices = [i for i, a in enumerate(actions) if a["op"] == "del"]
        add_indices = [i for i, a in enumerate(actions) if a["op"] == "add"]
        assert max(del_indices) < min(add_indices)


class TestJob51CertificationsVerification:
    def test_verify_results_success(self):
        official_after = {
            "certifications": [
                {"id": "1", "cert": "0815"},
                {"id": "2", "cert": "0108"},
                {"id": "3", "cert": "0117"},
            ]
        }
        local = {
            "certifications": ["0815", "0108", "0117"]
        }
        plan = {"actions": [{"module": "certifications", "op": "add"}]}
        results = verify_results(official_after, local, plan)
        assert len(results) == 1
        assert results[0]["module"] == "certifications"
        assert results[0]["match"] is True
        assert "3 条已生效" in results[0]["note"]

    def test_verify_results_count_mismatch(self):
        official_after = {
            "certifications": [
                {"id": "1", "cert": "0815"},
            ]
        }
        local = {
            "certifications": ["0815", "0108"]
        }
        plan = {"actions": [{"module": "certifications", "op": "add"}]}
        results = verify_results(official_after, local, plan)
        assert len(results) == 1
        assert results[0]["module"] == "certifications"
        assert results[0]["match"] is False
        assert "条数不一致" in results[0]["note"]


class TestJob51CertificationsDiagnosisAndDictionary:
    def test_diagnose_limit_reached_201604(self):
        action = {"module": "certifications", "op": "add"}
        resp = {"status": "201604", "message": "最多允许20条"}
        diag = _diagnose_writeback_failure(action, resp)
        assert diag["field"] == "count_limit"
        assert "数量超出官网限制" in diag["diagnosis"]
        assert "20" in diag["suggestion"]

    def test_local_cert_dictionary_structure(self):
        dict_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "../../frontend/public/51job_certificates.json"
        ))
        assert os.path.exists(dict_path)
        with open(dict_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 15  # 15 大官方分类

        all_codes = set()
        total_items = 0
        for cat in data:
            assert "name" in cat or "label" in cat
            assert "children" in cat
            for item in cat["children"]:
                assert "code" in item
                assert "name" in item
                assert len(item["code"]) == 4  # 4位数字代码
                assert item["code"] not in all_codes, f"重复代码: {item['code']}"
                all_codes.add(item["code"])
                total_items += 1

        assert total_items == 474  # 474 项标准证书
