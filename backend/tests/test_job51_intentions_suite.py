"""
51job 求职意向 (intentions) 全字段全面测试套件 (test_job51_intentions_suite.py)
验证求职意向模块下所有字段（expectIndustry, expectArea, expectFunction, seekType, minSalary, maxSalary, salaryMonth, preference）
在各种边界条件下的载荷组装、字段清洗、别名兼容、计划生成、无破坏性更新与复核比对。
"""

import pytest
from resume_editor.platforms.job51_write_back import (
    _build_intention_payload,
    _key_same,
    _match_official,
    plan_writeback,
    verify_results,
)
from resume_editor.platforms.job51_collector import transform_data


class TestJob51IntentionsFields:
    """求职意向各字段独立与组合测试"""

    # -------------------------------------------------------------
    # 1. 期望行业 (expectIndustry / industry)
    # -------------------------------------------------------------
    def test_industry_multi_codes_and_aliases(self):
        """测试多行业码值与别名 (industry / expectIndustry) 正确转为官网标准载荷"""
        item_with_industry = {
            "industry": "32,05,04",
            "industryNames": "互联网/电子商务、快速消费品(食品、饮料、化妆品)、贸易/进出口",
            "expectArea": "030200,040000",
            "expectFunction": "6102",
        }
        payload = _build_intention_payload(item_with_industry)
        assert payload["expectIndustry"] == "32,05,04"
        assert payload["expectArea"] == "030200,040000"
        assert payload["expectFunction"] == "6102"

        # 别名 expectIndustry 优先
        item_with_expect_ind = {
            "expectIndustry": "01,37",
            "industry": "32",
            "expectArea": "010000",
        }
        payload2 = _build_intention_payload(item_with_expect_ind)
        assert payload2["expectIndustry"] == "01,37"

    def test_industry_empty_or_unlimited(self):
        """测试行业不限 / 空行业时载荷为 None，不传递脏数据"""
        item_empty = {
            "industry": "",
            "industryNames": "",
            "expectArea": "030200",
            "expectFunction": "6102",
        }
        payload = _build_intention_payload(item_empty)
        assert payload["expectIndustry"] is None

    def test_industry_key_same_comparison(self):
        """测试 _key_same 对 expectIndustry 与 industry 别名及清空操作的比对"""
        # 本地用 industry，官网用 expectIndustry
        item = {"industry": "32,05,04"}
        off_item = {"expectIndustry": "32,05,04"}
        assert _key_same("expectIndustry", item, off_item) is True

        # 本地清空行业（显式置空），官网原本有行业 -> 判定为不一致，必须触发回写清除
        item_cleared = {"industry": ""}
        assert _key_same("expectIndustry", item_cleared, off_item) is False

        # 本地与官网均为空 -> 一致
        item_both_empty = {"industry": ""}
        off_both_empty = {"expectIndustry": ""}
        assert _key_same("expectIndustry", item_both_empty, off_both_empty) is True

        # 真实不同码值
        item_diff = {"industry": "01"}
        assert _key_same("expectIndustry", item_diff, off_item) is False

    # -------------------------------------------------------------
    # 2. 期望城市 (expectArea / expectAreaNames)
    # -------------------------------------------------------------
    def test_area_single_and_multi(self):
        """测试期望城市单选与多选城市码正确组装"""
        item_multi = {"expectArea": "030200,040000", "expectAreaNames": "广州、深圳"}
        payload = _build_intention_payload(item_multi)
        assert payload["expectArea"] == "030200,040000"

        item_single = {"expectArea": "010000"}
        payload_single = _build_intention_payload(item_single)
        assert payload_single["expectArea"] == "010000"

    def test_area_key_same_comparison(self):
        """测试 _key_same 对城市字段的比对"""
        item = {"expectArea": "030200,040000"}
        off_item = {"expectArea": "030200,040000", "expectAreaString": "广州,深圳"}
        assert _key_same("expectArea", item, off_item) is True

        item_diff = {"expectArea": "010000"}
        assert _key_same("expectArea", item_diff, off_item) is False

    # -------------------------------------------------------------
    # 3. 期望职位 (expectFunction / expectFunctionName)
    # -------------------------------------------------------------
    def test_function_standard_and_custom(self):
        """测试标准职能编码与自定义职位名称的载荷生成"""
        # 标准职能
        item_std = {
            "expectFunction": "6612",
            "expectFunctionName": "AI产品经理",
            "expectFunctionString": "AI产品经理",
        }
        p_std = _build_intention_payload(item_std)
        assert p_std["expectFunction"] == "6612"
        assert p_std["expectFunctionName"] == "AI产品经理"

        # 自定义职位（无编码）
        item_custom = {
            "expectFunction": "",
            "expectFunctionName": "高级AGI算法专家",
        }
        p_custom = _build_intention_payload(item_custom)
        assert p_custom["expectFunction"] is None
        assert p_custom["expectFunctionName"] == "高级AGI算法专家"

    # -------------------------------------------------------------
    # 4. 工作类型 (seekType)
    # -------------------------------------------------------------
    def test_seek_type_variants(self):
        """测试全职(0)/兼职(1)/实习(2)工作类型枚举转化"""
        for code in ["0", "1", "2", 0, 1, 2]:
            item = {"seekType": code}
            p = _build_intention_payload(item)
            assert p["seekType"] == str(code)

    # -------------------------------------------------------------
    # 5. 期望薪资 (minSalary, maxSalary, salaryMonth, salaryType)
    # -------------------------------------------------------------
    def test_salary_ranges_and_months(self):
        """测试月薪范围、薪资月数及特异范围（2千以下 / 10万及以上）"""
        # 常规月薪 15k-25k 14薪
        item_normal = {
            "minSalary": "15000",
            "maxSalary": "25000",
            "salaryMonth": 14,
        }
        p_normal = _build_intention_payload(item_normal)
        assert p_normal["minSalary"] == "15000"
        assert p_normal["maxSalary"] == "25000"
        assert p_normal["salaryMonth"] == 14
        assert p_normal["salaryType"] == 1

        # 字符串形态 salaryMonth
        item_str_month = {"salaryMonth": "16"}
        p_str = _build_intention_payload(item_str_month)
        assert p_str["salaryMonth"] == 16

        # 缺省默认 12 薪
        item_no_month = {}
        p_def = _build_intention_payload(item_no_month)
        assert p_def["salaryMonth"] == 12

    # -------------------------------------------------------------
    # 6. 求职偏好与打底继承 (intentionPreference)
    # -------------------------------------------------------------
    def test_preference_and_official_fallback(self):
        """测试求职偏好透传与官网字段打底继承（保留 accountId 等）"""
        off_item = {
            "id": "228032372",
            "accountId": "134699467",
            "expectArea": "030200",
            "expectFunction": "6102",
            "expectIndustry": "32",
            "intentionPreference": {"workType": ["双休"]},
        }
        item_update = {
            "id": "228032372",
            "industry": "32,05,04",  # 本地仅修改行业
        }
        payload = _build_intention_payload(item_update, off_item)
        assert payload["id"] == "228032372"
        assert payload["accountId"] == "134699467"
        assert payload["expectIndustry"] == "32,05,04"
        assert payload["expectArea"] == "030200"
        assert payload["expectFunction"] == "6102"
        assert payload["intentionPreference"] == {"workType": ["双休"]}


