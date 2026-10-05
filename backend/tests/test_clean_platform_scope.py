"""清洗管道平台范围 + 限量 scoping 测试（2026-09-27 /agent 清洗指令批）。

真实引擎级测试：临时 SQLite 造数（四平台 × 已存入数据），直接调
_async_run_pipeline(platform=..., limit=...)，断言清洗范围严格圈在参数内。
策略表给空过滤规则（allowed_cities/keyword_rules 等全 []）+ 宽松数值，
Tier1 全放行；ai_scout_rules='[]' 时 Tier2 AIScoutEngine 直接 PASS——
全程不触网、不耗 Token、无 LLM 依赖。
"""
import sqlite3

import pytest

from job_processor import step1_rule_filter

STRATEGY_VALUES = "0, 999, 99"  # min_salary_k=0, max_salary_k=999, experience_years_max=99


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
            experience_req TEXT,
            education_req TEXT,
            jd_text TEXT,
            publish_date TEXT,
            process_status TEXT DEFAULT '已存入数据',
            reject_reason TEXT
        )"""
    )
    conn.execute(
        f"""CREATE TABLE job_strategies (
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
        f"INSERT INTO job_strategies (is_active, min_salary_k, max_salary_k, experience_years_max) VALUES (1, {STRATEGY_VALUES})"
    )
    # 四平台 × 不同条数（智联 5 条对齐 /agent 用户场景）
    for plat, n in (("智联招聘", 5), ("BOSS直聘", 4), ("51job", 3), ("猎聘", 2)):
        for i in range(n):
            conn.execute(
                "INSERT INTO raw_jobs (job_link, platform, job_title, company_name, salary, city, experience_req, education_req, jd_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{plat}-{i}", plat, f"{plat}岗位{i}", "测试公司", "15-25K", "广州", "1-3年", "本科", "岗位职责描述内容"),
            )
    conn.commit()
    conn.close()


def _status_map(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT job_link, process_status FROM raw_jobs").fetchall()
    conn.close()
    return dict(rows)


def _count_platform_status(db_path, platform, status):
    conn = sqlite3.connect(db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM raw_jobs WHERE platform = ? AND process_status = ?", (platform, status)
    ).fetchone()[0]
    conn.close()
    return n


@pytest.fixture
def scope_db(tmp_path, monkeypatch):
    db = tmp_path / "scope.db"
    _make_db(db)
    monkeypatch.setattr(step1_rule_filter, "DB_PATH", str(db))
    return db


async def test_platform_scoped_clean_only_touches_target_platform(scope_db):
    """指定平台清洗：仅智联 5 条被推进，其余平台 9 条原地不动。"""
    passed = await step1_rule_filter._async_run_pipeline(platform="智联招聘")
    assert len(passed) == 5
    assert all(link.startswith("智联招聘") for link in passed)
    assert _count_platform_status(scope_db, "智联招聘", "待推送至飞书") == 5
    for other in ("BOSS直聘", "51job", "猎聘"):
        assert _count_platform_status(scope_db, other, "已存入数据") == {"BOSS直聘": 4, "51job": 3, "猎聘": 2}[other]


async def test_platform_alias_normalized(scope_db):
    """口语别名归一：zhilian/智联 等价于 智联招聘。"""
    passed = await step1_rule_filter._async_run_pipeline(platform="zhilian")
    assert len(passed) == 5
    assert all(link.startswith("智联招聘") for link in passed)
    assert _count_platform_status(scope_db, "智联招聘", "待推送至飞书") == 5


async def test_limit_applies_within_platform(scope_db):
    """平台 + 限量叠加：limit 在平台过滤之后生效，恰 3 条智联被处理。"""
    passed = await step1_rule_filter._async_run_pipeline(platform="智联招聘", limit=3)
    assert len(passed) == 3
    assert all(link.startswith("智联招聘") for link in passed)
    assert _count_platform_status(scope_db, "智联招聘", "待推送至飞书") == 3
    assert _count_platform_status(scope_db, "智联招聘", "已存入数据") == 2
    for other in ("BOSS直聘", "51job", "猎聘"):
        assert _count_platform_status(scope_db, other, "已存入数据") == {"BOSS直聘": 4, "51job": 3, "猎聘": 2}[other]


async def test_platform_none_cleans_all_regression(scope_db):
    """回归：不传 platform 保持既有全平台行为，14 条全处理。"""
    passed = await step1_rule_filter._async_run_pipeline()
    assert len(passed) == 14
    statuses = _status_map(scope_db)
    assert all(s == "待推送至飞书" for s in statuses.values())


def test_normalize_clean_platform_aliases():
    """归一函数：四平台常用别名 → 库内规范值；未知/空 → 空串。"""
    f = step1_rule_filter._normalize_clean_platform
    assert f("智联招聘") == "智联招聘"
    assert f("zhilian") == "智联招聘"
    assert f("智联") == "智联招聘"
    assert f("zhaopin") == "智联招聘"
    assert f("BOSS直聘") == "BOSS直聘"
    assert f("boss") == "BOSS直聘"
    assert f("前程无忧") == "51job"
    assert f("51job") == "51job"
    assert f("Liepin") == "猎聘"
    assert f("猎聘") == "猎聘"
    assert f("") == ""
    assert f(None) == ""
    assert f("虾皮") == ""


async def test_unknown_platform_no_op(scope_db):
    """不可识别平台名：空跑返回且零状态变化，绝不放大成全平台清洗。"""
    passed = await step1_rule_filter._async_run_pipeline(platform="虾皮")
    assert passed == []
    statuses = _status_map(scope_db)
    assert all(s == "已存入数据" for s in statuses.values())
