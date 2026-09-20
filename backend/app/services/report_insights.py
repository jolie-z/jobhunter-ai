# app/services/report_insights.py
"""
战报智能策略引擎 - 负责生成日报明日建议与周报下周策略复盘。
从 report_service 拆分出独立模块，解耦业务规则与数据聚合逻辑。
"""
from datetime import datetime, timedelta
from typing import Any


def generate_daily_suggestions(conn, goals: dict | None, crawl_today: int) -> list[str]:
    """基于规则生成日报明日建议与行动指引。"""
    suggestions = []

    if goals:
        target = goals.get("daily_crawl_target", 50)
        if crawl_today < target:
            gap = target - crawl_today
            suggestions.append(f"今日抓取 {crawl_today} 条，距目标还差 {gap} 条，建议检查爬虫会话是否正常")

        # 待清洗积压
        try:
            pending = conn.execute(
                "SELECT COUNT(*) as cnt FROM raw_jobs WHERE process_status IN ('已存入数据', '待AI初筛')"
            ).fetchone()["cnt"]
            if pending > 50:
                suggestions.append(f"待清洗岗位积压 {pending} 条，建议执行一次数据清洗")
        except Exception:
            pass

    # 平台异常检测（近3天无新增）
    try:
        three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        platforms = conn.execute("SELECT DISTINCT platform FROM raw_jobs").fetchall()
        for p in platforms:
            name = p["platform"]
            if not name or name in ("未知", "unknown", "None", "-"):
                continue
            recent = conn.execute("""
                SELECT COUNT(*) as cnt FROM raw_jobs
                WHERE platform = ? AND crawl_time >= ?
            """, (name, three_days_ago)).fetchone()["cnt"]
            if recent == 0:
                suggestions.append(f"{name} 近 3 天无新增抓取，建议检查爬虫会话")
    except Exception:
        pass

    if not suggestions:
        suggestions.append("今日各项指标健康，保持投递节奏！")

    return suggestions[:5]


def generate_weekly_suggestions(
    crawl_total: int,
    crawl_change: float,
    platforms: list[dict[str, Any]],
    feishu: dict[str, Any],
) -> list[str]:
    """基于周度数据聚合生成周报复盘与下周策略。"""
    suggestions = []

    # 1. 抓取与产能走势复盘
    if crawl_change <= -25.0:
        suggestions.append(
            f"本周新抓取 {crawl_total} 条，较上周环比下降 {abs(crawl_change)}%，建议检查各渠道爬虫有效性并拓宽职位关键词"
        )
    elif crawl_change >= 25.0:
        suggestions.append(
            f"本周抓取表现亮眼，环比激增 +{crawl_change}%，岗位储备丰富，建议加速初筛清洗"
        )
    else:
        suggestions.append(
            f"本周抓取节奏平稳（共 {crawl_total} 条，环比 {'+' if crawl_change >= 0 else ''}{crawl_change}%），产能维持正常水位"
        )

    # 2. 渠道贡献主力
    active_platforms = [p for p in platforms if (p.get("today", 0) > 0 or p.get("period_count", 0) > 0)]
    if active_platforms:
        active_sorted = sorted(
            active_platforms,
            key=lambda x: -(x.get("period_count", 0) or x.get("today", 0)),
        )
        top = active_sorted[0]
        cnt = top.get("period_count", 0) or top.get("today", 0)
        suggestions.append(
            f"渠道以【{top['name']}】为本周主力（新增 {cnt} 条），建议下周重点巡检该平台新发高潜岗位"
        )
    else:
        suggestions.append("本周各平台增量较为均匀，建议保持多渠道并进策略")

    # 3. 待投递池与下周投递节奏
    pending = feishu.get("total_pending", 0)
    week_deliv = feishu.get("week_delivered", 0)
    if pending > 100:
        suggestions.append(
            f"待投递池当前存量充沛（{pending} 个精选机会），建议下周二/周三黄金时间段分批集中投递"
        )
    elif pending < 20:
        suggestions.append(
            f"待投递池存量偏低（仅余 {pending} 个），建议下周初加大抓取与深评力度"
        )
    else:
        suggestions.append(
            f"本周累计投递 {week_deliv} 个岗位，待投递池现有 {pending} 个储备，建议按日均 10-15 个平稳推进"
        )

    # 4. 面试冲刺提醒
    interviews = feishu.get("total_interview", 0)
    offers = feishu.get("total_offer", 0)
    if interviews > 0:
        suggestions.append(
            f"已有 {interviews} 场面试推进中（已斩获 {offers} 个 Offer），建议做好面经复盘与精准追击"
        )

    return suggestions[:4]


def generate_monthly_suggestions(
    crawl_total: int,
    pass_rate: float,
    platform_roi: list[dict[str, Any]],
    feishu: dict[str, Any],
) -> list[str]:
    """基于月度全景数据生成宏观战略复盘与次月战术建议。"""
    suggestions = []

    # 1. 抓取规模与初筛质量诊断
    if crawl_total > 0 and pass_rate < 80.0:
        suggestions.append(
            f"本月 AI 初筛淘汰率偏高（合格率仅 {pass_rate}%），建议次月微调筛选严苛度或校准搜索关键词"
        )
    elif crawl_total < 50:
        suggestions.append(
            f"本月全网抓取总量偏少（共 {crawl_total} 条），次月建议拓宽求职城市或开启多渠道联动"
        )

    # 2. 宏观转化漏斗与瓶颈诊断
    delivered = feishu.get("total_delivered", 0)
    interview = feishu.get("total_interview", 0)
    offer = feishu.get("total_offer", 0)
    conv_rate = round(interview / max(delivered, 1) * 100, 1)

    if delivered > 30 and conv_rate < 3.0:
        suggestions.append(
            f"月度投递到面试转化率偏低（{conv_rate}%，投递 {delivered} ➔ 面试 {interview}），建议对 A 级岗位重点开启简历靶向定制改写"
        )
    elif interview > 0 and offer == 0:
        suggestions.append(
            f"已推进 {interview} 场面试但尚未斩获 Offer，次月战略重心应向“面经复盘与现场追击沟通”倾斜"
        )
    elif offer > 0:
        suggestions.append(
            f"本月已斩获 {offer} 个 Offer，漏斗各阶段流转健康，建议综合对比薪酬包与团队匹配度"
        )
    else:
        suggestions.append(
            f"求职漏斗处于起跑阶段（累计投递 {delivered} 个），建议保持投递节奏并持续验证简历关键词"
        )

    # 2. 渠道质量与重心建议
    if platform_roi:
        sorted_roi = sorted(platform_roi, key=lambda x: -x.get("crawled", 0))
        top_platform = sorted_roi[0]
        suggestions.append(
            f"【{top_platform['platform']}】为本月最大产出源（贡献 {top_platform['crawled']} 条，初筛合格率 {top_platform.get('pass_rate', 0)}%），次月建议维持重点监控"
        )

    # 3. 岗位池积压与次月节奏
    pending = feishu.get("total_pending", 0)
    if pending > 500:
        suggestions.append(
            f"待投递池当前积压 {pending} 个机会，次月首周应以“批量投递去库存”为主要战术，适当控制抓取配额"
        )
    elif pending < 50:
        suggestions.append(
            f"待投递池仅存 {pending} 个机会，次月建议拓宽求职城市与岗位搜索标签，快速补充优质线索"
        )
    else:
        suggestions.append(
            f"当前储备充足（{pending} 个精选机会），次月建议按每日 10-20 个稳定节奏推进投递"
        )

    return suggestions[:4]
