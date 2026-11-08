/**
 * 导轨阶段统计计算（Q10 拆分批次 2：从 pipeline-stepper.tsx 抽离的纯函数）。
 * 仅针对「本次任务」岗位计算前置流转阶段（初评/深评/改写/打招呼语）的分子分母与活跃态。
 *
 * 2026-10-30 口径修复：
 * - 失败岗不再算「已评估 / 已生成打招呼 / 已改写 / 已深评」；
 * - 深评/改写分母按后端实际自动化阈值（A/B/C）判定，不再硬编码 A/B；
 * - 待审批/待投递/已投递与前置阶段统一使用「本轮」口径；
 * - 新增各阶段实时运行岗位数，供导轨同时高亮多个并发阶段。
 */
import { isJobDelivered, isJobReadyToDeliver, isJobRejected, isJobWaitingReview } from "./job-predicates"
import { isGreetingSupportedPlatform } from "@/lib/platform-utils"
import type { PipelineJob } from "@/store/pipeline-store"

export interface StageStats {
  evalTotal: number
  evalDone: number
  /** 以下 is*Running 均为 runningCounts.* > 0 的兼容别名；新增代码优先使用 runningCounts */
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
  /** 各阶段当前正在运行的岗位数（并发岗位可同时点亮多个阶段） */
  runningCounts: {
    evaluating: number
    deep_eval: number
    rewriting: number
    greeting: number
    delivering: number
  }
}

const GRADE_ORDER: Record<string, number> = { A: 0, B: 1, C: 2 }

/**
 * 评级是否达到自动化阈值（与后端 feishu_utils._GRADE_THRESHOLDS 同口径）。
 * A -> 仅 A；B -> A/B；C -> A/B/C。D/F 永远不触发深评/改写。
 * 锚点：backend/app/core/feishu_utils.py `_GRADE_THRESHOLDS`，改动需两端同步。
 */
export function gradeMeetsThreshold(grade: string | undefined, threshold: string): boolean {
  const g = (grade || "").toUpperCase()
  if (!(g in GRADE_ORDER)) return false
  const t = (threshold || "A").toUpperCase()
  const required = t === "C" ? 2 : t === "B" ? 1 : 0
  return GRADE_ORDER[g] <= required
}

