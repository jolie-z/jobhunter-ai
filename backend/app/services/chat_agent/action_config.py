"""ChatAgent 状态驱动推荐动作配置中心：根据岗位跟进状态（10大生命周期）下发专属快捷交互按钮。"""
from typing import Any

# 10 大生命周期阶段的动作配置
STATUS_ACTION_RECOMMENDATIONS: dict[str, list[dict[str, Any]]] = {
    # 1. 新线索
    "新线索": [
        {"label": "🚀 发起 AI 全面评估", "type": "primary", "action": "run_pipeline"},
        {"label": "📋 查看岗位完整详情", "type": "default", "action": "send_prompt", "prompt": "查看该岗位的完整要求与JD原文"},
        {"label": "🏢 查公司业务情报", "type": "default", "action": "send_prompt", "prompt": "查一下该公司的核心业务线与情报"},
    ],
    # 2. 已完成初步评估
    "已完成初步评估": [
        {"label": "🚀 进行深度评估与改写", "type": "primary", "action": "send_prompt", "prompt": "对该岗位进行深度评估并改写定制简历"},
        {"label": "📊 查看 8 维初评得分与理由", "type": "default", "action": "send_prompt", "prompt": "查看该岗位的 8 维初评得分与详细理由"},
        {"label": "🏢 查公司业务情报", "type": "default", "action": "send_prompt", "prompt": "查一下该公司的核心业务线与情报"},
    ],
    # 3. 已完成深度评估
    "已完成深度评估": [
        {"label": "📝 定制改写简历并出物料", "type": "primary", "action": "send_prompt", "prompt": "生成该岗位的定制简历物料并渲染PDF与长图"},
        {"label": "🔍 查看深度诊断报告", "type": "default", "action": "send_prompt", "prompt": "查看该岗位的深度评估诊断报告"},
    ],
    # 4. 简历人工复核 / 海投人工复核
    "简历人工复核": [
        {"label": "📄 发送简历 PDF/长图与打招呼语", "type": "primary", "action": "send_materials"},
        {"label": "✏️ 自然语言微调简历", "type": "default", "action": "send_prompt", "prompt": "我想微调该岗位的定制简历，请告诉我当前简历的关键点"},
        {"label": "✅ 审批通过，放入待投递", "type": "default", "action": "update_status", "target_status": "待投递"},
        {"label": "📮 我已手动投递完成", "type": "default", "action": "mark_delivered"},
    ],
    "海投人工复核": [
        {"label": "📄 发送简历 PDF/长图与打招呼语", "type": "primary", "action": "send_materials"},
        {"label": "✏️ 自然语言微调简历", "type": "default", "action": "send_prompt", "prompt": "我想微调该岗位的定制简历，请告诉我当前简历的关键点"},
        {"label": "✅ 审批通过，放入待投递", "type": "default", "action": "update_status", "target_status": "待投递"},
        {"label": "📮 我已手动投递完成", "type": "default", "action": "mark_delivered"},
    ],
    # 5. 待投递
    "待投递": [
        {"label": "🕒 查看定时发射计划", "type": "primary", "action": "send_prompt", "prompt": "查看待投递岗位的定时发射计划与时间"},
        {"label": "📄 预览投递物料", "type": "default", "action": "send_materials"},
    ],
    # 6. 已投递
    "已投递": [
        {"label": "🕒 查看投递时间与记录", "type": "default", "action": "send_prompt", "prompt": "查看该岗位的投递时间、投递记录与详情"},
        {"label": "🎯 收到面试邀请（转一面）", "type": "primary", "action": "update_status", "target_status": "一面"},
        {"label": "🔮 查看专属面试预测题", "type": "default", "action": "send_prompt", "prompt": "查看该岗位的专属面试预测题与参考回答"},
    ],
    # 7. 一面
    "一面": [
        {"label": "🔮 岗位高频面试题预测", "type": "primary", "action": "send_prompt", "prompt": "生成针对该岗位的一面高频面试题预测与解题思路"},
        {"label": "🏢 公司核心业务深度情报", "type": "default", "action": "send_prompt", "prompt": "深度分析该公司的业务模式、产品线与面试考点"},
        {"label": "💡 反问面试官高分建议", "type": "default", "action": "send_prompt", "prompt": "提供几个适合在反问面试官环节提出的高分问题"},
        {"label": "🎉 一面通过，晋级二面", "type": "default", "action": "update_status", "target_status": "二面"},
    ],
    # 8. 二面
    "二面": [
        {"label": "⚡ 准备高杠杆主打亮点", "type": "primary", "action": "send_prompt", "prompt": "提炼针对该岗位二面的核心高杠杆匹配亮点与量化战绩"},
        {"label": "🚨 防御致命硬伤与毒点", "type": "default", "action": "send_prompt", "prompt": "帮我梳理该岗位可能被挑战的短板毒点与防御应对策略"},
        {"label": "🧪 破局行动计划策略", "type": "default", "action": "send_prompt", "prompt": "查看该岗位的破局行动计划（入职前90天规划方案）"},
        {"label": "🎉 二面通过，晋级终面", "type": "default", "action": "update_status", "target_status": "三面"},
    ],
    # 9. 三面 / HR面
    "三面": [
        {"label": "💰 薪资谈判与期望策略", "type": "primary", "action": "send_prompt", "prompt": "结合该岗位薪资区间与行业标准，给我一套谈薪谈判策略与话术"},
        {"label": "🤝 HR 经典软性问题防御", "type": "default", "action": "send_prompt", "prompt": "梳理三面/HR面常见的离职原因、职业规划与稳定性应对回答"},
        {"label": "🎉 拿到 Offer 啦！", "type": "default", "action": "update_status", "target_status": "Offer"},
    ],
    # 10. Offer
    "Offer": [
        {"label": "📊 岗位整体画像与薪资核对", "type": "primary", "action": "send_prompt", "prompt": "调出该岗位的完整档案与薪资核对画像"},
        {"label": "📝 入职前准备与避坑建议", "type": "default", "action": "send_prompt", "prompt": "给出入职该岗位前的准备事项、合同核对与避坑建议"},
        {"label": "🤝 确认接 Offer，完成求职", "type": "default", "action": "send_prompt", "prompt": "恭喜达成目标！为本次岗位求职做个完整总结归档"},
    ],
}

