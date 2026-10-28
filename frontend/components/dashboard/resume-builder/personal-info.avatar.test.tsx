import React from "react"
import { render, screen, act } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { PersonalInfo } from "./personal-info"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { fetchActiveResumeAvatar } from "@/lib/resume-avatar"

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

describe("PersonalInfo 未保存提醒误报回归（挂载期不得写 store 破坏基线）", () => {
  // 挂载 effect 的照片链路是多层异步（fetch → json → 写 store → 头像缓存），多轮排水确保断言前链路跑完
  async function flushAvatarChain() {
    for (let i = 0; i < 5; i++) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
      })
    }
  }

  beforeEach(async () => {
    fetchMock.mockClear()
    vi.stubGlobal("fetch", fetchMock)
    storeRef.current = undefined
  })

  afterEach(async () => {
    vi.unstubAllGlobals()
    // mockReset 恢复 vi.fn(默认实现) 的原始行为，防本 describe 的 mockImplementation 泄漏到后续测试
    fetchMock.mockReset()
    // 与 job-detail-workspace 卸载清理同形态，防跨测试污染
    useResumeV2Store.getState().setResumeData(null)
    useResumeV2Store.getState().setSavedBaseline("")
  })

  it("岗位无照片且配置大盘有启用简历照片：挂载自动回填不得使 store 偏离基线（未保存误报根因）", async () => {
    // 模拟定制面板 loadData：基线与 store 同事务建立，简历 JSON 不含 avatar_url
    useResumeV2Store.getState().setResumeDataWithBaseline({
      personalInfo: { name: "张三", title: "Product Manager", phone: "", email: "", location: "" },
      summary: "AI Agent 从 0 到 1 落地",
      moduleOrder: ["summary"],
    } as any)
    const baseline = useResumeV2Store.getState().savedBaseline
    expect(baseline).toBeTruthy()

    // PersonalInfo 挂载 effect 拉到启用底稿的照片：修复后岗位工作区形态只展示不回写，
    // store 必须与基线保持相等（本用例即未保存误报的常驻回归门）
    fetchMock.mockImplementation(() =>
      Promise.resolve({
        json: () =>
          Promise.resolve({
            status: "success",
            resumes: [{ status: "启用", avatar_url: "http://127.0.0.1:8001/api/strategy/avatar/active_token" }],
          }),
      } as any)
    )

    render(<PersonalInfo />)
    await flushAvatarChain()

    const { resumeData, savedBaseline } = useResumeV2Store.getState()
    expect(resumeData).toBeTruthy()
    // 未保存提醒的判定式：store 偏离基线 = dirty。用户零操作，必须仍然等于基线
    expect(JSON.stringify(resumeData)).toBe(savedBaseline)
    expect(savedBaseline).toBe(baseline)
  })

  it("工作区形态早到响应也不写入（persist=false 全程无 store 写入，store 为 null 时写入本就是 no-op）", async () => {
    // 挂载即发起 config 请求（此时 store 尚为 null，模拟 workspace 装载 await 窗口）
    fetchMock.mockImplementation(() =>
      Promise.resolve({
        json: () =>
          Promise.resolve({
            status: "success",
            resumes: [{ status: "启用", avatar_url: "http://127.0.0.1:8001/api/strategy/avatar/order_token" }],
          }),
      } as any)
    )
    render(<PersonalInfo />)

    // 排干 fetch 链：config 响应落地、写入尝试发生，此时基线仍未建立
    await flushAvatarChain()
    expect(useResumeV2Store.getState().resumeData).toBeNull()

    // 基线此刻才落地（store 无照片，与首用例同形态）
    useResumeV2Store.getState().setResumeDataWithBaseline({
      personalInfo: { name: "张三", title: "PM" },
      moduleOrder: [],
    } as any)
    const baseline = useResumeV2Store.getState().savedBaseline

    // 再排干：config 不会二次写入（effect 依赖未变未重跑，Promise 已消费）
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
      })
    }
    const { resumeData, savedBaseline } = useResumeV2Store.getState()
    expect(JSON.stringify(resumeData)).toBe(savedBaseline)
    expect(savedBaseline).toBe(baseline)
  })

  it("简历库形态（StrategyContext 存在）：启用底稿照片仍回写进 store（共用面约束——库页回写语义不得改变）", async () => {
    useResumeV2Store.getState().setResumeDataWithBaseline({
      personalInfo: { name: "张三" },
      moduleOrder: [],
    } as any)
    storeRef.current = { editingItem: { record_id: "recLib1", avatar_url: undefined }, fetchConfig: vi.fn() }

    fetchMock.mockImplementation(() =>
      Promise.resolve({
        json: () =>
          Promise.resolve({
            status: "success",
            resumes: [{ status: "启用", avatar_url: "http://127.0.0.1:8001/api/strategy/avatar/library_token" }],
          }),
      } as any)
    )

    render(<PersonalInfo />)
    await flushAvatarChain()

    // 库页保留回写：store personalInfo 拿到照片地址（persist=true 路径）
    expect(useResumeV2Store.getState().resumeData?.personalInfo?.avatar_url).toBe(
      "http://127.0.0.1:8001/api/strategy/avatar/library_token",
    )
  })

  it("store 已有照片但与配置大盘 URL 字符串不一致：不得静默覆写导致误报", async () => {
    useResumeV2Store.getState().setResumeDataWithBaseline({
      personalInfo: { name: "张三", avatar_url: "/api/strategy/avatar/relative_token" },
      moduleOrder: [],
    } as any)
    const baseline = useResumeV2Store.getState().savedBaseline

    fetchMock.mockImplementation(() =>
      Promise.resolve({
        json: () =>
          Promise.resolve({
            status: "success",
            resumes: [{ status: "启用", avatar_url: "http://127.0.0.1:8001/api/strategy/avatar/relative_token" }],
          }),
      } as any)
    )

    render(<PersonalInfo />)
    await flushAvatarChain()

    const { resumeData, savedBaseline } = useResumeV2Store.getState()
    expect(JSON.stringify(resumeData)).toBe(savedBaseline)
    expect(savedBaseline).toBe(baseline)
  })
})

