import asyncio
import json
from collections.abc import AsyncGenerator

from app.core.config import settings
from app.core.llm_client import get_openai_client


class InterviewPrepAgent:
    def __init__(self):
        self.llm = get_openai_client()
        if not self.llm:
            raise ValueError("AI 服务未配置（缺少 api_key）")

    async def generate_report_stream(self, resume_text: str, jd_text: str, company_name: str) -> AsyncGenerator[str, None]:
        prompt = f"""你是一位资深的职场面试教练。候选人即将面试【{company_name}】的相关职位。
【候选人简历片段/核心经历】：
{resume_text}

【目标岗位要求（JD）】：
{jd_text}

请你根据上述信息，为候选人生成一份专业、客观、事实驱动的面试准备指南。直接给出具体的建议，坚决杜绝使用“显著提升”、“深度赋能”等AI机器味词汇。

请严格使用 Markdown 格式输出：
### 🎯 核心考察点预测
(分析JD中最看重的3个核心能力)

### 🔍 简历深挖方向预测
(根据候选人经历与JD的匹配度，列出面试官最可能追问的3个犀利问题，并给出答题思路)

### 💡 面试避坑指南
(指出候选人可能存在的软肋，并提醒面试中千万不能说的关键错误)
"""

        yield json.dumps({"type": "log", "message": f"开始生成 {company_name} 的面试辅导指南..."}, ensure_ascii=False) + "\n"

        try:
            # 调用同步的 OpenAI API 需要包裹在 to_thread，但为了流式体验，最好是批量读取。
            # 这里简单处理，等待完整的生成，因为我们无法直接 yield 从 to_thread 返回的 chunk，除非使用 async openai client。
            # 或者我们在这里直接用 requests 或 aiohttp，或者 async openai client。
            # 为了简化，如果当前只有 sync client，我们就在后台生成完，再一次性推 result，中间推 log。
            def _call():
                return self.llm.chat.completions.create(
                    model=settings.OPENAI_MODEL or "gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6,
                )

            resp = await asyncio.to_thread(_call)
            full_content = (resp.choices[0].message.content or "").strip()

            yield json.dumps({"type": "log", "message": "指南生成完毕，正在整理报告..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "result", "content": full_content}, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": f"生成失败: {e}"}, ensure_ascii=False) + "\n"
