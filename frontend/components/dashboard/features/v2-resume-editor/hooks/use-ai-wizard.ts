import { API_BASE } from "@/lib/api"
import { useState, useCallback, useEffect, useRef, useMemo } from "react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { JobData } from "@/types/job"
import type { GrillSuggestion } from "@/components/dashboard/resume-builder/grill-suggestion-panel"
import { asLines } from "../utils/resume-search-utils"

export type WizardStep = 'idle' | 'step1' | 'step2' | 'step3' | 'step4' | 'step5' | 'step6'

export interface WizardProgress {
  pruneDone: boolean
  compressDone: boolean
  initialDraftProjectDone: boolean
  initialDraftWorkDone: boolean
  grillDone: boolean
  atsDone: boolean
  syncDone: boolean
  savedDone: boolean
}

export const DEFAULT_WIZARD_PROGRESS: WizardProgress = {
  pruneDone: false, compressDone: false, initialDraftProjectDone: false,
  initialDraftWorkDone: false, grillDone: false, atsDone: false, syncDone: false, savedDone: false
}

// 拼接标题：过滤空值和空字符串，用 " · " 连接
function joinTitle(...parts: (string | undefined)[]): string {
  return parts.filter(p => p != null && p.trim() !== "").join(" · ") || ""
}

