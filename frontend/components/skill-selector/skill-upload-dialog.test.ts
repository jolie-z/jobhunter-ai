import { describe, it, expect, vi } from "vitest"
import { sendWithOverrideConfirm } from "./skill-upload-dialog"

// 覆盖确认重发流程三态（agy-review P1：前端唯一行为变更必须有自动化覆盖）
// ① 409 + 用户取消 → 返回 null 且绝不发第二次（不带 force）请求
// ② 409 + 用户确认 → 带 force=true 重发并返回第二次响应
// ③ 非 409 → 单次透传，不弹确认

function jsonResponse(status: number, body?: Record<string, unknown>): Response {
  return {
    status,
    ok: status < 400,
    json: async () => body ?? {},
  } as Response
}

describe("sendWithOverrideConfirm 覆盖确认三态", () => {
  it("409 且用户取消：返回 null，不发 force 请求", async () => {
    const doSend = vi.fn().mockResolvedValueOnce(jsonResponse(409, { detail: "已存在内容完全相同的技能" }))
    const confirmFn = vi.fn().mockReturnValue(false)

    const result = await sendWithOverrideConfirm(doSend, confirmFn)

    expect(result).toBeNull()
    expect(confirmFn).toHaveBeenCalledWith("已存在内容完全相同的技能")
    expect(doSend).toHaveBeenCalledTimes(1)
    expect(doSend).toHaveBeenCalledWith(false)
  })

  it("409 且用户确认：带 force=true 重发并返回第二次响应", async () => {
    const okResponse = jsonResponse(200, { success: true })
    const doSend = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(409, { detail: "已存在同名/同源技能，但内容不同——替换将永久覆盖旧版本。是否继续？" }))
      .mockResolvedValueOnce(okResponse)
    const confirmFn = vi.fn().mockReturnValue(true)

    const result = await sendWithOverrideConfirm(doSend, confirmFn)

    expect(result).toBe(okResponse)
    expect(doSend).toHaveBeenCalledTimes(2)
    expect(doSend).toHaveBeenNthCalledWith(1, false)
    expect(doSend).toHaveBeenNthCalledWith(2, true)
  })

  it("非 409（如 200/400）：单次透传，不弹确认", async () => {
    for (const status of [200, 400]) {
      const doSend = vi.fn().mockResolvedValueOnce(jsonResponse(status, { detail: "任意响应" }))
      const confirmFn = vi.fn()

      const result = await sendWithOverrideConfirm(doSend, confirmFn)

      expect(result?.status).toBe(status)
      expect(confirmFn).not.toHaveBeenCalled()
      expect(doSend).toHaveBeenCalledTimes(1)
    }
  })

  it("409 响应体 json() 抛异常：走 .catch 回退默认确认文案", async () => {
    const broken = { status: 409, ok: false, json: async () => { throw new Error("invalid json") } } as unknown as Response
    const doSend = vi.fn().mockResolvedValueOnce(broken)
    const confirmFn = vi.fn().mockReturnValue(false)

    const result = await sendWithOverrideConfirm(doSend, confirmFn)

    expect(result).toBeNull()
    expect(confirmFn).toHaveBeenCalledWith("已存在同名技能，是否替换覆盖？")
  })
})
