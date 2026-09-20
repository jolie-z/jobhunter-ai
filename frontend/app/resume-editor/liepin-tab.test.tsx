import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react"
import { LiepinTab } from "./liepin-tab"
import { LiepinCatalogue } from "@/components/ui/liepin-catalogue"

class MockIntersectionObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

beforeEach(() => {
  window.IntersectionObserver = MockIntersectionObserver as any
  window.scrollTo = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const mockLiepinData = {
  name: { label: "姓名", required: true, type: "text", current_value: "张测试" },
  gender: { label: "性别", required: true, type: "text", current_value: "女" },
  mobile: { label: "手机号", required: true, type: "text", current_value: "13800000000" },
  email: { label: "邮箱", required: true, type: "text", current_value: "test@example.com" },
  cur_work_status: { label: "求职状态", required: true, type: "text", current_value: "离职-随时到岗" },
  self_assessment: { label: "优势亮点", required: false, type: "text", current_value: "5年全栈开发经验。" },
  expectations: {
    label: "求职期望",
    required: true,
    type: "array",
    current_value: [{ positions: ["全栈工程师"], industries: ["互联网"], city: "广州", salary_min: 20, salary_max: 30 }],
  },
  work_experience: {
    label: "工作经历",
    required: true,
    type: "array",
    current_value: [
      {
        company: "某科技公司",
        position: "全栈工程师",
        start_time: "2024-04",
        end_time: "",
        so_far: true,
        duty: "负责系统架构与全链路开发。",
      },
    ],
  },
  projects: {
    label: "项目经历",
    required: false,
    type: "array",
    current_value: [
      {
        project_name: "JobHunter AI",
        role: "架构师",
        start_time: "2024-01",
        end_time: "2024-06",
        description: "求职自动化系统",
      },
    ],
  },
  education: {
    label: "教育经历",
    required: true,
    type: "array",
    current_value: [
      {
        school: "临江大学",
        major: "软件工程",
        degree: "本科",
        start_time: "2014-09",
        end_time: "2018-06",
      },
    ],
  },
  certificates: {
    label: "资格证书",
    required: false,
    type: "array",
    current_value: ["PMP项目管理专业人士资格认证"],
  },
  skill_tags: {
    label: "技能标签",
    required: false,
    type: "array",
    current_value: ["React", "Python", "FastAPI", "Next.js"],
  },
  languages: {
    label: "语言能力",
    required: false,
    type: "array",
    current_value: [{ language: "英语", proficiency: "熟练", level: "CET-6" }],
  },
  additional_info: {
    label: "附加信息",
    required: false,
    type: "text",
    current_value: "可快速到岗",
  },
}

describe("LiepinCatalogue Component", () => {
  it("renders all 10 catalogue navigation items", () => {
    render(<LiepinCatalogue />)

    expect(screen.getByText("简历目录")).toBeDefined()
    expect(screen.getByText("基本信息")).toBeDefined()
    expect(screen.getByText("优势亮点")).toBeDefined()
    expect(screen.getByText("求职期望")).toBeDefined()
    expect(screen.getByText("工作经历")).toBeDefined()
    expect(screen.getByText("项目经历")).toBeDefined()
    expect(screen.getByText("教育经历")).toBeDefined()
    expect(screen.getByText("资格证书")).toBeDefined()
    expect(screen.getByText("技能标签")).toBeDefined()
    expect(screen.getByText("语言能力")).toBeDefined()
    expect(screen.getByText("附加信息")).toBeDefined()
  })

  it("handles smooth scroll when catalogue item is clicked", () => {
    render(
      <div>
        <LiepinCatalogue />
        <div id="section-workExp">Work Exp Section</div>
      </div>
    )

    const workExpBtn = screen.getByText("工作经历")
    fireEvent.click(workExpBtn)

    const targetEl = document.getElementById("section-workExp")
    expect(targetEl?.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" })
  })
})

describe("LiepinTab Component Integration", () => {
  it("renders sidebar catalogue alongside Liepin modules", () => {
    render(<LiepinTab data={mockLiepinData as any} loading={false} onRefresh={vi.fn()} />)

    // Catalogue is rendered
    expect(screen.getByText("简历目录")).toBeDefined()
    expect(screen.getByText("猎聘模块回写")).toBeDefined()

    // 10 sections are in the DOM
    expect(document.getElementById("section-baseInfo")).not.toBeNull()
    expect(document.getElementById("section-selfEval")).not.toBeNull()
    expect(document.getElementById("section-expectations")).not.toBeNull()
    expect(document.getElementById("section-workExp")).not.toBeNull()
    expect(document.getElementById("section-projects")).not.toBeNull()
    expect(document.getElementById("section-education")).not.toBeNull()
    expect(document.getElementById("section-certificates")).not.toBeNull()
    expect(document.getElementById("section-skillTags")).not.toBeNull()
    expect(document.getElementById("section-languages")).not.toBeNull()
    expect(document.getElementById("section-additionalInfo")).not.toBeNull()
  })

  it("renders work experience with 至今 correctly and enables modal toggle", () => {
    const testData = {
      ...mockLiepinData,
      work_experience: {
        label: "工作经历",
        required: true,
        type: "array",
        current_value: [
          {
            company: "自由职业者",
            position: "AI应用开发者",
            start_date: "2024/04",
            end_date: "至今",
            responsibilities: "全栈开发",
          },
        ],
      },
    }
    render(<LiepinTab data={testData as any} loading={false} onRefresh={vi.fn()} />)

    expect(screen.getByText(/2024\/04 - 至今/)).toBeDefined()
    expect(screen.getByText("自由职业者")).toBeDefined()
  })

  it("renders language skills and displays level options for 普通话", () => {
    const testData = {
      ...mockLiepinData,
      languages: {
        label: "语言能力",
        required: false,
        type: "array",
        current_value: [
          {
            language: "普通话",
            proficiency: "商务洽谈",
            level: "一级甲等",
          },
        ],
      },
    }
    render(<LiepinTab data={testData as any} loading={false} onRefresh={vi.fn()} />)

    expect(screen.getByText("普通话")).toBeDefined()
    expect(screen.getByText(/商务洽谈/)).toBeDefined()
    expect(screen.getByText(/一级甲等/)).toBeDefined()
  })

  it("triggers double check confirm dialog when clicking delete on work experience and allows cancel/confirm", async () => {
    const testData = {
      ...mockLiepinData,
      work_experience: {
        label: "工作经历",
        required: true,
        type: "array",
        current_value: [
          {
            company: "某美妆集团",
            position: "电商副店长",
            start_date: "2023/09",
            end_date: "2024/03",
          },
        ],
      },
    }
    render(<LiepinTab data={testData as any} loading={false} onRefresh={vi.fn()} />)

    // 找到工作经历卡片内的删除按钮并点击
    const workExpSection = document.getElementById("section-workExp")
    expect(workExpSection).not.toBeNull()
    const deleteBtn = Array.from(workExpSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)

    // 验证二次确认弹窗弹出
    expect(await screen.findByText(/确认删除工作经历「某美妆集团 · 电商副店长」？/)).toBeDefined()
    expect(screen.getByText(/删除后本地工作经历将移除该条目/)).toBeDefined()
    expect(screen.getByText("取消")).toBeDefined()
    expect(screen.getByText("确认删除")).toBeDefined()

    // 点击取消，弹窗关闭
    const cancelBtn = screen.getByText("取消")
    fireEvent.click(cancelBtn)
  })

  it("triggers double check confirm dialog when clicking delete on projects, education, and expectations", async () => {
    const testData = {
      ...mockLiepinData,
      expectations: {
        label: "求职期望",
        required: true,
        type: "array",
        current_value: [{ position: "AI训练师", city: "广州" }],
      },
      projects: {
        label: "项目经历",
        required: false,
        type: "array",
        current_value: [{ project_name: "全栈自动化SaaS" }],
      },
      education: {
        label: "教育经历",
        required: true,
        type: "array",
        current_value: [{ school: "某财经类大学", major: "社会工作" }],
      },
    }
    render(<LiepinTab data={testData as any} loading={false} onRefresh={vi.fn()} />)

    // 1. 测试项目经历删除二次确认
    const projSection = document.getElementById("section-projects")
    const projDeleteBtn = Array.from(projSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(projDeleteBtn).toBeDefined()
    fireEvent.click(projDeleteBtn!)
    expect(await screen.findByText(/确认删除项目经历「全栈自动化SaaS」？/)).toBeDefined()
    fireEvent.click(screen.getByText("取消"))

    // 2. 测试教育经历删除二次确认
    const eduSection = document.getElementById("section-education")
    const eduDeleteBtn = Array.from(eduSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(eduDeleteBtn).toBeDefined()
    fireEvent.click(eduDeleteBtn!)
    expect(await screen.findByText(/确认删除教育经历「某财经类大学 · 社会工作」？/)).toBeDefined()
    fireEvent.click(screen.getByText("取消"))

    // 3. 测试求职期望删除二次确认
    const expSection = document.getElementById("section-expectations")
    const expDeleteBtn = Array.from(expSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(expDeleteBtn).toBeDefined()
    fireEvent.click(expDeleteBtn!)
    expect(await screen.findByText(/确认删除求职期望「AI训练师」？/)).toBeDefined()
  })

  it("displays diagnostic action card with Liepin Agent button on writeback failure and triggers agent modal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/unified/sync-back")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            success: false,
            results: [
              {
                platform: "liepin",
                success: false,
                message: "猎聘接口校验异常",
                details: {
                  languages: { success: false, message: "缺少语言熟练度代码" },
                },
              },
            ],
          }),
        })
      }
      if (url.includes("/api/platforms/liepin/agent-diagnose")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            module: "languages",
            module_label: "语言能力",
            rule_code: "RULE_1_LANG_PROFICIENCY_MAPPING",
            rule_name: "猎聘语言代码与熟练度码表对齐法则",
            root_cause: "猎聘要求语言能力装配特定语言码（010普通话/020英语）及熟练度码。",
            confidence: 0.96,
            recipe: {
              action_type: "align_language_codes",
              module: "languages",
              title: "自动映射猎聘标准语言与熟练度代码",
              details: "为普通话和英语等语言条目补齐标准语言码与熟练度等级"
            },
            evidence: { item_count: 1 }
          }),
        })
      }
      if (url.includes("/api/platforms/liepin/agent-apply-heal")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            snapshot_id: "liepin_heal_lang_test.bak.json",
            healed_count: 1,
            message: "猎聘自愈完成！"
          }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ok: true, success: true }),
      })
    }))

    render(<LiepinTab data={mockLiepinData as any} loading={false} onRefresh={vi.fn()} />)

    // Trigger writeback
    fireEvent.click(screen.getByText(/回写选中模块/))
    fireEvent.click(await screen.findByText("确认回写"))

    // Diagnostic Card should appear with Liepin Agent button
    expect(await screen.findByText(/🤖 猎聘 自愈 Agent 待命/)).toBeDefined()
    expect(screen.getByText(/🤖 派出自愈 Agent 深度排查「语言能力」/)).toBeDefined()

    // Click Agent button
    fireEvent.click(screen.getByText(/🤖 派出自愈 Agent 深度排查「语言能力」/))

    // Liepin Agent Modal should open
    expect(await screen.findByText("猎聘数据回写自愈 Agent")).toBeDefined()
    expect(screen.getByText(/猎聘语言代码与熟练度码表对齐法则/)).toBeDefined()

    // Click apply recipe
    const applyHealBtn = screen.getByText(/⚡ 一键应用处方并自动重新回传/)
    fireEvent.click(applyHealBtn)

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/platforms/liepin/agent-apply-heal"),
        expect.anything()
      )
    })
  })
})


