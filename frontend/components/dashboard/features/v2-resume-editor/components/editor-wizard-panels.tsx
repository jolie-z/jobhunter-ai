import { useResumeV2Store } from "@/hooks/use-resume-v2-store"

import { WorkCompressor } from "@/components/dashboard/resume-builder/work-compressor"
import { ProjectPruner } from "@/components/dashboard/resume-builder/project-pruner"
import { InitialDraftReviewer } from "@/components/dashboard/resume-builder/initial-draft-reviewer"

import type { ExperienceV2, ProjectV2 } from "@/types/resume"
import type { JobData } from "@/types/job"
import type { WizardStep } from "../hooks/use-ai-wizard"
import { asLines } from "../utils/resume-search-utils"

interface WizardToolPanelProps {
  open: boolean
  setOpen: (open: boolean) => void
  job?: JobData | null
  wizardStep?: WizardStep
  handleWizardComplete?: (step: string, sectionId?: string) => void
}

/** 工作经历条目 → 面板条目（id=原始下标，跳过空位；includeOriginalContent 供折叠面板回写快照用） */
function toWorkItems(items?: (ExperienceV2 | null | undefined)[], opts?: { includeOriginalContent?: boolean }) {
  const list = items || []
  const out: Array<{ id: string; title: string; content: string; originalContent?: string }> = []
  for (let idx = 0; idx < list.length; idx++) {
    const w = list[idx]
    if (!w) continue
    out.push({
      id: String(idx),
      title: [w.company, w.title].filter(p => p != null && p.trim() !== "").join(" · ") || "未命名经历",
      content: Array.isArray(w.description) ? w.description.join('\n') : (w.description || ""),
      ...(opts?.includeOriginalContent ? { originalContent: w.originalContent } : {}),
    })
  }
  return out
}

/** 项目经历条目 → 面板条目（id=原始下标，跳过空位；idPrefix 供裁剪面板区分主列表 proj- 与归档 arch-，缺省为纯下标） */
function toProjectItems(items?: (ProjectV2 | null | undefined)[], idPrefix?: string) {
  const list = items || []
  const out: Array<{ id: string; title: string; content: string }> = []
  for (let idx = 0; idx < list.length; idx++) {
    const p = list[idx]
    if (!p) continue
    out.push({
      id: idPrefix ? `${idPrefix}${idx}` : String(idx),
      title: p.name || "",
      content: Array.isArray(p.description) ? p.description.join('\n') : (p.description || ""),
    })
  }
  return out
}

function composeDiagnosisSubset(job: JobData | undefined | null, fields: Array<keyof JobData>): string {
  if (!job) return ""
  const parts: string[] = []
  fields.forEach(field => {
    const titleMap: Record<string, string> = {
      dreamPicture: "理想画像与能力信号",
      atsAbilityAnalysis: "核心能力词典",
      strongFitAssessment: "高杠杆匹配点",
      riskRedFlags: "致命硬伤与毒点",
      deepActionPlan: "破局行动计划"
    }
    const val = job[field]
    if (val && typeof val === 'string') {
      parts.push(`【${titleMap[field as string] || field}】\n${val}`)
    }
  })
  return parts.join("\n\n")
}

/** 工作经历「AI判断重写or略写」面板（step1 折叠工具，自 editor-module-renderer 迁出） */
export function WorkCompressPanel({ open, setOpen, job, wizardStep, handleWizardComplete }: WizardToolPanelProps) {
  const { resumeData, updateWorkExperience } = useResumeV2Store()
  if (!open) return null
  return (
    <div data-section-id="compress" className="mb-4">
      <WorkCompressor
        works={toWorkItems(resumeData?.workExperience, { includeOriginalContent: true })}
        customJdContext={job?.jobDescription || ""}
        customDiagnosisContext={composeDiagnosisSubset(job, ['strongFitAssessment', 'dreamPicture'])}
        jobId={job?.id}
        onAccept={(compressions: any[]) => {
          compressions.forEach(c => {
            const idx = parseInt(c.id);
            const old = resumeData?.workExperience[idx];
            if (old) {
              updateWorkExperience(idx, { description: c.newContent.split('\n'), originalContent: old.originalContent || asLines(old.description).join('\n') });
            }
          });
          setOpen(false);
          if (wizardStep === 'step1') {
            handleWizardComplete?.('compress');
          }
        }}
        onCancel={() => setOpen(false)}
      />
    </div>
  )
}

