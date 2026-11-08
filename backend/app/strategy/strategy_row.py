"""job_strategies 策略行的单一事实源读取（2026-11-02 拆分子任务）。

config_service（pydantic 模型构造）与 structural_filter（引擎 dict）此前各自书写
SELECT 列序并按位置下标解析——每增删一列需多处平移（Shotgun Surgery，审计
CR-B3-R2-P2）。此处收口列清单与行映射，消费方引用 STRATEGY_COLUMNS 拼 SQL、
调 map_strategy_row 解析。
"""
import json

# 列序即 map_strategy_row 的解析序（新增列：清单尾部追加 + mapper 补一行）
STRATEGY_COLUMNS = (
    "min_salary_k", "max_salary_k", "experience_years_max",
    "exclude_education", "require_education", "allowed_cities",
    "safe_phrases", "keyword_rules", "ai_scout_rules",
)


_JSON_FIELDS = {"exclude_education", "require_education", "allowed_cities", "safe_phrases", "keyword_rules", "ai_scout_rules"}


def map_strategy_row(row) -> dict:
    """按列名语义解析一行 job_strategies（CR-Split-R1-P2：zip 按列名映射，
    消除位置下标平移风险；row 为任意序列：tuple/sqlite3.Row）。"""
    values = list(row) + [None] * (len(STRATEGY_COLUMNS) - len(row))
    mapped = dict(zip(STRATEGY_COLUMNS, values))
    for field in _JSON_FIELDS:
        mapped[field] = json.loads(mapped.get(field) or "[]")
    return mapped
