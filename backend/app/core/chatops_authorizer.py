"""ChatOps 审批门禁：状态变更动作的操作者白名单（Q-M9-4）。

背景：卡片「放行/批准投递/召回/回收」与文字快捷审批属状态变更（最终驱动真实投递），
此前任何群成员都可触发。本模块提供可配白名单门禁：
- `FEISHU_APPROVER_OPEN_IDS` 未配置 → 放行（向后兼容单人群自用），首次判定时打
  WARNING 告警留痕，开源多用户部署前应配置；
- 已配置 → 仅名单内 open_id 可触发受控动作；名单外拒绝并如实回执；
- 操作者身份缺失 → 拒绝（fail-closed，状态变更动作拿不到 open_id 属异常，宁拒勿放）。

只读查询（进度/岗位查询/ping/详情）不受门禁影响。ChatAgent 对话内 LLM 工具级鉴权
为后续加固项（当前门禁覆盖卡片动作与文字快捷审批两个主要入口）。
"""

import logging
import os

logger = logging.getLogger(__name__)

# 配置键：逗号/空白分隔的 open_id 白名单（settings.json 配置页或 .env 均可）
APPROVER_ENV_KEY = "FEISHU_APPROVER_OPEN_IDS"

_empty_warned = False

# 受控动作白名单（卡片按钮 action 值）：审批/放行/流转/召回/回收/发起流水线
GUARDED_CARD_ACTIONS = frozenset({
    "run_pipeline",
    "update_status",
    "mark_delivered",
    "approve_all_ab", "approve_selected_ab",
    "approve_all_mass", "approve_selected_mass",
    "recall_selected_rejected", "confirm_recall",
    "confirm_trash",
})

# 文字快捷审批触发词——**单一事实源**：agent_router 入口词表直接 import 本常量，杜绝双份维护漂移
APPROVAL_APPROVE_WORDS = frozenset({"放行", "通过", "批准", "approve", "yes"})
APPROVAL_REJECT_WORDS = frozenset({"拒绝", "跳过", "reject", "no"})
QUICK_APPROVAL_WORDS = APPROVAL_APPROVE_WORDS | APPROVAL_REJECT_WORDS

# 拒绝回执文案（WS/webhook 双通道同款）
DENY_REPLY = "⛔ 此操作需要审批权限，请联系审批人。"


def get_approver_open_ids() -> list[str]:
    """读取白名单：settings.FEISHU_APPROVER_OPEN_IDS 优先，回落环境变量。"""
    raw = ""
    try:
        from app.core.config import settings

        raw = str(getattr(settings, "FEISHU_APPROVER_OPEN_IDS", "") or "")
    except Exception:
        raw = ""
    if not raw:
        raw = os.getenv(APPROVER_ENV_KEY, "")
    return [x.strip() for x in raw.replace("；", ",").replace(";", ",").replace("，", ",").split(",") if x.strip()]


def _warn_empty_once() -> None:
    global _empty_warned
    if not _empty_warned:
        _empty_warned = True
        logger.warning(
            f"[审批门禁] {APPROVER_ENV_KEY} 未配置——状态变更动作对全部群成员放行（单人群自用可接受）；"
            f"开源/多人部署前请在配置页填写审批人 open_id 白名单"
        )


def is_authorized(sender_open_id: str | None, action: str = "") -> bool:
    """判定操作者是否可执行受控动作。

    - 白名单未配置 → 放行（首次告警，兼容既有单人群部署）
    - 白名单已配置 → 仅名单内放行；open_id 缺失一律拒绝（fail-closed）
    """
    approvers = get_approver_open_ids()
    if not approvers:
        _warn_empty_once()
        return True
    oid = str(sender_open_id or "").strip()
    if not oid:
        logger.warning(f"[审批门禁] 受控动作 {action!r} 缺少操作者 open_id，fail-closed 拒绝")
        return False
    return oid in approvers


def is_quick_approval_text(text: str) -> bool:
    """是否文字快捷审批指令（精确词表，与 agent_router 入口同源）。"""
    return str(text or "").strip().lower() in QUICK_APPROVAL_WORDS


def denied_text_approval(sender_open_id: str | None, text: str) -> bool:
    """文字快捷审批门禁：命中词表且操作者未授权 → True（调用方应回执 DENY_REPLY 并中止）。"""
    if not is_quick_approval_text(text):
        return False
    return not is_authorized(sender_open_id, f"文字快捷审批:{text}")