export function useAiWizard(job?: JobData | null) {
  const { resumeData } = useResumeV2Store()

  const [wizardStep, setWizardStep] = useState<WizardStep>('idle')
  const [wizardProgress, setWizardProgress] = useState<WizardProgress>(DEFAULT_WIZARD_PROGRESS)
  const [wizardHidden, setWizardHidden] = useState(false)

  // Step 3 Grill：建议列表 + 待处理队列
  const [grillSuggestions, setGrillSuggestions] = useState<GrillSuggestion[]>([])
  const [isLoadingGrillSuggestions, setIsLoadingGrillSuggestions] = useState(false)
  const [grillQueue, setGrillQueue] = useState<string[]>([])
  const [grillPanelOpen, setGrillPanelOpen] = useState(false)
  
  // Step 4 ATS：待处理队列
  const [atsQueue, setAtsQueue] = useState<string[]>([])
  const hasInitializedAtsQueue = useRef(false)

  // Step 5 Sync：待处理队列
  const [syncQueue, setSyncQueue] = useState<string[]>([])
  const hasInitializedSyncQueue = useRef(false)

  // localStorage 持久化 key
  const wizardStorageKey = job?.id ? `wizard_progress_${job.id}` : ""

  const saveWizardProgress = useCallback((step: WizardStep, progress: WizardProgress) => {
    if (!wizardStorageKey) return
    try {
      localStorage.setItem(wizardStorageKey, JSON.stringify({
        wizardStep: step,
        progress,
        grillQueue: [],
        timestamp: Date.now()
      }))
    } catch {}
  }, [wizardStorageKey])

  // wizardStep 或 wizardProgress 任一变化时落盘
  useEffect(() => {
    if (wizardStep !== 'idle') saveWizardProgress(wizardStep, wizardProgress)
  }, [wizardStep, wizardProgress, saveWizardProgress])

  const globalResumeMarkdown = useMemo(() => {
    if (!resumeData) return ""
    const parts: string[] = []
    if (resumeData.summary) parts.push(`# 个人总结\n\n${resumeData.summary}`)
    resumeData.workExperience?.forEach(w => {
      parts.push(`## ${w.company} - ${w.title}\n\n${asLines(w.description).join('\n')}`)
    })
    resumeData.personalProjects?.forEach(p => {
      parts.push(`## ${p.name}\n\n${asLines(p.description).join('\n')}`)
    })
    if (resumeData.additional?.technicalSkills?.length) {
      parts.push(`# 专业技能\n\n${resumeData.additional.technicalSkills.join('\n')}`)
    }
    return parts.join("\n\n").trim()
  }, [resumeData])

  const loadGrillSuggestions = useCallback(async () => {
    if (!job?.id) return
    setIsLoadingGrillSuggestions(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/grill_suggestion`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd_text: job.jobDescription || "",
          full_resume_context: globalResumeMarkdown
        })
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        setGrillSuggestions(data.data || [])
      } else {
        setGrillSuggestions([])
      }
    } catch {
      setGrillSuggestions([])
    } finally {
      setIsLoadingGrillSuggestions(false)
    }
  }, [job?.id, job?.jobDescription, globalResumeMarkdown])

  const grillSectionsList = useMemo(() => {
    if (!resumeData) return []
    const list: { id: string; title: string; isArchived?: boolean }[] = []
    resumeData.workExperience?.forEach((w, i) => list.push({ id: `work-${i}`, title: joinTitle(w.company, w.title) || `工作经历 ${i + 1}` }))
    resumeData.personalProjects?.forEach((p, i) => list.push({ id: `project-${i}`, title: joinTitle(p.name, p.role) || `项目经历 ${i + 1}` }))
    resumeData.archivedWorkExperience?.forEach((w, i) => list.push({ id: `arch-work-${i}`, title: joinTitle(w.company, w.title) || `工作经历 ${i + 1}`, isArchived: true }))
    resumeData.archivedProjects?.forEach((p, i) => list.push({ id: `arch-proj-${i}`, title: joinTitle(p.name, p.role) || `项目经历 ${i + 1}`, isArchived: true }))
    return list
  }, [resumeData])

  // 进入 Step 3 时自动加载建议
  useEffect(() => {
    if (wizardStep === 'step3' && grillSuggestions.length === 0 && !isLoadingGrillSuggestions) {
      setGrillPanelOpen(true)
      loadGrillSuggestions()
    }
  }, [wizardStep, grillSuggestions.length, isLoadingGrillSuggestions, loadGrillSuggestions])

  // Step 4: ATS 队列初始化
  useEffect(() => {
    if (wizardStep === 'step4' && !wizardProgress.atsDone && !hasInitializedAtsQueue.current) {
      hasInitializedAtsQueue.current = true
      const queue: string[] = []
      resumeData?.workExperience?.forEach((_, idx) => queue.push(`work-${idx}`))
      resumeData?.personalProjects?.forEach((_, idx) => queue.push(`project-${idx}`))
      
      if (queue.length === 0) {
        setWizardProgress(p => ({ ...p, atsDone: true }))
      } else {
        setAtsQueue(queue)
      }
    }
  }, [wizardStep, wizardProgress.atsDone, resumeData])

  // Step 5: Sync 队列初始化
  useEffect(() => {
    if (wizardStep === 'step5' && !wizardProgress.syncDone && !hasInitializedSyncQueue.current) {
      hasInitializedSyncQueue.current = true
      const queue: string[] = []
      
      const modules = [...new Set(resumeData?.moduleOrder || ["summary", "workExperience", "personalProjects", "education", "additional"])]
      
      if (modules.includes("summary")) queue.push("summary")
      if (modules.includes("additional")) queue.push("additional")

      if (modules.includes("education")) {
        resumeData?.education?.forEach((_, idx) => queue.push(`edu-${idx}`))
      }
      // 产品设定（用户 2026-09-19 拍板）：自定义模块（key 形如 custom_<ts>）不参与第五步联动更新，刻意排除，勿当遗漏恢复

      if (queue.length === 0) {
        setWizardProgress(p => ({ ...p, syncDone: true }))
      } else {
        setSyncQueue(queue)
      }
    }
  }, [wizardStep, wizardProgress.syncDone, resumeData])

  // Step 3：开始逐条 Grill 推进
  const handleStartGrillQueue = useCallback((sectionIds: string[]) => {
    setGrillPanelOpen(false)
    if (sectionIds.length === 0) {
      setWizardProgress(p => ({ ...p, grillDone: true }))
      return
    }
    setGrillQueue(sectionIds)
  }, [])

  // 向导启动（恢复历史进度 / 全新开始）
  const handleStartWizard = useCallback(() => {
    if (wizardStorageKey) {
      try {
        const cached = localStorage.getItem(wizardStorageKey)
        if (cached) {
          const data = JSON.parse(cached)
          if (data.wizardStep && data.wizardStep !== 'idle' && data.progress) {
            setWizardStep(data.wizardStep)
            setWizardProgress({ ...DEFAULT_WIZARD_PROGRESS, ...data.progress })
            setWizardHidden(false)
            if (data.wizardStep === 'step3' && grillSuggestions.length === 0 && !isLoadingGrillSuggestions) {
              setGrillPanelOpen(true)
              loadGrillSuggestions()
            }
            return
          }
        }
      } catch {}
    }
    const hasProject = (resumeData?.personalProjects?.length ?? 0) > 0
    const hasWork = (resumeData?.workExperience?.length ?? 0) > 0
    const fresh: WizardProgress = {
      pruneDone: !hasProject,
      compressDone: !hasWork,
      initialDraftProjectDone: !hasProject,
      initialDraftWorkDone: !hasWork,
      grillDone: false,
      atsDone: false,
      syncDone: false,
      savedDone: false,
    }
    setWizardProgress(fresh)
    setWizardStep('step1')
    setWizardHidden(false)
  }, [wizardStorageKey, resumeData?.personalProjects?.length, resumeData?.workExperience?.length, grillSuggestions.length, isLoadingGrillSuggestions, loadGrillSuggestions])

  const handleWizardComplete = useCallback((
    tool: string,
    sectionId?: string
  ) => {
    if (tool === 'grill_item_done' && sectionId) {
      setGrillQueue(prev => {
        const next = prev.filter(id => id !== sectionId)
        if (next.length === 0) {
          setWizardProgress(p => ({ ...p, grillDone: true }))
        }
        return next
      })
    } else if ((tool === 'ats_item_done' || tool === 'ats_item_cancel') && sectionId) {
      setAtsQueue(prev => {
        const next = prev.filter(id => id !== sectionId)
        if (next.length === 0 && tool === 'ats_item_done') {
          setWizardProgress(p => ({ ...p, atsDone: true }))
        }
        return next
      })
    } else if ((tool === 'sync_item_done' || tool === 'sync_item_cancel') && sectionId) {
      setSyncQueue(prev => {
        const next = prev.filter(id => id !== sectionId)
        if (next.length === 0 && tool === 'sync_item_done') {
          setWizardProgress(p => ({ ...p, syncDone: true }))
        }
        return next
      })
    } else if (tool === 'initial_draft_project') {
      setWizardProgress(p => ({ ...p, initialDraftProjectDone: true }))
    } else if (tool === 'initial_draft_work') {
      setWizardProgress(p => ({ ...p, initialDraftWorkDone: true }))
    } else {
      setWizardProgress(p => ({ ...p, [`${tool}Done`]: true }))
    }
  }, [])

  // 所有 sectionId → 标题 的映射（供进度面板显示和定位）
  const sectionTitles = useMemo(() => {
    const map: Record<string, string> = {}
    resumeData?.workExperience?.forEach((w, i) => { map[`work-${i}`] = joinTitle(w.company, w.title) || `工作经历 ${i + 1}` })
    resumeData?.personalProjects?.forEach((p, i) => { map[`project-${i}`] = joinTitle(p.name, p.role) || `项目经历 ${i + 1}` })
    resumeData?.education?.forEach((e, i) => { map[`edu-${i}`] = e.institution ? `${e.institution} · ${e.major || ""}`.trim() : `教育经历 ${i + 1}` })
    map["summary"] = "个人总结"
    map["additional"] = "专业技能"
    Object.keys(resumeData?.customModules || {}).forEach(modKey => {
      resumeData?.customModules?.[modKey]?.forEach((item: any, idx: number) => {
        map[`${modKey}-${idx}`] = item.title || item.name || `${modKey} ${idx + 1}`
      })
    })
    return map
  }, [resumeData])

  return {
    state: {
      wizardStep,
      wizardProgress,
      wizardHidden,
      grillSuggestions,
      isLoadingGrillSuggestions,
      grillQueue,
      grillPanelOpen,
      atsQueue,
      syncQueue,
      globalResumeMarkdown,
      wizardStorageKey,
      grillSectionsList,
      sectionTitles
    },
    actions: {
      setWizardStep,
      setWizardProgress,
      setWizardHidden,
      setGrillPanelOpen,
      setGrillQueue,
      handleStartGrillQueue,
      handleStartWizard,
      handleWizardComplete,
      saveWizardProgress
    }
  }
}
