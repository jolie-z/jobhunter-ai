import type { JobData } from "@/types/job"

/** 四类消耗 Token 的 AI 产物对应的任务标识（与后端 batch-process 的 task_type 同名） */
export type AiArtifactKind = "evaluate" | "deep_evaluate" | "rewrite" | "greeting"

export const AI_ARTIFACT_LABELS: Record<AiArtifactKind, string> = {
  evaluate: "AI初评",
  deep_evaluate: "深度评估",
  rewrite: "简历改写",
  greeting: "打招呼语",
}

// 深度评估落库的六个诊断字段（backend executor._handle_deep_evaluate 回写口径）
const DEEP_EVAL_FIELDS = [
  "dreamPicture",
  "atsAbilityAnalysis",
  "resumeAudit",
  "strongFitAssessment",
  "riskRedFlags",
  "deepActionPlan",
] as const

const hasText = (v: unknown): boolean => typeof v === "string" && v.trim().length > 0

/**
 * 判断岗位是否已存在对应 AI 产物（重复发起会覆盖旧结果并消耗 Token）。
 * ⚠️ 主页列表接口裁掉了详情大文本字段（DETAIL_ONLY_FIELDS），深评/改写/打招呼语
 * 在列表数据里恒为空 → 本函数对这三类在主页批量路径只作初筛，权威判断需配合
 * 后端 POST /api/jobs/check-ai-artifacts 按记录补查（定制面板拿到的是全量详情，无需补查）。
 */
export function hasAiArtifact(job: JobData | null | undefined, kind: AiArtifactKind): boolean {
  if (!job) return false
  switch (kind) {
    case "evaluate":
      return hasText(job.grade)
    case "deep_evaluate":
      return DEEP_EVAL_FIELDS.some((f) => hasText(job[f]))
    case "rewrite":
      return hasText(job.aiRewriteJson)
    case "greeting":
      return hasText(job.greetingMsg)
  }
}

/** 筛出已存在对应 AI 产物的岗位 */
export function filterJobsWithAiArtifact(jobs: JobData[], kind: AiArtifactKind): JobData[] {
  return (jobs || []).filter((j) => hasAiArtifact(j, kind))
}
