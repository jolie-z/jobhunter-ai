import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { act, render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react"
import { BossTab } from "./boss-tab"

// render 后冲掉挂载 effect 的异步 setState（act 警告根治专项：纯测试侧修复）
async function renderAsync(ui: Parameters<typeof render>[0]) {
  const result = render(ui)
  await act(async () => {})
  return result
}

class MockIntersectionObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

beforeEach(() => {
  window.IntersectionObserver = MockIntersectionObserver as any
  window.scrollTo = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const mockBossData = {
  base_info: {
    label: "基本信息",
    required: true,
    type: "object",
    current_value: {
      name: "张测试",
      gender: "女",
      job_status: "离职-随时到岗",
      birth_month: "1995-06",
      work_start_date: "2018-07",
      phone: "13800000000",
      email: "test@example.com",
    },
  },
  personal_advantage: {
    label: "个人优势",
    required: false,
    type: "text",
    current_value: "5年全栈开发经验，精通 React 与 Python FastAPI 架构设计。",
  },
  expectations: {
    label: "求职期望",
    required: true,
    type: "array",
    current_value: [
      {
        position: "全栈工程师",
        industry: "互联网",
        city: "广州",
        salary: "20-30K",
        positionType: "全职",
      },
    ],
  },
  work_experience: {
    label: "工作经历",
    required: true,
    type: "array",
    current_value: [
      {
        company: "自由职业者",
        industry: "互联网",
        department: "自主创业",
        position: "全栈工程师",
        startYear: "2024",
        startMonth: "04",
        endYear: "",
        endMonth: "",
        content: "针对大模型商业应用，独立设计智能架构与全链路自动化 SaaS。",
        achievement: "交付 5 项涵盖大模型智能体与供应链中台的数据产品。",
        skills: [
          { name: "LLM意图路由" },
          { name: "Pandas物理校验" },
          { name: "双轨制架构" },
          { name: "CDP协议" },
          { name: "NLP情感分析" },
          { name: "全栈研发" },
        ],
        hideResume: true,
      },
    ],
  },
  projects: {
    label: "项目经历",
    required: false,
    type: "array",
    current_value: [
      {
        project_name: "JobHunter AI 自动化求职平台",
        project_role: "架构师 & 核心开发",
        startYear: "2024",
        startMonth: "01",
        endYear: "2024",
        endMonth: "06",
        project_description: "多平台投递自动化系统",
        achievement: "实现 4 大招聘平台秒级同步",
      },
    ],
  },
  education: {
    label: "教育经历",
    required: false,
    type: "array",
    current_value: [
      {
        school: "临江大学",
        major: "软件工程",
        degree: "本科",
        startYear: "2014",
        endYear: "2018",
      },
    ],
  },
  certificates: {
    label: "资格证书",
    required: false,
    type: "array",
    current_value: ["英语六级", "PMP项目管理专业人士认证"],
  },
  stayAbroad: {
    label: "驻外选项",
    required: false,
    type: "object",
    current_value: {
      countries: ["中国香港", "德国"],
      languages: ["英语", "粤语"],
      duration: "2年",
    },
  },
}

function mockFetchEndpoints() {
  const calls: { url: string; body?: any; method?: string }[] = []
  const fetchMock = vi.fn(async (url: string, opts?: any) => {
    const u = String(url)
    const json = (data: any) =>
      new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      })
    calls.push({ url: u, body: opts?.body ? JSON.parse(opts.body) : null, method: opts?.method || "GET" })

    if (u.includes("/api/agent-map/reports")) {
      return json({ success: true, reports: {} })
    }
    if (u.includes("/api/agent-map/writeback-save")) {
      return json({ success: true, message: "保存快照成功" })
    }
    if (u.includes("/api/resume-editor/save/boss")) {
      return json({ success: true, message: "保存字段成功" })
    }
    if (u.includes("/api/agent-map/write-back")) {
      return json({ success: true, message: "回写成功", verify: [{ module: "work_experience", match: true }] })
    }
    return json({ success: true })
  })
  vi.stubGlobal("fetch", fetchMock)
  return { calls, fetchMock }
}

describe("BOSS直聘 Tab 前端组件与功能集成测试", () => {
  it("01. Loading 态正确展示加载指示器", async () => {
    mockFetchEndpoints()
    await renderAsync(<BossTab data={null} loading={true} onRefresh={vi.fn()} />)
    expect(screen.getByText(/加载中/i)).toBeTruthy()
  })

  it("02. 数据未就绪时展示与其他平台一致的空态（暂无数据 + 刷新按钮）", async () => {
    mockFetchEndpoints()
    await renderAsync(<BossTab data={null} loading={false} onRefresh={vi.fn()} />)
    // data 为 null（从未采集/刚清空）：统一为居中空态
    expect(screen.getByText("暂无 BOSS直聘数据")).toBeTruthy()
    expect(screen.getByText("请先运行采集脚本")).toBeTruthy()
    expect(screen.getByText("刷新数据")).toBeTruthy()
  })

  it("02b. 清空后点刷新加载到空对象时渲染空框架骨架（模块保留、值清空）", async () => {
    mockFetchEndpoints()
    await renderAsync(<BossTab data={{}} loading={false} onRefresh={vi.fn()} />)
    // data 为 {}（清空后点了「刷新数据」重新加载）：不再显示空态，而是空框架骨架
    expect(screen.queryByText("暂无 BOSS直聘数据")).toBeNull()
    expect(screen.getAllByText("简历目录").length).toBeGreaterThan(0)
    expect(screen.getAllByText("工作经历").length).toBeGreaterThan(0)
  })

  it("03. 正常渲染 8 大模块的核心卡片与数据", async () => {
    mockFetchEndpoints()
    await renderAsync(<BossTab data={mockBossData as any} loading={false} onRefresh={vi.fn()} />)

    // 验证各模块标题渲染
    expect(screen.getAllByText("基本信息").length).toBeGreaterThan(0)
    expect(screen.getAllByText("个人优势").length).toBeGreaterThan(0)
    expect(screen.getAllByText("求职期望").length).toBeGreaterThan(0)
    expect(screen.getAllByText("工作经历").length).toBeGreaterThan(0)
    expect(screen.getAllByText("项目经历").length).toBeGreaterThan(0)
    expect(screen.getAllByText("教育经历").length).toBeGreaterThan(0)
    expect(screen.getAllByText("资格证书").length).toBeGreaterThan(0)
    expect(screen.getAllByText("驻外选项").length).toBeGreaterThan(0)

    // 验证工作经历中的公司和描述
    expect(screen.getByText("自由职业者")).toBeTruthy()
    expect(screen.getByText(/针对大模型商业应用/)).toBeTruthy()
  })

  it("04. 能够触发工作经历编辑并展示编辑按钮", async () => {
    mockFetchEndpoints()
    await renderAsync(<BossTab data={mockBossData as any} loading={false} onRefresh={vi.fn()} />)

    const editBtns = screen.getAllByRole("button", { name: /编辑/ })
    expect(editBtns.length).toBeGreaterThan(0)
  })

  it("05. 点击保存快照能够向后端发送 writeback-save 请求", async () => {
    const { calls } = mockFetchEndpoints()
    await renderAsync(<BossTab data={mockBossData as any} loading={false} onRefresh={vi.fn()} />)

    const saveBtn = screen.getByRole("button", { name: /保存快照/ })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      const saveCall = calls.find((c) => c.url.includes("/api/agent-map/writeback-save"))
      expect(saveCall).toBeTruthy()
      expect(saveCall?.method).toBe("POST")
      expect(saveCall?.body?.platform).toBe("boss")
    })
  })

  it("06. 点击回写选中模块能够组装勾选的模块并在确认后向后端发起回写请求", async () => {
    const { calls } = mockFetchEndpoints()
    await renderAsync(<BossTab data={mockBossData as any} loading={false} onRefresh={vi.fn()} />)

    // 点击开启二次确认
    const writeBackBtn = screen.getByRole("button", { name: /回写选中模块/ })
    fireEvent.click(writeBackBtn)

    // 点击确认回写
    const confirmBtn = await screen.findByRole("button", { name: /确认回写/ })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      const wbCall = calls.find((c) => c.url.includes("/api/agent-map/write-back"))
      expect(wbCall).toBeTruthy()
      expect(wbCall?.body?.platform).toBe("boss")
      expect(Array.isArray(wbCall?.body?.paths)).toBe(true)
      expect(wbCall?.body?.paths).toContain("work_experience")
      expect(wbCall?.body?.paths).toContain("personal_advantage")
    })
  })

  it("07. 回写完成后展示结构化状态卡片与可展开日志", async () => {
    const { fetchMock } = mockFetchEndpoints()
    fetchMock.mockImplementation(async (url: string, opts?: any) => {
      const u = String(url)
      const json = (data: any) =>
        new Response(JSON.stringify(data), {
          headers: { "Content-Type": "application/json" },
        })
      if (u.includes("/api/agent-map/write-back")) {
        return json({
          success: true,
          message: "回写成功 2/2",
          results: [
            { module: "personal_advantage", ok: true, detail: "优势已更新" },
            { module: "work_experience", ok: true, detail: "经历已更新" },
          ],
          verify: [
            { module: "personal_advantage", match: true, note: "已生效" },
            { module: "work_experience", match: true, note: "已生效" },
          ],
          output: "=== BOSS Writeback Log ===\nAll modules updated.",
        })
      }
      return json({ success: true, reports: {} })
    })

    await renderAsync(<BossTab data={mockBossData as any} loading={false} onRefresh={vi.fn()} />)

    // 触发回写
    fireEvent.click(screen.getByRole("button", { name: /回写选中模块/ }))
    fireEvent.click(await screen.findByRole("button", { name: /确认回写/ }))

    // 验证结构化卡片渲染
    await waitFor(() => {
      expect(screen.getByText(/回写成功 2\/2/)).toBeTruthy()
      expect(screen.getByText(/个人优势:/)).toBeTruthy()
      expect(screen.getByText(/工作经历:/)).toBeTruthy()
      expect(screen.getByRole("button", { name: /查看日志/ })).toBeTruthy()
    })

    // 测试展开日志
    fireEvent.click(screen.getByRole("button", { name: /查看日志/ }))
    expect(screen.getByText(/=== BOSS Writeback Log ===/)).toBeTruthy()
    expect(screen.getByRole("button", { name: /收起日志/ })).toBeTruthy()
  })

  it("08. 回写失败时展示 BOSS 自愈 Agent 行动卡片，点击可呼出诊断弹窗并执行自愈", async () => {
    const json = (data: any) =>
      new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } })

    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes("/api/agent-map/write-back")) {
        return json({
          success: false,
          message: "BOSS 校验异常",
          verify: [{ module: "projects", match: false, note: "缺少项目职务" }],
        })
      }
      if (u.includes("/api/platforms/boss/agent-diagnose")) {
        return json({
          ok: true,
          module: "projects",
          module_label: "项目经历",
          rule_code: "RULE_1_PROJECT_ROLE_REQUIRED",
          rule_name: "BOSS 项目经历项目职务/角色必填法则",
          root_cause: "BOSS 直聘项目经历接口严格要求 role（项目职务/角色）非空。",
          confidence: 0.96,
          recipe: {
            action_type: "fix_project_roles",
            module: "projects",
            title: "自动补齐项目经历缺省职务角色",
            details: "为缺失 role 的项目条目自动注入默认职务"
          },
          evidence: { missing_role_count: 1 }
        })
      }
      if (u.includes("/api/platforms/boss/agent-apply-heal")) {
        return json({
          ok: true,
          snapshot_id: "boss_heal_proj_test.bak.json",
          healed_count: 1,
          message: "BOSS 自愈完成！"
        })
      }
      return json({ success: true, reports: {} })
    }))

    await renderAsync(<BossTab data={mockBossData as any} loading={false} onRefresh={vi.fn()} />)

    // 触发回写
    fireEvent.click(screen.getByRole("button", { name: /回写选中模块/ }))
    fireEvent.click(await screen.findByRole("button", { name: /确认回写/ }))

    // 验证 Agent 行动卡片
    expect(await screen.findByText(/🤖 BOSS直聘 自愈 Agent 待命/)).toBeTruthy()
    expect(screen.getByText(/🤖 派出自愈 Agent 深度排查「项目经历」/)).toBeTruthy()

    // 点击派出 Agent
    fireEvent.click(screen.getByText(/🤖 派出自愈 Agent 深度排查「项目经历」/))

    // 验证 Agent Modal 打开
    expect(await screen.findByText("BOSS直聘数据回写自愈 Agent")).toBeTruthy()
    expect(screen.getByText(/BOSS 项目经历项目职务\/角色必填法则/)).toBeTruthy()

    // 点击应用处方
    const applyHealBtn = screen.getByText(/⚡ 一键应用处方并自动重新回传/)
    fireEvent.click(applyHealBtn)

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/platforms/boss/agent-apply-heal"),
        expect.anything()
      )
    })
  })
})

