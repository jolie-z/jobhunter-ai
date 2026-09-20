import asyncio

from app.core.config import settings
from app.core.llm_client import get_openai_client


async def generate_interview_feedback(jd_text: str, transcript: str, role: str, style: str) -> str:
    """生成面试教练复盘反馈"""
    llm = get_openai_client()
    if not llm:
        raise ValueError("AI 服务未配置（缺少 api_key）")

    role_map = {"hr": "HRBP", "business": "业务线考官", "boss": "大老板/VP"}
    style_map = {"coach": "教练陪跑", "real": "全真模拟"}
    current_role = role_map.get(role, "考官")
    current_style = style_map.get(style, "测试")

    prompt = f"""你是一个资深的职场面试教练。请对候选人在【{current_role} - {current_style}】面试中的文字稿进行直接、客观、切中要害的复盘点评。
【目标岗位要求】：{jd_text}
【面试文字稿】：
{transcript}

请严格按照以下格式直接输出文本（切勿使用代码块包裹）：
#### 📊 面试复盘诊断报告
- **📐 表达结构**: (分析是否符合STAR法则，逻辑是否清晰，有无冗余表述)
- **🎯 岗位匹配度**: (分析回答是否准确覆盖岗位的核心要求与关键词)
- **🗣️ 沟通状态**: (指出口语化表达习惯、不流畅或逻辑跳跃的问题)
- **💡 改进建议与亮点**: (指出回答中的出彩点，并明确指出需要避免的关键错误)
"""

    def _call():
        return llm.chat.completions.create(
            model=settings.OPENAI_MODEL or "gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6
        )

    resp = await asyncio.to_thread(_call)
    report_text = (resp.choices[0].message.content or "").strip()
    usage = resp.usage
    if usage:
        token_info = f"\n\n> 💰 **本次复盘 Token 消耗明细**：输入 {usage.prompt_tokens} | 输出 {usage.completion_tokens} | 总计 {usage.total_tokens} Tokens"
        return "\n\n" + report_text + token_info
    return "\n\n" + report_text
