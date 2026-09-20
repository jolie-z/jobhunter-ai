# app/services/report_cards.py
"""
飞书求职战报卡片渲染引擎（方案 A 原生多列与组件规范）。
将 report_service 的结构化数据渲染为飞书 interactive card (卡片 2.0 协议)。
包含多列指标容器 (column_set)、原生数据表格 (table)、漏斗转化及动态 Token 成本展示。
"""
from datetime import datetime
from typing import Any

# 飞书卡片主题色
BLUE = "blue"
GREEN = "green"
ORANGE = "orange"
RED = "red"
GREY = "grey"
PURPLE = "purple"


def _format_tokens(tokens: int) -> str:
    return f"{tokens / 1000000:.1f}M" if tokens >= 1000000 else f"{tokens / 1000:.1f}K" if tokens >= 1000 else str(tokens)


def _format_model_brand(model_name: str) -> tuple[str, str]:
    m = (model_name or "mimo-v2.5-pro").lower().strip()
    desc = "小米 MiMo · 意向清洗研判" if "mimo" in m else "DeepSeek · 意向清洗研判" if "deepseek" in m else "通义千问 · 意向清洗研判" if "qwen" in m else "OpenAI · 意向清洗研判" if "gpt" in m else "智能初筛 / 意向分析"
    return model_name or "LLM Engine", desc


def _div_md(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _note_txt(content: str) -> dict[str, Any]:
    return {"tag": "note", "elements": [{"tag": "plain_text", "content": content}]}


def _metric_col(title: str, value: str | int, subtext: str, color: str = "blue", weight: int = 1) -> dict[str, Any]:
    """生成具有浅灰底色的独立圆角指标卡片列。"""
    return {
        "tag": "column",
        "width": "weighted",
        "weight": weight,
        "background_style": "grey",
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"<font color='grey'>{title}</font>\n<font color='{color}'>**{value}**</font>\n<font color='grey'>{subtext}</font>",
                },
            }
        ],
    }


def _channel_table(platforms: list[dict[str, Any]], period_key: str = "today", period_label: str = "今日新增") -> dict[str, Any]:
    """生成飞书原生数据表格展示各渠道产出与在库总量。"""
    tot_in_db = sum(p.get("total", 0) for p in platforms) or 1
    rows = []
    for item in platforms:
        cnt = item.get(period_key, 0)
        tot = item.get("total", 0)
        pct = f"{round(tot / tot_in_db * 100, 1)}%"
        rows.append({
            "channel": item["name"],
            "period": f"+{cnt}条" if cnt > 0 else "0条",
            "total": f"{tot}条",
            "share": pct,
        })
    return {
        "tag": "table",
        "page_size": 10,
        "row_height": "low",
        "header_style": {"text_align": "left", "background_style": "grey", "bold": True},
        "columns": [
            {"name": "channel", "display_name": "渠道平台", "width": "auto"},
            {"name": "period", "display_name": period_label, "width": "auto"},
            {"name": "total", "display_name": "在库总量", "width": "auto"},
            {"name": "share", "display_name": "总占比", "width": "auto"},
        ],
        "rows": rows,
    }


def _funnel_section(total_delivered: int, total_interview: int, total_offer: int,
                    interview_rate: float | None = None, offer_rate: float | None = None) -> list[dict[str, Any]]:
    """全局求职漏斗模块。"""
    sub_interview = f"转化率 {interview_rate}%" if interview_rate is not None else "累计初试/复试"
    sub_offer = f"转化率 {offer_rate}%" if offer_rate is not None else "求职终极目标达成"
    return [
        {"tag": "hr"},
        _div_md("**📈 全局求职漏斗 (All-Time)**\n<font color='grey'>全周期投递转化与面试进阶</font>"),
        {
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                _metric_col("累计已投递", f"{total_delivered} 个", "自动化 + 手工投递", color="blue"),
                _metric_col("推进面试轮次", f"{total_interview} 场", sub_interview, color="green"),
                _metric_col("最终斩获 Offer", f"{total_offer} 份", sub_offer, color="orange"),
            ],
        },
    ]


def _token_section(period_cost: float, period_tokens: int, period_calls: int,
                   sub_title: str, sub_cost_str: str, sub_detail: str,
                   model_name: str = "mimo-v2.5-pro",
                   period_label: str = "今日算力消耗") -> list[dict[str, Any]]:
    """AI 模型与算力消耗模块（真实模型动态绑定）。"""
    disp_model, engine_desc = _format_model_brand(model_name)
    return [
        {"tag": "hr"},
        _div_md("**🤖 AI 模型与算力消耗 (Token Consumption)**"),
        {
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                _metric_col(period_label, f"¥{period_cost:.2f}", f"{_format_tokens(period_tokens)} · {period_calls}次", color="purple"),
                _metric_col(sub_title, sub_cost_str, sub_detail, color="blue"),
                _metric_col("主力调用引擎", disp_model, engine_desc, color="green"),
            ],
        },
    ]


