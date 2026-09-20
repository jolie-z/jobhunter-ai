import os
import sqlite3
from datetime import datetime, timedelta

import pytest
from app.core.model_pricing import (
    calc_cost,
    calc_cost_detailed,
    get_rate,
    get_rate_with_metadata,
    is_mimo_model,
    save_custom_pricing,
    delete_custom_pricing,
    get_custom_pricing,
    reset_pricing_cache_for_testing,
)
from app.services.token_service import recalculate_historical_costs


@pytest.fixture(autouse=True)
def clean_pricing_cache():
    """每个测试前后彻底重置计价缓存，杜绝跨测试污染"""
    reset_pricing_cache_for_testing()
    yield
    reset_pricing_cache_for_testing()



def test_mimo_pricing_rates():
    """验证 MiMo-V2.5 官方真实单价配置"""
    assert is_mimo_model("mimo-v2.5-pro") is True
    assert is_mimo_model("mimo-v2.5") is True
    assert is_mimo_model("deepseek-chat") is False

    rate, is_est = get_rate_with_metadata("mimo-v2.5-pro")
    assert is_est is False
    assert rate["prompt"] == 0.003
    assert rate["cached_prompt"] == 0.000025
    assert rate["completion"] == 0.006

    rate_base, is_est_base = get_rate_with_metadata("mimo-v2.5")
    assert is_est_base is False
    assert rate_base["prompt"] == 0.001
    assert rate_base["cached_prompt"] == 0.000020
    assert rate_base["completion"] == 0.002


def test_calc_cost_without_cache():
    """验证没有缓存命中时的计费"""
    cost, is_est = calc_cost_detailed("mimo-v2.5-pro", prompt_tokens=2540, completion_tokens=1894, cached_tokens=0)
    assert is_est is False
    assert cost == 0.018984


def test_calc_cost_with_cache():
    """验证命中缓存时的优惠抵扣计费"""
    cost, is_est = calc_cost_detailed("mimo-v2.5-pro", prompt_tokens=8076, completion_tokens=3421, cached_tokens=4096)
    assert is_est is False
    assert cost == 0.032568


def test_calc_cost_bounds_guard():
    """验证边界防护（cached_tokens 超过 prompt_tokens 时不能倒扣）"""
    cost, is_est = calc_cost_detailed("mimo-v2.5-pro", prompt_tokens=1000, completion_tokens=500, cached_tokens=2000)
    assert is_est is False
    assert cost == 0.003025


def test_non_mimo_unconfigured_fallback():
    """验证非 MiMo 模型未配置时按 MiMo 兜底并标记为预估"""
    cost, is_est = calc_cost_detailed("deepseek-chat", prompt_tokens=2540, completion_tokens=1894, cached_tokens=0)
    # 未配置自定义单价时，应标记为预估
    assert is_est is True
    # 金额按 mimo-v2.5-pro 兜底
    assert cost == 0.018984


def test_custom_pricing_persistence_and_calc(tmp_path):
    """验证用户自定义单价配置、生效与重置"""
    test_db = str(tmp_path / "custom_test.db")
    
    # 1. 保存自定义单价（例如 deepseek: 输入未命中 2元/1M, 缓存 0.5元/1M, 输出 8元/1M）
    save_custom_pricing(
        model_name="deepseek-chat",
        prompt_per_1m=2.0,
        cached_prompt_per_1m=0.5,
        completion_per_1m=8.0,
        db_path=test_db,
    )

    custom = get_custom_pricing("deepseek-chat")
    assert custom is not None
    assert custom["raw_prompt_1m"] == 2.0
    assert custom["raw_cached_1m"] == 0.5
    assert custom["raw_completion_1m"] == 8.0

    # 计算成本: 输入 1000 (缓存 500), 输出 500
    # uncached 500 * (2/1M) = 0.0010
    # cached 500 * (0.5/1M) = 0.00025
    # completion 500 * (8/1M) = 0.0040
    # total = 0.00525
    cost, is_est = calc_cost_detailed("deepseek-chat", prompt_tokens=1000, completion_tokens=500, cached_tokens=500)
    assert is_est is False
    assert cost == 0.00525

    # 2. 删除重置
    deleted = delete_custom_pricing("deepseek-chat", db_path=test_db)
    assert deleted is True
    assert get_custom_pricing("deepseek-chat") is None

    # 重置后再计算，恢复预估
    cost_reset, is_est_reset = calc_cost_detailed("deepseek-chat", prompt_tokens=1000, completion_tokens=500, cached_tokens=500)
    assert is_est_reset is True


