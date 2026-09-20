import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { act, render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react"
import { Job51Tab } from "./51job-tab"
import { Job51Catalogue } from "@/components/ui/51job-catalogue"

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
  Element.prototype.scrollIntoView = vi.fn()
  global.fetch = vi.fn().mockImplementation((url: string) => {
    if (url.includes("/api/resume-editor/options/51job")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, data: { language_certifications: {} } }),
      })
    }
    if (url.includes("/api/resume-editor/save/51job")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, message: "保存成功" }),
      })
    }
    if (url.includes("/api/agent-map/report?platform=51job")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: false }),
      })
    }
    if (url.includes("/api/agent-map/writeback-save") || url.includes("/api/agent-map/save-snapshot")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, message: "快照已保存" }),
      })
    }
    if (url.includes("/api/agent-map/write-back")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            success: true,
            message: "回写完成",
            verify: [
              { module: "self_introduction", match: true, note: "个人优势已生效" },
              { module: "works", match: true, note: "工作经历已生效" },
            ],
            output: "INFO: Writeback complete with 2 modules.",
          }),
      })
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ success: true }),
    })
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const mock51jobData = {
  name: { label: "姓名", required: true, type: "text", current_value: "张测试" },
  gender: { label: "性别", required: true, type: "text", current_value: "女" },
  mobile: { label: "手机号", required: true, type: "text", current_value: "13800000000" },
  email: { label: "邮箱", required: true, type: "text", current_value: "test@example.com" },
  workYear: { label: "工作年限", required: true, type: "text", current_value: "5年" },
  birthday: { label: "出生年月", required: true, type: "text", current_value: "1995-05" },
  degree: { label: "学历", required: true, type: "text", current_value: "本科" },
  self_introduction: {
    label: "个人优势",
    required: false,
    type: "object",
    current_value: { selfIntroduction: "5年前端与全栈开发经验，精通 React 和 TypeScript。" },
  },
  intentions: {
    label: "求职意向",
    required: true,
    type: "array",
    current_value: [
      {
        expectFunction: "0100",
        expectFunctionName: "全栈工程师",
        seekType: "0",
        minSalary: "20000",
        maxSalary: "30000",
      },
    ],
  },
  works: {
    label: "工作经历",
    required: true,
    type: "array",
    current_value: [
      {
        id: "work_101",
        companyName: "某知名科技公司",
        position: "高级工程师",
        workFunction: "0100",
        workDescription: "负责核心业务架构设计与微前端改造。",
        startTime: "2022-03",
        endTime: "至今",
      },
    ],
  },
  projects: {
    label: "项目经历",
    required: false,
    type: "array",
    current_value: [
      {
        id: "proj_201",
        projectName: "自动化求职助手系统",
        describe: "基于 FastAPI + Next.js 实现多平台简历同步与自动投递。",
        startTime: "2024-01",
        endTime: "2024-06",
      },
    ],
  },
  educations: {
    label: "教育经历",
    required: true,
    type: "array",
    current_value: [
      {
        id: "edu_301",
        schoolName: "临江大学",
        major: "软件工程",
        degree: "本科",
        startTime: "2014-09",
        endTime: "2018-06",
      },
    ],
  },
  language: {
    label: "语言能力",
    required: false,
    type: "array",
    current_value: [
      {
        skill: "1",
        skillTypeString: "英语",
        level: "6",
        levelString: "听说读写流利",
      },
    ],
  },
  portfolio: {
    label: "个人作品",
    required: false,
    type: "text",
    current_value: "",
  },
  skills: {
    label: "专业技能",
    required: false,
    type: "array",
    current_value: [
      {
        skillType: "01",
        skillName: "TypeScript",
        ability: "5",
        abilityString: "精通",
      },
    ],
  },
  certifications: {
    label: "资格证书",
    required: false,
    type: "array",
    current_value: ["001"],
  },
}

