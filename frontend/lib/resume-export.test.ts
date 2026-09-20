import { describe, expect, it } from "vitest"
import { buildResumeExportRequest } from "./resume-export"
import type { ResumeDataV2 } from "@/types/resume"

const job = {
  id: "BOSS直聘-rec123",
  companyName: "测试公司",
  jobTitle: "产品经理",
}

describe("buildResumeExportRequest", () => {
  it("sends the current V2 AST to the V2 PDF endpoint", () => {
    const resumeDataV2: ResumeDataV2 = {
      personalInfo: { name: "候选人", title: "产品经理", phone: "", email: "", location: "" },
      summary: "",
      workExperience: [],
      education: [],
      personalProjects: [],
      additional: { technicalSkills: [], languages: [], certificationsTraining: [] },
      moduleOrder: [],
      moduleTitles: {},
    }

    expect(buildResumeExportRequest(job, resumeDataV2, "pdf", "color_v2")).toEqual({
      endpoint: "/api/jobs/resume-pdf",
      body: {
        job_id: job.id,
        resume_data_v2: resumeDataV2,
        page_size: "A4",
        template: "color_v2",
      },
    })
  })

  it("keeps the legacy route for the markdown editor", () => {
    expect(buildResumeExportRequest(job, null, "pdf", "classic")).toEqual({
      endpoint: "/api/strategy/resume-pdf",
      body: {
        record_id: "BOSS直聘-rec123",
        page_size: "A4",
        source: "job",
        template: "classic",
        company: "测试公司",
        job_title: "产品经理",
      },
    })
  })
})
