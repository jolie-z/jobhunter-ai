/**
 * 全局任务流 hook 回归测试（2026-09-12 质检修复批次）。
 *
 * 覆盖：
 * - B-2：并发派发第二个批量任务时，第一个任务的 SSE 流不被掐断（多流并存）
 * - B-1：SSE 断线且后端仍在运行 → 指数退避重连，而不是放弃导致 UI 永久卡「运行中」
 * - P3：重连成功后退避计数重置——长任务多次偶发断线不误判为中断
 * - B-2：单任务流终态 scoped 收尾——只清本批岗位，不误清其它在跑任务；全局状态保持 running
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useGlobalTaskStream } from "@/hooks/use-global-task-stream"

const { toastMock } = vi.hoisted(() => ({ toastMock: vi.fn() }))

vi.mock("@/hooks/use-toast", () => ({
  // 稳定的 toast 引用：避免每次渲染产生新回调导致 attachTaskSse 身份变化、effect 反复重跑
  useToast: () => ({ toast: toastMock }),
}))

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  onopen: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(_type: string, _listener: (e: unknown) => void) {
    // hook 会订阅具名 "end" 事件；桩测试通过 onmessage 的终态消息覆盖该路径
  }

  close() {
    this.closed = true
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  fail() {
    this.onerror?.(new Event("error"))
  }
}

function last(urlPart: string) {
  return FakeEventSource.instances.filter((e) => e.url.includes(urlPart)).slice(-1)[0]
}

describe("useGlobalTaskStream 质检修复回归", () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    toastMock.mockClear()
    vi.useFakeTimers()
    vi.stubGlobal("EventSource", FakeEventSource)
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (String(url).includes("/api/tasks/status")) {
          // 无参探活（mount）：无任务；带 task_id 探活：后端仍在运行
          const withTask = String(url).includes("task_id=")
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve(
                withTask
                  ? { is_processing: true, current_task_id: "t1", task: { status: "running", job_ids: ["rec1"], task_type: "evaluate" } }
                  : { is_processing: false, current_task_id: null }
              ),
          })
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
      })
    )
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  // 冲掉探活 fetch 的 promise 链（当前链深 fetch→json→setState 约 3~4 跳；
  // 源码若再加 .then 跳数，需同步加大 n——跳数不足的表现是 act 警告回归）
  const drain = (n = 4) =>
    act(async () => {
      for (let i = 0; i < n; i++) await Promise.resolve()
    })

  function setup() {
    const fetchJobs = vi.fn()
    const setSelectedJob = vi.fn()
    const setJobs = vi.fn()
    const setTrashBinCount = vi.fn()
    const hook = renderHook(() =>
      useGlobalTaskStream({ fetchJobs, setSelectedJob, setJobs, setTrashBinCount })
    )
    return { hook, fetchJobs }
  }

  const startTask = (taskId: string, jobIds: string[], taskType = "evaluate") => {
    act(() => {
      window.dispatchEvent(
        new CustomEvent("START_GLOBAL_TASK", {
          detail: { taskId, jobIds, taskType, title: "测试任务" },
        })
      )
    })
  }

  it("B-2: 并发派发第二个批量任务不掐断第一个任务的 SSE 流", () => {
    const { hook } = setup()
    startTask("t1", ["智联招聘-rec1"])
    startTask("t2", ["智联招聘-rec2"], "approve")

    expect(FakeEventSource.instances.filter((e) => e.url.includes("task_id=t1"))).toHaveLength(1)
    expect(FakeEventSource.instances.filter((e) => e.url.includes("task_id=t2"))).toHaveLength(1)
    // t1 的连接保持打开（旧行为是 close 掉）
    expect(last("task_id=t1").closed).toBe(false)
    // 两个任务的岗位都在转圈
    expect(hook.result.current.processingJobs["智联招聘-rec1"]).toBe("evaluate")
    expect(hook.result.current.processingJobs["智联招聘-rec2"]).toBe("approve")
  })

  it("B-1: SSE 断线且后端仍在运行时按退避策略重连", async () => {
    setup()
    startTask("t1", ["智联招聘-rec1"])
    expect(FakeEventSource.instances).toHaveLength(1)

    // 连接断开（后端探活返回 is_processing=true）
    await act(async () => {
      last("task_id=t1").fail()
      await drain()
    })

    // 未立即重连，也未标记中断
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    // 2s 退避到期后重连（重连后的探活 fetch promise 链须在同一 act 内冲刷，
    // 否则 setState 落在 act 外触发警告）
    await act(async () => {
      vi.advanceTimersByTime(2000)
      await drain()
    })
    expect(FakeEventSource.instances.filter((e) => e.url.includes("task_id=t1"))).toHaveLength(2)
  })

  it("P3: 重连成功后退避计数重置，长任务多次偶发断线不误判中断", async () => {
    const { hook } = setup()
    startTask("t1", ["智联招聘-rec1"])

    // 连续 6 轮「断线 → 探活仍在跑 → 2s 后重连成功(onopen)」：
    // 每次连接建立即重置计数，退避间隔恒为 2s，永不触发中断判定
    for (let i = 0; i < 6; i++) {
      await act(async () => {
        last("task_id=t1").fail()
        await drain()
      })
      await act(async () => {
        vi.advanceTimersByTime(2000)
        await drain()
      })
      await act(async () => {
        last("task_id=t1").onopen?.()
        await drain(2)
      })
    }

    expect(FakeEventSource.instances.filter((e) => e.url.includes("task_id=t1"))).toHaveLength(7)
    expect(toastMock).not.toHaveBeenCalled()
    expect(hook.result.current.globalTaskStatus).toBe("running")
  })

  it("B-2: 单任务终态 scoped 收尾，不误清其它在跑任务", async () => {
    const { hook, fetchJobs } = setup()
    startTask("t1", ["智联招聘-rec1"])
    startTask("t2", ["智联招聘-rec2"], "approve")
    const before = fetchJobs.mock.calls.length

    // t1 流收到终态消息
    await act(async () => {
      last("task_id=t1").emit({ type: "end", message: "done" })
    })

    // t1 的岗位转圈被清理，t2 的保留；t2 仍在跑 → 全局状态保持 running
    expect(hook.result.current.processingJobs["智联招聘-rec1"]).toBeUndefined()
    expect(hook.result.current.processingJobs["智联招聘-rec2"]).toBe("approve")
    expect(hook.result.current.globalTaskStatus).toBe("running")
    // scoped 收尾触发静默刷新
    expect(fetchJobs.mock.calls.length).toBeGreaterThan(before)
  })

  it("B-2: 最后一个任务完结后全局状态转为 completed", async () => {
    const { hook } = setup()
    startTask("t1", ["智联招聘-rec1"])

    await act(async () => {
      last("task_id=t1").emit({ type: "complete", message: "全部完成" })
    })

    expect(hook.result.current.processingJobs["智联招聘-rec1"]).toBeUndefined()
    expect(hook.result.current.globalTaskStatus).toBe("completed")
  })

  it("Q23: 日志洪峰批量缓冲——同一 200ms 窗口内多条消息合并为一次渲染", async () => {
    const { hook } = setup()
    startTask("t1", ["智联招聘-rec1"])

    const es = last("task_id=t1")
    // 模拟重连回放洪峰：20 条进度消息连发
    act(() => {
      for (let i = 0; i < 20; i++) {
        es.emit({ type: "progress", job_id: "rec1", message: `步骤${i}` })
      }
    })
    // 缓冲期（<200ms）内不产生任何 store 更新
    expect(hook.result.current.jobLiveLogs["智联招聘-rec1"]).toBeUndefined()

    // 200ms flush 后一次性合并（React 18 同步块内自动批渲染）
    await act(async () => {
      vi.advanceTimersByTime(210)
    })
    const logs = hook.result.current.jobLiveLogs["智联招聘-rec1"] ?? []
    expect(logs.length).toBe(3) // jobLiveLogs 只保留最近 3 条
    expect(logs[2]).toContain("步骤19")
  })
})