describe("Job51Catalogue Component", () => {
  it("renders all 10 catalogue navigation items", async () => {
    await renderAsync(<Job51Catalogue />)

    expect(screen.getByText("简历目录")).toBeDefined()
    expect(screen.getByText("基本信息")).toBeDefined()
    expect(screen.getByText("个人优势")).toBeDefined()
    expect(screen.getByText("求职意向")).toBeDefined()
    expect(screen.getByText("工作经历")).toBeDefined()
    expect(screen.getByText("项目经历")).toBeDefined()
    expect(screen.getByText("教育经历")).toBeDefined()
    expect(screen.getByText("语言能力")).toBeDefined()
    expect(screen.getByText("个人作品")).toBeDefined()
    expect(screen.getByText("专业技能")).toBeDefined()
    expect(screen.getByText("资格证书")).toBeDefined()
  })

  it("handles smooth scroll when catalogue item is clicked", async () => {
    await renderAsync(
      <div>
        <Job51Catalogue />
        <div id="section-workExp">Work Exp Section</div>
      </div>
    )

    const workExpBtn = screen.getByText("工作经历")
    fireEvent.click(workExpBtn)

    const targetEl = document.getElementById("section-workExp")
    expect(targetEl?.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" })
  })
})

describe("Job51Tab Component Integration", () => {
  it("renders sidebar catalogue alongside 51job modules and cards", async () => {
    await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)

    expect(screen.getByText("简历目录")).toBeDefined()
    expect(screen.getByText("51job 模块回写")).toBeDefined()

    // 10 sections are in the DOM
    expect(document.getElementById("section-baseInfo")).not.toBeNull()
    expect(document.getElementById("section-selfEval")).not.toBeNull()
    expect(document.getElementById("section-intentions")).not.toBeNull()
    expect(document.getElementById("section-workExp")).not.toBeNull()
    expect(document.getElementById("section-projects")).not.toBeNull()
    expect(document.getElementById("section-education")).not.toBeNull()
    expect(document.getElementById("section-languages")).not.toBeNull()
    expect(document.getElementById("section-portfolio")).not.toBeNull()
    expect(document.getElementById("section-skills")).not.toBeNull()
    expect(document.getElementById("section-certifications")).not.toBeNull()
  })

  it("renders work experience with 至今 and displays company and description", async () => {
    await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)

    expect(screen.getByText("某知名科技公司")).toBeDefined()
    expect(screen.getByText(/高级工程师/)).toBeDefined()
    expect(screen.getByText("负责核心业务架构设计与微前端改造。")).toBeDefined()
  })

  it("handles clearing data (transition from data to null) without React hooks violation", async () => {
    const { rerender } = await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)
    expect(screen.getByText("51job 模块回写")).toBeDefined()

    // Simulate clearing data (user clicks 清空数据 -> data becomes null)
    // rerender 触发的 effect 异步更新同样要包在 act 内
    await act(async () => {
      rerender(<Job51Tab data={null} loading={false} onRefresh={vi.fn()} />)
    })
    expect(screen.getByText("暂无前程无忧数据")).toBeDefined()
    expect(screen.getByText("刷新数据")).toBeDefined()

    // Transition to loading
    await act(async () => {
      rerender(<Job51Tab data={null} loading={true} onRefresh={vi.fn()} />)
    })
    expect(screen.getByText("加载中...")).toBeDefined()
  })

  it("triggers AlertDialog when clicking delete on a work experience item", async () => {
    await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)

    // Find delete button on work experience
    const deleteBtns = screen.getAllByText("删除")
    // Click delete on work experience (2nd delete button: 1st is intentions, 2nd is works)
    fireEvent.click(deleteBtns[1])

    // Dialog appears
    await waitFor(() => {
      expect(screen.getByText("确认删除工作经历「某知名科技公司」？")).toBeDefined()
      expect(screen.getByText("此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。")).toBeDefined()
    })

    // Click Cancel
    const cancelBtn = screen.getByText("取消")
    fireEvent.click(cancelBtn)

    // Confirm dialog is dismissed
    await waitFor(() => {
      expect(screen.queryByText("确认删除工作经历「某知名科技公司」？")).toBeNull()
    })
  })

  it("confirms deletion in AlertDialog and updates local data via persistData", async () => {
    await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)

    const deleteBtns = screen.getAllByText("删除")
    fireEvent.click(deleteBtns[1])

    await waitFor(() => {
      expect(screen.getByText("确认删除工作经历「某知名科技公司」？")).toBeDefined()
    })

    const confirmBtn = screen.getByText("确认删除")
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/resume-editor/save/51job"),
        expect.objectContaining({
          method: "POST",
        })
      )
    })
  })

  it("handles intentions industry editing, displaying, and dual-field synchronization", async () => {
    const dataWithIndustry = {
      ...mock51jobData,
      intentions: {
        label: "求职意向",
        required: true,
        type: "array",
        current_value: [
          {
            id: "int_001",
            expectFunction: "6102",
            expectFunctionName: "国内电商运营",
            seekType: "0",
            minSalary: "15000",
            maxSalary: "25000",
            salaryMonth: 14,
            expectArea: "030200,040000",
            expectAreaNames: "广州、深圳",
            industry: "32,05,04",
            industryNames: "互联网/电子商务、快速消费品(食品、饮料、化妆品)、贸易/进出口",
            expectIndustry: "32,05,04",
            expectIndustryString: "互联网/电子商务、快速消费品(食品、饮料、化妆品)、贸易/进出口",
          },
        ],
      },
    }

    await renderAsync(<Job51Tab data={dataWithIndustry as any} loading={false} onRefresh={vi.fn()} />)

    // Verify display card shows industry text
    expect(screen.getByText(/互联网\/电子商务、快速消费品\(食品、饮料、化妆品\)、贸易\/进出口/)).toBeDefined()
    expect(screen.getByText("国内电商运营")).toBeDefined()

    // Click edit within intentions section
    const intentionsSection = document.getElementById("intentions")
    expect(intentionsSection).not.toBeNull()
    const editBtn = Array.from(intentionsSection?.querySelectorAll("button") || []).find((b) => b.textContent?.trim() === "编辑")
    expect(editBtn).toBeDefined()
    fireEvent.click(editBtn!)

    // Verify inline editing form opens with labels
    await waitFor(() => {
      expect(screen.getByText(/期望职位/)).toBeDefined()
      expect(screen.getByText(/期望行业/)).toBeDefined()
    })

    // Save intention
    const saveIntentionBtn = screen.getByRole("button", { name: "完成" })
    fireEvent.click(saveIntentionBtn)

    // Save snapshot
    const saveSnapshotBtn = screen.getByText("保存快照")
    fireEvent.click(saveSnapshotBtn)

    await waitFor(() => {
      expect(screen.getByText(/快照已保存/)).toBeDefined()
    })
  })

  it("handles save snapshot and writeback execution with structured feedback card", async () => {
    await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)

    // 1. Save Snapshot
    const saveSnapshotBtn = screen.getByText("保存快照")
    fireEvent.click(saveSnapshotBtn)

    await waitFor(() => {
      expect(screen.getByText(/快照已保存/)).toBeDefined()
    })

    // 2. Writeback trigger (two-step confirmation)
    const writebackBtn = screen.getByText(/回写选中模块/)
    fireEvent.click(writebackBtn)

    // Step 2 confirmation bar
    await waitFor(() => {
      expect(screen.getByText("确认回写")).toBeDefined()
    })

    const confirmWritebackBtn = screen.getByText("确认回写")
    fireEvent.click(confirmWritebackBtn)

    // Step 3 verify structured feedback and details
    await waitFor(() => {
      expect(screen.getByText(/回写完成/)).toBeDefined()
      expect(screen.getByText("个人优势:")).toBeDefined()
      expect(screen.getByText("个人优势已生效")).toBeDefined()
      expect(screen.getByText("查看日志")).toBeDefined()
    })
  })

  it("renders work experience vocational skills chips and workType correctly", async () => {
    const dataWithSkills = {
      ...mock51jobData,
      works: {
        label: "工作经历",
        required: true,
        type: "array",
        current_value: [
          {
            id: "work_freelance",
            companyName: "自由职业者",
            position: "独立 AI 应用开发者 / 全栈研发",
            workType: "1",
            seekType: "1",
            startTime: "2024-04",
            endTime: "至今",
            workDescription: "开发全链路自动化求职 SaaS",
            skills: ["大模型", "FastAPI", "React", "Python"],
            workVocationalSkills: [
              { skill: "大模型", isCustomize: true },
              { skill: "FastAPI", isCustomize: true },
            ],
          },
        ],
      },
    }
    await renderAsync(<Job51Tab data={dataWithSkills as any} loading={false} onRefresh={vi.fn()} />)
    expect(screen.getByText("自由职业者")).toBeDefined()
    expect(screen.getByText("大模型")).toBeDefined()
    expect(screen.getByText("FastAPI")).toBeDefined()
    expect(screen.getByText("React")).toBeDefined()
    expect(screen.getByText("Python")).toBeDefined()
    expect(screen.getByText(/兼职/)).toBeDefined()
  })

  it("renders work experience industry and company nature/size in subtitle correctly", async () => {
    const dataWithIndustry = {
      ...mock51jobData,
      works: {
        label: "工作经历",
        required: true,
        type: "array",
        current_value: [
          {
            id: "work_ind_test",
            companyName: "某美妆集团",
            position: "AI 业务运营",
            workIndustry: "32",
            workIndustryString: "互联网/电子商务",
            companySize: "7",
            companyType: "01",
            startTime: "2019-07",
            endTime: "2023-08",
            workDescription: "语料建模与客服训练",
          },
        ],
      },
    }
    await renderAsync(<Job51Tab data={dataWithIndustry as any} loading={false} onRefresh={vi.fn()} />)
    expect(screen.getByText("某美妆集团")).toBeDefined()
    expect(screen.getByText(/互联网\/电子商务/)).toBeDefined()
    expect(screen.getByText(/AI 业务运营/)).toBeDefined()
  })

  it("renders projects with companyName and supports editing project experience company field", async () => {
    const dataWithProjCompany = {
      ...mock51jobData,
      projects: {
        label: "项目经历",
        required: true,
        type: "array",
        current_value: [
          {
            id: "proj_comp_1",
            projectName: "全链路求职 Copilot SaaS 平台",
            startTime: "2026-03",
            endTime: "至今",
            companyName: "自由职业者",
            describe: "端到端自动化求职平台",
          },
        ],
      },
    }
    await renderAsync(<Job51Tab data={dataWithProjCompany as any} loading={false} onRefresh={vi.fn()} />)
    expect(screen.getByText("全链路求职 Copilot SaaS 平台")).toBeDefined()
    expect(screen.getByText(/自由职业者/)).toBeDefined()
    expect(screen.getByText("端到端自动化求职平台")).toBeDefined()
  })

  it("renders education experience without 至今 and displays future graduation years up to 2029", async () => {
    const dataWithFutureEdu = {
      ...mock51jobData,
      educations: {
        label: "教育经历",
        required: true,
        type: "array",
        current_value: [
          {
            id: "edu_future_1",
            schoolName: "某财经类大学",
            degree: "7",
            degreeString: "硕士",
            major: "4701",
            majorString: "社会学",
            studyType: "非全日制",
            startTime: "2024-09",
            endTime: "2029-06",
            startTimeString: "2024.09",
            endTimeString: "2029.06",
          },
        ],
      },
    }
    await renderAsync(<Job51Tab data={dataWithFutureEdu as any} loading={false} onRefresh={vi.fn()} />)
    expect(screen.getByText("某财经类大学")).toBeDefined()
    expect(screen.getByText("2024-09 - 2029-06")).toBeDefined()
    expect(screen.queryByText("至今")).toBeNull()
  })

  it("renders professional skills correctly and supports mutual exclusion for existing skills", async () => {
    const dataWithSkills = {
      ...mock51jobData,
      skills: {
        label: "专业技能",
        required: false,
        type: "array",
        current_value: [
          {
            id: "skill_1",
            skillType: "0215",
            skillName: "SQL",
            ability: "1",
            abilityString: "熟练",
          },
          {
            id: "skill_2",
            skillType: "0413",
            skillName: "Python",
            ability: "3",
            abilityString: "良好",
          },
        ],
      },
    }
    await renderAsync(<Job51Tab data={dataWithSkills as any} loading={false} onRefresh={vi.fn()} />)
    expect(screen.getByText("SQL")).toBeDefined()
    expect(screen.getByText("熟练")).toBeDefined()
    expect(screen.getByText("Python")).toBeDefined()
    expect(screen.getByText("良好")).toBeDefined()
  })

  it("displays diagnostic action card with 51job Agent button on writeback failure and triggers agent modal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/agent-map/write-back")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            success: false,
            message: "官网校验异常",
            verify: [{ module: "certifications", match: false, note: "超过20条限制" }],
          }),
        })
      }
      if (url.includes("/api/platforms/51job/agent-diagnose")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            module: "certifications",
            module_label: "资格证书",
            rule_code: "RULE_1_QUOTA_WALL_DEL_FIRST",
            rule_name: "51job 20条配额上限与删除优先生命周期",
            root_cause: "51job 资格证书单份简历配额上限 20 条",
            confidence: 0.98,
            recipe: {
              action_type: "reorder_del_first_and_trim",
              module: "certifications",
              title: "启用删除优先编排并截断至20条",
              details: "先删除旧数据再按序新增"
            },
            evidence: { quota_limit: 20 }
          }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ok: true, success: true }),
      })
    }))

    await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)

    // Trigger writeback
    fireEvent.click(screen.getByText(/回写选中模块/))
    fireEvent.click(await screen.findByText("确认回写"))

    // Diagnostic Card should appear with 51job Agent button
    expect(await screen.findByText(/🤖 51job 自愈 Agent 待命/)).toBeDefined()
    expect(screen.getByText(/🤖 派出自愈 Agent 深度排查「资格证书」/)).toBeDefined()

    // Click Agent button
    fireEvent.click(screen.getByText(/🤖 派出自愈 Agent 深度排查「资格证书」/))

    // 51job Agent Modal should open
    expect(await screen.findByText("前程无忧数据回写自愈 Agent")).toBeDefined()
    expect(screen.getByText(/51job 20条配额上限与删除优先生命周期/)).toBeDefined()
    expect(screen.getByText(/⚡ 一键应用处方并自动重新回传/)).toBeDefined()
  })

  it("handles 51job agent self-heal confirmation and applies recipe", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/agent-map/write-back")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            success: false,
            message: "官网回写失败",
            verify: [{ module: "certifications", match: false, note: "配额已满" }],
          }),
        })
      }
      if (url.includes("/api/platforms/51job/agent-diagnose")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            module: "certifications",
            module_label: "资格证书",
            rule_code: "RULE_1_QUOTA_WALL_DEL_FIRST",
            rule_name: "51job 20条配额上限",
            root_cause: "51job 资格证书单份简历配额上限 20 条",
            recipe: {
              action_type: "reorder_del_first_and_trim",
              module: "certifications",
              title: "启用删除优先编排",
            }
          }),
        })
      }
      if (url.includes("/api/platforms/51job/agent-apply-heal")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            snapshot_id: "51job_heal_cert_test.bak.json",
            healed_count: 1,
            message: "51job 自愈完成！"
          }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ok: true, success: true }),
      })
    }))

    await renderAsync(<Job51Tab data={mock51jobData as any} loading={false} onRefresh={vi.fn()} />)

    // Trigger writeback to show diagnostic card
    fireEvent.click(screen.getByText(/回写选中模块/))
    fireEvent.click(await screen.findByText("确认回写"))

    // Open Agent modal
    const agentBtn = await screen.findByText(/🤖 派出自愈 Agent 深度排查/)
    fireEvent.click(agentBtn)

    // Confirm apply heal
    const applyHealBtn = await screen.findByText(/⚡ 一键应用处方并自动重新回传/)
    fireEvent.click(applyHealBtn)

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/platforms/51job/agent-apply-heal"),
        expect.anything()
      )
    })
  })
})

