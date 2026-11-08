import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { renderHook, waitFor, act } from "@testing-library/react"
import { useSchedulePanel } from "./use-schedule-panel"

// 定时调度面板 hook 的读取/失败/重试行为（2026-10-29 三态改造回归防护）：
// - 成功：以服务端 is_enabled 为准，不闪默认值
// - config 拉取失败或坏载荷：进入 scheduleLoadFailed（面板显示「读取失败 + 重试」），
//   scheduledEnabled 保持 null（开关/保存置灰），不再永久停在「读取配置中…」
// - retryLoadSchedule 成功后恢复可用

const configPayload = (is_enabled: boolean) => ({
  ok: true,
  json: async () => ({
    status: "success",
    data: {
      cron_time: "08:30",
      is_enabled,
      schedule_start_date: "",
      schedule_end_date: "",
      skip_non_workdays: true,
    },
  }),
})

const holidayPayload = { ok: true, json: async () => ({ status: "success", data: { installed: true } }) }

function stubFetch(configImpl: () => Promise<any>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: any) => {
      const url = String(input)
      if (url.includes("/api/automation/config")) return configImpl()
      if (url.includes("/api/automation/holiday-data-status")) return Promise.resolve(holidayPayload)
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
  )
}

describe("useSchedulePanel 配置读取三态", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("读取成功：以服务端 is_enabled 为准（含时间），不进失败态", async () => {
    stubFetch(() => Promise.resolve(configPayload(true)))
    const { result } = renderHook(() => useSchedulePanel())

    await waitFor(() => expect(result.current.scheduledEnabled).toBe(true))
    expect(result.current.scheduleLoadFailed).toBe(false)
    expect(result.current.dailyTime).toBe("08:30")
  })

  it("config 网络失败：进失败态、开关保持 null；重试成功后恢复", async () => {
    let fail = true
    stubFetch(() => (fail ? Promise.reject(new Error("network down")) : Promise.resolve(configPayload(false))))
    const { result } = renderHook(() => useSchedulePanel())

    await waitFor(() => expect(result.current.scheduleLoadFailed).toBe(true))
    expect(result.current.scheduledEnabled).toBeNull()

    fail = false
    await act(async () => {
      result.current.retryLoadSchedule()
    })
    await waitFor(() => expect(result.current.scheduledEnabled).toBe(false))
    expect(result.current.scheduleLoadFailed).toBe(false)
  })

  it("config 坏载荷（缺 is_enabled）：进失败态而非误判开/关", async () => {
    stubFetch(() => Promise.resolve({ ok: true, json: async () => ({ status: "success", data: {} }) }))
    const { result } = renderHook(() => useSchedulePanel())

    await waitFor(() => expect(result.current.scheduleLoadFailed).toBe(true))
    expect(result.current.scheduledEnabled).toBeNull()
  })

  it("保存入口兜底：scheduledEnabled 为 null 时 handleSaveSchedule 不发请求", async () => {
    stubFetch(() => Promise.reject(new Error("network down")))
    const { result } = renderHook(() => useSchedulePanel())
    await waitFor(() => expect(result.current.scheduleLoadFailed).toBe(true))

    const postSpy = vi.fn()
    vi.stubGlobal(
      "fetch",
      vi.fn((input: any, init?: any) => {
        if (String(input).includes("/api/automation/schedule-config")) {
          postSpy(String(input), init)
          return Promise.resolve({ ok: true, json: async () => ({ status: "success" }) })
        }
        return Promise.reject(new Error("network down"))
      })
    )

    await act(async () => {
      await result.current.handleSaveSchedule()
    })
    expect(postSpy).not.toHaveBeenCalled()
  })
})

describe("useSchedulePanel holiday 请求隔离（R5 P1-1 回归防护）", () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it("holiday 挂起：config 即时落定（不被 holiday 拖到 10s），且 10s 后系统仍无失败误判", async () => {
    vi.useFakeTimers()
    // config 正常返回；holiday fetch 永不 resolve（真实挂起形态）
    vi.stubGlobal(
      "fetch",
      vi.fn((input: any) => {
        const url = String(input)
        if (url.includes("/api/automation/config")) return Promise.resolve(configPayload(false))
        if (url.includes("/api/automation/holiday-data-status")) return new Promise(() => {})
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
    const { result } = renderHook(() => useSchedulePanel())

    // config 与 holiday 独立落定：config 在远小于 10s 的时刻就绪（R6-P2 修正——
    // 旧 Promise.all 实现会把它拖到 holiday 的 10s 边界，此处证伪「被 holiday 阻塞」）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    expect(result.current.scheduledEnabled).toBe(false)
    expect(result.current.scheduleLoadFailed).toBe(false)

    // 推进跨过 10s：holiday 超时自行降级，config 结果保持，无误判无回归
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_500)
    })
    expect(result.current.scheduledEnabled).toBe(false)
    expect(result.current.scheduleLoadFailed).toBe(false)
  })

  it("保存请求体整包断言：POST /schedule-config 必含五字段（R5 P1-2 前端行为锁定）", async () => {
    const postBodies: any[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn((input: any, init?: any) => {
        const url = String(input)
        if (url.includes("/api/automation/schedule-config")) {
          postBodies.push(JSON.parse(init.body))
          return Promise.resolve({ ok: true, json: async () => ({ status: "success", message: "ok" }) })
        }
        if (url.includes("/api/automation/config")) return Promise.resolve(configPayload(true))
        if (url.includes("/api/automation/holiday-data-status")) return Promise.resolve(holidayPayload)
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
    const { result } = renderHook(() => useSchedulePanel())
    await waitFor(() => expect(result.current.scheduledEnabled).toBe(true))

    act(() => {
      result.current.setStartDate("2026-11-01")
    })
    await act(async () => {
      await result.current.handleSaveSchedule()
    })
    expect(postBodies).toHaveLength(1)
    expect(postBodies[0]).toEqual({
      cron_time: "08:30",
      is_enabled: true,
      schedule_start_date: "2026-11-01",
      schedule_end_date: "",
      skip_non_workdays: true,
    })
  })
})