/** 工作经历「AI 初步改写」面板（step2 初改工具，自 editor-module-renderer 迁出） */
export function WorkInitialDraftPanel({ open, setOpen, job, wizardStep, handleWizardComplete }: WizardToolPanelProps) {
  const { resumeData, updateWorkExperience } = useResumeV2Store()
  if (!open) return null
  return (
    <div data-section-id="draft-work" className="mb-4">
      <InitialDraftReviewer
        sections={toWorkItems(resumeData?.workExperience)}
        parentCategory="工作经历"
        customJdContext={job?.jobDescription || ""}
        customDiagnosisContext={composeDiagnosisSubset(job, ['strongFitAssessment', 'dreamPicture'])}
        fullResumeContext={""}
        jobId={job?.id}
        onAccept={(drafts: any[]) => {
          drafts.forEach(draft => {
            const idx = parseInt(draft.id);
            updateWorkExperience(idx, { description: draft.newContent.split('\n') });
          });
          setOpen(false);
          if (wizardStep === 'step2') {
            handleWizardComplete?.('initial_draft_work');
          }
        }}
        onResolveWithoutDraft={wizardStep === 'step2' ? () => handleWizardComplete?.('initial_draft_work') : undefined}
        onCancel={() => setOpen(false)}
      />
    </div>
  )
}

/** 项目经历「AI 智能删减」面板（step1 裁剪工具，自 editor-module-renderer 迁出） */
export function ProjectPrunePanel({ open, setOpen, job, wizardStep, handleWizardComplete }: WizardToolPanelProps) {
  const { resumeData, archiveProject } = useResumeV2Store()
  if (!open) return null
  return (
    <div data-section-id="prune" className="mb-4">
      <ProjectPruner
        projects={toProjectItems(resumeData?.personalProjects, "proj-")}
        archivedProjects={toProjectItems(resumeData?.archivedProjects, "arch-")}
        customJdContext={job?.jobDescription || ""}
        customDiagnosisContext={composeDiagnosisSubset(job, ['riskRedFlags'])}
        jobId={job?.id}
        onAccept={(idsToDelete: any[]) => {
          const sortedIds = idsToDelete.map(id => parseInt(id.replace('proj-', '').replace('arch-', ''))).sort((a, b) => b - a);
          sortedIds.forEach(idx => archiveProject(idx));
          setOpen(false);
          if (wizardStep === 'step1') {
            handleWizardComplete?.('prune');
          }
        }}
        onCancel={() => setOpen(false)}
      />
    </div>
  )
}

/** 项目经历「AI 初步改写」面板（step2 初改工具，自 editor-module-renderer 迁出） */
export function ProjectInitialDraftPanel({ open, setOpen, job, wizardStep, handleWizardComplete }: WizardToolPanelProps) {
  const { resumeData, updateProject } = useResumeV2Store()
  if (!open) return null
  return (
    <div data-section-id="draft-project" className="mb-4">
      <InitialDraftReviewer
        sections={toProjectItems(resumeData?.personalProjects)}
        parentCategory="项目经历"
        customJdContext={job?.jobDescription || ""}
        customDiagnosisContext={composeDiagnosisSubset(job, ['strongFitAssessment', 'dreamPicture'])}
        fullResumeContext={""}
        jobId={job?.id}
        onAccept={(drafts: any[]) => {
          drafts.forEach(draft => {
            const idx = parseInt(draft.id);
            updateProject(idx, { description: draft.newContent.split('\n') });
          });
          setOpen(false);
          if (wizardStep === 'step2') {
            handleWizardComplete?.('initial_draft_project');
          }
        }}
        onResolveWithoutDraft={wizardStep === 'step2' ? () => handleWizardComplete?.('initial_draft_project') : undefined}
        onCancel={() => setOpen(false)}
      />
    </div>
  )
}
