import { renderHook, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { useDualChannelVoice } from "./use-dual-channel-voice"

// 语音会话代际守卫回归：旧连接 close 后迟到 onmessage（上一轮全量转写）不得污染新会话
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  readyState = FakeWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((e: { wasClean: boolean }) => void) | null = null
  sent: ArrayBuffer[] = []

  constructor() {
    FakeWebSocket.instances.push(this)
  }
  close() {
    this.readyState = FakeWebSocket.CLOSED
  }
  send(data: ArrayBuffer) {
    this.sent.push(data)
  }
  // 测试辅助：模拟服务端消息
  receive(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }
}

function lastWs() {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
}

describe("useDualChannelVoice 会话代际守卫", () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket)
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: {
        getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
      },
    })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(window as any).AudioContext = class {
      sampleRate = 48000
      createMediaStreamSource() {
        return { connect: vi.fn() }
      }
      createScriptProcessor() {
        return { connect: vi.fn(), disconnect: vi.fn(), onaudioprocess: null }
      }
      close = vi.fn()
    }
  })

  it("旧连接迟到消息不污染第二轮；提交只含本轮文本", async () => {
    const onComplete = vi.fn()
    const { result } = renderHook(() => useDualChannelVoice(onComplete))

    // 会话 A：录音、识别出第一轮文本
    await act(async () => {
      await result.current.toggleRecording()
    })
    const wsA = lastWs()
    act(() => wsA.open())
    act(() => wsA.receive({ status: "success", text: "第一轮回答" }))
    expect(result.current.streamingText).toBe("第一轮回答")

    // 停止 A：提交第一轮文本
    await act(async () => {
      await result.current.toggleRecording()
    })
    expect(onComplete).toHaveBeenCalledWith("第一轮回答")

    // 会话 B：新连接
    await act(async () => {
      await result.current.toggleRecording()
    })
    const wsB = lastWs()
    expect(wsB).not.toBe(wsA)
    act(() => wsB.open())

    // 关键回归点：A 的迟到消息到达。注：本用例实际锁定的是「解绑」层——
    // stopAllRecording 已把 wsA.onmessage 置 null，receive() 是空操作；
    // 代际守卫是第二保险（防 onopen/onerror 等未解绑路径的迟到触发），此处未直接触发。
    act(() => wsA.receive({ status: "success", text: "第一轮回答 迟到污染" }))
    expect(result.current.streamingText).not.toContain("迟到污染")

    // B 正常识别第二轮
    act(() => wsB.receive({ status: "success", text: "第二轮回答" }))
    expect(result.current.streamingText).toBe("第二轮回答")

    // 停止 B：只提交第二轮文本，第一轮不得混入
    await act(async () => {
      await result.current.toggleRecording()
    })
    expect(onComplete).toHaveBeenLastCalledWith("第二轮回答")
  })
})
