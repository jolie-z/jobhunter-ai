import { FAILED_TERMINAL_STATUSES, type PipelineJob } from "@/store/pipeline-store"

// ===== 状态集合常量（集中管理，避免魔法字符串） =====
// rejected_auto：初评 E/F 级自动淘汰（后端 snapshot_service 分诊，node=clean_rule_rejected）
export const JOB_STATUS_SETS = {
  REJECTED: new Set(["rejected", "rejected_auto", "清洗淘汰", "ai清洗淘汰", "ai 清洗淘汰"]),
  DELIVERED: new Set(["delivered", "已投递"]),
  READY_TO_DELIVER: new Set(["approved", "ready_to_deliver", "待投递"]),
  FAILED: FAILED_TERMINAL_STATUSES,
} as const

/**
 * 岗位是否已投递：判断岗位是否完成投递流程（最终状态）
 * @param job 岗位对象
 * @returns true 如果岗位处于已投递状态
 */
export function isJobDelivered(job: PipelineJob): boolean {
  return JOB_STATUS_SETS.DELIVERED.has(job.status)
}

/**
 * 岗位是否被拒绝/淘汰：包括硬规则清洗淘汰和 AI 筛选淘汰
 * @param job 岗位对象
 * @returns true 如果岗位被拒绝或淘汰
 */
export function isJobRejected(job: PipelineJob): boolean {
  return (
    JOB_STATUS_SETS.REJECTED.has(job.status) ||
    job.node === "clean_rejected" ||
    job.node === "clean_rule_rejected"
  )
}

/**
 * 岗位是否就绪可投递：包含手动放行等待投递的岗位
 * @param job 岗位对象
 * @returns true 如果岗位处于待投递状态（且未投递、未被拒绝、未投递失败）
 */
export function isJobReadyToDeliver(job: PipelineJob): boolean {
  if (isJobDelivered(job) || isJobRejected(job) || isJobFailed(job) || job.status === "running") return false
  return (
    JOB_STATUS_SETS.READY_TO_DELIVER.has(job.status) ||
    job.node === "ready_to_deliver" ||
    job.node === "approved_waiting_delivery"
  )
}

/**
 * 岗位是否处于运行态（node/sub_status/终态三方约束）：卡片渲染与投递判定共用。
 * 判定式与 job-card 旧内联实现完全一致。
 */
export function isJobRunning(job: PipelineJob | undefined): boolean {
  if (!job) return false
  return (
    (job.status === "running" ||
      job.node === "evaluate_node" ||
      job.node === "rewrite_node" ||
      job.node === "deep_eval_node" ||
      job.node === "greeting_node" ||
      job.node === "quick_greeting_node") &&
    job.status !== "done" &&
    job.status !== "waiting" &&
    job.status !== "delivered" &&
    !isJobRejected(job) &&
    job.sub_status !== "eval_done"
  )
}

/**
 * 岗位是否正在自动投递：卡片「终止投递」按钮显隐与终止中状态的自动复位共用同一口径。
 */
export function isJobDelivering(job: PipelineJob | undefined): boolean {
  if (!job) return false
  return isJobRunning(job) && (job.sub_status === "delivering" || job.node === "delivery_node")
}

/**
 * 岗位是否等待老板审批：当前人工审批断点的岗位
 * @param job 岗位对象
 * @returns true 如果岗位处于待审批状态
 */
export function isJobWaitingReview(job: PipelineJob): boolean {
  if (isJobDelivered(job) || isJobRejected(job) || isJobReadyToDeliver(job) || isJobFailed(job) || job.status === "running") return false
  // 初评排队（eval_pending/eval_queued）与停机未评估（eval_incomplete）的 status 也是
  // waiting：宽匹配曾把它们错归待审批 tab（2026-11-01 疑似重复记录误归事件）。排队/
  // 未评估属评估侧，不属于人工审批断点；eval_incomplete 另归待重评 tab（审计 P1-5）——
  // 它们从未跑过 AI 评估，进入待审批曾被「一键放行」直接推进投递队列。
  if (job.node === "evaluate_node" && (job.sub_status === "eval_pending" || job.sub_status === "eval_queued" || job.sub_status === "eval_incomplete")) return false
  return job.status === "waiting" || job.node === "manual_review_node"
}

