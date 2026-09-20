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
    monkeypatch.setattr(mod, "fetch_exact_address", lambda context, link: "")
    monkeypatch.setattr(mod, "save_to_raw_db", lambda job_data: saved.__setitem__("n", saved["n"] + 1) or True)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    items = [{"jobName": f"t{i}", "companyName": f"c{i}", "jobHref": f"l{i}"} for i in range(10)]
    n = mod.process_job_items(None, items, target=3)
    assert n == 3          # 配额 3 → 只入库 3 条，不整页超收
    assert saved["n"] == 3


def test_process_job_items_unlimited_when_target_zero(monkeypatch):
    mod = _load("job51_collector", "51job_scraper/51job_collector.py")
    monkeypatch.setattr(mod, "check_exists", lambda company, title, city: False)
    monkeypatch.setattr(mod, "fetch_exact_address", lambda context, link: "")
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
