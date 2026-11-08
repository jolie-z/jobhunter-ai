import { describe, it, expect } from "vitest"
import { computeStageStats, gradeMeetsThreshold } from "./stepper-stats"
import type { PipelineJob } from "@/store/pipeline-store"

const job = (overrides: Partial<PipelineJob> = {}): PipelineJob =>
  ({
    job_id: "rec_test",
    job_name: "测试岗位",
    company_name: "测试公司",
    platform: "boss",
    status: "running",
    is_current_run: true,
    ...overrides,
  }) as PipelineJob

describe("stepper-stats 口径（2026-10-30 SSE 状态同步修复）", () => {
  it("失败岗不再算已评估 / 已生成打招呼 / 已深评 / 已改写", () => {
    const stats = computeStageStats([
      job({
        job_id: "rec_failed",
        status: "error",
        node: "error",
        grade: undefined,
        score: undefined,
        deep_eval_done: false,
      }),
    ])
    expect(stats.evalTotal).toBe(1)
    expect(stats.evalDone).toBe(0)
    expect(stats.greetingDone).toBe(0)
    expect(stats.deepEvalDone).toBe(0)
    expect(stats.rewriteDone).toBe(0)
  })

  it("失败岗若已有真实 score/grade，仍算已评估（评估成功但后续投递失败）", () => {
    const stats = computeStageStats([
      job({ status: "error", node: "error", grade: "C", score: 71 }),
    ])
    expect(stats.evalDone).toBe(1)
  })

  it("深评/改写分母跟随自动化阈值：阈值 A 时 B 级海投岗不计入", () => {
    const jobs = [
      job({ job_id: "rec_a", grade: "A", status: "waiting", node: "manual_review_node", review_type: "custom_tailored" }),
      job({ job_id: "rec_b", grade: "B", status: "waiting", node: "manual_review_node", review_type: "mass_apply" }),
    ]
    const thresholdA = computeStageStats(jobs, undefined, "A")
    expect(thresholdA.deepEvalTotal).toBe(1)
    expect(thresholdA.rewriteTotal).toBe(1)

    const thresholdB = computeStageStats(jobs, undefined, "B")
    expect(thresholdB.deepEvalTotal).toBe(2)
    expect(thresholdB.rewriteTotal).toBe(2)
  })

  it("已有真实 AI改写JSON 的 B 级定制岗，即使阈值 A 也计入深评/改写分母", () => {
    const stats = computeStageStats(
      [
        job({
          job_id: "rec_b_custom",
          grade: "B",
          status: "waiting",
          node: "manual_review_node",
          review_type: "custom_tailored",
          has_rewrite: true,
        }),
      ],
      undefined,
      "A",
    )
    expect(stats.deepEvalTotal).toBe(1)
    expect(stats.rewriteTotal).toBe(1)
    expect(stats.rewriteDone).toBe(1)
  })

  it("阈值 C 时 C 级岗位计入深评/改写分母", () => {
    const jobs = [job({ job_id: "rec_c", grade: "C", status: "running", node: "deep_eval_node" })]
    expect(computeStageStats(jobs, undefined, "A").deepEvalTotal).toBe(1) // 节点兜底
    expect(computeStageStats(jobs, undefined, "C").deepEvalTotal).toBe(1)
    expect(gradeMeetsThreshold("C", "C")).toBe(true)
    expect(gradeMeetsThreshold("C", "B")).toBe(false)
    expect(gradeMeetsThreshold("D", "C")).toBe(false)
  })

  it("深评完成标记跨阶段保留：rewrite running 时 deepEvalDone 已 +1，但 rewriteDone 仍为 0", () => {
    const stats = computeStageStats([
      job({
        job_id: "rec_rewrite",
        grade: "A",
        node: "rewrite_node",
        sub_status: "rewriting",
        status: "running",
        deep_eval_done: true,
      }),
    ])
    expect(stats.deepEvalTotal).toBe(1)
    expect(stats.deepEvalDone).toBe(1)
    expect(stats.rewriteTotal).toBe(1)
    expect(stats.rewriteDone).toBe(0)
    expect(stats.runningCounts.rewriting).toBe(1)
    expect(stats.isDeepEvalRunning).toBe(false)
  })

  it("待审批/待投递/已投递与前置阶段统一按本轮过滤", () => {
    const stats = computeStageStats([
      job({ job_id: "rec_old_ready", status: "ready_to_deliver", node: "ready_to_deliver", is_current_run: false }),
      job({ job_id: "rec_old_delivered", status: "delivered", node: "delivery_node", is_current_run: false }),
      job({ job_id: "rec_old_waiting", status: "waiting", node: "manual_review_node", is_current_run: false }),
    ])
    expect(stats.evalTotal).toBe(0)
    expect(stats.pendingCount).toBe(0)
    expect(stats.readyToDeliverCount).toBe(0)
    expect(stats.deliveredCount).toBe(0)
  })

  it("打招呼分母排除不支持微聊的平台，分子只认真实话术产物", () => {
    const stats = computeStageStats([
      job({ job_id: "rec_51", platform: "51job", node: "quick_greeting_node", status: "done" }),
      job({ job_id: "rec_boss", platform: "boss", node: "quick_greeting_node", status: "done" }),
      job({ job_id: "rec_boss_wait", platform: "boss", status: "waiting", node: "manual_review_node" }),
    ])
    expect(stats.greetingTotal).toBe(2)
    // quick_greeting done 算一条；waiting 但没有 greeting_msg 不算
    expect(stats.greetingDone).toBe(1)
  })

  it("并发阶段可以同时有运行岗位数", () => {
    const stats = computeStageStats([
      job({ job_id: "rec_eval", status: "running", node: "evaluate_node", sub_status: "ai_eval" }),
      job({ job_id: "rec_deep", status: "running", node: "deep_eval_node", sub_status: "deep_eval" }),
      job({ job_id: "rec_rewrite", status: "running", node: "rewrite_node", sub_status: "rewriting" }),
      job({ job_id: "rec_greet", status: "running", node: "greeting_node", sub_status: "greeting" }),
      job({ job_id: "rec_deliver", status: "running", node: "delivery_node", sub_status: "delivering" }),
    ])
    expect(stats.runningCounts).toEqual({
      evaluating: 1,
      deep_eval: 1,
      rewriting: 1,
      greeting: 1,
      delivering: 1,
    })
    expect(stats.isEvaluatingRunning).toBe(true)
    expect(stats.isDeepEvalRunning).toBe(true)
    expect(stats.isRewritingRunning).toBe(true)
    expect(stats.isGreetingRunning).toBe(true)
    expect(stats.isDeliveringRunning).toBe(true)
  })
})
