import { describe, it, expect, vi, beforeEach } from "vitest"
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react"
import { ResumeActionBar } from "./resume-action-bar"

// render 后冲掉挂载 effect 的异步 setState（act 警告根治专项：纯测试侧修复）
async function renderAsync(ui: Parameters<typeof render>[0]) {
  const result = render(ui)
  await act(async () => {})
  return result
}

describe("ResumeActionBar Component", () => {
  const mockShowToast = vi.fn()
  const mockOnReportGenerated = vi.fn()
  const mockOnCheckStatus = vi.fn()
  const mockOnLaunchBrowser = vi.fn()
  const mockOnGotoLogin = vi.fn()
  const mockOnCollect = vi.fn()
  const mockOnSyncBack = vi.fn()
  const mockOnRefreshData = vi.fn()
  const mockOnClearData = vi.fn()
  const mockSetSelectedPlatforms = vi.fn()

  const defaultProps = {
    apiBase: "http://127.0.0.1:8000",
    platformStatus: {
      boss: { port: 19222, online: true, logged_in: true },
      liepin: { port: 19223, online: true, logged_in: false },
      "51job": { port: 19224, online: false, logged_in: false },
      zhilian: { port: 19225, online: true, logged_in: true },
    },
    statusRefreshing: false,
    launchingPlatform: null,
    loginPlatform: null,
    selectedPlatforms: { boss: true, liepin: true, "51job": true, zhilian: true },
    setSelectedPlatforms: mockSetSelectedPlatforms,
    onCheckStatus: mockOnCheckStatus,
    onLaunchBrowser: mockOnLaunchBrowser,
    onGotoLogin: mockOnGotoLogin,
    onCollect: mockOnCollect,
    onSyncBack: mockOnSyncBack,
    onRefreshData: mockOnRefreshData,
    onClearData: mockOnClearData,
    collecting: null,
    syncing: null,
    showToast: mockShowToast,
    onReportGenerated: mockOnReportGenerated,
  }

  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/agent-map/resumes")) {
        return Promise.resolve({
          json: () =>
            Promise.resolve({
              success: true,
              resumes: [
                { record_id: "rec_1", name: "通用全职架构师简历", status: "启用中", char_count: 12000 },
                { record_id: "rec_2", name: "产品经理备用简历", status: "草稿", char_count: 8500 },
              ],
            }),
        })
      }
      if (url.includes("/api/agent-map/generate")) {
        return Promise.resolve({
          json: () => Promise.resolve({ success: true }),
        })
      }
      return Promise.resolve({
        json: () => Promise.resolve({ success: true }),
      })
    })
  })

  it("01. 渲染返回主页链接与卡片内嵌精致标题", async () => {
    await renderAsync(<ResumeActionBar {...defaultProps} />)
    const homeLink = screen.getByText("返回主页")
    expect(homeLink).toBeDefined()
    expect(homeLink.closest("a")?.getAttribute("href")).toBe("/")
    expect(screen.getByText("在线简历多平台同步中心")).toBeDefined()
    expect(screen.getByText("4 平台同步")).toBeDefined()
  })

  it("02. 渲染四平台登录状态与启动/去登录入口", async () => {
    await renderAsync(<ResumeActionBar {...defaultProps} />)
    expect(screen.getAllByText("BOSS直聘").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("猎聘").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("前程无忧").length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText("智联招聘").length).toBeGreaterThanOrEqual(1)

    // 51job 未启动 -> 启动按钮
    const launchBtn = screen.getByText("启动")
    expect(launchBtn).toBeDefined()
    fireEvent.click(launchBtn)
    expect(mockOnLaunchBrowser).toHaveBeenCalledWith("51job")

    // 猎聘 未登录 -> 去登录按钮
    const loginBtn = screen.getByText("去登录")
    expect(loginBtn).toBeDefined()
    fireEvent.click(loginBtn)
    expect(mockOnGotoLogin).toHaveBeenCalledWith("liepin")
  })

  it("03. 渲染主简历来源下拉列表与字符数提示", async () => {
    await renderAsync(<ResumeActionBar {...defaultProps} />)
    await waitFor(() => {
      expect(screen.getByText(/通用全职架构师简历/)).toBeDefined()
    })
    expect(screen.getByText("飞书云端简历")).toBeDefined()
  })

  it("04. 触发批量操作动作：采集、回写、刷新、清空", async () => {
    await renderAsync(<ResumeActionBar {...defaultProps} />)

    fireEvent.click(screen.getByText("采集数据"))
    expect(mockOnCollect).toHaveBeenCalled()

    fireEvent.click(screen.getByText("回写数据"))
    expect(mockOnSyncBack).toHaveBeenCalled()

    fireEvent.click(screen.getByText("刷新数据"))
    expect(mockOnRefreshData).toHaveBeenCalled()

    fireEvent.click(screen.getByText("清空数据"))
    expect(mockOnClearData).toHaveBeenCalled()
  })

  it("05. 渲染映射模块及其专属平台标签 (智联/51job/BOSS/猎聘)", async () => {
    await renderAsync(<ResumeActionBar {...defaultProps} />)
    expect(screen.getByText("基本信息")).toBeDefined()
    expect(screen.getByText("个人优势")).toBeDefined()
    expect(screen.getByText("工作经历")).toBeDefined()
    expect(screen.getByText("项目经历")).toBeDefined()
    expect(screen.getByText("专业技能")).toBeDefined()
    expect(screen.getByText("证书与语言")).toBeDefined()
    expect(screen.getByText("培训经历")).toBeDefined()
    expect(screen.getByText("驻外偏好")).toBeDefined()
  })

  it("06. 快捷预设按钮支持：全选、仅经历模块、反选", async () => {
    await renderAsync(<ResumeActionBar {...defaultProps} />)

    const expBtn = screen.getByText("仅经历模块")
    fireEvent.click(expBtn)

    const allBtn = screen.getByText("全选")
    fireEvent.click(allBtn)

    const invertBtn = screen.getByText("反选")
    fireEvent.click(invertBtn)
  })

  it("07. 点击【生成映射报告】发起批量映射请求并触发回调", async () => {
    await renderAsync(<ResumeActionBar {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText(/通用全职架构师简历/)).toBeDefined()
    })

    const generateBtn = screen.getByText("生成映射报告")
    fireEvent.click(generateBtn)

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/agent-map/generate"),
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("selected_modules"),
        })
      )
      expect(mockOnReportGenerated).toHaveBeenCalled()
      expect(mockShowToast).toHaveBeenCalledWith(
        expect.stringContaining("已成功为"),
        "success"
      )
    })
  })
})
