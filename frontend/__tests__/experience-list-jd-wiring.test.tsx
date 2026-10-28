import React from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, waitFor } from "@testing-library/react"

/**
 * 定制面板「死参数」修复（2026-10-17）：岗位 JD 经 ExperienceList → ExperienceItem 透传到
 * AtsAligner / ExperienceGriller 的 customJdContext；空/纯空白归一为 undefined 让两面板回退全局画像。
 * 面板借向导队列自动打开（step3+grillQueue / step4+atsQueue），stub 面板只记录收到的 props。
 */

const captured: { grill: any[]; ats: any[] } = { grill: [], ats: [] }

vi.mock("@/lib/api", () => ({ API_BASE: "http://backend.test" }))
vi.mock("@/components/dashboard/resume-builder/experience-griller", () => ({
  ExperienceGriller: (props: any) => {
    captured.grill.push(props)
    return <div data-testid="grill-stub" />
  },
}))
vi.mock("@/components/dashboard/resume-builder/ats-aligner", () => ({
  AtsAligner: (props: any) => {
    captured.ats.push(props)
    return <div data-testid="ats-stub" />
  },
}))
vi.mock("@/hooks/use-resume-v2-store", () => {
  const resumeData = {
    workExperience: [{ company: "某公司", title: "工程师", years: "2023-2024", description: ["做了个数据报表"] }],
    personalProjects: [],
    education: [],
    customModules: {},
  }
  const noop = () => {}
  const store = {
    resumeData,
    updateWorkExperience: noop, updateProject: noop, updateEducation: noop, updateCustomItem: noop,
    removeWorkExperience: noop, removeProject: noop, removeEducation: noop, removeCustomItem: noop,
    addWorkExperience: noop, addProject: noop, addEducation: noop, addCustomItem: noop,
    reorderWorkExperience: noop, reorderProject: noop, reorderEducation: noop, reorderCustomItem: noop,
  }
  const useResumeV2Store = () => store
  ;(useResumeV2Store as any).getState = () => store
  return { useResumeV2Store }
})

import { ExperienceList } from "@/components/dashboard/resume-builder/experience-list"

beforeEach(() => {
  captured.grill.length = 0
  captured.ats.length = 0
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("ExperienceList 透传岗位 JD 到拷问/ATS 面板", () => {
  it("定制面板传入岗位 JD → 经历拷问收到同一字符串", async () => {
    render(<ExperienceList type="workExperience" wizardStep="step3" grillQueue={["work-0"]} customJdContext="某公司 · AI 工程师 JD 原文" />)
    await waitFor(() => expect(captured.grill.length).toBeGreaterThan(0))
    expect(captured.grill[0].customJdContext).toBe("某公司 · AI 工程师 JD 原文")
  })

  it("定制面板传入岗位 JD → ATS 对齐收到同一字符串", async () => {
    render(<ExperienceList type="workExperience" wizardStep="step4" atsQueue={["work-0"]} customJdContext="某公司 · AI 工程师 JD 原文" />)
    await waitFor(() => expect(captured.ats.length).toBeGreaterThan(0))
    expect(captured.ats[0].customJdContext).toBe("某公司 · AI 工程师 JD 原文")
  })

  it("岗位 JD 为纯空白 → 归一为 undefined，面板回退全局画像", async () => {
    render(<ExperienceList type="workExperience" wizardStep="step3" grillQueue={["work-0"]} customJdContext={"   \n\t"} />)
    await waitFor(() => expect(captured.grill.length).toBeGreaterThan(0))
    expect(captured.grill[0].customJdContext).toBeUndefined()
  })

  it("简历库不传该 prop → 面板收到 undefined（行为与修复前一致）", async () => {
    render(<ExperienceList type="workExperience" wizardStep="step4" atsQueue={["work-0"]} />)
    await waitFor(() => expect(captured.ats.length).toBeGreaterThan(0))
    expect(captured.ats[0].customJdContext).toBeUndefined()
  })
})