def test_recalculate_historical_costs(tmp_path):
    """验证历史数据批量重算逻辑"""
    test_db = str(tmp_path / "test_hunter.db")
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE token_log (
            id TEXT PRIMARY KEY,
            action_name TEXT DEFAULT '',
            caller TEXT DEFAULT '',
            job_id TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            model_name TEXT DEFAULT '',
            cost_cny REAL DEFAULT 0,
            estimated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO token_log (id, action_name, prompt_tokens, completion_tokens, total_tokens, cached_tokens, model_name, cost_cny, created_at)
        VALUES ('1', 'skill_rewrite', 8076, 3421, 11497, 4096, 'mimo-v2.5-pro', 0.1610, '2026-09-12 15:00:00')
    """)
    conn.commit()
    conn.close()

    res = recalculate_historical_costs(db_path=test_db)
    assert res["updated_count"] == 1
    assert res["old_total_cost"] == 0.1610
    assert res["new_total_cost"] == 0.0326

    # 检查数据库中的值
    conn = sqlite3.connect(test_db)
    row = conn.execute("SELECT cost_cny, estimated FROM token_log WHERE id = '1'").fetchone()
    conn.close()
    assert row[0] == 0.032568
    assert row[1] == 0


def test_mimo_v2_5_standard_pricing():
    """验证 mimo-v2.5 标准版的官方精准计价（未命中1.0元/1M, 缓存0.02元/1M, 输出2.0元/1M）"""
    # 1000 prompt (500 uncached, 500 cached), 500 completion
    # uncached: 500 * (1.0 / 1_000_000) = 0.0005
    # cached: 500 * (0.02 / 1_000_000) = 0.00001
    # completion: 500 * (2.0 / 1_000_000) = 0.001
    # total = 0.00151
    cost, is_est = calc_cost_detailed(
        "mimo-v2.5",
        prompt_tokens=1000,
        completion_tokens=500,
        cached_tokens=500,
    )
    assert is_est is False
    assert round(cost, 6) == 0.00151


def test_recalculate_target_model_isolation(tmp_path):
    """验证重算历史记录时，根据 target_model 精准隔离，绝不破坏其他模型的历史记录"""
    test_db = str(tmp_path / "test_hunter_isolation.db")
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE token_log (
            id TEXT PRIMARY KEY,
            action_name TEXT DEFAULT '',
            caller TEXT DEFAULT '',
            job_id TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            model_name TEXT DEFAULT '',
            cost_cny REAL DEFAULT 0,
            estimated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    # 插入三条不同模型的记录：
    # 1. deepseek-chat（属于 deepseek 系列）
    # 2. gpt-4o（独立第三方模型，自定义成本保留 9.999）
    # 3. mimo-v2.5-pro（官方模型）
    conn.execute("""
        INSERT INTO token_log (id, action_name, prompt_tokens, completion_tokens, total_tokens, cached_tokens, model_name, cost_cny, created_at)
        VALUES 
            ('row-ds', 'test_act', 1000000, 1000000, 2000000, 0, 'deepseek-chat', 99.0, '2026-09-12 12:00:00'),
            ('row-gpt', 'test_act', 1000000, 1000000, 2000000, 0, 'gpt-4o', 9.999, '2026-09-12 12:00:00'),
            ('row-mimo', 'test_act', 1000000, 1000000, 2000000, 0, 'mimo-v2.5-pro', 8.888, '2026-09-12 12:00:00')
    """)
    conn.commit()
    conn.close()

    # 为 deepseek 配置自定义单价：输入 2.0，输出 8.0（总价应为 10.0）
    save_custom_pricing(
        model_name="deepseek",
        prompt_per_1m=2.0,
        cached_prompt_per_1m=0.5,
        completion_per_1m=8.0,
        db_path=test_db,
    )

    # 仅针对 deepseek 触发历史重算（前缀兼容 deepseek-chat）
    res = recalculate_historical_costs(target_model="deepseek", db_path=test_db)
    assert res["updated_count"] == 1
    assert res["old_total_cost"] == 99.0
    assert res["new_total_cost"] == 10.0

    # 检查数据库验证隔离性：gpt-4o 和 mimo 的 cost 必须保持原样不变！
    conn = sqlite3.connect(test_db)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, cost_cny, estimated FROM token_log").fetchall()}
    conn.close()

    # deepseek-chat 被更新为自定义精确计算
    assert rows["row-ds"][0] == 10.0
    assert rows["row-ds"][1] == 0

    # gpt-4o 毫发无损！
    assert rows["row-gpt"][0] == 9.999

    # mimo 毫发无损！
    assert rows["row-mimo"][0] == 8.888


def test_save_custom_pricing_rejects_mimo():
    """验证 save_custom_pricing 防呆拦截，禁止对 MiMo 官方模型保存自定义计价"""
    with pytest.raises(ValueError, match="属于 MiMo 官方系列"):
        save_custom_pricing(
            model_name="mimo-v2.5-pro",
            prompt_per_1m=1.0,
            cached_prompt_per_1m=0.1,
            completion_per_1m=2.0,
        )


def test_recalculate_skips_empty_and_reverse_prefix(tmp_path):
    """验证重算逻辑严格跳过空模型名行，且杜绝反向模糊匹配（如 target 为 deepseek-chat 时绝不误改 deepseek）"""
    test_db = str(tmp_path / "test_hunter_strict_match.db")
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE token_log (
            id TEXT PRIMARY KEY,
            action_name TEXT DEFAULT '',
            caller TEXT DEFAULT '',
            job_id TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            model_name TEXT DEFAULT '',
            cost_cny REAL DEFAULT 0,
            estimated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO token_log (id, action_name, prompt_tokens, completion_tokens, total_tokens, cached_tokens, model_name, cost_cny, estimated, created_at)
        VALUES 
            ('row-empty', 'act', 1000, 1000, 2000, 0, '', 5.55, 1, '2026-09-12 12:00:00'),
            ('row-short', 'act', 1000, 1000, 2000, 0, 'deepseek', 6.66, 0, '2026-09-12 12:00:00'),
            ('row-exact', 'act', 1000000, 1000000, 2000000, 0, 'deepseek-chat', 99.0, 1, '2026-09-12 12:00:00')
    """)
    conn.commit()
    conn.close()

    save_custom_pricing(
        model_name="deepseek-chat",
        prompt_per_1m=2.0,
        cached_prompt_per_1m=0.5,
        completion_per_1m=8.0,
        db_path=test_db,
    )

    # 以 deepseek-chat 为 target_model 执行定向重算
    res = recalculate_historical_costs(target_model="deepseek-chat", db_path=test_db)
    assert res["updated_count"] == 1
    assert res["old_total_cost"] == 99.0
    assert res["new_total_cost"] == 10.0

    # 验证空模型行和短名称行分毫未动
    conn = sqlite3.connect(test_db)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, cost_cny, estimated FROM token_log").fetchall()}
    conn.close()

    assert rows["row-empty"][0] == 5.55
    assert rows["row-empty"][1] == 1

    assert rows["row-short"][0] == 6.66
    assert rows["row-short"][1] == 0

    assert rows["row-exact"][0] == 10.0
    assert rows["row-exact"][1] == 0


