"""ChatAgent 卡片构建器：将 Agent 回复渲染为飞书 interactive card (lark_md 富文本结构 + 状态驱动交互按钮)。"""
from typing import Any

from app.services.chat_agent.action_config import build_status_action_elements


def build_agent_reply_card(
    text: str,
    title: str = "🤖 求职助理",
    record_id: str | None = None,
    follow_status: str | None = None,
) -> dict[str, Any]:
    """将 Agent 回复包装为飞书交互卡片 (lark_md)。

    - 支持粗体 **bold**、斜体 *italic*、列表、行内代码、代码块、超链接等 Markdown 语法原生渲染；
    - 支持长文本自动切块（单块上限 3500 字符，防飞书单元素超限）；
    - 支持按岗位跟进状态自动挂载底部推荐操作按钮组；
    - 响应式宽屏模式 + 沉稳蓝主题条 (template: "blue")。
    """
    clean_text = (text or "").strip() or "（这次没有产出回复，换个说法试试？）"

    # 单 div 元素安全长度（飞书推荐 <= 4000 字符）
    MAX_CHUNK_LEN = 3500
    chunks: list[str] = []

    if len(clean_text) <= MAX_CHUNK_LEN:
        chunks.append(clean_text)
    else:
        # 按换行优先切分
        lines = clean_text.split("\n")
        curr_buf: list[str] = []
        curr_len = 0
        for line in lines:
            if curr_len + len(line) + 1 > MAX_CHUNK_LEN and curr_buf:
                chunks.append("\n".join(curr_buf))
                curr_buf = [line]
                curr_len = len(line)
            else:
                curr_buf.append(line)
                curr_len += len(line) + 1
        if curr_buf:
            chunks.append("\n".join(curr_buf))

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": chunk,
            },
        }
        for chunk in chunks
    ]

    # 如果带有具体的岗位与状态上下文，动态挂载底部快捷动作按钮组
    if record_id:
        action_elements = build_status_action_elements(follow_status, record_id)
        elements.extend(action_elements)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


def build_job_selected_card(
    job_info: dict[str, Any],
    record_id: str,
    card_title: str = "🎯 目标岗位已选定",
) -> dict[str, Any]:
    """构建「目标岗位已锁定/已就绪」的富文本交互卡片（带元数据、状态驱动专属按钮与多维表格复核入口）。"""
    company = job_info.get("company") or "未知公司"
    title = job_info.get("title") or "未知岗位"
    salary = job_info.get("salary") or "面议"
    city = job_info.get("city") or "全国"
    status = job_info.get("status") or "新线索"
    platform = job_info.get("platform") or ""
    grade = job_info.get("grade") or ""

    meta_parts = [f"💰 薪资：{salary}", f"📍 城市：{city}"]
    if platform:
        meta_parts.append(f"🏢 平台：{platform}")
    if grade:
        meta_parts.append(f"📊 评级：{grade}")
    meta_parts.append(f"🏷️ 状态：{status}")
    meta_line = " ｜ ".join(meta_parts)

    body_md = f"**{company} · {title}**\n{meta_line}"

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": body_md,
            },
        }
    ]

    # 挂载状态驱动的快捷操作按钮
    action_elements = build_status_action_elements(status, record_id)
    elements.extend(action_elements)

    # 增加多维表格复核跳转链接
    from app.core.config import settings
    app_token = settings.FEISHU_APP_TOKEN or ""
    table_id = settings.FEISHU_TABLE_ID_JOBS or ""
    if app_token and table_id and record_id:
        record_url = f"https://feishu.cn/base/{app_token}?table={table_id}&record={record_id}"
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "👉 点此复核多维表格岗位详情"},
                "type": "default",
                "url": record_url,
            }],
        })

    # 底部说明
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "💡 提示：点击上方按钮直达下一步，也可直接在输入框发送自然语言指令。",
        }],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "indigo",
            "title": {"tag": "plain_text", "content": card_title},
        },
        "elements": elements,
    }