export function computeStageStats(
  jobList: PipelineJob[],
  feishuSyncTotal?: number,
  autoEvalThreshold: string = "A",
): StageStats {

    // 仅针对「本次任务」的岗位计算所有阶段的分子分母。
    // 待审批/待投递/已投递也必须按本轮过滤，否则今日早先任务的已投递岗位
    // 会让「自动投递」阶段显示成已完成。
    const currentRunJobs = jobList.filter((j) => j.is_current_run !== false)

    // 排除被清洗/初评淘汰的岗位，计算有效流转岗位池（含 rejected_auto，与看板淘汰 Tab 同口径）。
    // rejected_manual（老板审批拒绝）只在「全部岗位」归档，不参与导轨分母，避免拒绝后
    // 深评/改写阶段永远停在 0/1。
    const evalPool = currentRunJobs.filter(
      (j) => !isJobRejected(j) && j.status !== "rejected_manual"
    )
    const evalTotal = evalPool.length || (feishuSyncTotal || 0)

    // 4. AI 初评 (分母为进入评估总岗位，分子为已完成打分/评级的岗位)
    // 失败岗只有拿到真实 score/grade 时才算完成；纯 error 不再虚增分子。
    const evalDone = evalPool.filter(
      (j) =>
        (j.score !== undefined && j.score !== null) ||
        !!j.grade ||
        j.sub_status === "eval_done" ||
        isJobWaitingReview(j) ||
        isJobReadyToDeliver(j) ||
        isJobDelivered(j)
    ).length

    // 5. 深度评估 (分母为实际达到自动化阈值/已进入深评节点的岗位，分子为已完成深评的岗位)
    const deepEvalTargetJobs = evalPool.filter(
      (j) =>
        j.deep_eval_done === true ||
        j.has_rewrite === true ||
        j.node === "deep_eval_node" ||
        j.sub_status === "deep_eval" ||
        j.node === "rewrite_node" ||
        j.sub_status === "rewriting" ||
        (j.review_type === "custom_tailored" && !j.grade) ||
        (!!j.grade && gradeMeetsThreshold(j.grade, autoEvalThreshold))
    )
    const deepEvalTotal = deepEvalTargetJobs.length
    const deepEvalDone = deepEvalTargetJobs.filter(
      (j) =>
        j.deep_eval_done === true ||
        j.has_rewrite === true ||
        j.node === "rewrite_node" ||
        j.sub_status === "rewriting" ||
        j.node === "greeting_node" ||
        j.sub_status === "greeting" ||
        isJobWaitingReview(j) ||
        isJobReadyToDeliver(j) ||
        isJobDelivered(j)
    ).length

    // 6. 简历改写 (分母与深评目标一致；分子只认改写节点真正完成)
    const rewriteTargetJobs = deepEvalTargetJobs
    const rewriteTotal = rewriteTargetJobs.length
    const rewriteDone = rewriteTargetJobs.filter(
      (j) =>
        j.has_rewrite === true ||
        (j.node === "rewrite_node" && j.status === "done") ||
        (j.sub_status === "rewriting" && j.status === "done") ||
        // 精投轨的 greeting_node 是 rewrite_node 内部的子阶段：此时改写文本已产出，
        // 只剩打招呼语/物料渲染，简历改写阶段可以如实记为完成。
        j.node === "greeting_node" ||
        isJobWaitingReview(j) ||
        isJobReadyToDeliver(j) ||
        isJobDelivered(j)
    ).length

    // 7. 打招呼语 (分母只统计平台本身支持微聊话术的岗位；分子只认真实话术产物)
    const greetingTargetJobs = evalPool.filter((j) => isGreetingSupportedPlatform(j.platform))
    const greetingTotal = greetingTargetJobs.length
    const greetingDone = greetingTargetJobs.filter(
      (j) =>
        j.delivery_materials?.greeting ||
        !!j.greeting_msg ||
        (j.node === "greeting_node" && j.status === "done") ||
        (j.node === "quick_greeting_node" && j.status === "done") ||
        (j.sub_status === "greeting" && j.status === "done")
    ).length

    // 8. 待审批 / 待投递 / 已投递（本轮口径）
    const pendingCount = currentRunJobs.filter(isJobWaitingReview).length
    const readyToDeliverCount = currentRunJobs.filter(isJobReadyToDeliver).length
    const deliveredCount = currentRunJobs.filter(isJobDelivered).length

    // 各阶段实时运行数：并发岗位可以同时点亮多个阶段，不能只信最后一条 stage 事件
    const runningCounts = {
      evaluating: evalPool.filter((j) => j.status === "running" && j.node === "evaluate_node").length,
      deep_eval: evalPool.filter((j) => j.status === "running" && j.node === "deep_eval_node").length,
      rewriting: evalPool.filter((j) => j.status === "running" && j.node === "rewrite_node").length,
      greeting: evalPool.filter(
        (j) => j.status === "running" && (j.node === "greeting_node" || j.node === "quick_greeting_node")
      ).length,
      delivering: evalPool.filter(
        (j) => j.status === "running" && j.node === "delivery_node"
      ).length,
    }

    return {
      evalTotal,
      evalDone,
      isEvaluatingRunning: runningCounts.evaluating > 0,
      deepEvalTotal,
      deepEvalDone,
      isDeepEvalRunning: runningCounts.deep_eval > 0,
      rewriteTotal,
      rewriteDone,
      isRewritingRunning: runningCounts.rewriting > 0,
      greetingTotal,
      greetingDone,
      isGreetingRunning: runningCounts.greeting > 0,
      pendingCount,
      readyToDeliverCount,
      deliveredCount,
      isDeliveringRunning: runningCounts.delivering > 0,
      runningCounts,
    }
}