def build_daily_card(report: dict[str, Any]) -> dict[str, Any]:
    """构建日报飞书卡片（方案A 原生多列与组件规范）。"""
    d = report["date"]
    crawl = report["crawl"]
    tokens = report.get("tokens", {})
    month_tokens = report.get("month_tokens", {})
    suggestions = report.get("suggestions", [])
    feishu = report.get("feishu", {})

    total_crawled = crawl.get("total", 0)
    rejected_count = crawl.get("rejected", 0)
    passed_count = max(0, total_crawled - rejected_count)
    pass_rate = crawl.get("pass_rate", 100)

    today_delivered = feishu.get("today_delivered", 0)
    total_delivered = feishu.get("total_delivered", 0)
    total_interview = feishu.get("total_interview", 0)
    total_offer = feishu.get("total_offer", 0)
    total_pending = feishu.get("total_pending", 0)

    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday_str = weekdays[dt.weekday()]
    except Exception:
        weekday_str = "今日"

    platforms_list = crawl.get("platforms", [])
    sug_lines = [f"• {s}" for s in suggestions] if suggestions else ["• 各项指标流转正常，继续保持求职节奏！"]
    sug_text = "\n".join(sug_lines)

    elements: list[dict[str, Any]] = [
        _div_md("**⚡ 今日流水动态 (Today)**\n<font color='grey'>24小时抓取与投递周转效率</font>"),
        {
            "tag": "column_set",
            "flex_mode": "bisect",
            "columns": [
                _metric_col("今日新抓取", f"{total_crawled} 条", "全网渠道聚合", color="blue"),
                _metric_col("AI 清洗放行", f"{passed_count} 条", f"放行率 {pass_rate}%", color="turquoise"),
                _metric_col("今日实际投递", f"{today_delivered} 个", "自动打招呼送达", color="green"),
                _metric_col("待投递池存量", f"{total_pending} 个", "优质待处理储备", color="orange"),
            ],
        },
    ]

    elements.extend(_funnel_section(total_delivered, total_interview, total_offer))

    if platforms_list:
        elements.extend([
            {"tag": "hr"},
            _div_md("**📡 各渠道今日产出与在库总量**"),
            _channel_table(platforms_list, period_key="today", period_label="今日新增"),
        ])

    m_cost = month_tokens.get("cost_cny", 0)
    m_tokens = month_tokens.get("tokens", 0)
    m_calls = month_tokens.get("calls", 0)
    primary_m = tokens.get("primary_model") or month_tokens.get("primary_model") or "mimo-v2.5-pro"

    elements.extend(
        _token_section(
            period_cost=tokens.get("cost_cny", 0),
            period_tokens=tokens.get("tokens", 0),
            period_calls=tokens.get("calls", 0),
            sub_title="当月累计算力",
            sub_cost_str=f"¥{m_cost:.2f}",
            sub_detail=f"{_format_tokens(m_tokens)} · {m_calls}次",
            model_name=primary_m,
            period_label="今日算力消耗",
        )
    )

    elements.extend([
        {"tag": "hr"},
        _div_md(f"**🔮 智能求职建议 & 复盘 (AI Insights)**\n{sug_text}"),
        {"tag": "hr"},
        _note_txt(f"JobHunter AI Copilot · 原生卡片规范 · {datetime.now().strftime('%H:%M')}"),
    ])

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 求职战报中心 · {d}（{weekday_str}）"},
            "template": BLUE,
        },
        "elements": elements,
    }


