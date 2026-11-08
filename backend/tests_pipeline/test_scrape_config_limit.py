"""条件队列上限校验 + 条件历史记录（/api/pipeline/scrape-config、/keyword-history*）

背景：条件队列上限 10 组（每组 = 关键词+薪资+城市），满了只能删减/归档不能再新增；
历史记录用于防止忘记抓过某个关键词（链路自动记录 + 手动归档 + 添加时重复提醒）。
临时 DB 隔离，不碰用户真实配置。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.pipeline as pipeline_mod
from app.pipeline.router import router


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(pipeline_mod, "_initialized", False)
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_keyword_queue_over_cap_rejected(client):
    kws = [{"keyword": f"测试词{i}"} for i in range(11)]
    r = client.put(
        "/api/pipeline/scrape-config",
        json={"keywords": kws, "platforms": {}, "default_city": "", "default_salary": ""},
    )
    assert r.status_code == 400
    assert "最多 10 组" in r.json()["detail"]


def test_keyword_queue_at_cap_saved(client):
    kws = [{"keyword": f"测试词{i}"} for i in range(10)]
    r = client.put(
        "/api/pipeline/scrape-config",
        json={"keywords": kws, "platforms": {}, "default_city": "广州", "default_salary": "不限"},
    )
    assert r.status_code == 200
    assert r.json()["code"] == 0
    got = client.get("/api/pipeline/scrape-config").json()["data"]
    assert len(got["keywords"]) == 10
    assert got["default_city"] == "广州"


def test_keyword_history_archive_and_roundtrip(client):
    # 手动归档一条
    r = client.post(
        "/api/pipeline/keyword-history/archive",
        json={"keyword": "AI应用", "city": "广州", "salary": "不限"},
    )
    assert r.status_code == 200 and r.json()["code"] == 0

    # 列表可查到，来源为 archive
    items = client.get("/api/pipeline/keyword-history").json()["data"]
    assert len(items) == 1
    assert items[0]["keyword"] == "AI应用"
    assert items[0]["source"] == "archive"

    # 重复检测：忽略大小写/首尾空格
    hits = client.get("/api/pipeline/keyword-history/check", params={"keyword": " ai应用 "}).json()["data"]
    assert len(hits) == 1

    # 未命中
    hits2 = client.get("/api/pipeline/keyword-history/check", params={"keyword": "前端开发"}).json()["data"]
    assert hits2 == []

    # 删除
    hid = items[0]["id"]
    assert client.delete(f"/api/pipeline/keyword-history/{hid}").status_code == 200
    assert client.get("/api/pipeline/keyword-history").json()["data"] == []
    # 重复删除返回 404
    assert client.delete(f"/api/pipeline/keyword-history/{hid}").status_code == 404


def test_salary_mapping_endpoint(client):
    r = client.get("/api/pipeline/salary-mapping")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "tiers" in data and "mapping" in data
    assert "15-20K" in data["tiers"]
    tier_15_20 = data["mapping"]["15-20K"]
    assert tier_15_20["boss"] == "15-20K"
    assert tier_15_20["zhilian"] == "15K-25K"
    assert tier_15_20["51job"] == "15-20K"
    assert tier_15_20["liepin"] == "15-20K"


def test_condition_progress_endpoint(client):
    r = client.get("/api/pipeline/condition-progress")
    assert r.status_code == 200
    assert r.json()["code"] == 0

    # Reset endpoint
    reset_r = client.post(
        "/api/pipeline/condition-progress/reset",
        json={"keyword": "AI测试", "city": "广州", "salary": "不限", "platform": "boss"},
    )
    assert reset_r.status_code == 200
    assert reset_r.json()["code"] == 0



def test_platform_limit_clamped_to_new_cap_on_save_and_read(client):
    """单平台单轮上限 50→15 收紧：保存时 clamp、读取时同样 clamp（存量超限值即时收敛）。"""
    r = client.put(
        "/api/pipeline/scrape-config",
        json={
            "keywords": [{"keyword": "agent"}],
            "platforms": {"boss": {"enabled": True, "limit": 20}, "liepin": {"enabled": True, "limit": 15}},
            "default_city": "广州",
            "default_salary": "不限",
        },
    )
    assert r.status_code == 200
    got = client.get("/api/pipeline/scrape-config").json()["data"]
    # 保存路径：超限 20 → 15；上限值 15 原样保留
    assert got["platforms"]["boss"]["limit"] == 15
    assert got["platforms"]["liepin"]["limit"] == 15

    # 读取路径兜底：直接改库写入超限值（模拟历史版本存量数据），读出来也必须 ≤15
    import sqlite3
    conn = sqlite3.connect(pipeline_mod.DB_PATH)
    try:
        conn.execute(
            "UPDATE pipeline_scrape_config SET platforms = ? WHERE id = 1",
            ['{"boss": {"enabled": true, "limit": 50}}'],
        )
        conn.commit()
    finally:
        conn.close()
    got = client.get("/api/pipeline/scrape-config").json()["data"]
    assert got["platforms"]["boss"]["limit"] == 15


def test_platform_limit_default_three_kept_and_invalid_falls_back(client):
    """新默认值 3 不被误 clamp；非法值回落 3。"""
    r = client.put(
        "/api/pipeline/scrape-config",
        json={
            "keywords": [{"keyword": "agent"}],
            "platforms": {"boss": {"enabled": True, "limit": 3}, "zhilian": {"enabled": True, "limit": "abc"}},
            "default_city": "",
            "default_salary": "",
        },
    )
    assert r.status_code == 200
    got = client.get("/api/pipeline/scrape-config").json()["data"]
    assert got["platforms"]["boss"]["limit"] == 3
    assert got["platforms"]["zhilian"]["limit"] == 3
