import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { act, render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react"
import { ZhilianTab } from "./zhilian-tab"
import { ZhilianCatalogue } from "@/components/ui/zhilian-catalogue"

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
    if (url.includes("/api/resume-editor/save/zhilian")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, message: "保存成功" }),
      })
    }
    if (url.includes("/api/agent-map/reports")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, reports: {} }),
      })
    }
    if (url.includes("/api/agent-map/writeback-save")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, message: "快照已保存" }),
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

const mockZhilianData = {
  profile: {
    name: "张测试",
    gender: "2",
    birthyear: "1995",
    birthmonth: "06",
    mobile: "13800000000",
    email: "test@example.com",
    currentCity: "广州",
    currentProvince: "广东",
    currentIdentity: "1",
    currentStatus: "1",
    eduHighestLevel: "4",
    maritalStatus: "1",
  },
  selfEvaluation: [
    {
      selfEvaTitle: "自我介绍",
      selfEvaContent: "5年全栈开发经验，精通 React 与 Python FastAPI。",
    },
  ],
  jobStatus: {
    jobState: "在职-暂不考虑",
    jobStateCode: "1",
  },
  wanna: [
    {
      title: "期望职位",
      preferredJobNature: "1",
      preferredJobNatureTranslation: "全职",
      pnewPreferredJobType: "全栈工程师",
      pnewPreferredJobTypeTranslation: "全栈工程师",
      preferredLocation: "530",
      preferredSalaryMin: 20000,
      preferredSalaryMax: 30000,
    },
  ],
  workExperience: [
    {
      companyName: "某科技公司",
      jobTitle: "全栈工程师",
      startDate: 1711929600000,
      endDate: 0,
      workDesc: "负责系统架构与研发。",
    },
  ],
  education: [
    {
      eduSchoolName: "临江大学",
      eduMajorV: "软件工程",
      eduBackgroundTranslation: "本科",
      eduStartDate: 1409529600000,
      eduEndDate: 1527811200000,
    },
  ],
  project: [
    {
      proExpProjectName: "JobHunter AI",
      proExpStartDate: 1704067200000,
      proExpEndDate: 1717200000000,
      proExpProjectDesc: "求职自动化系统",
    },
  ],
  training: [
    {
      trainName: "高级系统架构师实战",
      trainCourse: "架构与微服务",
      trainStartDate: 1680307200000,
      trainEndDate: 1682899200000,
    },
  ],
  language: [
    {
      langLanguageT: "英语",
      langLSProficiency: "熟练",
      langRWProficiency: "熟练",
      langCertificatesFormat: [{ certificateName: "CET-6" }],
    },
  ],
  professionalSkills: [
    {
      proskillName: "React",
      proskillLevel: "精通",
      proskillUseTime: "36",
    },
  ],
  certificate: [
    {
      certUserdefName: "PMP",
      certDate: 1654041600000,
    },
  ],
  works: [],
}

