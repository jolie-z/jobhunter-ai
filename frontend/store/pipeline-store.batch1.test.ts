/**
 * 第一批修复（2026-11-02 审计 P1-8/P1-9）前端单测：
 * - mergeJobsSnapshot 任务一致性双保险守卫（在途旧响应不清板/不劫持）
 * - SSE end 帧 reason 分诊（aborted/task_expired/no_resume 不再谎报「任务完成」）
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { usePipelineStore } from "./pipeline-store"

const JOB_A = {
  job_id: "boss-jobA",
  status: "waiting",
  node: "manual_review_node",
  company_name: "公司A",
  job_name: "岗位A",
}

function resetStore() {
  usePipelineStore.getState().reset()
}

describe("mergeJobsSnapshot 任务一致性守卫（P1-8）", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    resetStore()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("startPipeline 短窗内：旧任务在途响应整体跳过（不清板、不劫持 pipelineTaskId）", () => {
    const st = usePipelineStore.getState()
    st.startPipeline("pipeline_A")
    // 在 pipeline_A 名下落一个岗位
    usePipelineStore.getState().mergeJobsSnapshot([JOB_A], "pipeline_A", undefined)
    expect(usePipelineStore.getState().jobs["boss-jobA"]).toBeTruthy()

    // 旧任务 pipeline_OLD 的在途快照此刻才落地（持最新请求序号的场景由组件层序号挡，
    // 这里验证第二层：载荷任务与本地链路不一致 + running + 短窗内 → 整体跳过）
    usePipelineStore.getState().mergeJobsSnapshot(
      [{ ...JOB_A, job_id: "boss-jobOLD" }],
      "pipeline_OLD",
      undefined,
    )

    const after = usePipelineStore.getState()
    expect(after.pipelineTaskId).toBe("pipeline_A")
    expect(after.jobs["boss-jobA"]).toBeTruthy()
    expect(after.jobs["boss-jobOLD"]).toBeUndefined()
  })

  it("短窗过期后恢复接管分支：服务端当前任务与本地不一致时正常切换并清板", () => {
    const realNow = Date.now()
    const nowSpy = vi.spyOn(Date, "now")

    nowSpy.mockReturnValue(realNow)
    const st = usePipelineStore.getState()
    st.startPipeline("pipeline_A")
    usePipelineStore.getState().mergeJobsSnapshot([JOB_A], "pipeline_A", undefined)

    // 窗口过期（>30s）：同一份「不一致 task_id」载荷现在应触发接管
    nowSpy.mockReturnValue(realNow + 31_000)
    usePipelineStore.getState().mergeJobsSnapshot(
      [{ ...JOB_A, job_id: "boss-jobB" }],
      "pipeline_B",
      undefined,
    )

    const after = usePipelineStore.getState()
    expect(after.pipelineTaskId).toBe("pipeline_B")
    expect(after.jobs["boss-jobB"]).toBeTruthy()
    expect(after.jobs["boss-jobA"]).toBeUndefined()
  })
})

describe("SSE end 帧 reason 分诊（P1-9）", () => {
  beforeEach(() => {
    resetStore()
    usePipelineStore.getState().startPipeline("pipeline_X")
  })

  it("aborted → 中性就绪态（非「任务完成」），日志含终止说明", () => {
    usePipelineStore.getState().handleEvent({ type: "end", reason: "aborted", message: "用户手动终止" })
    const s = usePipelineStore.getState()
    expect(s.status).toBe("idle")
    expect(s.logs.some((l) => l.includes("终止"))).toBe(true)
  })

  it("task_expired → 异常态，日志提示后端可能已重启", () => {
    usePipelineStore.getState().handleEvent({ type: "end", reason: "task_expired" })
    const s = usePipelineStore.getState()
    expect(s.status).toBe("error")
    expect(s.logs.some((l) => l.includes("后端可能已重启"))).toBe(true)
  })

  it("no_resume → 异常态而非「任务完成」", () => {
    usePipelineStore.getState().handleEvent({ type: "end", reason: "no_resume", message: "未找到启用状态的基础简历" })
    const s = usePipelineStore.getState()
    expect(s.status).toBe("error")
    expect(s.logs.some((l) => l.includes("启用") || l.includes("no_resume"))).toBe(true)
  })

  it("正常收口（无 reason 无 error）维持 done；带 error 维持 error", () => {
    usePipelineStore.getState().handleEvent({ type: "end", summary: { outcome: "ok" } })
    expect(usePipelineStore.getState().status).toBe("done")

    resetStore()
    usePipelineStore.getState().startPipeline("pipeline_Y")
    usePipelineStore.getState().handleEvent({ type: "end", summary: { error: "链路异常" } })
    expect(usePipelineStore.getState().status).toBe("error")
  })

  it("summary.outcome=blocked 阻塞收口不受 reason 分诊影响", () => {
    usePipelineStore.getState().handleEvent({
      type: "end",
      reason: "blocked",
      summary: { outcome: "blocked", blocked: { kind: "rate_limited", message: "LLM 限流" } },
    })
    const s = usePipelineStore.getState()
    expect(s.status).toBe("blocked")
  })
})
