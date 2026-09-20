/**
 * 导轨阶段统计计算（Q10 拆分批次 2：从 pipeline-stepper.tsx 抽离的纯函数）。
 * 仅针对「本次任务」岗位计算前置流转阶段（初评/深评/改写/打招呼语）的分子分母与活跃态。
 */
import { isJobDelivered, isJobReadyToDeliver, isJobRejected, isJobWaitingReview } from "./job-predicates"
import type { PipelineJob } from "@/store/pipeline-store"

export interface StageStats {
  evalTotal: number
  evalDone: number
  isEvaluatingRunning: boolean
  deepEvalTotal: number
  deepEvalDone: number
  isDeepEvalRunning: boolean
  rewriteTotal: number
  rewriteDone: number
  isRewritingRunning: boolean
  greetingTotal: number
  greetingDone: number
  isGreetingRunning: boolean
  pendingCount: number
  readyToDeliverCount: number
  deliveredCount: number
  isDeliveringRunning: boolean
}

export function computeStageStats(
  jobList: PipelineJob[],
  feishuSyncTotal?: number
): StageStats {

    // 仅针对「本次任务」的岗位计算前置流转阶段（初评、深评、改写、打招呼语）
    const currentRunJobs = jobList.filter((j) => j.is_current_run !== false)

    // 排除被清洗/初评淘汰的岗位，计算有效流转岗位池（含 rejected_auto，与看板淘汰 Tab 同口径）
    const evalPool = currentRunJobs.filter((j) => !isJobRejected(j))
    const evalTotal = evalPool.length || (feishuSyncTotal || 0)

    // 4. AI 初评 (分母为进入评估总岗位，分子为已完成打分/评级的岗位)
    const evalDone = evalPool.filter(
      (j) =>
        (j.score !== undefined && j.score !== null) ||
        !!j.grade ||
        j.sub_status === "eval_done" ||
        isJobWaitingReview(j) ||
        isJobReadyToDeliver(j) ||
        isJobDelivered(j) ||
        j.status === "error"
    ).length
    const isEvaluatingRunning = evalPool.some(
      (j) => j.node === "evaluate_node" && j.status === "running"
    )

    // 5. 深度评估 (分母严格为属于 A/B 级的精投岗位，分子为已完成深度画像诊断的岗位)
    const deepEvalTargetJobs = evalPool.filter(
      (j) =>
        j.grade === "A" ||
        j.grade === "B" ||
        j.review_type === "custom_tailored" ||
        j.node === "deep_eval_node" ||
        j.sub_status === "deep_eval" ||
        j.node === "rewrite_node" ||
        j.sub_status === "rewriting"
    )
    const deepEvalTotal = deepEvalTargetJobs.length
    const deepEvalDone = deepEvalTargetJobs.filter(
      (j) =>
        (j.node === "deep_eval_node" && j.status === "done") ||
        j.sub_status === "deep_eval" ||
        j.node === "rewrite_node" ||
        j.sub_status === "rewriting" ||
        j.node === "greeting_node" ||
        j.sub_status === "greeting" ||
        isJobWaitingReview(j) ||
        isJobReadyToDeliver(j) ||
        isJobDelivered(j) ||
        j.status === "error"
    ).length
    const isDeepEvalRunning = evalPool.some(
      (j) => j.node === "deep_eval_node" && j.status === "running"
    )

    // 6. 简历改写 (分母严格为需定制精修的 A/B 级精投岗位，分子为已完成定制简历生成的岗位)
    const rewriteTargetJobs = deepEvalTargetJobs
    const rewriteTotal = rewriteTargetJobs.length
    const rewriteDone = rewriteTargetJobs.filter(
      (j) =>
        (j.node === "rewrite_node" && j.status === "done") ||
        (j.sub_status === "rewriting" && j.status === "done") ||
        j.node === "greeting_node" ||
        j.sub_status === "greeting" ||
        isJobWaitingReview(j) ||
        isJobReadyToDeliver(j) ||
        isJobDelivered(j) ||
        j.status === "error"
    ).length
    const isRewritingRunning = evalPool.some(
      (j) => j.node === "rewrite_node" && j.status === "running"
    )

    // 7. 打招呼语 (分母为全量通过初筛的岗位，包含 A/B 定制话术与 C-F 通用话术)
    const greetingTargetJobs = evalPool
    const greetingTotal = greetingTargetJobs.length
    const greetingDone = greetingTargetJobs.filter(
      (j) =>
        j.delivery_materials?.greeting ||
        (j.node === "greeting_node" && j.status === "done") ||
        (j.node === "quick_greeting_node" && j.status === "done") ||
        (j.sub_status === "greeting" && j.status === "done") ||
        isJobWaitingReview(j) ||
        isJobReadyToDeliver(j) ||
        isJobDelivered(j) ||
        j.status === "error"
    ).length
    const isGreetingRunning = evalPool.some(
      (j) => (j.node === "greeting_node" || j.node === "quick_greeting_node") && j.status === "running"
    )

    // 8. 待审批 (当前处于人工审批断点的岗位累计数)
    const pendingCount = jobList.filter(isJobWaitingReview).length

    // 9. 待投递与已投递岗位累计数
    const readyToDeliverCount = jobList.filter(isJobReadyToDeliver).length
    const deliveredCount = jobList.filter(isJobDelivered).length
    const isDeliveringRunning = jobList.some(
      (j) => j.node === "delivery_node" && j.status === "running"
    )

    return {
      evalTotal,
      evalDone,
      isEvaluatingRunning,
      deepEvalTotal,
      deepEvalDone,
      isDeepEvalRunning,
      rewriteTotal,
      rewriteDone,
      isRewritingRunning,
      greetingTotal,
      greetingDone,
      isGreetingRunning,
      pendingCount,
      readyToDeliverCount,
      deliveredCount,
      isDeliveringRunning,
    }
}
