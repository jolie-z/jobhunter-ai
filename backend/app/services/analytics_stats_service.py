# app/services/analytics_stats_service.py
"""
大模型 Token 算力与费用统计聚合服务层。
集中收敛 token_log 的全量用量计算、分时统计（今日/当月/全量）、场景聚合、模型分布、14天日趋势及明细分页。
统一供 v1 (/api/analytics/tokens) 与 v2 (/api/v2/analytics/tokens) 路由复用，消除多处重复代码与连接泄漏风险。
"""
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.model_pricing import get_custom_pricing, is_mimo_model
from common.config import CLEANER_LLM_MODEL, CLEANER_VISION_MODEL, VISION_MODEL

logger = logging.getLogger(__name__)

# 本地数据库默认路径
_LOCAL_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "job_hunter.db"
)
DEFAULT_DB_PATH = os.environ.get("ANALYTICS_DB_PATH") or _LOCAL_DB

# 中文场景名映射字典（v1/v2 合并收录，缺条目会导致明细页渲染英文原名）
ACTION_DISPLAY_NAMES = {
    "step1_rule_filter:evaluate_job": "AI岗位评估",
    "router:call_llm": "路由LLM调用",
    "resume_structurer:call_llm": "简历结构化",
    "test_precheck": "预检测试",
    "verify_fix": "验证修复",
    "step1_ai_scout": "AI侦察兵初筛",
    "ai_evaluator": "AI评估器",
    "skill_rewrite": "简历改写",
    "step2_deep_evaluate:evaluate_deep": "AI深度评估",
    "step2_deep_evaluate:generate_report": "生成诊断报告",
    "llm_client:call": "大模型调用",
    "agent_chat": "Agent实时对话",
    "quick_greeting": "快捷打招呼",
    "copilot": "Copilot助手",
    "deep_rewrite": "深度改写",
    "global_diagnosis": "全局诊断",
    "grill_suggestion": "面试追问建议",
    "ats_align": "ATS对齐",
}


def _hit_rate(cached_tokens: int, prompt_tokens: int) -> float:
    """缓存命中率 = 命中缓存的输入 / 总输入（百分比，保留1位）。输入为 0 时返回 0。"""
    if not prompt_tokens:
        return 0.0
    return round((cached_tokens or 0) / prompt_tokens * 100, 1)


def _calc_cost_for_row(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    stored_cost: float,
    cached_tokens: int = 0,
) -> float:
    """如果存储的 cost_cny 为 0，用计价表实时补算（包含缓存命中优惠）。"""
    if stored_cost and stored_cost > 0:
        return stored_cost
    try:
        from app.core.model_pricing import calc_cost
        return calc_cost(
            model_name or "",
            prompt_tokens or 0,
            completion_tokens or 0,
            cached_tokens or 0,
        )
    except Exception:
        return 0.0


def _get_display_name(action_name: str | None) -> str:
    if not action_name:
        return "未知场景"
    return ACTION_DISPLAY_NAMES.get(action_name, action_name)


