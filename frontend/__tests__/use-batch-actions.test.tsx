/**
 * 批量操作 hook 回归测试（2026-09-12 质检修复批次）。
 *
 * 覆盖：
 * - B-10：isProcessingRef 同步守卫，派发进行中重复点击为 no-op
 * - B-6：幽灵选中 id（列表中已不存在的岗位）派发前被剔除
 * - B-7：负向终态/进行中岗位（已拒绝/面试等）海投前必须二次确认，取消则终止
 * - B-11：海投打招呼语配置预检网络失败 → fail-closed 终止派发
 * - B-4：单岗审批失败后回滚乐观更新（静默硬刷新）
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import { renderHook, act, waitFor } from "@testing-library/react"
import { useBatchActions, type UseBatchActionsOptions } from "@/hooks/use-batch-actions"
import type { JobData } from "@/types/job"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const baseJobs = [
  {
    id: "智联招聘-rec1",
    platform: "智联招聘",
    followStatus: "新线索",
    companyName: "A公司",
    jobTitle: "岗位一",
  },
  {
    id: "BOSS直聘-rec2",
    platform: "BOSS直聘",
    followStatus: "简历人工复核",
    companyName: "B公司",
    jobTitle: "岗位二",
    grade: "A",
  },
  {
    id: "猎聘-rec3",
    platform: "猎聘",
    followStatus: "已拒绝",
    companyName: "C公司",
    jobTitle: "岗位三",
  },
] as unknown as JobData[]

type HookProps = Omit<UseBatchActionsOptions, "setSelectedJobIds"> & {
  selectedJobIds: string[]
}

function renderBatchActions(props: Pick<HookProps, "jobs"> & Partial<HookProps>) {
  let currentSelected: string[] = props.selectedJobIds ?? []
  const setSelectedJobIds = vi.fn((updater: any) => {
    const next = typeof updater === "function" ? updater(currentSelected) : updater
    currentSelected = next
  })

  const buildProps = (): HookProps =>
    ({
      jobs: props.jobs,
      selectedJobIds: currentSelected,
      onRefreshJobs: props.onRefreshJobs,
      onBatchDelete: props.onBatchDelete,
      processingJobs: props.processingJobs,
    }) as HookProps

  const hook = renderHook((p: HookProps) => useBatchActions({ ...p, setSelectedJobIds }), {
    initialProps: buildProps(),
  })

  const syncRerender = () => hook.rerender(buildProps())

  return { hook, setSelectedJobIds, getSelected: () => currentSelected, syncRerender }
}

function okFetch(body: unknown = {}) {
  return vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) })
}

describe("useBatchActions 质检修复回归", () => {
  beforeEach(() => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    vi.spyOn(window, "alert").mockImplementation(() => {})
  })

  it("B-6: 派发前剔除幽灵选中 id", async () => {
    const fetchMock = okFetch({ task_id: "t1" })
    vi.stubGlobal("fetch", fetchMock)

    const { hook, getSelected } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["智联招聘-rec1", "幽灵平台-recGhost"],
    })

    await act(async () => {
      hook.result.current.handleBatchEvaluate()
    })

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))
      expect(call).toBeTruthy()
    })
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))![1].body)
    expect(payload.job_ids).toEqual(["智联招聘-rec1"])
    expect(getSelected()).toEqual([])
  })

  it("B-10: 派发进行中重复触发为 no-op（ref 同步守卫）", async () => {
    let releaseFetch!: (v: unknown) => void
    const gate = new Promise((resolve) => (releaseFetch = resolve))
    const fetchMock = vi.fn().mockImplementation(() => gate.then(() => ({ ok: true, json: () => Promise.resolve({ task_id: "t1" }) })))
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["智联招聘-rec1"],
    })

    let first!: Promise<void>
    act(() => {
      first = hook.result.current.handleBatchEvaluate()
    })
    // 第一次点击已进入 fetch 等待（isProcessingRef=true），第二次点击应被同步拒绝
    await act(async () => {
      await hook.result.current.handleBatchEvaluate()
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    releaseFetch({ ok: true, json: () => Promise.resolve({ task_id: "t1" }) })
    await act(async () => {
      await first
    })
  })

  it("B-7: 海投命中负向状态岗位时取消确认则不派发", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    const confirmSpy = window.confirm as ReturnType<typeof vi.spyOn>
    confirmSpy.mockReturnValue(false)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["猎聘-rec3"],
    })

    await act(async () => {
      await hook.result.current.handleBatchMassApply()
    })

    expect(confirmSpy).toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("B-7: 确认后继续走配置预检与派发", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/automation/config")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { mass_apply_greeting: "您好" } }) })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ task_id: "t2" }) })
    })
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["猎聘-rec3"],
    })

    await act(async () => {
      await hook.result.current.handleBatchMassApply()
    })

    const dispatchCall = fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))
    expect(dispatchCall).toBeTruthy()
    const payload = JSON.parse(dispatchCall![1].body)
    expect(payload.task_type).toBe("mass_apply")
    expect(payload.job_ids).toEqual(["猎聘-rec3"])
  })

  it("B-11: 海投配置预检网络失败时 fail-closed 终止", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("backend down"))
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["智联招聘-rec1"],
    })

    await act(async () => {
      await hook.result.current.handleBatchMassApply()
    })
    // 冲掉 fail-closed catch 链上滞后的 setState，避免 act 警告
    await act(async () => {})

    expect(fetchMock).toHaveBeenCalledTimes(1) // 只有一次 config 探测，无 batch-process 派发
    expect(window.alert).toHaveBeenCalled()
  })

  it("B-4: 单岗审批失败后回滚乐观更新（静默硬刷新）", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: "飞书写入失败" }),
    })
    vi.stubGlobal("fetch", fetchMock)
    const onRefreshJobs = vi.fn()

    const events: string[] = []
    const capture = (e: Event) => events.push((e as CustomEvent).type)
    window.addEventListener("OPTIMISTIC_JOB_UPDATE", capture)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: [],
      onRefreshJobs,
    })

    await act(async () => {
      await hook.result.current.dispatchResumeTask("approve", ["智联招聘-rec1"])
    })

    window.removeEventListener("OPTIMISTIC_JOB_UPDATE", capture)
    expect(events).toContain("OPTIMISTIC_JOB_UPDATE") // 乐观更新已派发
    expect(onRefreshJobs).toHaveBeenCalledWith(true, true) // 失败后静默硬刷新回滚
  })
})

describe("重复发起 AI 任务二次确认门禁", () => {
  beforeEach(() => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    vi.spyOn(window, "alert").mockImplementation(() => {})
  })

  it("初评命中已有评级岗位：挂起派发弹门禁，确认后继续原批量", async () => {
    const fetchMock = okFetch({ task_id: "t1" })
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["BOSS直聘-rec2"], // grade="A"，已有初评产物
    })

    await act(async () => {
      await hook.result.current.handleBatchEvaluate()
    })

    // 未派发，门禁弹窗打开且命中岗位正确
    expect(fetchMock).not.toHaveBeenCalled()
    expect(hook.result.current.rerunGateOpen).toBe(true)
    expect(hook.result.current.rerunGateKind).toBe("evaluate")
    expect(hook.result.current.rerunGateJobs.map((j: JobData) => j.id)).toEqual(["BOSS直聘-rec2"])

    // 取消 → 不派发，选中集保留
    act(() => {
      hook.result.current.cancelRerunDispatch()
    })
    expect(hook.result.current.rerunGateOpen).toBe(false)

    // 再次发起 → 确认 → 继续原批量派发
    await act(async () => {
      await hook.result.current.handleBatchEvaluate()
    })
    act(() => {
      hook.result.current.confirmRerunDispatch()
    })
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))
      expect(call).toBeTruthy()
    })
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))![1].body)
    expect(payload.task_type).toBe("evaluate")
    expect(payload.job_ids).toEqual(["BOSS直聘-rec2"])
  })

  it("深评字段属列表裁剪大文本：回源 check-ai-artifacts 补查命中则弹门禁", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("check-ai-artifacts")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "success", data: { rec2: { has_deep_eval: true, has_rewrite: false, has_greeting: false } } }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ task_id: "t9" }) })
    })
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["BOSS直聘-rec2"], // 已过初评（grade=A），列表数据无深评字段
    })

    await act(async () => {
      await hook.result.current.handleBatchDeepEvaluate()
    })

    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("check-ai-artifacts"))).toBe(true)
    expect(hook.result.current.rerunGateOpen).toBe(true)
    expect(hook.result.current.rerunGateKind).toBe("deep_evaluate")
    // 确认前不派发 batch-process
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("batch-process"))).toBe(false)

    act(() => {
      hook.result.current.confirmRerunDispatch()
    })
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))
      expect(call).toBeTruthy()
    })
  })

  it("深评补查无产物：不弹门禁直接派发", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("check-ai-artifacts")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "success", data: { rec2: { has_deep_eval: false, has_rewrite: false, has_greeting: false } } }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ task_id: "t10" }) })
    })
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["BOSS直聘-rec2"],
    })

    await act(async () => {
      await hook.result.current.handleBatchDeepEvaluate()
    })

    expect(hook.result.current.rerunGateOpen).toBe(false)
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))
      expect(call).toBeTruthy()
    })
  })

  it("补查端点失败（软门禁）：退化为本地判断直接派发", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("check-ai-artifacts")) {
        return Promise.resolve({ ok: false, json: () => Promise.resolve({ detail: "boom" }) })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ task_id: "t11" }) })
    })
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["BOSS直聘-rec2"], // 已过初评，改写门禁（B4/B6）放行
    })

    await act(async () => {
      await hook.result.current.handleBatchRewrite()
    })

    expect(hook.result.current.rerunGateOpen).toBe(false)
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))
      expect(call).toBeTruthy()
    })
    const payload = JSON.parse(fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))![1].body)
    expect(payload.task_type).toBe("rewrite")
  })

  it("海投/批准投递不经过重复产物门禁", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/api/automation/config")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { mass_apply_greeting: "您好" } }) })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ task_id: "t12" }) })
    })
    vi.stubGlobal("fetch", fetchMock)

    const { hook } = renderBatchActions({
      jobs: baseJobs,
      selectedJobIds: ["BOSS直聘-rec2"], // 已有初评产物，但海投不应触发门禁
    })

    await act(async () => {
      await hook.result.current.handleBatchMassApply()
    })

    expect(hook.result.current.rerunGateOpen).toBe(false)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("check-ai-artifacts"))).toBe(false)
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("batch-process"))
      expect(call).toBeTruthy()
    })
  })
})
