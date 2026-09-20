#!/usr/bin/env python3
"""
QA Evaluator - 简历二次质检模块
对 AI 改写后的简历进行最终质量保证检查
"""

import json
from openai import OpenAI

from app.core.llm_tracker import make_tracked_client
# 🌟 替换为新架构的 config
from app.core.config import settings

# 🌟 配置统一走 settings 动态读取（配置页保存即生效）；不在模块级冻结快照
_client = None
_client_sig = None


def get_client():
    """惰性构建并缓存 OpenAI 客户端；Key/URL 变更时自动重建。"""
    global _client, _client_sig
    sig = (settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL)
    if _client is None or _client_sig != sig:
        _client = make_tracked_client(OpenAI(api_key=sig[0], base_url=sig[1]), caller="qa_evaluator")
        _client_sig = sig
    return _client

# ==========================================
# 质检灵魂 prompt（原「Prompt 策略库」飞书表已退役：该表从未被命中加载，
# 现行评估/改写引擎均已固化在代码内，见 docs/plans/飞书多维表格审计_2026-09-03.md）
# ==========================================
QA_SOUL_PROMPT = "你是一个严格的简历质量保证（QA）专家。任务是对AI重写过的简历进行交叉质检。保持冷酷、精准、客观。"

def qa_evaluate_resume(job_description: str, rewritten_resume_text: str) -> dict:
    """对改写后的简历进行二次质检评估"""

    soul_prompt = QA_SOUL_PROMPT

    # 🌟 肉体：锁死强约束 JSON，绝不妥协
    body_format = """
【任务要求】
请快速扫描当前简历，并输出一份极其精简的【最终质检与人工待办报告】。
必须严格输出纯 JSON 字符串，绝不能包含 Markdown 代码块标记。

{
  "match_verification": {
    "achieved_points": [
      "• 列出 2-3 个简历现在已经完美契合 JD 的硬核技能或业务要求"
    ],
    "missing_points": [
      "• 一针见血地指出改写后依然没有体现，或者体现得很弱的 1-2 个 JD 强制要求"
    ]
  },
  "hallucination_check": [
    "• 指出简历中听起来过于宏大或经不起深挖的表述及后果。若无，输出'未发现明显过度包装'"
  ],
  "human_action_items": [
    "[ ] 待办1：请在 XX 项目的成果部分，补充具体的 % 数据",
    "[ ] 待办2：检查技能清单中的 XX 工具，确认是否能够应对白板编程"
  ]
}
"""

    full_prompt = f"{soul_prompt}\n\n{body_format}\n\n【目标岗位 JD】：\n{job_description}\n\n【当前改写后的简历文本】：\n{rewritten_resume_text}"

    try:
        response = get_client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        
        # 🌟 安全清理 JSON 外壳（防崩溃语法）
        prefix_json = "`" * 3 + "json"
        suffix = "`" * 3
        if content.startswith(prefix_json): content = content[7:]
        elif content.startswith(suffix): content = content[3:]
        if content.endswith(suffix): content = content[:-3]
        
        qa_report = json.loads(content.strip())
        return qa_report
        
    except json.JSONDecodeError as e:
        error_msg = f"QA 评估 JSON 解析失败: {str(e)}"
        print(f"❌ {error_msg}")
        raise ValueError(error_msg) from e
    except Exception as e:
        error_msg = f"QA 评估 LLM 调用失败: {str(e)}"
        print(f"❌ {error_msg}")
        raise RuntimeError(error_msg) from e


if __name__ == "__main__":
    # 测试代码
    test_jd = "招聘 AI 产品经理，要求熟悉大模型应用开发，有 Prompt Engineering 经验"
    test_resume = "我是一名 AI 产品经理，精通大模型应用开发和 Prompt Engineering"
    
    result = qa_evaluate_resume(test_jd, test_resume)
    print(json.dumps(result, ensure_ascii=False, indent=2))