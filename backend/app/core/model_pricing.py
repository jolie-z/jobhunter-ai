import datetime
import logging
import os
import sqlite3

logger = logging.getLogger("model_pricing")

# 价格内部基准单位: CNY / 1K tokens
# 注: 用户界面统一输入 "元 / 1M tokens" (百万 tokens)，存取时统一进行 /1000 与 *1000 换算

# MiMo 官方标准资费 (基于小米官网最新定价: pro 未命中 ¥3/1M, 命中 ¥0.025/1M, 输出 ¥6/1M)
MIMO_PRICING: dict[str, dict[str, float]] = {
    "mimo-v2.5-pro": {"prompt": 0.003, "cached_prompt": 0.000025, "completion": 0.006},
    "mimo-v2.5":     {"prompt": 0.001, "cached_prompt": 0.000020, "completion": 0.002},
    "mimo":          {"prompt": 0.003, "cached_prompt": 0.000025, "completion": 0.006},
}

# 默认兜底费率 (当非 MiMo 且用户未配置时使用，并标记为预估)
DEFAULT_MIMO_RATE: dict[str, float] = MIMO_PRICING["mimo-v2.5-pro"]

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "job_hunter.db",
)

# 内存缓存自定义定价，避免每次调用均查询 SQLite
_CUSTOM_PRICING_CACHE: dict[str, dict[str, float]] = {}
_CACHE_INITIALIZED = False


def _ensure_pricing_db(db_path: str = DB_PATH) -> None:
    """初始化 custom_model_pricing 表"""
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_model_pricing (
                    model_name TEXT PRIMARY KEY,
                    prompt_rate REAL NOT NULL,        -- 元 / 1M tokens
                    cached_prompt_rate REAL NOT NULL, -- 元 / 1M tokens
                    completion_rate REAL NOT NULL,   -- 元 / 1M tokens
                    updated_at TEXT NOT NULL
                );
            """)
            conn.commit()
    except Exception as e:
        logger.warning(f"[model_pricing] 初始化 custom_model_pricing 表失败: {e}")


def _load_custom_pricing_cache(db_path: str = DB_PATH) -> None:
    """启动或更新时加载全部自定义模型价格到内存"""
    global _CUSTOM_PRICING_CACHE, _CACHE_INITIALIZED
    try:
        _ensure_pricing_db(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM custom_model_pricing").fetchall()
            new_cache = {}
            for r in rows:
                m_name = (r["model_name"] or "").lower().strip()
                new_cache[m_name] = {
                    "prompt": float(r["prompt_rate"] or 0) / 1000.0,
                    "cached_prompt": float(r["cached_prompt_rate"] or 0) / 1000.0,
                    "completion": float(r["completion_rate"] or 0) / 1000.0,
                    "raw_prompt_1m": float(r["prompt_rate"] or 0),
                    "raw_cached_1m": float(r["cached_prompt_rate"] or 0),
                    "raw_completion_1m": float(r["completion_rate"] or 0),
                }
            _CUSTOM_PRICING_CACHE = new_cache
            _CACHE_INITIALIZED = True
    except Exception as e:
        logger.warning(f"[model_pricing] 读取自定义模型计价缓存失败: {e}")
        _CACHE_INITIALIZED = True


def is_mimo_model(model_name: str) -> bool:
    """判断模型是否为小米 MiMo 系列"""
    if not model_name:
        return False
    name = model_name.lower().strip()
    return name.startswith("mimo")


def get_custom_pricing(model_name: str, db_path: str = DB_PATH) -> dict[str, float] | None:
    """获取指定模型的自定义定价信息，若未配置返回 None"""
    global _CACHE_INITIALIZED
    if not _CACHE_INITIALIZED:
        _load_custom_pricing_cache(db_path)
    if not model_name:
        return None
    name = model_name.lower().strip()
    if name in _CUSTOM_PRICING_CACHE:
        return _CUSTOM_PRICING_CACHE[name]
    # 前缀匹配
    for k, v in _CUSTOM_PRICING_CACHE.items():
        if name.startswith(k):
            return v
    return None


def reset_pricing_cache_for_testing() -> None:
    """仅供测试隔离使用：复位内存缓存状态"""
    global _CUSTOM_PRICING_CACHE, _CACHE_INITIALIZED
    _CUSTOM_PRICING_CACHE = {}
    _CACHE_INITIALIZED = False


def save_custom_pricing(
    model_name: str,
    prompt_per_1m: float,
    cached_prompt_per_1m: float,
    completion_per_1m: float,
    db_path: str = DB_PATH,
) -> None:
    """保存或更新用户自定义模型计价（入参单位：元 / 1M tokens）"""
    name = (model_name or "").lower().strip()
    if not name:
        raise ValueError("模型名称不能为空")
    if is_mimo_model(name):
        raise ValueError(f"模型 [{name}] 属于 MiMo 官方系列，系统已内置基准精准资费，无需重复配置")

    _ensure_pricing_db(db_path)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO custom_model_pricing (model_name, prompt_rate, cached_prompt_rate, completion_rate, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(model_name) DO UPDATE SET
                prompt_rate = excluded.prompt_rate,
                cached_prompt_rate = excluded.cached_prompt_rate,
                completion_rate = excluded.completion_rate,
                updated_at = excluded.updated_at
            """,
            (name, prompt_per_1m, cached_prompt_per_1m, completion_per_1m, now_str),
        )
        conn.commit()
    # 刷新内存缓存
    _load_custom_pricing_cache(db_path)
    logger.info(
        f"[model_pricing] 已保存自定义计价: model={name}, prompt={prompt_per_1m}¥/1M, "
        f"cached={cached_prompt_per_1m}¥/1M, completion={completion_per_1m}¥/1M"
    )


