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
 * 岗位是否等待老板审批：当前人工审批断点的岗位
 * @param job 岗位对象
 * @returns true 如果岗位处于待审批状态
 */
export function isJobWaitingReview(job: PipelineJob): boolean {
  if (isJobDelivered(job) || isJobRejected(job) || isJobReadyToDeliver(job) || isJobFailed(job) || job.status === "running") return false
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
