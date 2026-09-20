import React from "react"
import { render, screen, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { PersonalInfo } from "./personal-info"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

// render 后冲掉挂载 effect 的异步 setState（否则 act 警告）
async function renderAsync(ui: React.ReactElement) {
  const result = render(ui)
  await act(async () => {})
  return result
}

// 头像编辑权归属（产品拍板 2026-09-19）：
// - 岗位工作区编辑区（无 StrategyContext）：头像只读，hover 引导前往配置大盘-简历库
// - 配置大盘-简历库页面（有 StrategyContext）：可上传/更换/删除
// mock strategy store：storeRef.current 为 undefined 即岗位工作区形态
const storeRef: { current: any } = { current: undefined }
vi.mock("@/hooks/use-strategy-store", () => ({
  useOptionalStrategyStore: () => storeRef.current,
}))

// stub 全局 fetch：自动读取启用底稿照片的链路不允许打到真实后端
const fetchMock = vi.fn(() =>
  Promise.resolve({ json: () => Promise.resolve({ status: "success", resumes: [] }) } as any)
)

describe("PersonalInfo 头像编辑权归属", () => {
  beforeEach(async () => {
    fetchMock.mockClear()
    vi.stubGlobal("fetch", fetchMock)
    useResumeV2Store.getState().setResumeData({
      personalInfo: { name: "", title: "", phone: "", email: "", location: "", website: "" },
      moduleOrder: [],
    } as any)
    storeRef.current = undefined
  })

  afterEach(async () => {
    vi.unstubAllGlobals()
  })

  it("岗位工作区（无简历库上下文）：头像只读，引导文案不在常驻 DOM（Tooltip 仅 hover 浮现），且不渲染文件选择器", async () => {
    await renderAsync(<PersonalInfo />)
    // Radix Tooltip 内容未 hover 时不挂载——页面上不常有任何提示文字
    expect(screen.queryByText("请前往 配置大盘-简历库 修改照片")).toBeNull()
    expect(screen.queryByText("上传照片")).toBeNull()
    expect(screen.queryByText("更换照片")).toBeNull()
    // 文件选择器不渲染：点击头像不可能触发上传
    expect(document.querySelector('input[type="file"]')).toBeNull()
    // 头像框存在且标记为只读
    expect(screen.getByLabelText("照片（只读）")).toBeTruthy()
  })
  // 注：hover 浮现气泡的行为不在 jsdom 断言——Radix Tooltip 依赖 isTrusted 指针事件，
  // 合成事件无法触发；该行为由 GUI 实测闭环（hover 浮现引导语、移开消失）。

  it("岗位工作区（无上下文）但已有照片：img 正常渲染，仍只读", async () => {
    useResumeV2Store.getState().setResumeData({
      personalInfo: { name: "", avatar_url: "http://127.0.0.1:8001/api/strategy/avatar/fake_token" },
      moduleOrder: [],
    } as any)
    await renderAsync(<PersonalInfo />)
    expect(screen.getByAltText("Avatar")).toBeTruthy()
    expect(screen.queryByText("更换照片")).toBeNull()
    expect(document.querySelector('input[type="file"]')).toBeNull()
  })

  it("简历库页面（有简历库上下文）：头像可编辑，hover 显示上传照片，文件选择器存在", async () => {
    storeRef.current = { editingItem: { record_id: "recTest123", avatar_url: undefined }, fetchConfig: vi.fn() }
    await renderAsync(<PersonalInfo />)
    expect(screen.getByText("上传照片")).toBeTruthy()
    expect(screen.queryByText("请前往 配置大盘-简历库 修改照片")).toBeNull()
    expect(document.querySelector('input[type="file"]')).toBeTruthy()
  })

  it("简历库页面已有照片：hover 显示更换照片", async () => {
    storeRef.current = {
      editingItem: { record_id: "recTest123", avatar_url: "http://127.0.0.1:8001/api/strategy/avatar/fake_token" },
      fetchConfig: vi.fn(),
    }
    await renderAsync(<PersonalInfo />)
    expect(screen.getByText("更换照片")).toBeTruthy()
  })
})