def calculate_token_stats(
    time_range: str = "all",
    page: int = 1,
    page_size: int = 10,
    db_path: str | None = None,
    backfill_missing_cost: bool = False,
) -> dict[str, Any]:
    """
    聚合计算系统 Token 用量与成本统计数据。
    支持时段过滤 (today / month / all) 与审计日志分页。

    backfill_missing_cost: 对 cost_cny=0 的存量行按计价表实时补算（v1 历史行为）。
    v1 路由传 True 以保持既有口径；v2 维持 False 直读存储值，双方各自零漂移。
    """
    target_db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        now_dt = datetime.now()
        today = now_dt.strftime("%Y-%m-%d")
        month_start = now_dt.strftime("%Y-%m") + "-01"

        all_rows = conn.execute(
            "SELECT action_name, model_name, prompt_tokens, completion_tokens, total_tokens, cached_tokens, cost_cny, created_at FROM token_log"
        ).fetchall()

        # v1 历史口径：对 cost=0 的存量行按计价表实时补算，并按动作/模型/日预聚合费用
        action_cost_sum: dict[str, float] = {}
        model_cost_sum: dict[str, float] = {}
        day_cost_sum: dict[str, float] = {}
        if backfill_missing_cost:
            for r in all_rows:
                c = _calc_cost_for_row(
                    r["model_name"],
                    r["prompt_tokens"],
                    r["completion_tokens"],
                    r["cost_cny"],
                    r["cached_tokens"],
                )
                d_key = (r["created_at"] or "")[:10]
                day_cost_sum[d_key] = day_cost_sum.get(d_key, 0.0) + c
                created = r["created_at"] or ""
                # 仅对符合当前 time_range 的行累加动作/模型费用，与 by_action/by_model 的 SQL 过滤同口径
                # （daily_trend 的 SQL 是全周期近 14 天，故 day_cost_sum 不受此守卫约束）
                if time_range == "today" and created < today:
                    continue
                if time_range == "month" and created < month_start:
                    continue
                a_key = r["action_name"] or ""
                m_key = r["model_name"] or ""
                action_cost_sum[a_key] = action_cost_sum.get(a_key, 0.0) + c
                model_cost_sum[m_key] = model_cost_sum.get(m_key, 0.0) + c

        today_tokens = month_tokens = total_tokens = 0
        today_cost = month_cost = total_cost = 0.0
        today_prompt = today_cached = 0
        month_prompt = month_cached = 0
        total_prompt = total_cached = 0

        for r in all_rows:
            tokens = int(r["total_tokens"] or 0)
            if backfill_missing_cost:
                cost = _calc_cost_for_row(
                    r["model_name"],
                    r["prompt_tokens"],
                    r["completion_tokens"],
                    r["cost_cny"],
                    r["cached_tokens"],
                )
            else:
                cost = float(r["cost_cny"] or 0.0)
            created = r["created_at"] or ""
            prompt = int(r["prompt_tokens"] or 0)
            cached = int(r["cached_tokens"] or 0)

            total_tokens += tokens
            total_cost += cost
            total_prompt += prompt
            total_cached += cached

            if created >= today:
                today_tokens += tokens
                today_cost += cost
                today_prompt += prompt
                today_cached += cached

            if created >= month_start:
                month_tokens += tokens
                month_cost += cost
                month_prompt += prompt
                month_cached += cached

        # 筛选条件
        where_clause = ""
        params: list[Any] = []
        if time_range == "today":
            where_clause = "WHERE created_at >= ?"
            params = [today]
        elif time_range == "month":
            where_clause = "WHERE created_at >= ?"
            params = [month_start]

        # 业务动作场景聚合
        by_action_rows = conn.execute(f"""
            SELECT action_name, COUNT(*) as call_count,
                   COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                   COALESCE(SUM(total_tokens), 0) as total_tokens,
                   COALESCE(SUM(cached_tokens), 0) as cached_tokens,
                   COALESCE(SUM(cost_cny), 0) as cost_cny
            FROM token_log {where_clause}
            GROUP BY action_name
            ORDER BY total_tokens DESC
            LIMIT 20
        """, params).fetchall()

        by_action = [
            {
                "action_name": r["action_name"],
                "display_name": _get_display_name(r["action_name"]),
                "call_count": r["call_count"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "total_tokens": r["total_tokens"],
                "cached_tokens": r["cached_tokens"],
                "cache_hit_rate": _hit_rate(r["cached_tokens"], r["prompt_tokens"]),
                "cost_cny": round(action_cost_sum.get(r["action_name"] or "", 0.0), 4) if backfill_missing_cost else round(float(r["cost_cny"]), 4),
            }
            for r in by_action_rows
        ]

        # 模型消耗分布
        by_model_rows = conn.execute(f"""
            SELECT model_name, COUNT(*) as call_count,
                   COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                   COALESCE(SUM(total_tokens), 0) as total_tokens,
                   COALESCE(SUM(cached_tokens), 0) as cached_tokens,
                   COALESCE(SUM(cost_cny), 0) as cost_cny
            FROM token_log {where_clause}
            GROUP BY model_name
            ORDER BY total_tokens DESC
            LIMIT 10
        """, params).fetchall()

        by_model = [
            {
                "model_name": r["model_name"],
                "call_count": r["call_count"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "total_tokens": r["total_tokens"],
                "cached_tokens": r["cached_tokens"],
                "cache_hit_rate": _hit_rate(r["cached_tokens"], r["prompt_tokens"]),
                "cost_cny": round(model_cost_sum.get(r["model_name"] or "", 0.0), 4) if backfill_missing_cost else round(float(r["cost_cny"]), 4),
            }
            for r in by_model_rows
        ]

        # 近 14 天每日调用与消耗趋势
        fourteen_days_ago = (now_dt - timedelta(days=13)).strftime("%Y-%m-%d")
        trend_rows = conn.execute("""
            SELECT SUBSTR(created_at, 1, 10) as date,
                   COALESCE(SUM(total_tokens), 0) as total_tokens,
                   COALESCE(SUM(cost_cny), 0) as cost_cny,
                   COUNT(*) as call_count
            FROM token_log
            WHERE created_at >= ?
            GROUP BY SUBSTR(created_at, 1, 10)
            ORDER BY date ASC
        """, (fourteen_days_ago,)).fetchall()

        daily_trend = [
            {
                "date": r["date"],
                "total_tokens": r["total_tokens"],
                "cost_cny": round(day_cost_sum.get(r["date"], 0.0), 4) if backfill_missing_cost else round(float(r["cost_cny"]), 4),
                "call_count": r["call_count"],
            }
            for r in trend_rows
        ]

        # 审计调用明细（分页）
        logs_total_row = conn.execute("SELECT COUNT(*) as cnt FROM token_log").fetchone()
        logs_total = logs_total_row["cnt"] if logs_total_row else 0
        offset = max(0, (page - 1) * page_size)

        log_rows = conn.execute("""
            SELECT id, action_name, caller, job_id, model_name, prompt_tokens, completion_tokens,
                   total_tokens, cached_tokens, cost_cny, estimated, created_at
            FROM token_log
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (page_size, offset)).fetchall()

        logs = [
            {
                "id": r["id"],
                "action_name": r["action_name"],
                "display_name": _get_display_name(r["action_name"]),
                "caller": r["caller"] or "",
                "job_id": r["job_id"] if "job_id" in r.keys() else None,
                "model_name": r["model_name"] or "",
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "total_tokens": int(r["total_tokens"] or 0),
                "cached_tokens": int(r["cached_tokens"] or 0),
                "cost_cny": round(_calc_cost_for_row(r["model_name"], r["prompt_tokens"], r["completion_tokens"], r["cost_cny"], r["cached_tokens"]), 6) if backfill_missing_cost else round(float(r["cost_cny"] or 0.0), 6),
                "estimated": int(r["estimated"] or 0),
                "created_at": r["created_at"] or "",
            }
            for r in log_rows
        ]

        # 系统当前多角色模型与计价状态检查
        active_model = settings.OPENAI_MODEL or "mimo-v2.5-pro"
        is_mimo = is_mimo_model(active_model)
        has_custom = get_custom_pricing(active_model) is not None

        system_models = []
        if active_model:
            system_models.append({"role": "主评估推理", "key": "main_model", "model_name": active_model})
        if CLEANER_LLM_MODEL:
            system_models.append({"role": "数据清洗专用", "key": "cleaner_model", "model_name": CLEANER_LLM_MODEL})
        if VISION_MODEL:
            system_models.append({"role": "主视觉模型", "key": "vision_model", "model_name": VISION_MODEL})
        if CLEANER_VISION_MODEL:
            system_models.append({"role": "清洗视觉模型", "key": "cleaner_vision_model", "model_name": CLEANER_VISION_MODEL})

        # 检查是否有未配置的第三方模型（保持顺序并去重）
        unconfigured_models = list(dict.fromkeys([
            m["model_name"] for m in system_models
            if m["model_name"] and not is_mimo_model(m["model_name"]) and get_custom_pricing(m["model_name"]) is None
        ]))
        need_pricing_tip = len(unconfigured_models) > 0

        return {
            "active_model": active_model,
            "is_mimo": is_mimo,
            "has_custom_pricing": has_custom,
            "need_pricing_tip": need_pricing_tip,
            "unconfigured_models": unconfigured_models,
            "today_tokens": today_tokens,
            "month_tokens": month_tokens,
            "total_tokens": total_tokens,
            "today_cost_cny": round(today_cost, 4),
            "month_cost_cny": round(month_cost, 4),
            "total_cost_cny": round(total_cost, 4),
            "today_cached_tokens": today_cached,
            "month_cached_tokens": month_cached,
            "total_cached_tokens": total_cached,
            "today_cache_hit_rate": _hit_rate(today_cached, today_prompt),
            "month_cache_hit_rate": _hit_rate(month_cached, month_prompt),
            "total_cache_hit_rate": _hit_rate(total_cached, total_prompt),
            "by_action": by_action,
            "by_model": by_model,
            "daily_trend": daily_trend,
            "logs": logs,
            "logs_total": logs_total,
            "page": page,
            "page_size": page_size,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass
