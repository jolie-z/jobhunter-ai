export const MODEL_COLORS = [
  "#6366f1",
  "#38bdf8",
  "#34d399",
  "#fbbf24",
  "#f87171",
  "#a855f7",
  "#ec4899",
  "#94a3b8",
]

export const ACTION_LABELS: Record<string, string> = {
  // 极速录入与多模态视觉提取
  "service:_parse_fields_by_vision": "多模态截图解析",
  "service:_call_llm_for_job_parsing": "岗位文本解析",
  "service:_parse_fields_by_text": "文本智能提取",
  "service:parse_job_by_llm": "岗位详情提取",
  // 企业背景与工商调研
  "company_intel:search_company_intel": "企业情报与工商调研",
  "company_intel:search_company": "企业背景调研",
  "company_intel": "企业情报调研",
  // 简历与打招呼
  "skill_rewrite:run_skill_based_rewrite": "技能化改写",
  "skill_greeting:run_skill_based_greeting": "智能招呼语",
  "ai_evaluator:_call_10dim_evaluation": "AI 8维评估",
  "ai_evaluator:call_10dim_evaluation": "AI 8维评估",
  "ai_scorer:deep_evaluate_resume": "简历深度评估",
  "markdown_to_json:parse_markdown_to_json": "格式解析",
  "step1_rule_filter:evaluate_job": "AI 岗位初筛",
  "router:call_llm": "路由 LLM 调用",
  "resume_structurer:call_llm": "简历结构化",
  "step1_ai_scout": "AI 侦察兵初筛",
  "ai_evaluator": "AI 评估器",
  "skill_rewrite": "简历改写",
  "quick_greeting": "快捷打招呼",
  "copilot": "Copilot 助手",
  "deep_rewrite": "深度改写",
  "global_diagnosis": "全局诊断",
  "grill_suggestion": "面试追问建议",
  "ats_align": "ATS 对齐",
}

export function actionLabel(name: string) {
  if (!name) return "大模型调用"
  if (ACTION_LABELS[name]) return ACTION_LABELS[name]

  // 智能模糊语义归一化（防止未知堆栈泄露英文）
  const lower = name.toLowerCase()
  if (lower.includes("vision") || lower.includes("screenshot")) return "多模态截图解析"
  if (lower.includes("job_parsing") || lower.includes("parse_job")) return "岗位文本解析"
  if (lower.includes("company")) return "企业情报与工商调研"
  if (lower.includes("rewrite")) return "简历深度改写"
  if (lower.includes("greeting")) return "智能招呼语"
  if (lower.includes("10dim") || lower.includes("evaluat")) return "AI 岗位评估"
  if (lower.includes("structur")) return "简历结构化解析"
  if (lower.includes("grill")) return "面试深度追问"
  if (lower.includes("diagnosis")) return "全局竞争力诊断"
  if (lower.includes("scout") || lower.includes("filter")) return "初筛排雷"

  if (name.includes(":")) {
    const parts = name.split(":")
    return parts[1] || name
  }
  return name
}

export function fmtDateTime(raw: string) {
  if (!raw) return "—"
  const clean = raw.replace("T", " ")
  if (clean.length >= 19) {
    return clean.slice(5, 19)
  }
  return clean
}

export function fmtNum(n: number) {
  return (n || 0).toLocaleString("en-US")
}

export function fmtCost(n: number) {
  return `¥${(n || 0).toFixed(4)}`
}

export function fmtK(n: number) {
  if (!n) return "0"
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : `${Math.round(n / 1000)}K`
}
