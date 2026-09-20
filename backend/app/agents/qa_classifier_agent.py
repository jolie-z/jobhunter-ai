import asyncio
import json

from app.core.config import settings
from app.core.llm_client import get_openai_client


class QAClassifierAgent:
    def __init__(self):
        self.llm = get_openai_client()
        if not self.llm:
            raise ValueError("AI 服务未配置（缺少 api_key）")

    async def classify_and_deduplicate(
        self, parent_job: str, new_question: str, q_list_text: str
    ) -> tuple[list, str, str | None]:
        """
        拆词、分类、查重。
        返回: (core_tags, q_type, dup_id)
        """
        prompt = f"""你是一个极其专业的面试题库架构师。请完成以下三个任务，并严格输出 JSON 格式。
任务1【拆词】：从原岗位名称 "{parent_job}" 中提取2-3个核心原子标签（如"人力资源", "AI产品经理"）。
任务2【分类】：判断新问题 "{new_question}" 属于哪种类型？只能从 ["业务专业题", "HR通用题", "宏观战略题"] 中选一个。
任务3【查重】：对比下方的【已有题库】，判断新问题是否与其中某道题实质上考察的是同一个核心技能点？如果是，返回对应题目的 ID；如果没有重复，返回 null。

【已有题库】：
{q_list_text or "暂无题目"}

输出格式要求严格如下：
{{"core_tags": ["标签1", "标签2"], "question_type": "HR通用题", "duplicate_id": "xxx" 或 null}}"""

        def _call():
            return self.llm.chat.completions.create(
                model=settings.OPENAI_MODEL or "gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

        try:
            resp = await asyncio.to_thread(_call)
            ai_analysis = json.loads(resp.choices[0].message.content)
            core_tags = ai_analysis.get("core_tags", [parent_job])
            q_type = ai_analysis.get("question_type", "业务专业题")
            dup_id = ai_analysis.get("duplicate_id")
            return core_tags, q_type, dup_id
        except Exception as e:
            print(f"⚠️ AI 判定失败，降级处理: {e}")
            return [parent_job], "业务专业题", None
