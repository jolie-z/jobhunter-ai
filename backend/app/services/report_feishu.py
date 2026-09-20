# app/services/report_feishu.py
"""
飞书战报卡片调度与消息发送门面。
卡片排版逻辑已按照 Rule 2 模块化规范迁移至 report_cards.py，本模块通过 __all__ 进行统一重导出。
"""
import os
from typing import Any

from app.services.report_cards import (
    BLUE,
    GREEN,
    GREY,
    ORANGE,
    PURPLE,
    RED,
    build_daily_card,
    build_final_card,
    build_monthly_card,
    build_weekly_card,
)

__all__ = [
    "BLUE",
    "GREEN",
    "GREY",
    "ORANGE",
    "PURPLE",
    "RED",
    "build_daily_card",
    "build_weekly_card",
    "build_monthly_card",
    "build_final_card",
    "_get_receive_id",
    "send_daily_report",
    "send_weekly_report",
    "send_monthly_report",
    "send_final_report",
    "send_test_report",
]


def _get_receive_id() -> str:
    """获取飞书消息接收 ID（群聊 chat_id 或个人 open_id）。"""
    # 优先从 job_goals 表读取用户设定
    try:
        from app.services.goal_service import get_current_goals
        goals = get_current_goals()
        if goals and goals.get("feishu_receive_id"):
            return goals["feishu_receive_id"]
    except Exception:
        pass

    # 降级：预警接收人（页面「飞书」分组 / .env 均可配，_cfg 动态读取感知页面保存）
    try:
        from common.config import _cfg
        alert_id = _cfg("FEISHU_ALERT_RECEIVE_ID", json_key="FEISHU_ALERT_RECEIVE_ID")
        if alert_id:
            return alert_id
    except Exception:
        pass

    return os.environ.get("FEISHU_REPORT_RECEIVE_ID", "")


async def _send_card(card: dict[str, Any], receive_id: str | None = None) -> bool:
    """发送飞书卡片消息。"""
    target = receive_id or _get_receive_id()
    if not target:
        print("[report_feishu] 未配置飞书接收ID，跳过发送")
        return False

    try:
        from app.core.feishu_messaging import send_feishu_card
        await send_feishu_card(
            receive_id=target,
            card_content=card,
            receive_id_type="chat_id",
        )
        print(f"[report_feishu] 卡片已发送至 {target}")
        return True
    except Exception as e:
        print(f"[report_feishu] 发送失败: {e}")
        return False


async def send_daily_report(target_date: str | None = None) -> bool:
    """生成并发送日报。"""
    from app.services.report_service import generate_daily_report
    return await _send_card(build_daily_card(generate_daily_report(target_date)))


async def send_weekly_report(week_start: str | None = None) -> bool:
    """生成并发送周报。"""
    from app.services.report_service import generate_weekly_report
    return await _send_card(build_weekly_card(generate_weekly_report(week_start)))


async def send_monthly_report(month: str | None = None) -> bool:
    """生成并发送月报。"""
    from app.services.report_service import generate_monthly_report
    return await _send_card(build_monthly_card(generate_monthly_report(month)))


async def send_final_report() -> bool:
    """生成并发送终报。"""
    from app.services.report_service import generate_final_report
    report = generate_final_report()
    if report.get("error"):
        print(f"[report_feishu] 终报生成失败: {report['error']}")
        return False
    return await _send_card(build_final_card(report))


async def send_test_report() -> bool:
    """发送测试日报（用于验证飞书连通性）。"""
    from app.services.report_service import generate_daily_report
    card = build_daily_card(generate_daily_report())
    card["header"]["title"]["content"] = "[测试] " + card["header"]["title"]["content"]
    return await _send_card(card)
