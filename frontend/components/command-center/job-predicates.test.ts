import { describe, it, expect } from "vitest"
import type { PipelineJob } from "@/store/pipeline-store"
import {
  isJobDelivered,
  isJobRejected,
  isJobReadyToDeliver,
  isJobWaitingReview,
  isJobFailed,
  isJobEvaluating,
} from "./job-predicates"

/**
 * 指挥中心看板谓词全矩阵回归（质检计划第 3.1 层）：
 * 口径基准 docs/全链路指挥中心-真实链路图.md「Tab 判定速查」+ 后端 snapshot_service 状态词汇表。
 * 任何后端新增状态（如 rejected_auto / clean_rule_rejected）必须同步进本矩阵，
 * 杜绝「后端分诊已淘汰、前端看板无 Tab 归属」的契约 drift 再次发生。
 */
const job = (overrides: Partial<PipelineJob> = {}): PipelineJob =>
  ({
    job_id: "rec_test",
    job_name: "测试岗位",
    company_name: "测试公司",
    status: "running",
    ...overrides,
  }) as PipelineJob

type Predicates = ReturnType<typeof predicateSnapshot>
function predicateSnapshot(j: PipelineJob) {
  return {
    rejected: isJobRejected(j),
    delivered: isJobDelivered(j),
    ready: isJobReadyToDeliver(j),
    waiting: isJobWaitingReview(j),
    failed: isJobFailed(j),
    evaluating: isJobEvaluating(j),
  }
}

// 期望位序：rejected / delivered / ready / waiting / failed / evaluating
const CASES: Array<[string, Partial<PipelineJob>, [boolean, boolean, boolean, boolean, boolean, boolean]]> = [
  // ---- 淘汰 Tab：清洗淘汰 / ai清洗淘汰 / node=clean_rejected / E-F 初评淘汰 rejected_auto ----
  ["硬规则清洗淘汰(status)", { status: "rejected" }, [true, false, false, false, false, false]],
  ["硬规则清洗淘汰(中文门牌)", { status: "清洗淘汰" }, [true, false, false, false, false, false]],
  ["AI 清洗淘汰(无空格)", { status: "ai清洗淘汰" }, [true, false, false, false, false, false]],
  ["AI 清洗淘汰(带空格)", { status: "ai 清洗淘汰" }, [true, false, false, false, false, false]],
  ["清洗淘汰(node 判定)", { status: "running", node: "clean_rejected" }, [true, false, false, false, false, false]],
  ["E/F 初评自动淘汰(status)", { status: "rejected_auto" }, [true, false, false, false, false, false]],
  ["E/F 初评自动淘汰(node 判定)", { status: "running", node: "clean_rule_rejected" }, [true, false, false, false, false, false]],

  // ---- 待老板审批 Tab：waiting / node=manual_review_node ----
  ["待审批(waiting)", { status: "waiting" }, [false, false, false, true, false, false]],
  ["待审批(node=manual_review_node)", { status: "done", node: "manual_review_node" }, [false, false, false, true, false, false]],

  // ---- 待投递 Tab：approved / ready_to_deliver / 门牌待投递 ----
  ["待投递(ready_to_deliver)", { status: "ready_to_deliver" }, [false, false, true, false, false, false]],
  ["待投递(approved)", { status: "approved" }, [false, false, true, false, false, false]],
  ["待投递(中文门牌)", { status: "待投递" }, [false, false, true, false, false, false]],
  ["待投递(node=ready_to_deliver)", { status: "done", node: "ready_to_deliver" }, [false, false, true, false, false, false]],
  ["待投递(node=approved_waiting_delivery)", { status: "done", node: "approved_waiting_delivery" }, [false, false, true, false, false, false]],

  // ---- 已投递 Tab ----
  ["已投递(delivered)", { status: "delivered" }, [false, true, false, false, false, false]],
  ["已投递(中文门牌)", { status: "已投递" }, [false, true, false, false, false, false]],

  // ---- 执行失败 Tab：error/failed/执行失败/投递失败 + node=error + failure_info 残留 ----
  ["执行失败(error)", { status: "error" }, [false, false, false, false, true, false]],
  ["执行失败(failed)", { status: "failed" }, [false, false, false, false, true, false]],
  ["执行失败(执行失败)", { status: "执行失败" }, [false, false, false, false, true, false]],
  ["投递失败(20bd3bc 门牌闭环)", { status: "投递失败" }, [false, false, false, false, true, false]],
  ["执行失败(node=error)", { status: "done", node: "error" }, [false, false, false, false, true, false]],
  ["失败后复活：waiting 时 failure_info 残留不算失败", { status: "waiting", failure_info: { reason: "旧账" } as never }, [false, false, false, true, false, false]],
  ["失败后复活：ready_to_deliver 时 failure_info 残留不算失败", { status: "ready_to_deliver", failure_info: { reason: "旧账" } as never }, [false, false, true, false, false, false]],

  // ---- 评估/改写/投递中 Tab：其余 status=running ----
  ["评估中(running)", { status: "running" }, [false, false, false, false, false, true]],
  ["改写中(node=rewrite_node)", { status: "running", node: "rewrite_node" }, [false, false, false, false, false, true]],
  ["投递执行中(sub_status=delivering)", { status: "running", sub_status: "delivering", node: "delivery_node" }, [false, false, false, false, false, true]],

  // ---- 全部岗位 Tab 专属（不进任何专项 Tab）：done / rejected_manual ----
  ["初评完成(done 卡，仅全部 Tab)", { status: "done" }, [false, false, false, false, false, false]],
  ["老板已拒绝(rejected_manual，仅全部 Tab)", { status: "rejected_manual" }, [false, false, false, false, false, false]],
]

describe("指挥中心看板谓词全矩阵（Tab 判定速查表对齐）", () => {
  for (const [name, overrides, expected] of CASES) {
    it(name, () => {
      const result = predicateSnapshot(job(overrides))
      const actual: Predicates = result
      expect(Object.values(actual)).toEqual(expected)
    })
  }
})

describe("谓词互斥与优先级守卫", () => {
  it("已投递优先于一切：delivered + failure_info 仍是已投递", () => {
    const j = job({ status: "delivered", failure_info: { reason: "旧账" } as never })
    expect(isJobDelivered(j)).toBe(true)
    expect(isJobFailed(j)).toBe(false)
  })

  it("running 是最低优先级：任何专项状态命中后不再算评估中", () => {
    for (const status of ["rejected_auto", "rejected_manual", "done", "waiting", "ready_to_deliver", "delivered", "error"]) {
      expect(isJobEvaluating(job({ status }))).toBe(false)
    }
  })

  it("后端 snapshot_service 状态词汇全覆盖：无「无 Tab 归属」的未知终态", () => {
    // snapshot_service 实际产出的全部 status 词汇（node/sub_status 变体已在 CASES 矩阵覆盖）
    const backendVocabulary = [
      "rejected", "rejected_auto", "rejected_manual",
      "waiting", "ready_to_deliver", "approved", "delivered", "done",
      "error", "failed", "running",
    ]
    for (const status of backendVocabulary) {
      const j = job({ status })
      const claimed =
        isJobRejected(j) || isJobDelivered(j) || isJobReadyToDeliver(j) ||
        isJobWaitingReview(j) || isJobFailed(j) || isJobEvaluating(j) ||
        status === "done" || status === "rejected_manual" // 文档口径：done/rejected_manual 仅全部 Tab
      expect(claimed).toBe(true)
    }
  })
})