describe("fetchActiveResumeAvatar 同源 helper（基线回填与组件展示共用）", () => {
  beforeEach(async () => {
    fetchMock.mockClear()
    vi.stubGlobal("fetch", fetchMock)
  })

  afterEach(async () => {
    vi.unstubAllGlobals()
    fetchMock.mockReset()
  })

  it("启用简历有照片：原样返回该 URL（与 workspace 基线回填严格同形）", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve({
        json: () =>
          Promise.resolve({
            status: "success",
            resumes: [
              { status: "停用", avatar_url: "http://x/inactive" },
              { status: "启用", avatar_url: "http://x/active_token" },
            ],
          }),
      } as any)
    )
    await expect(fetchActiveResumeAvatar()).resolves.toBe("http://x/active_token")
  })

  it("无启用简历或照片字段为空：返回 null", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve({ json: () => Promise.resolve({ status: "success", resumes: [{ status: "启用" }] }) } as any)
    )
    await expect(fetchActiveResumeAvatar()).resolves.toBeNull()
  })

  it("全部简历均非启用（find 落空）：返回 null", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve({
        json: () =>
          Promise.resolve({
            status: "success",
            resumes: [{ status: "停用", avatar_url: "http://x/disabled" }],
          }),
      } as any)
    )
    await expect(fetchActiveResumeAvatar()).resolves.toBeNull()
  })

  it("请求失败不抛错：返回 null", async () => {
    fetchMock.mockImplementation(() => Promise.reject(new Error("network down")))
    await expect(fetchActiveResumeAvatar()).resolves.toBeNull()
  })
})

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
