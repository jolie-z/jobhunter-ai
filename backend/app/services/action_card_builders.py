# backend/app/services/action_card_builders.py
"""
全链路指挥中心 · 卡片交互操作回执卡片构建器。
按照 Rule 2 模块化原则从 pipeline_card_builders 拆分，专职负责动作执行结果的飞书 Card 2.0 渲染。
"""

from typing import Any


def build_action_result_card(
    title: str,
    succ_cnt: int,
    target_queue: str,
    flow_desc: str,
    fail_cnt: int = 0,
    fail_details: str = "",
    target_status: str = "待投递",
    theme: str = "turquoise",
) -> dict[str, Any]:
    """构建高审美的大盘交互操作回执卡片。"""
    # 卡片主题色与状态配置
    if fail_cnt > 0 and succ_cnt > 0:
        header_theme = "orange"
    elif fail_cnt > 0 and succ_cnt == 0:
        header_theme = "carmine"
    else:
        header_theme = theme

    elements: list[dict[str, Any]] = [
        {
            "tag": "column_set",
            "flex_mode": "bisect",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "background_style": "grey",
                    "elements": [{
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"<font color='grey'>处理数量</font>\n<font color='green'>**{succ_cnt} 条**</font>\n<font color='grey'>{'全量成功' if fail_cnt == 0 else f'失败 {fail_cnt} 条'}</font>"
                        }
                    }]
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "background_style": "grey",
                    "elements": [{
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"<font color='grey'>目标队列</font>\n<font color='blue'>**{target_queue}**</font>\n<font color='grey'>状态: {target_status}</font>"
                        }
                    }]
                }
            ]
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"🚀 **下一步流转**：\n{flow_desc}"
            }
        }
    ]

    if fail_cnt > 0 and fail_details:
        elements.extend([
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"⚠️ **失败详情 (前5条)**：\n{fail_details}"
                }
            }
        ])

    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "JobHunter 全链路指挥中心 · 状态已双端即时同步"}]
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": header_theme
        },
        "elements": elements
    }
