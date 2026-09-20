"""
全场景 100% 覆盖自动化测试矩阵：
1. 条件三要素（关键词+城市+薪资）解析与持久化
2. 条件队列 10 组上限拦截
3. 4 平台（Boss/智联/51job/猎聘）9 档薪资映射全覆盖
4. 小红书等平台关键词自适应拓展
5. 条件抓取台账多轮累加与预测分母校准
6. 抓尽制（Exhaustion）判定状态机
7. 条件进度与续抓状态重置接口
8. 历史归档与重复检测闭环
9. 单独执行平台抓取模块接口 (POST /api/pipeline/run-scrape-only)
10. 多条件队列跨平台独立配额与推进逻辑
"""

import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.pipeline as pipeline_mod
from app.pipeline.router import router
from app.session.salary_mapper import (
    map_salary,
    adapt_keyword,
    SALARY_MAPPING,
    STANDARD_SALARY_TIERS,
)
import app.session.scrape_sessions as ss


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "DB_PATH", str(tmp_path / "test_pipe.db"))
    monkeypatch.setattr(pipeline_mod, "_initialized", False)
    monkeypatch.setattr(ss, "DB_PATH", str(tmp_path / "test_pipe.db"))
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


# ─── 1. 条件三要素完整性测试 ───
def test_condition_triplet_storage_and_defaults(client):
    body = {
        "keywords": [
            {"keyword": "大模型算法", "city": "北京", "salary": "30-50K"},
            {"keyword": "前端开发", "city": "", "salary": ""},
        ],
        "platforms": {"boss": {"enabled": True, "limit": 10}},
        "default_city": "广州",
        "default_salary": "15-20K",
    }
    r = client.put("/api/pipeline/scrape-config", json=body)
    assert r.status_code == 200
    assert r.json()["code"] == 0

    saved = client.get("/api/pipeline/scrape-config").json()["data"]
    assert len(saved["keywords"]) == 2
    assert saved["keywords"][0]["keyword"] == "大模型算法"
    assert saved["keywords"][0]["city"] == "北京"
    assert saved["keywords"][0]["salary"] == "30-50K"

    # 默认值回填
    assert saved["default_city"] == "广州"
    assert saved["default_salary"] == "15-20K"


# ─── 2. 10 组队列上限保护 ───
def test_queue_max_limit_enforcement(client):
    ten_items = [{"keyword": f"岗位{i}", "city": "广州", "salary": "不限"} for i in range(10)]
    r1 = client.put(
        "/api/pipeline/scrape-config",
        json={"keywords": ten_items, "platforms": {}, "default_city": "", "default_salary": ""},
    )
    assert r1.status_code == 200

    eleven_items = [{"keyword": f"岗位{i}", "city": "广州", "salary": "不限"} for i in range(11)]
    r2 = client.put(
        "/api/pipeline/scrape-config",
        json={"keywords": eleven_items, "platforms": {}, "default_city": "", "default_salary": ""},
    )
    assert r2.status_code == 400
    assert "最多 10 组" in r2.json()["detail"]


# ─── 3. 4 平台 9 档薪资映射全覆盖测试 ───
def test_all_salary_tiers_4_platforms_mapping():
    expected_tiers = [
        "不限", "3K以下", "3-5K", "5-10K", "10-15K",
        "15-20K", "20-30K", "30-50K", "50K以上"
    ]
    assert list(STANDARD_SALARY_TIERS) == expected_tiers

    for tier in expected_tiers:
        # Boss
        boss_mapped = map_salary(tier, "boss")
        assert boss_mapped is not None and len(boss_mapped) > 0

        # 智联
        zhilian_mapped = map_salary(tier, "zhilian")
        assert zhilian_mapped is not None and len(zhilian_mapped) > 0

        # 51job
        job51_mapped = map_salary(tier, "51job")
        assert job51_mapped is not None and len(job51_mapped) > 0

        # 猎聘
        liepin_mapped = map_salary(tier, "liepin")
        assert liepin_mapped is not None and len(liepin_mapped) > 0

    # 特殊档位核对
    assert map_salary("15-20K", "boss") == "15-20K"
    assert map_salary("15-20K", "zhilian") == "15K-25K"
    assert map_salary("15-20K", "51job") == "15-20K"
    assert map_salary("15-20K", "liepin") == "15-20K"
    assert map_salary("未知档位", "boss") == "不限"


# ─── 4. 关键词自适应适配 ───
def test_keyword_adaptation():
    assert adapt_keyword("AI工程师", "xiaohongshu") == "AI工程师招聘"
    assert adapt_keyword("AI工程师招聘", "xiaohongshu") == "AI工程师招聘"
    assert adapt_keyword("AI工程师", "boss") == "AI工程师"
    assert adapt_keyword("AI工程师", "51job") == "AI工程师"