def test_recalculate_target_model_case_insensitive(tmp_path):
    """验证大小写归一：target 与行模型名大小写不同（DeepSeek-Chat vs deepseek-chat）仍能精准匹配重算"""
    test_db = str(tmp_path / "test_hunter_case.db")
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE token_log (
            id TEXT PRIMARY KEY,
            action_name TEXT DEFAULT '',
            caller TEXT DEFAULT '',
            job_id TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            model_name TEXT DEFAULT '',
            cost_cny REAL DEFAULT 0,
            estimated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO token_log (id, action_name, prompt_tokens, completion_tokens, total_tokens, cached_tokens, model_name, cost_cny, estimated, created_at)
        VALUES
            ('row-upper', 'act', 1000000, 1000000, 2000000, 0, 'DeepSeek-Chat', 99.0, 1, '2026-09-12 12:00:00'),
            ('row-gpt', 'act', 1000000, 1000000, 2000000, 0, 'GPT-4o', 9.999, 0, '2026-09-12 12:00:00')
    """)
    conn.commit()
    conn.close()

    save_custom_pricing(
        model_name="deepseek-chat",
        prompt_per_1m=2.0,
        cached_prompt_per_1m=0.5,
        completion_per_1m=8.0,
        db_path=test_db,
    )

    # 以大写形态的模型名作为 target，也应命中小写存储行（双方均做 lower().strip() 归一）
    res = recalculate_historical_costs(target_model="DeepSeek-Chat", db_path=test_db)
    assert res["updated_count"] == 1
    assert res["new_total_cost"] == 10.0

    # 计价查找同样大小写归一：大写模型名应命中自定义单价且非预估
    rate, is_est = get_rate_with_metadata("DeepSeek-Chat")
    assert is_est is False
    assert rate["prompt"] == 2.0 / 1000.0

    conn = sqlite3.connect(test_db)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, cost_cny, estimated FROM token_log").fetchall()}
    conn.close()
    assert rows["row-upper"][0] == 10.0
    assert rows["row-upper"][1] == 0
    # 大小写不同的其他模型毫发无损
    assert rows["row-gpt"][0] == 9.999


def test_cleanup_old_records_keeps_latest_50(tmp_path):
    """验证写路径轮转：token_log 超过 50 条时仅保留最新 50 条"""
    from app.services.token_service import _cleanup_old_records

    test_db = str(tmp_path / "test_hunter_rotate.db")
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE token_log (
            id TEXT PRIMARY KEY,
            action_name TEXT DEFAULT '',
            caller TEXT DEFAULT '',
            job_id TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            model_name TEXT DEFAULT '',
            cost_cny REAL DEFAULT 0,
            estimated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.executemany(
        "INSERT INTO token_log (id, created_at) VALUES (?, ?)",
        [(f"row-{i:02d}", f"2026-09-12 10:{i:02d}:00") for i in range(55)],
    )
    conn.commit()

    _cleanup_old_records(conn)
    conn.commit()

    ids = [r[0] for r in conn.execute("SELECT id FROM token_log ORDER BY created_at ASC").fetchall()]
    conn.close()
    assert len(ids) == 50
    # 最旧的 5 条被清除，保留的是 row-05..row-54
    assert ids[0] == "row-05"
    assert ids[-1] == "row-54"


def test_backfill_cost_respects_time_range_filter(tmp_path):
    """验证 backfill 补算聚合与 time_range 过滤同口径：今日视图不污染昨日成本，daily_trend 仍保持全周期"""
    from app.services.analytics_stats_service import calculate_token_stats

    test_db = str(tmp_path / "test_hunter_range.db")
    conn = sqlite3.connect(test_db)
    conn.execute("""
        CREATE TABLE token_log (
            id TEXT PRIMARY KEY,
            action_name TEXT DEFAULT '',
            caller TEXT DEFAULT '',
            job_id TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            model_name TEXT DEFAULT '',
            cost_cny REAL DEFAULT 0,
            estimated INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 10:00:00")
    today = datetime.now().strftime("%Y-%m-%d 10:00:00")
    conn.executemany(
        "INSERT INTO token_log (id, action_name, model_name, cost_cny, created_at) VALUES (?,?,?,?,?)",
        [
            ("row-yday", "skill_rewrite", "mimo-v2.5-pro", 1.0, yday),
            ("row-today", "skill_rewrite", "mimo-v2.5-pro", 2.0, today),
        ],
    )
    conn.commit()
    conn.close()

    # 今日视图：by_action 成本只能是今天的 2.0，不得混入昨天的 1.0
    d_today = calculate_token_stats(time_range="today", backfill_missing_cost=True, db_path=test_db)
    assert d_today["by_action"][0]["cost_cny"] == 2.0
    assert d_today["today_cost_cny"] == 2.0
    # daily_trend 不受 range 过滤：两天成本必须齐全（1.0 / 2.0）
    assert sorted(x["cost_cny"] for x in d_today["daily_trend"]) == [1.0, 2.0]

    # 全量视图：同一动作成本为两天之和
    d_all = calculate_token_stats(time_range="all", backfill_missing_cost=True, db_path=test_db)
    assert d_all["by_action"][0]["cost_cny"] == 3.0
    assert d_all["total_cost_cny"] == 3.0



