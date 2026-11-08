/**
 * 阻塞任务全局出口单测（外审 R4-P1-1/P1-2 修复配套）。
 * 断言走可观测 store 状态（zustand 每次 set 浅拷贝 state，spy 会被 spread 带入
 * 后续状态对象造成跨用例泄漏，故不 spy action）：
 * - resumeBlockedTask：刷新恢复场景（pipelineTaskId=null）走 startPipeline 补建链路
 *   （整板重建：blockedDetail 被清空、pipelineTaskId 补上）；同 id 场景走 resumePipeline
 *   只切状态保现场（blockedDetail 保留）
 * - terminateBlockedTask：先清后端阻塞登记（clear-blocked），再复位本地 store
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { usePipelineStore } from "./pipeline-store"
import { resumeBlockedTask, terminateBlockedTask } from "./blocked-task-actions"

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const TASK_ID = "task-blocked-1"

function seedBlocked(pipelineTaskId: string | null = null) {
  usePipelineStore.setState({
    status: "blocked",
    blockedDetail: {
      blocked: true,
      task_id: TASK_ID,
      kind: "quota",
      message: "额度不足",
    },
    pipelineTaskId,
  })
}

function resetStore() {
  usePipelineStore.getState().reset()
}

function mockFetchOk() {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ task_id: TASK_ID }), { status: 200 },
  )))
}

describe("resumeBlockedTask（继续阻塞任务）", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    resetStore()
    seedBlocked()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    resetStore()
  })

  it("刷新恢复场景：pipelineTaskId=null 时走 startPipeline 补建链路（整板重建）", async () => {
    mockFetchOk()

    const ok = await resumeBlockedTask()

    expect(ok).toBe(true)
    const st = usePipelineStore.getState()
    // startPipeline 语义：emptyState 整板重建 + 按 task_id 补建链路标识
    expect(st.pipelineTaskId).toBe(TASK_ID)
    expect(st.status).toBe("running")
    expect(st.blockedDetail).toBeNull()
  })

  it("同任务进行中场景：pipelineTaskId 一致时仅 resumePipeline（保留现场不清板）", async () => {
    seedBlocked(TASK_ID)
    mockFetchOk()

    const ok = await resumeBlockedTask()

    expect(ok).toBe(true)
    const st = usePipelineStore.getState()
    // resumePipeline 语义：只切 running，blockedDetail/现场保留
    expect(st.status).toBe("running")
    expect(st.pipelineTaskId).toBe(TASK_ID)
    expect(st.blockedDetail?.task_id).toBe(TASK_ID)
  })

  it("后端拒绝（无 task_id）时返回 false 且不动链路状态", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "无可继续任务" }), { status: 409 },
    )))

    const ok = await resumeBlockedTask()

    expect(ok).toBe(false)
    const st = usePipelineStore.getState()
    expect(st.status).toBe("blocked")
    expect(st.blockedDetail?.task_id).toBe(TASK_ID)
    expect(st.pipelineTaskId).toBeNull()
  })
})

describe("terminateBlockedTask（终止阻塞任务）", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    resetStore()
    seedBlocked()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    resetStore()
  })

  it("先 fire-and-forget 清后端阻塞登记，再复位本地 store（防刷新后横幅复活）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)

    terminateBlockedTask()

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/automation/clear-blocked"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ task_id: TASK_ID }),
      }),
    )
    expect(usePipelineStore.getState().blockedDetail).toBeNull()
    expect(usePipelineStore.getState().status).not.toBe("blocked")
  })

  it("无 task_id 时跳过后端请求、仅本地复位", () => {
    usePipelineStore.setState({ blockedDetail: { blocked: true, kind: "quota", message: "x" } })
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    terminateBlockedTask()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(usePipelineStore.getState().blockedDetail).toBeNull()
  })
})
