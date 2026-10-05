"""51job「凑满即停」配额截断测试。

背景：51job collector 原先无配额概念，靠上层掐进程；现移植剩余配额参数，
process_job_items 必须按 target 截断，最后一页不整页超收。
"""
import importlib.util
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, BACKEND / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_process_job_items_truncates_at_target(monkeypatch):
    mod = _load("job51_collector", "51job_scraper/51job_collector.py")
    saved = {"n": 0}
    monkeypatch.setattr(mod, "check_exists", lambda company, title, city: False)
    monkeypatch.setattr(mod, "fetch_detail_info", lambda context, link: {})
    monkeypatch.setattr(mod, "save_to_raw_db", lambda job_data: saved.__setitem__("n", saved["n"] + 1) or True)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    items = [{"jobName": f"t{i}", "companyName": f"c{i}", "jobHref": f"l{i}"} for i in range(10)]
    n = mod.process_job_items(None, items, target=3)
    assert n == 3          # 配额 3 → 只入库 3 条，不整页超收
    assert saved["n"] == 3


def test_process_job_items_unlimited_when_target_zero(monkeypatch):
    mod = _load("job51_collector", "51job_scraper/51job_collector.py")
    monkeypatch.setattr(mod, "check_exists", lambda company, title, city: False)
    monkeypatch.setattr(mod, "fetch_detail_info", lambda context, link: {})
    monkeypatch.setattr(mod, "save_to_raw_db", lambda job_data: True)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    items = [{"jobName": f"t{i}", "companyName": f"c{i}", "jobHref": f"l{i}"} for i in range(6)]
    n = mod.process_job_items(None, items, target=0)
    assert n == 6          # 0=不限制，行为兼容旧调用


def test_controller_passes_remaining_quota():
    mod = _load("job51_nl_controller", "51job_scraper/51job_nl_controller.py")
    cmd = mod._build_crawler_cmd("/x/51job_collector.py", 2, "测试", "广州", "不限", remaining=5)
    assert "--target" in cmd
    assert cmd[cmd.index("--target") + 1] == "5"
    # 不传 remaining 时默认 0（不限制），兼容旧行为
    cmd0 = mod._build_crawler_cmd("/x/51job_collector.py", 2, "测试", "广州", "不限")
    assert cmd0[cmd0.index("--target") + 1] == "0"


def test_jd_text_write_priority(monkeypatch):
    """2026-09-25 字段补采：7 字段三级数据流——详情页下钻值优先 / 卡片 sensorsdata 键兜底 / 默认值。"""
    mod = _load("job51_collector", "51job_scraper/51job_collector.py")
    saved = []
    monkeypatch.setattr(mod, "check_exists", lambda company, title, city: False)
    monkeypatch.setattr(mod, "fetch_detail_info", lambda context, link: {
        "address": f"地址{link}", "jd_text": f"JD正文{link}",
        "welfare_tags": "五险一金、年终奖金", "hr_skill_tags": "python、fastapi",
        "company_intro": "公司简介", "industry": "计算机软件", "company_size": "1000-5000人"})
    monkeypatch.setattr(mod, "save_to_raw_db", lambda job_data: saved.append(job_data) or True)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    # 一级：详情页下钻值全量优先
    items = [{"jobName": "t1", "companyName": "c1", "jobHref": "l1"}]
    assert mod.process_job_items(None, items, target=0) == 1
    row = saved[0]
    assert row["jd_text"] == "JD正文l1" and row["work_address"] == "地址l1"
    assert row["welfare_tags"] == "五险一金、年终奖金" and row["hr_skill_tags"] == "python、fastapi"
    assert row["company_intro"] == "公司简介"
    assert row["industry"] == "计算机软件" and row["company_size"] == "1000-5000人"

    # 二级：下钻失败（空 dict）→ 卡片 sensorsdata 键兜底
    monkeypatch.setattr(mod, "fetch_detail_info", lambda context, link: {})
    saved.clear()
    items = [{"jobName": "t2", "companyName": "c2", "jobHref": "l2", "jobDescribe": "卡片JD",
              "jobLabel": "卡片标签", "companyIndustryType1Str": "互联网",
              "companySizeString": "150-500人", "companyInfo": "卡片简介"}]
    assert mod.process_job_items(None, items, target=0) == 1
    row = saved[0]
    assert row["jd_text"] == "卡片JD" and row["welfare_tags"] == "卡片标签" and row["hr_skill_tags"] == "卡片标签"
    assert row["industry"] == "互联网" and row["company_size"] == "150-500人" and row["company_intro"] == "卡片简介"

    # 三级：两边皆空 → 各字段默认值
    saved.clear()
    items = [{"jobName": "t3", "companyName": "c3", "jobHref": "l3"}]
    assert mod.process_job_items(None, items, target=0) == 1
    row = saved[0]
    assert row["jd_text"] == "无详情" and row["industry"] == "其他" and row["company_size"] == "未知规模"
    assert row["welfare_tags"] == "" and row["hr_skill_tags"] == "" and row["company_intro"] == ""
