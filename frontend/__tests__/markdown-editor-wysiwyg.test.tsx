// markdown-editor WYSIWYG 安全边界用例（2026-09-23 agy 第3轮 P1 回归钉）。
// 不变式：实例「未 ready（after 未回调）」时，超时兜底/卸载/外部点击导致的
// commitNow 一律不得 emit——否则 getValue() 的空串会把父级简历正文清空。
import React from "react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, act } from "@testing-library/react"
import { MarkdownEditor } from "@/components/dashboard/resume-builder/markdown-editor"

// 假 vditor：after 是否回调、getValue 返回值均可编程控制
const instances: any[] = []
class FakeVditor {
  opts: any
  destroyed = false
  constructor(_el: HTMLElement, opts: any) {
    this.opts = opts
    instances.push(this)
  }
  getValue() {
    return this.opts.__value ?? ""
  }
  setValue() {}
  focus() {}
  destroy() {
    this.destroyed = true
  }
}
vi.mock("vditor", () => ({ default: FakeVditor }))

async function enterEdit(initial = "原始底稿") {
  const onChange = vi.fn()
  render(<MarkdownEditor value={initial} onChange={onChange} />)
  // 阅读态点击进入编辑态（点击内容冒泡到容器 onClick）
  fireEvent.click(screen.getByText(/原始底稿/))
  await act(async () => {}) // 冲刷动态 import 微任务，让 FakeVditor 完成构造
  return { onChange }
}

describe("MarkdownEditor WYSIWYG 安全边界", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    instances.length = 0
  })

  it("未 ready 时 8s 超时回退：不得 emit 任何值，且回退 Textarea 保留原稿", async () => {
    const { onChange } = await enterEdit()
    expect(instances.length).toBe(1)
    expect(instances[0].destroyed).toBe(false)

    await act(async () => {
      vi.advanceTimersByTime(8000)
    })
    // 兜底触发：半初始化实例已销毁，组件回退 Textarea 且内容仍是原稿
    expect(instances[0].destroyed).toBe(true)
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement
    expect(textarea.value).toBe("原始底稿")
    // 核心不变式：绝不 emit（空串覆盖 = 静默丢稿）
    expect(onChange).not.toHaveBeenCalled()
  })

  it("未 ready 时直接卸载：不得 emit 任何值", async () => {
    const onChange = vi.fn()
    const { unmount } = render(<MarkdownEditor value="原始底稿" onChange={onChange} />)
    fireEvent.click(screen.getByText(/原始底稿/))
    await act(async () => {})
    unmount()
    expect(onChange).not.toHaveBeenCalled()
  })

  it("ready 后正常链路：input 防抖冲刷出新值、blur 退出回阅读态", async () => {
    const { onChange } = await enterEdit()
    const inst = instances[0]
    act(() => {
      inst.opts.after() // 模拟 vditor 初始化完成
    })
    inst.opts.__value = "改后的稿"
    await act(async () => {
      inst.opts.input?.()
      vi.advanceTimersByTime(400) // 越过 300ms 防抖
    })
    expect(onChange).toHaveBeenCalledWith("改后的稿")
  })
})
