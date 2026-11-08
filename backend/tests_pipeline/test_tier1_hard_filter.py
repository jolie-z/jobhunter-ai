"""Tier 1 硬规则清洗回归（2026-10-31 修复「硬规则空转」）。

事故：_run_tier1_hard_filter 先把本轮行原子认领为「清洗中」，但 6 个过滤器仍按
「已存入数据」查询，导致 Tier 1 一条规则都匹配不到（2026-09-03 bb074e26 回归）。

本用例锁定：
- 城市 / 空详情 / 学历 / 经验 / 薪资 / 关键词六条规则都真正生效；
- city 与 work_address 同时为空时按「位置未知」放行（不硬杀）；
- 首个命中的规则决定 reject_reason，后续过滤器不得二次改写；
- 独立入口 _async_run_hard_filter_only 同样生效，且不动 target_links 之外的行。
"""
import sqlite3

import pytest

from job_processor import step1_rule_filter

STRATEGY = {
    "min_salary_k": 10,
    "max_salary_k": 30,
    "experience_years_max": 10,
    "exclude_education": ["高中", "中专"],
    "allowed_cities": ["广州", "深圳"],
    "keyword_rules": [{"keyword": "销售", "scope": "title", "action": "reject"}],
}

JOBS = [
    # link, title, city, address, salary, exp, edu, jd, 期望状态, 期望原因
    ("https://t/clean", "AI产品经理", "广州", "", "15-25K", "3-5年", "本科", "JD 内容", "待AI初筛", None),
    ("https://t/salary", "产品经理", "广州", "", "5-8K", "3-5年", "本科", "JD 内容", "清洗淘汰", "薪资区间不符"),
    ("https://t/city", "全栈工程师", "重庆", "重庆·璧山区", "15-25K", "3-5年", "本科", "JD 内容", "清洗淘汰", "工作城市不在目标范围内"),
    ("https://t/empty-city", "远程运营", "", "", "15-25K", "3-5年", "本科", "JD 内容", "待AI初筛", None),
    ("https://t/edu", "AI合伙人", "广州", "", "15-20K", "1-3年", "高中", "JD 内容", "清洗淘汰", "学历要求不符(高中/中专)"),
    ("https://t/exp", "AI agent", "广州", "", "15-25K", "10年以上", "本科", "JD 内容", "清洗淘汰", "要求资历过高(≥10年)"),
    ("https://t/empty-jd", "产品设计经理", "广州", "", "15-25K", "3-5年", "本科", "", "清洗淘汰", "岗位详情为空"),
    ("https://t/keyword", "AI销售经理", "广州", "", "15-25K", "3-5年", "本科", "JD 内容", "清洗淘汰", "标题包含排除词: 销售"),
    # 同时命中学历+薪资：按过滤器顺序，学历先命中，原因必须保持学历
    ("https://t/multi", "低薪中专岗", "广州", "", "5-8K", "3-5年", "中专", "JD 内容", "清洗淘汰", "学历要求不符(高中/中专)"),
]


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE raw_jobs (
            job_link TEXT PRIMARY KEY,
            platform TEXT,
            job_title TEXT,
            company_name TEXT,
            salary TEXT,
            city TEXT,
            work_address TEXT,
            experience_req TEXT,
            education_req TEXT,
            jd_text TEXT,
            publish_date TEXT,
            process_status TEXT DEFAULT '已存入数据',
            reject_reason TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE job_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            is_active INTEGER,
            min_salary_k REAL,
            max_salary_k REAL,
            experience_years_max INTEGER,
            exclude_education TEXT DEFAULT '[]',
            allowed_cities TEXT DEFAULT '[]',
            safe_phrases TEXT DEFAULT '[]',
            keyword_rules TEXT DEFAULT '[]',
            ai_scout_rules TEXT DEFAULT '[]'
        )"""
    )
    conn.execute(
        "INSERT INTO job_strategies (is_active, min_salary_k, max_salary_k, experience_years_max, "
        "exclude_education, allowed_cities, keyword_rules) VALUES (1, 10, 30, 10, ?, ?, ?)",
        ('["高中", "中专"]', '["广州", "深圳"]', '[{"keyword": "销售", "scope": "title", "action": "reject"}]'),
    )
    for link, title, city, addr, salary, exp, edu, jd, _status, _reason in JOBS:
        conn.execute(
            "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, salary, city, "
            "work_address, experience_req, education_req, jd_text) "
            "VALUES (?, '智联招聘', ?, '测试公司', ?, ?, ?, ?, ?, ?)",
            (link, title, salary, city, addr, exp, edu, jd),
        )
    # target_links 之外的行：必须原地不动
    conn.execute(
        "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, salary, city, jd_text) "
        "VALUES ('https://t/outside', '智联招聘', '圈外岗位', '测试公司', '5-8K', '重庆', 'JD')"
    )
    conn.commit()
    conn.close()


def _status_map(path):
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT job_link, process_status, reject_reason FROM raw_jobs").fetchall()
    conn.close()
    return {r[0]: (r[1], r[2]) for r in rows}


@pytest.fixture
def tier1_db(tmp_path, monkeypatch):
    db = tmp_path / "tier1.db"
    _make_db(db)
    monkeypatch.setattr(step1_rule_filter, "DB_PATH", str(db))
    step1_rule_filter.set_stop_flag(False)
    return db


def test_tier1_filters_actually_run(tier1_db):
    """六条硬规则都必须真正生效（修复前全部空转）。"""
    links = [j[0] for j in JOBS]
    conn = sqlite3.connect(tier1_db)
    try:
        step1_rule_filter._run_tier1_hard_filter(conn.cursor(), conn, STRATEGY, links)
    finally:
        conn.close()

    status = _status_map(tier1_db)
    for link, _title, _city, _addr, _salary, _exp, _edu, _jd, expected_status, expected_reason in JOBS:
        got_status, got_reason = status[link]
        assert got_status == expected_status, f"{link} 状态应为 {expected_status}，实际 {got_status}"
        if expected_reason is None:
            assert got_reason is None
        else:
            assert got_reason == expected_reason, f"{link} 原因应为 {expected_reason}，实际 {got_reason}"

    # target_links 之外的行不得被认领/淘汰
    assert status["https://t/outside"] == ("已存入数据", None)


async def test_hard_filter_only_entry_uses_claim_state(tier1_db):
    """独立硬规则入口（认领→过滤→推进）必须与核心函数同口径。"""
    # 独立入口按「全部已存入数据」圈选，包含 target_links 用例里的圈外行
    total = len(JOBS) + 1
    result = await step1_rule_filter._async_run_hard_filter_only()
    assert result == {"total": total, "passed": 2, "rejected": total - 2}

    status = _status_map(tier1_db)
    assert status["https://t/clean"] == ("待AI初筛", None)
    assert status["https://t/empty-city"] == ("待AI初筛", None)
    assert status["https://t/salary"][0] == "清洗淘汰"
    # 圈外行（重庆）在全量入口下同样按城市规则淘汰
    assert status["https://t/outside"] == ("清洗淘汰", "工作城市不在目标范围内")


async def test_empty_city_is_passed_not_rejected(tier1_db):
    """city 与 work_address 同时为空 = 位置字段缺失，放给 AI，不按城市硬杀。"""
    links = ["https://t/empty-city"]
    conn = sqlite3.connect(tier1_db)
    try:
        step1_rule_filter._run_tier1_hard_filter(conn.cursor(), conn, STRATEGY, links)
    finally:
        conn.close()

    got_status, got_reason = _status_map(tier1_db)["https://t/empty-city"]
    assert got_status == "待AI初筛"
    assert got_reason is None
