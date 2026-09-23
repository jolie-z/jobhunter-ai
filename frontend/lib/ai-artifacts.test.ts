import { describe, it, expect } from "vitest"
import { hasAiArtifact, filterJobsWithAiArtifact, AI_ARTIFACT_LABELS } from "@/lib/ai-artifacts"
import type { JobData } from "@/types/job"

const baseJob = {
  id: "BOSS直聘-rec1",
  companyName: "A公司",
  jobTitle: "岗位一",
} as unknown as JobData

const withField = (fields: Partial<JobData>): JobData =>
  ({ ...baseJob, ...fields }) as unknown as JobData

describe("hasAiArtifact 重复产物判定", () => {
  it("job 为 null/undefined 时返回 false 不抛错（空值防御）", () => {
    expect(hasAiArtifact(null, "evaluate")).toBe(false)
    expect(hasAiArtifact(undefined, "greeting")).toBe(false)
    expect(hasAiArtifact(null, "deep_evaluate")).toBe(false)
  })

  it("evaluate：综合评级非空即视为已有初评产物", () => {
    expect(hasAiArtifact(withField({ grade: "A" }), "evaluate")).toBe(true)
    expect(hasAiArtifact(withField({ grade: "  " }), "evaluate")).toBe(false)
    expect(hasAiArtifact(baseJob, "evaluate")).toBe(false)
  })

  it("deep_evaluate：六个深评字段任一非空即命中", () => {
    expect(
      hasAiArtifact(
        withField({ dreamPicture: "画像", atsAbilityAnalysis: "", resumeAudit: "", strongFitAssessment: "", riskRedFlags: "", deepActionPlan: "" }),
        "deep_evaluate"
      )
    ).toBe(true)
    expect(
      hasAiArtifact(
        withField({ riskRedFlags: "毒点" }),
        "deep_evaluate"
      )
    ).toBe(true)
    expect(
      hasAiArtifact(
        withField({ dreamPicture: "", atsAbilityAnalysis: "", resumeAudit: "", strongFitAssessment: "", riskRedFlags: "", deepActionPlan: "" }),
        "deep_evaluate"
      )
    ).toBe(false)
  })

  it("rewrite：AI改写JSON非空即命中（手工保存也写该字段，同样应警示覆盖）", () => {
    expect(hasAiArtifact(withField({ aiRewriteJson: "{\"a\":1}" }), "rewrite")).toBe(true)
    expect(hasAiArtifact(baseJob, "rewrite")).toBe(false)
  })

  it("greeting：打招呼语非空即命中", () => {
    expect(hasAiArtifact(withField({ greetingMsg: "您好" }), "greeting")).toBe(true)
    expect(hasAiArtifact(baseJob, "greeting")).toBe(false)
  })
})

describe("filterJobsWithAiArtifact", () => {
  it("只保留已存在对应产物的岗位", () => {
    const jobs = [
      withField({ id: "rec1", grade: "B" }),
      baseJob,
      withField({ id: "rec3", grade: " A " }),
    ] as JobData[]
    const hits = filterJobsWithAiArtifact(jobs, "evaluate")
    expect(hits.map((j) => j.id)).toEqual(["rec1", "rec3"])
  })
})

describe("AI_ARTIFACT_LABELS", () => {
  it("四类动作均有中文标签", () => {
    expect(Object.keys(AI_ARTIFACT_LABELS)).toEqual(["evaluate", "deep_evaluate", "rewrite", "greeting"])
    expect(Object.values(AI_ARTIFACT_LABELS).every((l) => l.length > 0)).toBe(true)
  })
})
