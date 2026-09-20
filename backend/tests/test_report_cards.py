"""
飞书战报卡片构建与组件规范单元测试。
测试日常战报、周报、月报与终报的卡片元素、表格结构及 Token 模块。
"""
import sqlite3

import pytest
from app.services.report_service import (
    generate_daily_report,
    generate_weekly_report,
    generate_monthly_report,
    generate_final_report,
)
from app.services.report_feishu import (
    build_daily_card,
    build_weekly_card,
    build_monthly_card,
    build_final_card,
)


@pytest.fixture(autouse=True)
def _hermetic_analytics_db(tmp_path, monkeypatch):
    """密闭化：战报统计只读三张表（job_goals/token_log/raw_jobs），
    用临时空库隔离，杜绝依赖本地生产 SQLite（CI/新克隆无库必炸）。"""
    from app.services import report_service

    db = tmp_path / "analytics_test.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE job_goals (id INTEGER PRIMARY KEY);
        CREATE TABLE token_log (created_at TEXT, total_tokens REAL, model_name TEXT);
        CREATE TABLE raw_jobs (crawl_time TEXT, platform TEXT, process_status TEXT);
        """
    )
    con.commit()
    con.close()
    monkeypatch.setattr(report_service, "DB_PATH", str(db))
    yield


def test_daily_card_structure():
    rep = generate_daily_report()
    card = build_daily_card(rep)

    assert card["config"]["wide_screen_mode"] is True
    assert card["header"]["template"] == "blue"
    assert "求职战报中心" in card["header"]["title"]["content"]

    elements = card["elements"]
    assert len(elements) >= 8

    # 验证第一组 column_set (4列今日流水)
    flow_col_set = next(e for e in elements if e.get("tag") == "column_set" and e.get("flex_mode") == "bisect")
    assert len(flow_col_set["columns"]) == 4
    col_titles = [c["elements"][0]["text"]["content"] for c in flow_col_set["columns"]]
    assert any("今日新抓取" in t for t in col_titles)
    assert any("AI 清洗放行" in t for t in col_titles)
    assert any("今日实际投递" in t for t in col_titles)
    assert any("待投递池存量" in t for t in col_titles)

    # 验证第二组 column_set (3列全局漏斗)
    funnel_col_set = next(e for e in elements if e.get("tag") == "column_set" and e.get("flex_mode") == "none")
    assert len(funnel_col_set["columns"]) == 3

    # 验证渠道表格
    channel_table = next(e for e in elements if e.get("tag") == "table")
    assert len(channel_table["columns"]) == 4
    assert len(channel_table["rows"]) > 0

    # 验证 Token 模块展示真实主力模型（非写死 DeepSeek）
    token_headers = [e for e in elements if e.get("tag") == "div" and "AI 模型与算力消耗" in e["text"]["content"]]
    assert len(token_headers) == 1
    token_col_sets = [e for e in elements if e.get("tag") == "column_set"]
    token_col_set = token_col_sets[-1]
    engine_col = token_col_set["columns"][-1]["elements"][0]["text"]["content"]
    assert "DeepSeek" not in engine_col
    assert "mimo" in engine_col.lower()


def test_weekly_card_structure():
    rep = generate_weekly_report()
    card = build_weekly_card(rep)

    assert card["header"]["template"] == "green"
    assert "求职周报" in card["header"]["title"]["content"]

    elements = card["elements"]
    # 验证包含渠道表格
    channel_table = next(e for e in elements if e.get("tag") == "table")
    assert channel_table is not None

    # 验证 Token 模块
    token_headers = [e for e in elements if e.get("tag") == "div" and "AI 模型与算力消耗" in e["text"]["content"]]
    assert len(token_headers) == 1


def test_monthly_card_structure():
    rep = generate_monthly_report()
    card = build_monthly_card(rep)

    assert card["header"]["template"] == "purple"
    assert "求职月报" in card["header"]["title"]["content"]

    elements = card["elements"]
    # 验证包含表格
    table = next(e for e in elements if e.get("tag") == "table")
    assert table is not None

    # 验证包含日均算力成本
    token_col_set = [e for e in elements if e.get("tag") == "column_set"]
    assert len(token_col_set) >= 2


def test_final_card_structure():
    rep = generate_final_report()
    card = build_final_card(rep)

    assert card["header"]["template"] == "orange"
    assert "求职终报" in card["header"]["title"]["content"]