def delete_custom_pricing(model_name: str, db_path: str = DB_PATH) -> bool:
    """删除指定模型的自定义计价"""
    _ensure_pricing_db(db_path)
    name = (model_name or "").lower().strip()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_model_pricing WHERE model_name = ?", (name,))
        conn.commit()
        deleted = cursor.rowcount > 0
    _load_custom_pricing_cache(db_path)
    return deleted


def get_rate_with_metadata(model_name: str) -> tuple[dict[str, float], bool]:
    """
    根据模型名查找计价费率及是否为预估模式。

    返回: (rate_dict, is_estimated)
    - rate_dict 格式: {"prompt": float, "cached_prompt": float, "completion": float} (单位: CNY/1K)
    - is_estimated: bool（若非 MiMo 且用户未配置，则为 True）
    """
    if not model_name:
        return DEFAULT_MIMO_RATE, True

    name = model_name.lower().strip()

    # 1. 命中 MiMo 系列 -> 精确官方定价
    if is_mimo_model(name):
        if name in MIMO_PRICING:
            return MIMO_PRICING[name], False
        for prefix, rate in MIMO_PRICING.items():
            if name.startswith(prefix):
                return rate, False
        return DEFAULT_MIMO_RATE, False

    # 2. 非 MiMo 模型 -> 查询用户自定义配置
    custom = get_custom_pricing(name)
    if custom:
        return {
            "prompt": custom["prompt"],
            "cached_prompt": custom["cached_prompt"],
            "completion": custom["completion"],
        }, False

    # 3. 非 MiMo 模型且未配置 -> 使用 MiMo-v2.5-pro 兜底，并标记为「预估」
    return DEFAULT_MIMO_RATE, True


def get_rate(model_name: str) -> dict[str, float]:
    """兼容旧接口：返回费率字典"""
    rate, _ = get_rate_with_metadata(model_name)
    return rate


def calc_cost_detailed(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> tuple[float, bool]:
    """
    计算单次调用的成本（CNY），同时返回是否为预估成本 (is_estimated)。
    """
    rate, is_estimated = get_rate_with_metadata(model_name)
    cached = max(0, min(int(cached_tokens or 0), int(prompt_tokens or 0)))
    uncached = max(0, int(prompt_tokens or 0) - cached)

    prompt_rate = rate.get("prompt", 0.0)
    cached_rate = rate.get("cached_prompt", prompt_rate)
    completion_rate = rate.get("completion", 0.0)

    cost = (
        (uncached / 1000.0) * prompt_rate
        + (cached / 1000.0) * cached_rate
        + (int(completion_tokens or 0) / 1000.0) * completion_rate
    )
    return round(cost, 6), is_estimated


def calc_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """计算单次调用的成本（CNY）"""
    cost, _ = calc_cost_detailed(model_name, prompt_tokens, completion_tokens, cached_tokens)
    return cost