describe("ZhilianCatalogue Component", () => {
  it("renders all 12 catalogue navigation items", async () => {
    await renderAsync(<ZhilianCatalogue />)

    expect(screen.getByText("简历目录")).toBeDefined()
    expect(screen.getByText("基本信息")).toBeDefined()
    expect(screen.getByText("自我评价")).toBeDefined()
    expect(screen.getByText("求职状态")).toBeDefined()
    expect(screen.getByText("求职意向")).toBeDefined()
    expect(screen.getByText("工作经历")).toBeDefined()
    expect(screen.getByText("教育经历")).toBeDefined()
    expect(screen.getByText("项目经历")).toBeDefined()
    expect(screen.getByText("培训经历")).toBeDefined()
    expect(screen.getByText("语言能力")).toBeDefined()
    expect(screen.getByText("专业技能")).toBeDefined()
    expect(screen.getByText("资格证书")).toBeDefined()
    expect(screen.getByText("作品展示")).toBeDefined()
  })

  it("handles smooth scroll when catalogue item is clicked", async () => {
    await renderAsync(
      <div>
        <ZhilianCatalogue />
        <div id="section-workExp">Work Exp Section</div>
      </div>
    )

    const workExpBtn = screen.getByText("工作经历")
    fireEvent.click(workExpBtn)

    const targetEl = document.getElementById("section-workExp")
    expect(targetEl?.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" })
  })
})

describe("ZhilianTab Component Integration", () => {
  it("renders sidebar catalogue alongside Zhilian modules", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)

    // Catalogue is rendered
    expect(screen.getByText("简历目录")).toBeDefined()
    expect(screen.getByText("智联模块回写")).toBeDefined()

    // 12 sections are in the DOM
    expect(document.getElementById("section-baseInfo")).not.toBeNull()
    expect(document.getElementById("section-selfEval")).not.toBeNull()
    expect(document.getElementById("section-jobStatus")).not.toBeNull()
    expect(document.getElementById("section-wanna")).not.toBeNull()
    expect(document.getElementById("section-workExp")).not.toBeNull()
    expect(document.getElementById("section-education")).not.toBeNull()
    expect(document.getElementById("section-projects")).not.toBeNull()
    expect(document.getElementById("section-training")).not.toBeNull()
    expect(document.getElementById("section-languages")).not.toBeNull()
    expect(document.getElementById("section-skills")).not.toBeNull()
    expect(document.getElementById("section-certificates")).not.toBeNull()
    expect(document.getElementById("section-works")).not.toBeNull()
  })

  it("triggers AlertDialog when clicking delete on a work experience item and allows cancel", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)

    const workExpSection = document.getElementById("section-workExp")
    expect(workExpSection).not.toBeNull()
    const deleteBtn = Array.from(workExpSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)

    // Dialog appears
    await waitFor(() => {
      expect(screen.getByText("确认删除工作经历「某科技公司」？")).toBeDefined()
      expect(screen.getByText("此操作将从本地数据中移除该条目，需点击「保存快照」或「回写官网」后生效。")).toBeDefined()
    })

    // Click Cancel
    const cancelBtn = screen.getByText("取消")
    fireEvent.click(cancelBtn)

    // Confirm dialog is dismissed
    await waitFor(() => {
      expect(screen.queryByText("确认删除工作经历「某科技公司」？")).toBeNull()
    })
  })

  it("confirms deletion in AlertDialog and updates local data via persistData", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)

    const workExpSection = document.getElementById("section-workExp")
    const deleteBtn = Array.from(workExpSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    fireEvent.click(deleteBtn!)

    expect(await screen.findByText("确认删除工作经历「某科技公司」？")).toBeDefined()

    const confirmBtn = screen.getByText("确认删除")
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/resume-editor/save/zhilian"),
        expect.objectContaining({
          method: "POST",
        })
      )
    })
  }, 10000)

  it("triggers double check confirm dialog when clicking delete on wanna (求职意向)", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    const wannaSection = document.getElementById("section-wanna")
    const deleteBtn = Array.from(wannaSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)
    expect(await screen.findByText("确认删除求职意向「全栈工程师」？")).toBeDefined()
    fireEvent.click(screen.getByText("取消"))
    await waitFor(() => {
      expect(screen.queryByText("确认删除求职意向「全栈工程师」？")).toBeNull()
    })
  })

  it("triggers double check confirm dialog when clicking delete on education (教育经历)", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    const eduSection = document.getElementById("section-education")
    const deleteBtn = Array.from(eduSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)
    expect(await screen.findByText("确认删除教育经历「临江大学」？")).toBeDefined()
    fireEvent.click(screen.getByText("取消"))
    await waitFor(() => {
      expect(screen.queryByText("确认删除教育经历「临江大学」？")).toBeNull()
    })
  })

  it("triggers double check confirm dialog when clicking delete on project (项目经历)", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    const projSection = document.getElementById("section-projects")
    const deleteBtn = Array.from(projSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)
    expect(await screen.findByText("确认删除项目经历「JobHunter AI」？")).toBeDefined()
    fireEvent.click(screen.getByText("取消"))
    await waitFor(() => {
      expect(screen.queryByText("确认删除项目经历「JobHunter AI」？")).toBeNull()
    })
  })

  it("triggers double check confirm dialog when clicking delete on training (培训经历)", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    const trainSection = document.getElementById("section-training")
    const deleteBtn = Array.from(trainSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)
    expect(await screen.findByText("确认删除培训经历「高级系统架构师实战」？")).toBeDefined()
    fireEvent.click(screen.getByText("取消"))
    await waitFor(() => {
      expect(screen.queryByText("确认删除培训经历「高级系统架构师实战」？")).toBeNull()
    })
  })

  it("triggers double check confirm dialog when clicking delete on language (语言能力)", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    const langSection = document.getElementById("section-languages")
    const deleteBtn = Array.from(langSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)
    expect(await screen.findByText("确认删除语言能力「英语」？")).toBeDefined()
    fireEvent.click(screen.getByText("取消"))
    await waitFor(() => {
      expect(screen.queryByText("确认删除语言能力「英语」？")).toBeNull()
    })
  })

  it("triggers double check confirm dialog when clicking delete on professional skills (专业技能)", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    const skillSection = document.getElementById("section-skills")
    const deleteBtn = Array.from(skillSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)
    expect(await screen.findByText("确认删除专业技能「React」？")).toBeDefined()
    fireEvent.click(screen.getByText("取消"))
    await waitFor(() => {
      expect(screen.queryByText("确认删除专业技能「React」？")).toBeNull()
    })
  })

  it("triggers double check confirm dialog when clicking delete on certificates (资格证书)", async () => {
    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    const certSection = document.getElementById("section-certificates")
    const deleteBtn = Array.from(certSection?.querySelectorAll("button") || []).find(b => b.textContent === "删除")
    expect(deleteBtn).toBeDefined()
    fireEvent.click(deleteBtn!)
    expect(await screen.findByText("确认删除证书「PMP」？")).toBeDefined()
    fireEvent.click(screen.getByText("取消"))
    await waitFor(() => {
      expect(screen.queryByText("确认删除证书「PMP」？")).toBeNull()
    })
  })

  it("displays structured feedback details and allows toggling raw output logs on writeback", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/agent-map/write-back")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            success: false,
            message: "回写完成 3/3，复核异常 1 项",
            verify: [
              { module: "work_experience", match: false, note: "未找到匹配条目（Career Sabbatical）" }
            ],
            output: "=== 智联招聘回写终端日志 ===\n[OP] updateResumeAction\n[VERIFY] failed: work_experience",
          }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true }),
      })
    }))

    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)
    // Click writeback button
    const wbBtn = screen.getByText(/回写选中模块/)
    fireEvent.click(wbBtn)

    // Click confirm writeback
    const confirmBtn = await screen.findByText("确认回写")
    fireEvent.click(confirmBtn)

    // Should display error status and structured detail
    expect(await screen.findByText(/回写完成 3\/3，复核异常 1 项/)).toBeDefined()
    expect(screen.getByText("工作经历:")).toBeDefined()
    expect(screen.getByText("未找到匹配条目（Career Sabbatical）")).toBeDefined()

    // Click 查看日志
    const logBtn = screen.getByText("查看日志")
    fireEvent.click(logBtn)

    // Terminal output should now be visible
    expect(screen.getByText(/=== 智联招聘回写终端日志 ===/)).toBeDefined()

    // Click 收起日志
    fireEvent.click(screen.getByText("收起日志"))
    expect(screen.queryByText(/=== 智联招聘回写终端日志 ===/)).toBeNull()
  })

  it("displays diagnostic action card with Agent button on writeback failure and triggers agent diagnosis modal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/agent-map/write-back")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            success: false,
            message: "官网校验异常",
            verify: [{ module: "certificates", match: false, note: "未找到匹配条目" }],
          }),
        })
      }
      if (url.includes("/api/platforms/zhilian/agent-diagnose")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            module: "certificates",
            module_label: "资格证书",
            rule_code: "RULE_1_ACTION_ROUTING",
            rule_name: "专用批量接口路由与 Store 刷新机制",
            root_cause: "智联官网资格证书模块采用专属批量保存接口 saveCertificationList",
            confidence: 0.98,
            recipe: {
              action_type: "normalize_certs",
              module: "certificates",
              title: "对齐资格证书字段并强制刷新 Vuex 缓存",
              details: "规范化本地证书结构"
            },
            evidence: { official_items_count: 1 }
          }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ok: true, success: true }),
      })
    }))

    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)

    // Trigger writeback
    fireEvent.click(screen.getByText(/回写选中模块/))
    fireEvent.click(await screen.findByText("确认回写"))

    // Diagnostic Card should appear with Agent button
    expect(await screen.findByText(/🤖 自愈 Agent 待命/)).toBeDefined()
    expect(screen.getByText(/🤖 派出自愈 Agent 深度排查「资格证书」/)).toBeDefined()

    // Click Agent button
    fireEvent.click(screen.getByText(/🤖 派出自愈 Agent 深度排查「资格证书」/))

    // Agent Modal should open
    expect(await screen.findByText("智联招聘数据回写自愈 Agent")).toBeDefined()
    expect(screen.getByText(/专用批量接口路由与 Store 刷新机制/)).toBeDefined()
    expect(screen.getByText(/⚡ 一键应用处方并自动重新回传/)).toBeDefined()
  })

  it("handles agent self-heal confirmation and applies recipe", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/agent-map/write-back")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            success: false,
            message: "官网回写失败",
            verify: [{ module: "certificates", match: false, note: "缺少字段" }],
          }),
        })
      }
      if (url.includes("/api/platforms/zhilian/agent-diagnose")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            module: "certificates",
            module_label: "资格证书",
            rule_code: "RULE_1_ACTION_ROUTING",
            rule_name: "专用批量接口路由",
            root_cause: "专用批量保存接口",
            recipe: {
              action_type: "normalize_certs",
              module: "certificates",
              title: "对齐资格证书字段",
            }
          }),
        })
      }
      if (url.includes("/api/platforms/zhilian/agent-apply-heal")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ok: true,
            snapshot_id: "zhilian_heal_cert_test.bak.json",
            healed_count: 1,
            message: "自愈完成！"
          }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ok: true, success: true }),
      })
    }))

    await renderAsync(<ZhilianTab data={mockZhilianData as any} loading={false} onRefresh={vi.fn()} />)

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
        expect.stringContaining("/api/platforms/zhilian/agent-apply-heal"),
        expect.anything()
      )
    })
  })
})