# 通用默认备选动作（无匹配状态或兜底）
DEFAULT_FALLBACK_ACTIONS: list[dict[str, Any]] = [
    {"label": "📋 查看岗位完整详情", "type": "primary", "action": "send_prompt", "prompt": "查看该岗位的完整要求与JD原文"},
    {"label": "🏢 查公司业务情报", "type": "default", "action": "send_prompt", "prompt": "查一下该公司的核心业务线与情报"},
]


def get_actions_for_status(follow_status: str | None) -> list[dict[str, Any]]:
    """根据跟进状态获取动作配置列表。"""
    st = (follow_status or "").strip()
    return STATUS_ACTION_RECOMMENDATIONS.get(st, DEFAULT_FALLBACK_ACTIONS)


def build_status_action_elements(follow_status: str | None, record_id: str) -> list[dict[str, Any]]:
    """生成飞书卡片的 actions 交互元素组（分行排列，每行最多 2~3 个按钮，确保移动端显示舒适）。"""
    configs = get_actions_for_status(follow_status)
    if not configs or not record_id:
        return []

    buttons: list[dict[str, Any]] = []
    for cfg in configs:
        val: dict[str, Any] = {
            "action": cfg["action"],
            "record_id": record_id,
        }
        if "prompt" in cfg:
            val["prompt"] = cfg["prompt"]
        if "target_status" in cfg:
            val["target_status"] = cfg["target_status"]

        buttons.append({
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": cfg["label"],
            },
            "type": cfg.get("type", "default"),
            "value": val,
        })

    elements: list[dict[str, Any]] = [
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "**💡 快捷操作建议（点击直达）：**",
            },
        },
    ]

    # 飞书卡片单 action 行推荐放置 2~3 个按钮，超过 2 个时拆成多行 action 提升移动端可读性
    CHUNK_SIZE = 2
    for i in range(0, len(buttons), CHUNK_SIZE):
        elements.append({
            "tag": "action",
            "actions": buttons[i:i + CHUNK_SIZE],
        })

    return elements