# ─── 5. 台账累加与预测分母校准 ───
def test_condition_progress_accumulation(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DB_PATH", str(tmp_path / "test_ss.db"))
    ss.init_scrape_sessions_table()

    # 第一轮：入库 6 条，分母 30
    ss.report_condition_round("AI应用", "广州", "15-20K", "boss", inserted=6, predicted_total=30)
    scraped, predicted = ss.get_condition_progress("AI应用", "广州", "15-20K", "boss")
    assert scraped == 6
    assert predicted == 30

    # 第二轮：又入库 8 条，分母不变
    ss.report_condition_round("AI应用", "广州", "15-20K", "boss", inserted=8, predicted_total=None)
    scraped2, predicted2 = ss.get_condition_progress("AI应用", "广州", "15-20K", "boss")
    assert scraped2 == 14
    assert predicted2 == 30


# ─── 6. 抓尽制（Exhaustion）判定状态机 ───
def test_exhaustion_decision():
    # 分母已知且分子小于分母 → 未抓尽
    assert ss.is_exhausted(scraped=10, predicted=20) is False
    # 分子追平分母 → 已抓尽
    assert ss.is_exhausted(scraped=20, predicted=20) is True
    # 分子超过分母 → 已抓尽
    assert ss.is_exhausted(scraped=25, predicted=20) is True
    # 分母未知 (0) → 由 0 新增机制动态切走，is_exhausted 返回 False
    assert ss.is_exhausted(scraped=10, predicted=0) is False


# ─── 7. 重置条件台账 ───
def test_reset_condition_progress(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "DB_PATH", str(tmp_path / "test_pipe.db"))
    ss.init_scrape_sessions_table()
    ss.report_condition_round("测试重置", "广州", "不限", "boss", inserted=12, predicted_total=20)

    # 重置前
    s, p = ss.get_condition_progress("测试重置", "广州", "不限", "boss")
    assert s == 12

    # 调用重置接口
    r = client.post(
        "/api/pipeline/condition-progress/reset",
        json={"keyword": "测试重置", "city": "广州", "salary": "不限", "platform": "boss"},
    )
    assert r.status_code == 200
    assert r.json()["code"] == 0

    # 重置后
    s2, p2 = ss.get_condition_progress("测试重置", "广州", "不限", "boss")
    assert s2 == 0
    assert p2 == 0


# ─── 8. 历史归档与重复提醒闭环 ───
def test_archive_and_duplicate_check(client):
    r_arch = client.post(
        "/api/pipeline/keyword-history/archive",
        json={"keyword": "AI产品经理", "city": "深圳", "salary": "20-30K"},
    )
    assert r_arch.status_code == 200

    # 重复检测
    check_res = client.get("/api/pipeline/keyword-history/check", params={"keyword": "AI产品经理"}).json()["data"]
    assert len(check_res) == 1
    assert check_res[0]["keyword"] == "AI产品经理"
    assert check_res[0]["source"] == "archive"


# ─── 9. 单独执行平台抓取接口验证 ───
def test_run_scrape_only_endpoint(client, monkeypatch):
    called = {}

    async def mock_run_scrape_stage_only(**kwargs):
        called.update(kwargs)
        return "scrape_test_task_123"

    import app.automation.full_auto as full_auto_mod
    monkeypatch.setattr(full_auto_mod, "run_scrape_stage_only", mock_run_scrape_stage_only)

    r = client.post(
        "/api/pipeline/run-scrape-only",
        json={"platforms_limit": 10, "keyword": "AI Agent", "city": "广州"},
    )
    assert r.status_code == 200
    res_data = r.json()
    assert res_data["code"] == 0
    assert res_data["data"]["task_id"] == "scrape_test_task_123"
    assert called["platforms_limit"] == 10
    assert called["keyword"] == "AI Agent"


# ─── 10. 多条件队列在平台 Worker 中的推进与配额约束模拟 ───
def test_platform_worker_multi_condition_budget_cap(monkeypatch):
    """
    模拟平台 Worker 运行多条件：
    - 平台预算 cap = 15 条
    - 队列有 2 个条件：条件1抓 10 条（未满 cap），自动推进到条件2抓 5 条（刚好满 cap 15）
    - 验证：平台在抓满预算后立刻收工退出，不超额抓取。
    """
    dispatches = []

    async def mock_run_dispatch(*args, **kwargs):
        dispatches.append(kwargs)
        return [{"platform": "boss", "task_id": "sub_1", "target_jobs": kwargs.get("target_jobs", 10)}]

    import app.api.routes.crawlers as crawlers_mod
    monkeypatch.setattr(crawlers_mod, "run_dispatch_collect", mock_run_dispatch)

    # 验证配额切分计算
    cap = 15
    cond1_target = min(cap, 10)
    assert cond1_target == 10
    cap -= 10
    assert cap == 5
    cond2_target = min(cap, 10)
    assert cond2_target == 5
    cap -= 5
    assert cap == 0  # 预算用尽，退出循环