def build_weekly_card(report: dict[str, Any]) -> dict[str, Any]:
    """构建周报飞书卡片（方案A 原生多列与组件规范）。"""
    ws = report["week_start"]
    we = report["week_end"]
    crawl = report["crawl"]
    tokens = report.get("tokens", {})
    daily_bd = report.get("daily_breakdown", [])
    feishu = report.get("feishu", {})
    suggestions = report.get("suggestions", [])

    crawl_change = report.get("crawl_change_percent", 0)
    change_emoji = "📈" if crawl_change >= 0 else "📉"
    change_text = f"{change_emoji} 环比上周 {'+' if crawl_change >= 0 else ''}{crawl_change}%"

    tok_change = report.get("token_change_percent", 0)
    tok_change_text = f"环比 {'+' if tok_change >= 0 else ''}{tok_change}%"

    week_delivered = feishu.get("week_delivered", 0)
    total_pending = feishu.get("total_pending", 0)
    total_delivered = feishu.get("total_delivered", 0)
    total_interview = feishu.get("total_interview", 0)
    total_offer = feishu.get("total_offer", 0)
    passed_count = max(0, crawl["total"] - crawl.get("rejected", 0))
    pass_rate = crawl.get("pass_rate", 0)

    daily_lines = []
    for item in daily_bd:
        d_label = item["date"][5:]
        bar = "▓" * min(item["crawled"] // 2 if item["crawled"] <= 10 else 5 + item["crawled"] // 10, 12) if item["crawled"] > 0 else "·"
        daily_lines.append(f"  {d_label} | {bar} {item['crawled']}条")
    daily_text = "\n".join(daily_lines) if daily_lines else "  暂无每日数据"

    platforms = crawl.get("platforms", [])
    sug_lines = [f"• {s}" for s in suggestions] if suggestions else ["• 各项数据健康，下周按计划推进投递！"]
    sug_text = "\n".join(sug_lines)

    elements: list[dict[str, Any]] = [
        _div_md(f"**🎯 本周流转战报**\n<font color='grey'>周度聚合效能 ({change_text})</font>"),
        {
            "tag": "column_set",
            "flex_mode": "bisect",
            "columns": [
                _metric_col("本周新抓取", f"{crawl['total']} 条", change_text, color="blue"),
                _metric_col("AI 清洗放行", f"{passed_count} 条", f"通过率 {pass_rate}%", color="turquoise"),
                _metric_col("本周实际投递", f"{week_delivered} 个", "自动打招呼送达", color="green"),
                _metric_col("待投递池存量", f"{total_pending} 个", "待投储备岗位", color="orange"),
            ],
        },
    ]

    elements.extend(_funnel_section(total_delivered, total_interview, total_offer))

    if daily_lines:
        elements.extend([
            {"tag": "hr"},
            _div_md(f"**📅 周内 7 天推进节奏**:\n{daily_text}"),
        ])

    if platforms:
        elements.extend([
            {"tag": "hr"},
            _div_md("**📡 各渠道本周产出贡献与在库总量**"),
            _channel_table(platforms, period_key="period_count", period_label="本周新增"),
        ])

    primary_m = tokens.get("primary_model") or "mimo-v2.5-pro"
    elements.extend(
        _token_section(
            period_cost=tokens.get("cost_cny", 0),
            period_tokens=tokens.get("tokens", 0),
            period_calls=tokens.get("calls", 0),
            sub_title="周均算力波动",
            sub_cost_str=tok_change_text,
            sub_detail="模型调用能耗监测",
            model_name=primary_m,
            period_label="本周算力消耗",
        )
    )

    elements.extend([
        {"tag": "hr"},
        _div_md(f"**🔮 下周策略与建议**\n{sug_text}"),
        {"tag": "hr"},
        _note_txt(f"JobHunter AI Copilot · 原生卡片规范 · {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
    ])

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 求职周报 · {ws} ~ {we}"},
            "template": GREEN,
        },
        "elements": elements,
    }


