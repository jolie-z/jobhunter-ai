# backend/app/services/delivery_card_notifier.py
"""
全链路指挥中心 · 自动投递波次结果战报卡片通知器。
负责在每轮定时/手动投递波次（上午波次、下午波次、批次补投等）执行完毕后，
汇总各平台投递成功、受阻与跳过数据，拼装高颜值 Card 2.0 卡片同步到飞书聊天框。
"""

import logging
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.feishu_messaging import is_valid_receive_id, send_feishu_card
from app.services.pipeline_card_builders import get_base_url
from app.services.report_feishu import _get_receive_id

logger = logging.getLogger("delivery_card_notifier")


def build_delivery_batch_card(
    window_label: str,
    total_targets: int,
    ok_jobs: list[dict[str, Any]],
    failed_jobs: list[tuple[dict[str, Any], str]],
    skipped_cnt: int = 0,
    executed_at: datetime | None = None,
) -> dict[str, Any]:
    """构建自动投递波次执行战报卡片。"""
    now = executed_at or datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    ok_cnt = len(ok_jobs)
    fail_cnt = len(failed_jobs)

    succ_rate = round((ok_cnt / total_targets) * 100) if total_targets > 0 else (100 if ok_cnt > 0 else 0)

    # 确定卡片头部色调
    if total_targets == 0:
        header_theme = "blue"
    elif fail_cnt == 0 and ok_cnt > 0:
        header_theme = "turquoise"
    elif ok_cnt > 0 and fail_cnt > 0:
        header_theme = "orange"
    elif fail_cnt > 0 and ok_cnt == 0:
        header_theme = "carmine"
    else:
        header_theme = "blue"

    frontend_url = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000") or "http://localhost:3000"
    base_url = get_base_url()

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"⏱ **{now_str}** · **{window_label}**自动投递波次已执行完毕"
            }
        },
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": "**📊 本轮投递执行效能**"}},
        {
            "tag": "column_set",
            "flex_mode": "bisect",
            "columns": [
                {
                    "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                    "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>就绪待投</font>\n<font color='blue'>**{total_targets} 条**</font>\n<font color='grey'>审批池提取</font>"}}]
                },
                {
                    "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                    "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>成功投递</font>\n<font color='green'>**{ok_cnt} 条**</font>\n<font color='grey'>{'全量成功' if fail_cnt == 0 and ok_cnt > 0 else f'成功率 {succ_rate}%'}</font>"}}]
                },
                {
                    "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                    "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>投递受阻</font>\n<font color='{'grey' if fail_cnt == 0 else 'red'}'>**{fail_cnt} 条**</font>\n<font color='grey'>{'零受阻' if fail_cnt == 0 else '已挂起排查'}</font>"}}]
                },
                {
                    "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                    "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>跳过/风控</font>\n<font color='{'grey' if skipped_cnt == 0 else 'orange'}'>**{skipped_cnt} 条**</font>\n<font color='grey'>{'正常流转' if skipped_cnt == 0 else '留待后续波次'}</font>"}}]
                }
            ]
        }
    ]

    # 成功岗位清单
    if ok_jobs:
        elements.append({"tag": "hr"})
        lines = []
        for i, j in enumerate(ok_jobs[:15], 1):
            plat = str(j.get("platform") or "平台").upper()
            comp = str(j.get("company_name") or "")[:16]
            name = str(j.get("job_name") or "")[:20]
            lines.append(f"{i}. [{plat}] {comp} - {name}")
        more_txt = f"\n<font color='grey'>... 其余 {len(ok_jobs) - 15} 条成功岗位已在电脑端已投递Tab归档</font>" if len(ok_jobs) > 15 else ""
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**🎉 成功送达清单 (共 {ok_cnt} 条)**：\n" + "\n".join(lines) + more_txt
            }
        })

    # 受阻条目清单
    if failed_jobs:
        elements.append({"tag": "hr"})
        fail_lines = []
        for j, err in failed_jobs[:5]:
            plat = str(j.get("platform") or "平台").upper()
            comp = str(j.get("company_name") or "")[:12]
            name = str(j.get("job_name") or "")[:16]
            err_short = str(err)[:45].replace("\n", " ")
            fail_lines.append(f"· [{plat}] {comp} · {name}\n  <font color='red'>受阻原因: {err_short}</font>")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**⚠️ 投递受阻清单 (共 {fail_cnt} 条待处理)**：\n" + "\n".join(fail_lines)
            }
        })

    if total_targets == 0:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "🎉 **本轮「待投递」队列暂无积压岗位**\n所有审批放行岗位均已完成投递，系统处于就绪状态，等待下一轮放行或定时任务触发。"
            }
        })

    # 跳转按钮组
    buttons = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "💻 打开电脑端指挥中心"},
            "type": "primary",
            "url": frontend_url
        }
    ]
    if base_url:
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📑 查看飞书多维表格"},
            "type": "default",
            "url": base_url
        })

    elements.extend([
        {"tag": "hr"},
        {"tag": "action", "actions": buttons},
        {
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": "JobHunter 全链路指挥中心 · 投递状态与附件日志已双端实时同步"}]
        }
    ])

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🚀 全链路指挥中心 · 自动投递战报 · {window_label}"},
            "template": header_theme
        },
        "elements": elements
    }


async def send_delivery_round_report(
    window_label: str,
    total_targets: int,
    ok_jobs: list[dict[str, Any]],
    failed_jobs: list[tuple[dict[str, Any], str]],
    skipped_cnt: int = 0,
    receive_id: str | None = None,
) -> bool:
    """构建自动投递战报卡片并推送到飞书聊天会话。"""
    try:
        target = receive_id or _get_receive_id()
        if not is_valid_receive_id(target):
            logger.warning(f"[DeliveryNotifier] 飞书接收 ID 未配置或格式无效 ({target!r})，跳过投递战报卡片发送")
            return False

        card = build_delivery_batch_card(
            window_label=window_label,
            total_targets=total_targets,
            ok_jobs=ok_jobs,
            failed_jobs=failed_jobs,
            skipped_cnt=skipped_cnt,
        )

        ok = await send_feishu_card(
            receive_id=target,
            card_content=card,
            receive_id_type="chat_id" if target.startswith("oc_") else "open_id",
        )
        if ok:
            logger.info(f"📮 [DeliveryNotifier] 自动投递战报卡片（{window_label}）已成功推送至飞书群: {target}")
        else:
            logger.warning("[DeliveryNotifier] 自动投递战报卡片推送失败，飞书 API 返回未成功")
        return ok
    except Exception as e:
        logger.warning(f"[DeliveryNotifier] 自动投递战报卡片发送异常: {e}")
        return False
