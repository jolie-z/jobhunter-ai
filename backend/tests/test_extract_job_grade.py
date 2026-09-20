"""评级提取 helper：杜绝看板兜底伪造等级（此前兜底 "B" 曾把 C/D 级岗位显示成 B）。"""
from app.core.feishu_utils import extract_job_grade


def test_reads_evaluator_field():
    """评估器写入的是「综合评级 (A-F)」，必须能读到真实评级。"""
    assert extract_job_grade({"综合评级 (A-F)": "D"}) == "D"


def test_prefers_legacy_fields_first():
    """历史字段「综合等级」「评级」有值时优先（老记录兼容）。"""
    assert extract_job_grade({"综合等级": "b", "综合评级 (A-F)": "D"}) == "B"
    assert extract_job_grade({"评级": "C"}) == "C"


def test_returns_empty_when_no_grade():
    """三个字段都缺失时返回空串，绝不伪造等级。"""
    assert extract_job_grade({"公司名称": "某公司"}) == ""
    assert extract_job_grade({}) == ""


def test_rich_text_field_value():
    """飞书富文本字段经 extract_feishu_text 提取后仍能读到评级。"""
    assert extract_job_grade({"综合评级 (A-F)": [{"text": "C"}]}) == "C"
