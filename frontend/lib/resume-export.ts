import type { JobData } from "@/types/job"
import type { ResumeDataV2 } from "@/types/resume"

export type ResumeExportType = "pdf" | "image"
export type ResumeExportTemplate = "classic" | "color" | "color_v2"

type ResumeExportJob = Pick<JobData, "id" | "companyName" | "jobTitle">

export interface ResumeExportRequest {
  endpoint: string
  body: Record<string, unknown>
}

/**
 * Build the export request for the active editor mode.
 *
 * V2 must send the in-memory AST directly.  The legacy route remains for the
 * old markdown editor, which does not have a ResumeDataV2 value to send.
 */
export function buildResumeExportRequest(
  job: ResumeExportJob,
  resumeDataV2: ResumeDataV2 | null,
  type: ResumeExportType,
  template: ResumeExportTemplate,
): ResumeExportRequest {
  if (resumeDataV2) {
    return {
      endpoint: type === "pdf" ? "/api/jobs/resume-pdf" : "/api/jobs/resume-images",
      body: {
        job_id: job.id,
        resume_data_v2: resumeDataV2,
        page_size: "A4",
        template,
      },
    }
  }

  const recordId = job.id.split("/").pop() || job.id
  return {
    endpoint: type === "pdf" ? "/api/strategy/resume-pdf" : "/api/strategy/resume-images",
    body: {
      record_id: recordId,
      page_size: "A4",
      source: "job",
      template,
      company: job.companyName || "",
      job_title: job.jobTitle || "",
    },
  }
}
