/**
 * Agent 映射异步任务 SSE hook 回归测试（Phase 4）。
 *
 * 覆盖：
 * - 异步启动：POST /generate 携带 mode=async，拿到 task_id 后订阅 stream 端点
 * - 事件状态机：started/platform_start/retry_wait/platform_done 驱动各平台状态与失败载荷
 * - 终态：complete 触发 onTerminal（仅一次）并关闭 EventSource；cancelled 语义透传
 * - 取消：cancel() POST /generate/cancel 携带 task_id
 * - 回滚兼容：后端返回无 task_id 的同步结果 → start() 以 syncResult 上抛，不开流
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { renderHook, act } from "@testing-library/react"
import { useAgentMapStream } from "./use-agent-map-stream"

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  closed = false
  readyState = 0

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  /** 瞬断（浏览器会自动重连）或永久关闭（readyState=2，如 404） */
  fail(permanent = false) {
    this.readyState = permanent ? 2 : 0
    this.onerror?.(new Event("error"))
  }
}

const API = "http://127.0.0.1:8000"

function mockFetchJson(body: unknown) {
  return vi.fn().mockResolvedValue({ json: () => Promise.resolve(body) })
}

describe("useAgentMapStream", () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal("EventSource", FakeEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("异步启动：不显式传 mode，拿到 task_id 后订阅 stream，并按事件驱动平台状态机", async () => {
    const fetchMock = mockFetchJson({ success: true, mode: "async", task_id: "t-1" })
    vi.stubGlobal("fetch", fetchMock)
    const onTerminal = vi.fn()
    const { result } = renderHook(() => useAgentMapStream(API, onTerminal))

    let outcome: any
    await act(async () => {
      outcome = await result.current.start({ platforms: ["boss", "zhilian"], record_id: "rec1", selected_modules: ["work_experience"] })
    })
    expect(outcome.started).toBe(true)
    // 不显式传 mode：异步/同步由后端熔断开关决定，前端不得绕过 settings.json 回滚
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).mode).toBeUndefined()
    const es = FakeEventSource.instances[0]
    expect(es.url).toBe(`${API}/api/agent-map/generate/stream/t-1`)
    expect(result.current.state.phase).toBe("connecting")
    expect(result.current.state.platforms.boss.status).toBe("pending")

    act(() => es.emit({ type: "started", platforms: ["boss", "zhilian"] }))
    expect(result.current.state.phase).toBe("running")

    act(() => es.emit({ type: "platform_start", platform: "boss" }))
    expect(result.current.state.platforms.boss.status).toBe("running")

    act(() => es.emit({ type: "retry_wait", platform: "boss", seconds: 2.5, attempt: 1 }))
    expect(result.current.state.platforms.boss.status).toBe("retry_wait")
    expect(result.current.state.platforms.boss.retrySeconds).toBe(2.5)

    act(() => es.emit({ type: "heartbeat" }))  // 心跳不驱动状态机
    expect(result.current.state.platforms.boss.status).toBe("retry_wait")

    act(() => es.emit({ type: "platform_done", platform: "boss", success: true, message: "映射完成", warnings: ["⚠️ 已降级为确定性规则映射"], degraded: true }))
    expect(result.current.state.platforms.boss.status).toBe("done")
    expect(result.current.state.platforms.boss.degraded).toBe(true)
    expect(result.current.state.platforms.boss.retrySeconds).toBeUndefined()

    act(() => es.emit({ type: "platform_start", platform: "zhilian" }))
    act(() => es.emit({ type: "platform_done", platform: "zhilian", success: false, message: "速率限制", warnings: [], degraded: false }))
    expect(result.current.state.platforms.zhilian.status).toBe("failed")
    expect(result.current.state.platforms.zhilian.message).toBe("速率限制")

    const reports = { boss: { success: true }, zhilian: { success: false, message: "速率限制" } }
    act(() => es.emit({ type: "complete", success: false, cancelled: false, reports }))
    expect(result.current.state.phase).toBe("complete")
    expect(result.current.isRunning).toBe(false)
    expect(es.closed).toBe(true)
    expect(onTerminal).toHaveBeenCalledTimes(1)
    expect(onTerminal).toHaveBeenCalledWith({ ok: false, cancelled: false, reports })

    // 终态后重复 complete 不重复触发回调
    act(() => es.emit({ type: "complete", success: false, cancelled: false, reports }))
    expect(onTerminal).toHaveBeenCalledTimes(1)
  })

  it("取消：cancel() 携带 task_id POST /generate/cancel；cancelled 终态透传", async () => {
    const fetchMock = mockFetchJson({ success: true, mode: "async", task_id: "t-2" })
    vi.stubGlobal("fetch", fetchMock)
    const onTerminal = vi.fn()
    const { result } = renderHook(() => useAgentMapStream(API, onTerminal))

    await act(async () => {
      await result.current.start({ platforms: ["boss"], record_id: null, selected_modules: [] })
    })
    await act(async () => {
      await result.current.cancel()
    })
    const cancelCall = fetchMock.mock.calls.find((c: any[]) => String(c[0]).includes("/generate/cancel"))
    expect(cancelCall).toBeDefined()
    expect(JSON.parse(cancelCall![1].body)).toEqual({ task_id: "t-2" })

    const es = FakeEventSource.instances[0]
    act(() => es.emit({ type: "cancel_requested", task_id: "t-2" }))
    act(() => es.emit({ type: "complete", success: false, cancelled: true, reports: {} }))
    expect(result.current.state.phase).toBe("cancelled")
    expect(onTerminal).toHaveBeenCalledWith({ ok: false, cancelled: true, reports: {} })
  })

  it("回滚兼容：后端返回同步结果（无 task_id）时以 syncResult 上抛且不开流", async () => {
    const sync = { success: true, reports: { boss: { success: true } } }
    vi.stubGlobal("fetch", mockFetchJson(sync))
    const onTerminal = vi.fn()
    const { result } = renderHook(() => useAgentMapStream(API, onTerminal))

    let outcome: any
    await act(async () => {
      outcome = await result.current.start({ platforms: ["boss"], record_id: null, selected_modules: [] })
    })
    expect(outcome.started).toBe(false)
    expect(outcome.syncResult).toEqual(sync)
    expect(FakeEventSource.instances).toHaveLength(0)
    expect(onTerminal).not.toHaveBeenCalled()
  })

  it("断线：瞬断不改变状态（交给自动重连），永久关闭则判定 error 终态并通知一次", async () => {
    vi.stubGlobal("fetch", mockFetchJson({ success: true, mode: "async", task_id: "t-3" }))
    const onTerminal = vi.fn()
    const { result } = renderHook(() => useAgentMapStream(API, onTerminal))
    await act(async () => {
      await result.current.start({ platforms: ["boss"], record_id: null, selected_modules: [] })
    })
    const es = FakeEventSource.instances[0]
    act(() => es.emit({ type: "started", platforms: ["boss"] }))

    act(() => es.fail(false))  // 瞬断
    expect(result.current.state.phase).toBe("running")
    expect(onTerminal).not.toHaveBeenCalled()

    act(() => es.fail(true))   // 永久关闭（任务过期 404）
    expect(result.current.state.phase).toBe("error")
    expect(onTerminal).toHaveBeenCalledTimes(1)
    expect(onTerminal.mock.calls[0][0].ok).toBe(false)
    expect(es.closed).toBe(true)
  })

  it("网络异常：start() 返回 error 且 phase 置 error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")))
    const { result } = renderHook(() => useAgentMapStream(API, vi.fn()))

    let outcome: any
    await act(async () => {
      outcome = await result.current.start({ platforms: ["boss"], record_id: null, selected_modules: [] })
    })
    expect(outcome.started).toBe(false)
    expect(outcome.error).toContain("ECONNREFUSED")
    expect(result.current.state.phase).toBe("error")
  })
})