/**
 * 岗位是否失败：存在 failure_info 且不在活跃流转状态
 * @param job 岗位对象
 * @returns true 如果岗位失败
 */
export function isJobFailed(job: PipelineJob): boolean {
  if (isJobDelivered(job) || isJobRejected(job) || job.status === "running") return false
  if (JOB_STATUS_SETS.FAILED.has(job.status) || job.node === "error") return true
  // 岗位重新流转（waiting/ready_to_deliver）后 failure_info 残留不再视为失败
  if (
    job.status === "waiting" ||
    job.node === "manual_review_node" ||
    job.node === "ready_to_deliver" ||
    job.node === "approved_waiting_delivery" ||
    JOB_STATUS_SETS.READY_TO_DELIVER.has(job.status)
  ) return false
  return job.failure_info !== undefined
}

/**
 * 岗位是否在评估中：仅指当前运行中的初评节点
 * @param job 岗位对象
 * @returns true 如果岗位正在评估中
 */
export function isJobEvaluating(job: PipelineJob): boolean {
  if (
    isJobDelivered(job) ||
    isJobRejected(job) ||
    isJobWaitingReview(job) ||
    isJobReadyToDeliver(job) ||
    isJobFailed(job)
  ) {
    return false
  }
  return job.status === "running"
}

/**
 * 岗位是否待重评：停机期间未经 AI 评估的岗位（waiting/evaluate_node/eval_incomplete）。
 * 归待重评 tab 纯展示（下次链路启动自动补评估）；后端 /auto-heal-and-approve 已加评级闸，
 * 此类岗位不可被放行（2026-11-02 审计 P1-5）。
 */
export function isJobPendingReeval(job: PipelineJob): boolean {
  if (job.status !== "waiting" || job.node !== "evaluate_node") return false
  return job.sub_status === "eval_incomplete"
}

// ===== 平台识别单一事实源（CR-B3 拆分子任务；CR-Split-R2-P2 常量表单点驱动）=====
// 四平台匹配词/展示名/other 兜底统一在 KNOWN_PLATFORMS：正向匹配、反向分桶、other
// 判定全部由该表驱动，新增平台只改这一处（消除三处手抄失步）
const KNOWN_PLATFORMS = [
  { key: "51job", label: "51Job", keywords: ["51", "前程"] },
  { key: "zhilian", label: "智联招聘", keywords: ["智联", "zhilian"] },
  { key: "boss", label: "BOSS直聘", keywords: ["boss"] },
  { key: "liepin", label: "猎聘", keywords: ["猎聘", "liepin"] },
] as const

const _OTHER_EXCLUDED_KEYWORDS = KNOWN_PLATFORMS.flatMap((p) => p.keywords)

export function resolvePlatformKey(raw: string, platformKey: string): boolean {
  const r = (raw || "").toLowerCase()
  const known = KNOWN_PLATFORMS.find((p) => p.key === platformKey)
  if (known) return known.keywords.some((kw) => r.includes(kw))
  if (platformKey === "other") {
    // 「其他」桶：小红书或平台字段缺失的失败岗（审计 P2-25 行为修正）
    if (!r) return true
    return !_OTHER_EXCLUDED_KEYWORDS.some((kw) => r.includes(kw))
  }
  return false
}

// 反向封装：岗位→所属平台桶 key（failed-batch-bar 分桶统计用）
export function resolvePlatformKeyForJob(rawPlatform: string | undefined): { key: string; label: string } {
  const raw = (rawPlatform || "").toLowerCase()
  for (const p of KNOWN_PLATFORMS) {
    if (p.keywords.some((kw) => raw.includes(kw))) return { key: p.key, label: p.label }
  }
  return { key: "other", label: "其他" }
}