def build_monthly_card(report: dict[str, Any]) -> dict[str, Any]:
    """构建月报飞书卡片（方案A 原生多列与组件规范）。"""
    month = report["month"]
    crawl = report["crawl"]
    tokens = report.get("tokens", {})
    feishu = report.get("feishu", {})
    suggestions = report.get("suggestions", [])
    funnel_rates = report.get("funnel_rates", {})
    platform_roi = report.get("platform_roi", [])
    days_elapsed = report.get("days_elapsed", 30)

    total_delivered = feishu.get("total_delivered", 0)
    total_interview = feishu.get("total_interview", 0)
    total_offer = feishu.get("total_offer", 0)
    month_delivered = feishu.get("month_delivered", 0)
    total_pending = feishu.get("total_pending", 0)
    passed_count = max(0, crawl["total"] - crawl.get("rejected", 0))
    pass_rate = crawl.get("pass_rate", 0)

    sug_lines = [f"• {s}" for s in suggestions] if suggestions else ["• 漏斗数据平稳，建议下月继续扩大投递量！"]
    sug_text = "\n".join(sug_lines)

    platforms = crawl.get("platforms", [])
    roi_rows = []
    if platform_roi:
        for item in platform_roi:
            roi_rows.append({
                "channel": item["platform"],
                "crawled": f"{item['crawled']}条",
                "rate": f"{item['pass_rate']}%",
                "stock": f"{item.get('total_in_stock', 0)}条",
            })

    table_element = {
        "tag": "table",
        "page_size": 10,
        "row_height": "low",
        "header_style": {"text_align": "left", "background_style": "grey", "bold": True},
        "columns": [
            {"name": "channel", "display_name": "渠道平台", "width": "auto"},
            {"name": "crawled", "display_name": "本月抓取", "width": "auto"},
            {"name": "rate", "display_name": "初筛合格率", "width": "auto"},
            {"name": "stock", "display_name": "在库总量", "width": "auto"},
        ],
        "rows": roi_rows,
    } if roi_rows else _channel_table(platforms, period_key="period_count", period_label="本月新增")

    elements: list[dict[str, Any]] = [
        _div_md("**⚡ 本月战果与流转效能**\n<font color='grey'>月度全周期机会转化</font>"),
        {
            "tag": "column_set",
            "flex_mode": "bisect",
            "columns": [
                _metric_col("本月新抓取", f"{crawl['total']} 条", "全网机会汇聚", color="blue"),
                _metric_col("AI 清洗放行", f"{passed_count} 条", f"合格率 {pass_rate}%", color="turquoise"),
                _metric_col("本月实际投递", f"{month_delivered} 个", "自动打招呼送达", color="green"),
                _metric_col("待投递池存量", f"{total_pending} 个", "待投储备岗位", color="orange"),
            ],
        },
    ]

    elements.extend(
        _funnel_section(
            total_delivered,
            total_interview,
            total_offer,
            interview_rate=funnel_rates.get("interview_rate"),
            offer_rate=funnel_rates.get("offer_rate"),
        )
    )

    elements.extend([
        {"tag": "hr"},
        _div_md("**📡 各渠道月度质量与在库矩阵**"),
        table_element,
    ])

    m_cost = tokens.get("cost_cny", 0)
    daily_cost = m_cost / max(days_elapsed, 1)
    primary_m = tokens.get("primary_model") or "mimo-v2.5-pro"

    elements.extend(
        _token_section(
            period_cost=m_cost,
            period_tokens=tokens.get("tokens", 0),
            period_calls=tokens.get("calls", 0),
            sub_title="日均算力成本",
            sub_cost_str=f"¥{daily_cost:.2f}/天",
            sub_detail=f"统计跨度 {days_elapsed} 天",
            model_name=primary_m,
            period_label="本月算力消耗",
        )
    )

    elements.extend([
        {"tag": "hr"},
        _div_md(f"**🔮 月度战略复盘与次月战术**\n{sug_text}"),
        {"tag": "hr"},
        _note_txt(f"JobHunter AI Copilot · 原生卡片规范 · {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
    ])

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🌐 求职月报 · {month}"},
            "template": PURPLE,
        },
        "elements": elements,
    }


def build_final_card(report: dict[str, Any]) -> dict[str, Any]:
    """构建终报飞书卡片（方案A 原生多列与组件规范）。"""
    start = report.get("start_date", "?")
    end = report.get("end_date", "?")
    total_days = report.get("total_days", 1)
    crawl = report.get("crawl", {})
    tokens = report.get("tokens", {})
    platform_contrib = report.get("platform_contribution", [])

    contrib_rows = []
    for item in platform_contrib:
        contrib_rows.append({
            "channel": item["platform"],
            "crawled": f"{item['crawled']}条",
            "share": f"{item['percent']}%",
        })

    table_element = {
        "tag": "table",
        "page_size": 10,
        "row_height": "low",
        "header_style": {"text_align": "left", "background_style": "grey", "bold": True},
        "columns": [
            {"name": "channel", "display_name": "渠道平台", "width": "auto"},
            {"name": "crawled", "display_name": "累计抓取", "width": "auto"},
            {"name": "share", "display_name": "总贡献占比", "width": "auto"},
        ],
        "rows": contrib_rows,
    }

    elements: list[dict[str, Any]] = [
        _div_md(f"**🎯 全程历时与核心效能**\n<font color='grey'>{start} ~ {end} (共 {total_days} 天)</font>"),
        {
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                _metric_col("总抓取岗位", f"{crawl.get('total', 0)} 条", f"清洗通过率 {crawl.get('pass_rate', 0)}%", color="blue"),
                _metric_col("总 Token 算力", f"¥{tokens.get('cost_cny', 0):.2f}", f"{_format_tokens(tokens.get('tokens', 0))} 消耗", color="purple"),
                _metric_col("历经天数", f"{total_days} 天", "求职旅程圆满完成", color="orange"),
            ],
        },
    ]

    if contrib_rows:
        elements.extend([
            {"tag": "hr"},
            _div_md("**🏆 各招聘渠道贡献榜**"),
            table_element,
        ])

    elements.extend([
        {"tag": "hr"},
        _div_md("🎊 **恭喜斩获心仪 Offer！求职旅程圆满收官！**"),
        {"tag": "hr"},
        _note_txt(f"JobHunter AI Copilot · 终报归档于 {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
    ])

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🎉 求职终报 · {start} ~ {end}"},
            "template": ORANGE,
        },
        "elements": elements,
    }