class TestJob51IntentionsPlanAndVerify:
    """求职意向回写计划与复核比对测试"""

    def test_plan_writeback_intentions_edit_industry(self):
        """验证当仅修改期望行业时，正确生成 editIntention 动作且载荷带 expectIndustry"""
        official = {
            "resumeId": "369525152",
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200,040000",
                    "expectFunction": "6102",
                    "expectFunctionName": "国内电商运营",
                    "expectIndustry": None,  # 官网原本行业不限
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        local = {
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200,040000",
                    "expectFunction": "6102",
                    "expectFunctionName": "国内电商运营",
                    "industry": "32,05,04",  # 本地设定3个行业
                    "industryNames": "互联网/电子商务、快速消费品(食品、饮料、化妆品)、贸易/进出口",
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        plan = plan_writeback(local, official, selected_modules=["intentions"])
        assert len(plan["actions"]) == 1
        action = plan["actions"][0]
        assert action["module"] == "intentions"
        assert action["op"] == "edit"
        assert action["method"] == "editIntention"
        assert action["args"][0] == "int_1"
        payload = action["args"][1]
        assert payload["expectIndustry"] == "32,05,04"
        assert payload["expectFunction"] == "6102"
        assert payload["expectArea"] == "030200,040000"

    def test_plan_writeback_intentions_match_without_id(self):
        """验证本地条目丢失 id 时，通过 expectFunction/expectFunctionName 智能配对官网条目"""
        official = {
            "resumeId": "369525152",
            "intentions": [
                {
                    "id": "off_int_999",
                    "seekType": "0",
                    "expectArea": "030200,040000",
                    "expectFunction": "6102",
                    "expectFunctionName": "国内电商运营",
                    "expectIndustry": "",
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        local_no_id = {
            "intentions": [
                {
                    # 无 id
                    "seekType": "0",
                    "expectArea": "030200,040000",
                    "expectFunction": "6102",
                    "expectFunctionName": "国内电商运营",
                    "industry": "32,05,04",
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        plan = plan_writeback(local_no_id, official, selected_modules=["intentions"])
        assert len(plan["actions"]) == 1
        assert plan["actions"][0]["op"] == "edit"
        assert plan["actions"][0]["args"][0] == "off_int_999"  # 成功复用官网 id
        assert plan["actions"][0]["args"][1]["expectIndustry"] == "32,05,04"

    def test_plan_writeback_intentions_clear_industry(self):
        """验证当清空期望行业时（industry='' 或 expectIndustry=''），正确生成 editIntention 动作并将 expectIndustry 设为 None"""
        official = {
            "resumeId": "369525152",
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200,040000",
                    "expectFunction": "6102",
                    "expectFunctionName": "国内电商运营",
                    "expectIndustry": "32,05,04",  # 官网原有行业
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        local_cleared = {
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200,040000",
                    "expectFunction": "6102",
                    "expectFunctionName": "国内电商运营",
                    "industry": "",  # 本地清除行业
                    "industryNames": "",
                    "expectIndustry": "",
                    "expectIndustryString": "",
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        plan = plan_writeback(local_cleared, official, selected_modules=["intentions"])
        assert len(plan["actions"]) == 1
        action = plan["actions"][0]
        assert action["module"] == "intentions"
        assert action["op"] == "edit"
        assert action["args"][0] == "int_1"
        payload = action["args"][1]
        assert payload["expectIndustry"] is None  # 官网载荷将 expectIndustry 设为 None 以清空

    def test_verify_results_all_intentions_fields(self):
        """测试复核比对引擎对行业、城市、职位、薪资、薪资月数等 7 大字段的校验"""
        plan = {"actions": [{"module": "intentions", "op": "edit"}]}
        local = {
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200",
                    "expectFunction": "6102",
                    "industry": "32,05,04",
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }

        # 1. 官网全部生效一致
        verify_succ = {
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200",
                    "expectFunction": "6102",
                    "expectIndustry": "32,05,04",
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        res_succ = verify_results(verify_succ, local, plan)
        assert len(res_succ) == 1
        assert res_succ[0]["match"] is True

        # 2. 官网行业不一致（如行业回传失败变成空）
        verify_fail_ind = {
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200",
                    "expectFunction": "6102",
                    "expectIndustry": "",  # 行业未生效
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": 14,
                }
            ]
        }
        res_fail = verify_results(verify_fail_ind, local, plan)
        assert len(res_fail) == 1
        assert res_fail[0]["match"] is False
        assert "行业不一致" in res_fail[0]["note"]


class TestJob51CollectorIntentionsTransform:
    """采集器数据结构转换与双向别名测试"""

    def test_collector_intentions_transform(self):
        raw_data = {
            "intentions": [
                {
                    "id": "int_1",
                    "seekType": "0",
                    "expectArea": "030200,040000",
                    "expectAreaString": "广州,深圳",
                    "expectFunction": "6102",
                    "expectFunctionString": "国内电商运营",
                    "expectIndustry": "32,05,04",
                    "expectIndustryString": "互联网/电子商务、快速消费品(食品、饮料、化妆品)、贸易/进出口",
                    "minSalary": "15000",
                    "maxSalary": "25000",
                    "salaryMonth": "14",
                    "diagnosis": {"text": "不重要的诊断"},
                }
            ]
        }
        fields = transform_data(raw_data)
        intentions = fields["intentions"]["current_value"]
        assert len(intentions) == 1
        item = intentions[0]
        # 验证前端字段与官网字段双向存在
        assert item["expectAreaNames"] == "广州,深圳"
        assert item["expectFunctionName"] == "国内电商运营"
        assert item["industry"] == "32,05,04"
        assert item["expectIndustry"] == "32,05,04"
        assert item["industryNames"] == "互联网/电子商务、快速消费品(食品、饮料、化妆品)、贸易/进出口"
        assert item["expectIndustryString"] == "互联网/电子商务、快速消费品(食品、饮料、化妆品)、贸易/进出口"
        assert item["salaryMonth"] == 14
        assert "diagnosis" not in item
