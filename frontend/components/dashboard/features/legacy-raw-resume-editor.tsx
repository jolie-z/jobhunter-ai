import React, { useState, useEffect, useRef, useCallback, useMemo, type ReactNode } from "react"
import { GripVertical, ArrowUp, ArrowDown, Plus, X, Eye, FileText, FileDown, ImageIcon, Save, Sparkles, Loader2, ChevronUp, ChevronDown, CheckCircle, Search, Bold, Replace, Target, Flame, Scissors, Trash2, Scale, RotateCcw, XCircle } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip"
import { Separator } from "@/components/ui/separator"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"
import { Badge } from "@/components/ui/badge"

import type { JobData } from "@/types/job"
import type { ResumeSection, ResumeData } from "@/types/resume"
import { HighlightText } from "@/components/shared/highlight-text"
import { MdPreview } from "@/components/shared/md-preview"
import { AtsAligner } from "../resume-builder/ats-aligner"
import { ExperienceGriller } from "../resume-builder/experience-griller"
import { AiModuleSyncInline } from "../resume-builder/ai-module-sync-inline"
import { ProjectPruner } from "../resume-builder/project-pruner"
import { WorkCompressor } from "../resume-builder/work-compressor"
import { WorkRestoreBin } from "../resume-builder/work-restore-bin"
import { ProjectTrashBin } from "../resume-builder/project-trash-bin"
import { InitialDraftReviewer } from "../resume-builder/initial-draft-reviewer"
import { GrillSuggestionPanel, type GrillSuggestion } from "../resume-builder/grill-suggestion-panel"
import { API_BASE } from "@/lib/api"

/**
 * 🌟 方案B：精准喂料工具 —— 按按钮场景从 job 上挑取所需的诊断字段子集并拼接。
 * 避免每个按钮都把 5 个字段（~5000-7000 字 ≈ 8K-12K tokens）全量喂给大模型。
 * 字段语义：
 *   - dreamPicture         理想画像与能力信号（结构重组方向）
 *   - atsAbilityAnalysis   核心能力词典（ATS术语锚定）
 *   - strongFitAssessment  高杠杆匹配点（放大亮点/侧重点偏移）
 *   - riskRedFlags         致命硬伤与毒点（剪除决策/规避弱点）
 *   - deepActionPlan       破局行动计划（整体投递策略）
 */
function composeDiagnosisSubset(job: JobData | undefined | null, fields: Array<keyof JobData>): string {
  if (!job) return ""
  const parts: string[] = []
  fields.forEach(field => {
    const titleMap: Record<string, string> = {
      dreamPicture: "【理想画像与能力信号】",
      atsAbilityAnalysis: "【核心能力词典】",
      strongFitAssessment: "【高杠杆匹配点】",
      riskRedFlags: "【致命硬伤与毒点】",
      deepActionPlan: "【破局行动计划】",
    }
    const title = titleMap[field as string]
    const content = (job[field] as string)?.trim()
    if (title && content) parts.push(`${title}\n${content}`)
  })
  return parts.join("\n\n")
}

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
  pruneDone: false,
  compressDone: false,
  initialDraftProjectDone: false,
  initialDraftWorkDone: false,
  grillDone: false,
  atsDone: false,
  syncDone: false,
  savedDone: false,
}

export interface EditableSectionProps {
  section: ResumeSection
  isMatched: boolean
  onSelectText: (text: string, sectionId: string) => void
  onCommit: (nextSection: ResumeSection) => void
  onCommitMultiple?: (nextSections: ResumeSection[]) => void
  onDragStart: (sectionId: string) => void
  onDropTo: (targetSectionId: string) => void
  onMoveUp: () => void
  onMoveDown: () => void
  findText: string
  currentMatchIndex: number
  onRegisterMatch: (id: string) => number
  onOpenVoiceCopilot?: (section: ResumeSection) => void
  hideContent?: boolean
  job?: JobData
  experiencesContext?: string
  childrenSections?: ResumeSection[]
  archivedChildrenSections?: ResumeSection[]
  onDeleteSections?: (ids: string[]) => void
  onRestoreSections?: (ids: string[]) => void
  fullResumeContext?: string
  activeToolToOpen?: string | null
  onClearActiveTool?: () => void
  onRunDiagnosis?: () => void
  wizardStep?: WizardStep
  isAtsActive?: boolean
  isSyncActive?: boolean
  /** 单条 Grill/ATS 完成时，向外层发信号 */
  onWizardComplete?: (
    tool:
      | 'prune'
      | 'compress'
      | 'initial_draft_project'
      | 'initial_draft_work'
      | 'grill_item_done'
      | 'ats_item_done'
      | 'sync_item_done',
    sectionId?: string
  ) => void
}

function EditableBlock({
  id,
  hoveredBlock,
  setHoveredBlock,
  children,
}: {
  id: string
  hoveredBlock: string | null
  setHoveredBlock: (id: string | null) => void
  children: ReactNode
}) {
  const isHovered = hoveredBlock === id
  return (
    <div
      className={`transition-all rounded px-1 -mx-1 ${isHovered ? "bg-muted/50 ring-1 ring-dashed ring-border" : ""
        }`}
      onMouseEnter={() => setHoveredBlock(id)}
      onMouseLeave={() => setHoveredBlock(null)}
    >
      {children}
    </div>
  )
}


// ============================================================================
// 🌟 下方为：专用于原始简历展示的旧版画布引擎 (融合了新版工具栏 UI)
// ============================================================================

function LegacyEditableSection({
  section,
  isMatched,
  onSelectText,
  onCommit,
  onCommitMultiple,
  onDragStart,
  onDropTo,
  onMoveUp,
  onMoveDown,
  findText,
  currentMatchIndex,
  onRegisterMatch,
  hideContent = false,
  job,
  experiencesContext = "",
  childrenSections,
  archivedChildrenSections = [],
  onDeleteSections,
  onRestoreSections,
  fullResumeContext,
  activeToolToOpen,
  onClearActiveTool,
  wizardStep,
  isAtsActive,
  isSyncActive,
  onWizardComplete
}: EditableSectionProps) {
  const [localTitle, setLocalTitle] = useState(section.title)
  const [localContent, setLocalContent] = useState(section.content)
  const [isEditing, setIsEditing] = useState(false)

  const [atsOpen, setAtsOpen] = useState(false)
  const [grillOpen, setGrillOpen] = useState(false)
  const [syncOpen, setSyncOpen] = useState(false)
  const [pruneOpen, setPruneOpen] = useState(false)
  const [trashOpen, setTrashOpen] = useState(false)
  const [workCompressOpen, setWorkCompressOpen] = useState(false)
  const [workRestoreOpen, setWorkRestoreOpen] = useState(false)
  const [initialDraftOpen, setInitialDraftOpen] = useState(false)

  const onCommitRef = useRef(onCommit)
  const onCommitMultipleRef = useRef(onCommitMultiple)
  
  useEffect(() => { onCommitRef.current = onCommit }, [onCommit])
  useEffect(() => { onCommitMultipleRef.current = onCommitMultiple }, [onCommitMultiple])
  useEffect(() => { setLocalTitle(section.title) }, [section.id, section.title])
  useEffect(() => { setLocalContent(section.content) }, [section.id, section.content])
  useEffect(() => { setIsEditing(false) }, [section.id])

  useEffect(() => {
    if (activeToolToOpen) {
      if (activeToolToOpen === 'grill') {
        setGrillOpen(true); setAtsOpen(false); setSyncOpen(false); setPruneOpen(false); setWorkCompressOpen(false);
      } else if (activeToolToOpen === 'ats_align') {
        setAtsOpen(true); setGrillOpen(false); setSyncOpen(false); setPruneOpen(false); setWorkCompressOpen(false);
      } else if (activeToolToOpen === 'prune') {
        setPruneOpen(true); setAtsOpen(false); setGrillOpen(false); setSyncOpen(false); setWorkCompressOpen(false);
      } else if (activeToolToOpen === 'compress') {
        setWorkCompressOpen(true); setAtsOpen(false); setGrillOpen(false); setSyncOpen(false); setPruneOpen(false); setInitialDraftOpen(false);
      } else if (activeToolToOpen === 'initial_draft') {
        setInitialDraftOpen(true); setWorkCompressOpen(false); setAtsOpen(false); setGrillOpen(false); setSyncOpen(false); setPruneOpen(false);
      }
      if (onClearActiveTool) onClearActiveTool();
    }
  }, [activeToolToOpen, onClearActiveTool]);

  useEffect(() => {
    if (isAtsActive && !section.isAtsAligned) {
      setAtsOpen(true)
      setGrillOpen(false)
      setSyncOpen(false)
      setPruneOpen(false)
      setWorkCompressOpen(false)
    }
  }, [isAtsActive, section.isAtsAligned])

  useEffect(() => {
    if (isSyncActive && !section.isSynced) {
      setSyncOpen(true)
      setAtsOpen(false)
      setGrillOpen(false)
      setPruneOpen(false)
      setWorkCompressOpen(false)
    }
  }, [isSyncActive, section.isSynced])

  useEffect(() => {
    // 🌟 向导步骤变化时，先关闭所有面板，再打开当前步骤对应的面板
    setPruneOpen(false)
    setWorkCompressOpen(false)
    setInitialDraftOpen(false)
    setGrillOpen(false)
    setAtsOpen(false)
    setSyncOpen(false)

    if (wizardStep === 'step1') {
      if (section.title.includes('项目经历')) {
        setPruneOpen(true)
      } else if (section.title.includes('工作经历')) {
        setWorkCompressOpen(true)
      }
    } else if (wizardStep === 'step2') {
      if (section.title.includes('项目经历') || section.title.includes('工作经历')) {
        setInitialDraftOpen(true)
      }
    } else if (wizardStep === 'step3') {
      // Step 3 的 Grill 面板由 grillQueue 自动控制，不需要这里打开
    } else if (wizardStep === 'step4') {
      // Step 4 的 ATS 面板由 activeAtsIds 自动控制，不需要这里打开
    }
  }, [wizardStep, section.title])

  useEffect(() => {
    const timer = setTimeout(() => {
      if (localTitle !== section.title || localContent !== section.content) {
        onCommitRef.current({ ...section, title: localTitle, content: localContent })
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [localTitle, localContent, section.title, section.content, section.id])

  const flushCommit = () => {
    if (localTitle !== section.title || localContent !== section.content) {
      onCommitRef.current({ ...section, title: localTitle, content: localContent })
    }
  }

  const getSectionMinHeightClass = (sectionId: string) => {
    if (section.level === 2) return "min-h-[60px]"
    if (sectionId === "summary") return "min-h-[100px]"
    if (sectionId === "skills") return "min-h-[150px]"
    if (sectionId === "project" || sectionId === "work" || sectionId === "experience") return "min-h-[250px]"
    return "min-h-[100px]"
  }

  return (
    <div className={`rounded ${isMatched ? "ring-1 ring-amber-300" : ""}`} onDragOver={(e: React.DragEvent<HTMLDivElement>) => e.preventDefault()} onDrop={() => onDropTo(section.id)}>
      <div className="flex items-center justify-between gap-2 mb-1">
        <Input value={localTitle} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setLocalTitle(e.target.value)} onBlur={flushCommit} className="h-6 text-xs border-none bg-transparent p-0 font-semibold text-slate-800" />
        <div className="flex items-center gap-1">
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-slate-400 cursor-grab active:cursor-grabbing" draggable onDragStart={() => onDragStart(section.id)}><GripVertical className="h-3.5 w-3.5" /></Button>
              </TooltipTrigger>
              <TooltipContent>拖拽模块</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-slate-400" onClick={onMoveUp}><ArrowUp className="h-3.5 w-3.5" /></Button>
              </TooltipTrigger>
              <TooltipContent>上移</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-slate-400" onClick={onMoveDown}><ArrowDown className="h-3.5 w-3.5" /></Button>
              </TooltipTrigger>
              <TooltipContent>下移</TooltipContent>
            </Tooltip>
            {section.level === 1 && section.title.includes("项目") && (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="sm" onClick={() => { setPruneOpen(v => !v); setTrashOpen(false); setInitialDraftOpen(false) }} className="h-6 w-6 p-0 text-red-600 hover:text-red-700 hover:bg-red-50/80 transition-all">
                      <Scissors className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>AI剪除项目经历</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="sm" onClick={() => { setInitialDraftOpen(v => !v); setPruneOpen(false); setTrashOpen(false) }} className="h-6 w-6 p-0 text-blue-600 hover:text-blue-700 hover:bg-blue-50/80 transition-all ml-1">
                      <FileText className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>AI 初步改写 (结构与重点)</TooltipContent>
                </Tooltip>

                {archivedChildrenSections.length > 0 && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="ghost" size="sm" onClick={() => { setTrashOpen(v => !v); setPruneOpen(false); setInitialDraftOpen(false) }} className="h-6 w-6 p-0 text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-all ml-1">
                        <div className="relative">
                          <Trash2 className="h-3.5 w-3.5" />
                          <span className="absolute -top-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-slate-800 text-[8px] text-white">
                            {archivedChildrenSections.length}
                          </span>
                        </div>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>项目回收站 (可恢复)</TooltipContent>
                  </Tooltip>
                )}
              </>
            )}
            {section.level === 1 && section.title.includes("工作") && (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="sm" onClick={() => { setWorkCompressOpen(v => !v); setWorkRestoreOpen(false); setInitialDraftOpen(false) }} className="h-6 w-6 p-0 text-purple-600 hover:text-purple-700 hover:bg-purple-50/80 transition-all">
                      <Scale className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>AI判断工作经历重写or略写</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="sm" onClick={() => { setInitialDraftOpen(v => !v); setWorkCompressOpen(false); setWorkRestoreOpen(false) }} className="h-6 w-6 p-0 text-blue-600 hover:text-blue-700 hover:bg-blue-50/80 transition-all ml-1">
                      <FileText className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>AI 初步改写 (结构与重点)</TooltipContent>
                </Tooltip>

                {childrenSections && childrenSections.filter(s => s.originalContent).length > 0 && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button variant="ghost" size="sm" onClick={() => { setWorkRestoreOpen(v => !v); setWorkCompressOpen(false); setInitialDraftOpen(false) }} className="h-6 w-6 p-0 text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-all ml-1">
                        <div className="relative">
                          <RotateCcw className="h-3.5 w-3.5" />
                          <span className="absolute -top-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-slate-800 text-[8px] text-white">
                            {childrenSections.filter(s => s.originalContent).length}
                          </span>
                        </div>
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>工作经历快照还原</TooltipContent>
                  </Tooltip>
                )}
              </>
            )}
          </TooltipProvider>
        </div>
      </div>
      {!hideContent && (
        findText ? (
          <div className={`w-full ${getSectionMinHeightClass(section.id)} overflow-y-auto text-[11px] leading-tight whitespace-pre-wrap break-words border border-slate-200 rounded-sm p-2 ${isMatched ? "border-amber-300 bg-amber-50/50" : ""}`}>
            <HighlightText text={localContent} searchKeyword={findText} currentMatchIndex={currentMatchIndex} onRegisterMatch={onRegisterMatch} />
          </div>
        ) : isEditing ? (
          <Textarea
            className={`w-full min-h-[500px] !resize-y overflow-y-auto text-sm leading-relaxed text-slate-700 whitespace-pre-wrap break-words border border-indigo-200 bg-indigo-50/30 rounded-sm p-2 outline-none focus:ring-1 focus:ring-indigo-300`}
            value={localContent} onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setLocalContent(e.target.value)} onBlur={() => { flushCommit(); setIsEditing(false) }}
            onSelect={(e: React.SyntheticEvent<HTMLTextAreaElement>) => {
              const target = e.currentTarget
              const text = target.value.slice(target.selectionStart ?? 0, target.selectionEnd ?? 0).trim()
              onSelectText(text, section.id)
            }} autoFocus
          />
        ) : (
          <div className={`w-full ${getSectionMinHeightClass(section.id)} cursor-text p-2 rounded-sm border transition-colors ${isMatched ? "border-amber-300 bg-amber-50/50" : "border-transparent hover:bg-slate-50"}`} onClick={() => setIsEditing(true)} title="点击编辑">
            <MdPreview text={localContent} />
          </div>
        )
      )}

      {/* 🚀 新增：工具按钮及组件区 */}
      <div className="mt-1 flex flex-col items-end">
        {section.level === 2 && (
          <div className="flex gap-1.5 mb-1.5">
            <Button variant="ghost" onClick={() => { setAtsOpen(v => !v); if (grillOpen) setGrillOpen(false); }} className={`h-6 px-2 text-[11px] transition-all font-medium ${section.isAtsAligned ? "text-slate-400 bg-slate-50" : "text-blue-600 hover:text-blue-700 hover:bg-blue-50/80"}`}>
              {section.isAtsAligned ? <CheckCircle className="mr-1 h-3 w-3 text-green-500" /> : <Target className="mr-1 h-3 w-3" />}
              {section.isAtsAligned ? "已 ATS 靶向" : "ATS 靶向预写"}
            </Button>
            <Button variant="ghost" onClick={() => { setGrillOpen(v => !v); if (atsOpen) setAtsOpen(false); }} className={`h-6 px-2 text-[11px] transition-all font-medium ${section.isGrilled ? "text-slate-400 bg-slate-50" : "text-orange-600 hover:text-orange-700 hover:bg-orange-50/80"}`}>
              {section.isGrilled ? <CheckCircle className="mr-1 h-3 w-3 text-green-500" /> : <Flame className="mr-1 h-3 w-3" />}
              {section.isGrilled ? "已深度拷问" : "Grill-me 深度拷打"}
            </Button>
          </div>
        )}

        {section.level === 1 && !section.title.includes("项目") && !section.title.includes("工作") && (
          <div className="flex gap-1.5 mb-1.5">
            <Button variant="ghost" onClick={() => setSyncOpen(v => !v)} className="h-6 px-2 text-[11px] text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50/80 transition-all font-medium">
              <Sparkles className="mr-1 h-3 w-3" /> AI 联动更新
            </Button>
          </div>
        )}

        {atsOpen && section.level === 2 && (
          <AtsAligner
            originalExperience={`[${localTitle}]\n${localContent}`}
            customJdContext={job?.jobDescription || ""}
            fullResumeContext={fullResumeContext}
            onAccept={(newContent) => {
              let cleanNewContent = newContent
              const titleMatch = newContent.match(/^\[(.*?)\]\n([\s\S]*)/)
              if (titleMatch) cleanNewContent = titleMatch[2]
              setLocalContent(cleanNewContent.trim())
              onCommitRef.current({ ...section, content: cleanNewContent.trim(), isAtsAligned: true })
              setAtsOpen(false)
              if (onWizardComplete) onWizardComplete('ats_item_done', section.id)
            }}
            onCancel={() => setAtsOpen(false)}
          />
        )}

        {grillOpen && section.level === 2 && (
          <ExperienceGriller
            originalExperience={`[${localTitle}]\n${localContent}`}
            customJdContext={job ? `【岗位要求】：\n${job.jobDescription}\n\n【简历诊断报告】：\n${composeDiagnosisSubset(job, ['dreamPicture', 'deepActionPlan'])}` : ""}
            fullResumeContext={fullResumeContext}
            onAccept={(newContent) => {
              let cleanNewContent = newContent
              const titleMatch = newContent.match(/^\[(.*?)\]\n([\s\S]*)/)
              if (titleMatch) cleanNewContent = titleMatch[2]
              setLocalContent(cleanNewContent.trim())
              onCommitRef.current({ ...section, content: cleanNewContent.trim(), isGrilled: true })
              setGrillOpen(false)
              if (onWizardComplete) onWizardComplete('grill_item_done', section.id)
            }}
            onCancel={() => setGrillOpen(false)}
          />
        )}

        {syncOpen && section.level === 1 && (
          <AiModuleSyncInline
            moduleTitle={localTitle}
            currentContent={localContent}
            experiencesContext={experiencesContext}
            onAccept={(newContent) => {
              setLocalContent(newContent.trim())
              onCommitRef.current({ ...section, content: newContent.trim(), isSynced: true })
              setSyncOpen(false)
              if (onWizardComplete) onWizardComplete('sync_item_done', section.id)
            }}
            onCancel={() => {
              setSyncOpen(false)
              if (onWizardComplete) onWizardComplete('sync_item_done', section.id)
            }}
          />
        )}

        {pruneOpen && section.level === 1 && childrenSections && (
          <ProjectPruner
            projects={childrenSections}
            archivedProjects={archivedChildrenSections}
            customJdContext={job?.jobDescription || ""}
            customDiagnosisContext={composeDiagnosisSubset(job, ['riskRedFlags'])}
            onAccept={(idsToDelete) => {
              if (onDeleteSections) onDeleteSections(idsToDelete)
              setPruneOpen(false)
              if (onWizardComplete) onWizardComplete('prune')
            }}
            onCancel={() => {
              setPruneOpen(false)
              if (onWizardComplete) onWizardComplete('prune')
            }}
          />
        )}

        {trashOpen && section.level === 1 && archivedChildrenSections && (
          <ProjectTrashBin
            archivedProjects={archivedChildrenSections}
            onRestore={(idsToRestore) => {
              if (onRestoreSections) onRestoreSections(idsToRestore)
              if (idsToRestore.length === archivedChildrenSections.length) setTrashOpen(false)
            }}
            onCancel={() => setTrashOpen(false)}
          />
        )}

        {workCompressOpen && section.level === 1 && childrenSections && (
          <WorkCompressor
            works={childrenSections}
            customJdContext={job?.jobDescription || ""}
            customDiagnosisContext={composeDiagnosisSubset(job, ['atsAbilityAnalysis', 'strongFitAssessment'])}
            onAccept={(compressions) => {
              const updatedSections: ResumeSection[] = []
              compressions.forEach(comp => {
                const targetSection = childrenSections.find(s => s.id === comp.id)
                if (targetSection) {
                  updatedSections.push({ 
                    ...targetSection, 
                    content: comp.newContent,
                    originalContent: targetSection.content 
                  })
                }
              })
              if (updatedSections.length > 0) {
                if (onCommitMultipleRef.current) {
                  onCommitMultipleRef.current(updatedSections)
                } else {
                  updatedSections.forEach(s => onCommitRef.current(s)) // Fallback, might still bug if not handled
                }
              }
              setWorkCompressOpen(false)
              if (onWizardComplete) onWizardComplete('compress')
            }}
            onCancel={() => {
              setWorkCompressOpen(false)
              if (onWizardComplete) onWizardComplete('compress')
            }}
          />
        )}

        {initialDraftOpen && section.level === 1 && childrenSections && (
          <InitialDraftReviewer
            sections={childrenSections.filter(s => !s.isArchived)}
            parentCategory={section.title.includes('项目经历') ? '项目经历' : '工作经历'}
            customJdContext={job?.jobDescription || ""}
            customDiagnosisContext={composeDiagnosisSubset(job, ['strongFitAssessment', 'dreamPicture'])}
            fullResumeContext={fullResumeContext}
            onAccept={(drafts) => {
              const updatedSections: ResumeSection[] = []
              drafts.forEach(draft => {
                const targetSection = childrenSections.find(s => s.id === draft.id)
                if (targetSection) {
                  updatedSections.push({ 
                    ...targetSection, 
                    content: draft.newContent,
                    isDrafted: true
                  })
                }
              })
              if (updatedSections.length > 0) {
                if (onCommitMultipleRef.current) {
                  onCommitMultipleRef.current(updatedSections)
                } else {
                  updatedSections.forEach(s => onCommitRef.current(s))
                }
              }
              setInitialDraftOpen(false)
              if (onWizardComplete) {
                if (section.title.includes('项目经历')) onWizardComplete('initial_draft_project')
                else if (section.title.includes('工作经历')) onWizardComplete('initial_draft_work')
              }
            }}
            onCancel={() => {
              setInitialDraftOpen(false)
              if (onWizardComplete) {
                if (section.title.includes('项目经历')) onWizardComplete('initial_draft_project')
                else if (section.title.includes('工作经历')) onWizardComplete('initial_draft_work')
              }
            }}
          />
        )}

        {workRestoreOpen && section.level === 1 && childrenSections && childrenSections.some(s => s.originalContent) && (
          <WorkRestoreBin
            compressedWorks={childrenSections.filter(s => s.originalContent)}
            onRestore={(idsToRestore) => {
              const updatedSections: ResumeSection[] = []
              idsToRestore.forEach(id => {
                const targetSection = childrenSections.find(s => s.id === id)
                if (targetSection && targetSection.originalContent) {
                  updatedSections.push({ 
                    ...targetSection, 
                    content: targetSection.originalContent,
                    originalContent: undefined
                  })
                }
              })
              if (updatedSections.length > 0) {
                if (onCommitMultipleRef.current) {
                  onCommitMultipleRef.current(updatedSections)
                } else {
                  updatedSections.forEach(s => onCommitRef.current(s))
                }
              }
              if (idsToRestore.length === childrenSections.filter(s => s.originalContent).length) {
                setWorkRestoreOpen(false)
              }
            }}
            onCancel={() => setWorkRestoreOpen(false)}
          />
        )}
      </div>
    </div>
  )
}

interface LegacyRawResumeEditorProps {
  resumeData: ResumeData
  onChange: (nextData: ResumeData) => void
  selectedText: string
  selectedSectionId: string | null
  onClearSelection: () => void
  onTextSelect: (text: string, sectionId: string | null) => void
  onUndo: () => void
  canUndo: boolean
  job: JobData
  onQAComplete?: (report: any) => void
  onUpdateJob: (job: JobData | null, action?: 'remove') => void
  onExport: (type: "pdf" | "image") => void
  exportingType: "pdf" | "image" | null
  onClose?: () => void
  // 🌟 新增类型声明
  processingJobs?: Record<string, string>
  jobLiveLogs?: Record<string, string[]>
  globalTaskStatus?: "idle" | "running" | "completed" | "interrupted"
}

export function LegacyRawResumeEditor({
  resumeData, onChange, selectedText, selectedSectionId, onClearSelection, onTextSelect, onUndo, canUndo, job, onQAComplete, onUpdateJob, onExport, exportingType, onClose,
  // 🌟 新增参数解构
  processingJobs, jobLiveLogs, globalTaskStatus
}: LegacyRawResumeEditorProps) {
  const [hoveredBlock, setHoveredBlock] = useState<string | null>(null)
  const [findText, setFindText] = useState("")
  const [replaceText, setReplaceText] = useState("")
  const [matchedSectionIds, setMatchedSectionIds] = useState<string[]>([])
  const [draggingSectionId, setDraggingSectionId] = useState<string | null>(null)
  const [isQAEvaluating, setIsQAEvaluating] = useState(false)
  const [isSavingResume, setIsSavingResume] = useState(false)
  const [totalMatches, setTotalMatches] = useState(0)
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0)
  const [isPreviewOpen, setIsPreviewOpen] = useState(false)
  const [activeToolToOpen, setActiveToolToOpen] = useState<{ sectionId: string; tool: string } | null>(null)
  const [isDiagnosing, setIsDiagnosing] = useState(false)
  const [diagnosisSuggestions, setDiagnosisSuggestions] = useState<any[]>([])

  // 🌟 Wizard State（升级版：Step 3 拆为 Grill，Step 4 ATS，Step 5 保存）
  const [wizardStep, setWizardStep] = useState<WizardStep>('idle')
  const [wizardProgress, setWizardProgress] = useState<WizardProgress>(DEFAULT_WIZARD_PROGRESS)
  const [wizardHidden, setWizardHidden] = useState(false)  // 🌟 向导隐藏状态：隐藏面板但保留进度，点击AI全局按钮可恢复

  // Step 3 Grill：建议列表 + 待处理队列
  const [grillSuggestions, setGrillSuggestions] = useState<GrillSuggestion[]>([])
  const [isLoadingGrillSuggestions, setIsLoadingGrillSuggestions] = useState(false)
  const [grillQueue, setGrillQueue] = useState<string[]>([])
  const [grillPanelOpen, setGrillPanelOpen] = useState(false) // 是否展示建议勾选面板

  // Step 4 ATS：并行限流控制（最多 3 个同时进行）
  const [activeAtsIds, setActiveAtsIds] = useState<string[]>([])
  // Step 5 Sync：联动更新并行（全量一起执行）
  const [activeSyncIds, setActiveSyncIds] = useState<string[]>([])

  const [isResetting, setIsResetting] = useState(false)

  const matchIdsRef = useRef<string[]>([])

  const globalResumeMarkdown = React.useMemo(() => {
    const mdParts: string[] = []
    for (const section of resumeData.sections) {
      if (!section.title.trim() && !section.content.trim()) continue
      if (section.isArchived) continue
      mdParts.push(`${section.level === 2 ? "##" : "#"} ${section.title}\n\n${section.content.trim()}\n`)
    }
    return mdParts.join("\n").trim()
  }, [resumeData.sections])

  const handleGlobalDiagnosis = async () => {
    if (!job?.id) {
      alert("请先选择一个 JD")
      return
    }
    setIsDiagnosing(true)
    try {
      const response = await fetch(`${API_BASE}/api/strategy/global_diagnosis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd_text: job.jobDescription,
          full_resume_context: globalResumeMarkdown
        })
      })
      const data = await response.json()
      if (response.ok && data.status === "success") {
        setDiagnosisSuggestions(data.data || [])
      } else {
        alert("诊断失败: " + data.message)
      }
    } catch (err: any) {
      alert("诊断异常: " + err.message)
    } finally {
      setIsDiagnosing(false)
    }
  }

  // ===================== 🌟 向导进度 localStorage 持久化 =====================
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

  const handleStartWizard = () => {
    // 优先尝试恢复历史进度
    if (wizardStorageKey) {
      try {
        const cached = localStorage.getItem(wizardStorageKey)
        if (cached) {
          const data = JSON.parse(cached)
          if (data.wizardStep && data.wizardStep !== 'idle' && data.progress) {
            setWizardStep(data.wizardStep)
            setWizardProgress({ ...DEFAULT_WIZARD_PROGRESS, ...data.progress })
            setWizardHidden(false)  // 恢复进度时显示向导
            // 若恢复到 step3 且建议面板尚未加载，则触发加载
            if (data.wizardStep === 'step3' && grillSuggestions.length === 0 && !isLoadingGrillSuggestions) {
              setGrillPanelOpen(true)
              loadGrillSuggestions()
            }
            return
          }
        }
      } catch {}
    }
    // 全新开始：进入 Step 1
    const hasProject = resumeData.sections.some((s: ResumeSection) => s.title.includes('项目经历'))
    const hasWork = resumeData.sections.some((s: ResumeSection) => s.title.includes('工作经历'))
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
    setWizardHidden(false)  // 新开始时显示向导
  }

  // ===================== Step 3：加载 AI 深挖建议 =====================
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

  // 进入 Step 3 时自动加载建议
  useEffect(() => {
    if (wizardStep === 'step3' && grillSuggestions.length === 0 && !isLoadingGrillSuggestions) {
      setGrillPanelOpen(true)
      loadGrillSuggestions()
    }
  }, [wizardStep, grillSuggestions.length, isLoadingGrillSuggestions, loadGrillSuggestions])

  // ===================== Step 3：开始逐条 Grill 推进 =====================
  const handleStartGrillQueue = useCallback((sectionIds: string[]) => {
    setGrillPanelOpen(false)
    if (sectionIds.length === 0) {
      // 没有要深挖的，直接完成 Step 3
      setWizardProgress(p => ({ ...p, grillDone: true }))
      return
    }
    setGrillQueue(sectionIds)
    // 自动展开队列第一条
    openGrillForSection(sectionIds[0])
  }, [])

  // 通过 activeToolToOpen 信号让目标经历自动展开 Grill 面板 + 滚动
  const openGrillForSection = useCallback((sectionId: string) => {
    setActiveToolToOpen({ sectionId, tool: 'grill' })
    const el = document.getElementById(`section-${sectionId}`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [])

  // ===================== Step 5：AI 联动更新（非项目/工作经历模块）=====================
  useEffect(() => {
    if (wizardStep !== 'step5') return
    const syncSections = resumeData.sections.filter(s => s.level === 1 && !s.title.includes("项目") && !s.title.includes("工作") && !s.isArchived && (s.title.trim() || s.content.trim()))
    if (syncSections.length === 0) {
      setWizardProgress(p => ({ ...p, syncDone: true }))
      return
    }
    const pendingIds = syncSections.filter(s => !s.isSynced).map(s => s.id)
    if (pendingIds.length === 0) {
      setWizardProgress(p => ({ ...p, syncDone: true }))
      if (activeSyncIds.length > 0) setActiveSyncIds([])
      return
    }
    // 全部一次性拉起
    if (activeSyncIds.length !== pendingIds.length) {
      setActiveSyncIds(pendingIds)
      setTimeout(() => {
        const el = document.getElementById(`section-${pendingIds[0]}`)
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 100)
    }
  }, [wizardStep, resumeData.sections, activeSyncIds])

  // ===================== Step 4：ATS 并行限流（最多 3 个同时进行）=====================
  useEffect(() => {
    if (wizardStep !== 'step4') return
    const allLevel2 = resumeData.sections.filter(s => s.level === 2 && !s.isArchived)
    if (allLevel2.length === 0) {
      setWizardProgress(p => ({ ...p, atsDone: true }))
      return
    }
    const doneIds = allLevel2.filter(s => s.isAtsAligned).map(s => s.id)
    const pendingIds = allLevel2.filter(s => !s.isAtsAligned).map(s => s.id)

    if (pendingIds.length === 0) {
      // 全部完成（⚠️ 仅当 activeAtsIds 非空时才清空，避免空数组新引用触发无限循环）
      setWizardProgress(p => ({ ...p, atsDone: true }))
      if (activeAtsIds.length > 0) setActiveAtsIds([])
      return
    }
    // 当前活跃窗口（剔除已完成的）
    const currentActive = activeAtsIds.filter(id => !doneIds.includes(id))
    const slotsAvailable = 3 - currentActive.length
    if (slotsAvailable > 0) {
      const nextBatch = pendingIds.filter(id => !activeAtsIds.includes(id)).slice(0, slotsAvailable)
      if (nextBatch.length > 0) {
        const merged = [...currentActive, ...nextBatch]
        setActiveAtsIds(merged)
        // 自动展开新补位的 ATS 面板，使用 setTimeout 确保 DOM 已经更新并展开
        setTimeout(() => {
          const el = document.getElementById(`section-${nextBatch[0]}`)
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }, 100)
      }
    }
  }, [wizardStep, resumeData.sections, activeAtsIds])

  // ===================== 统一的向导事件回调 =====================
  const handleWizardComplete = useCallback((
    tool:
      | 'prune'
      | 'compress'
      | 'initial_draft_project'
      | 'initial_draft_work'
      | 'grill_item_done'
      | 'ats_item_done'
      | 'sync_item_done',
    sectionId?: string
  ) => {
    if (tool === 'grill_item_done' && sectionId) {
      setGrillQueue(prev => {
        const next = prev.filter(id => id !== sectionId)
        if (next.length === 0) {
          // 队列清空，Step 3 完成
          setWizardProgress(p => ({ ...p, grillDone: true }))
        } else {
          // 自动展开下一条
          setTimeout(() => openGrillForSection(next[0]), 200)
        }
        return next
      })
    } else if (tool === 'ats_item_done') {
      // 让 Step 4 的 useEffect 监听 isAtsAligned 变化后自动补位
      // 这里不需要做什么，resumeData.sections 变化会触发上面的 effect
    } else if (tool === 'sync_item_done') {
      // Step 5 同理
    } else if (tool === 'initial_draft_project') {
      setWizardProgress(p => ({ ...p, initialDraftProjectDone: true }))
    } else if (tool === 'initial_draft_work') {
      setWizardProgress(p => ({ ...p, initialDraftWorkDone: true }))
    } else {
      setWizardProgress(p => ({ ...p, [`${tool}Done`]: true }))
    }
  }, [openGrillForSection])

  const applyDiagnosisAction = (suggestion: any) => {
    const sectionIndex = resumeData.sections.findIndex((s: ResumeSection) => 
      s.title.includes(suggestion.section_title) || suggestion.section_title.includes(s.title)
    )
    
    if (sectionIndex !== -1) {
      let targetSection = resumeData.sections[sectionIndex]

      // 对于 prune 和 compress，它们是挂载在 Level 1 父节点上的
      if (suggestion.action === 'prune' || suggestion.action === 'compress') {
        if (targetSection.level === 2) {
          // 向上寻找最近的 Level 1 父节点
          for (let i = sectionIndex - 1; i >= 0; i--) {
            if (resumeData.sections[i].level === 1) {
              targetSection = resumeData.sections[i]
              break
            }
          }
        }
      }

      setActiveToolToOpen({ sectionId: targetSection.id, tool: suggestion.action })
      const el = document.getElementById(`section-${targetSection.id}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    } else {
      alert(`未找到对应标题为 "${suggestion.section_title}" 的小节，请手动操作。`)
    }
  }

  const moveSection = (index: number, direction: -1 | 1) => {
    const nextSections = [...resumeData.sections];
    const sec = nextSections[index];

    if (sec.level === 2) {
      const targetIndex = index + direction;
      if (targetIndex < 0 || targetIndex >= nextSections.length) return;
      if (nextSections[targetIndex].level !== 2) return;

      const [moved] = nextSections.splice(index, 1);
      nextSections.splice(targetIndex, 0, moved);
      onChange({ ...resumeData, sections: nextSections });
    } else {
      let blockEnd = index;
      while (blockEnd + 1 < nextSections.length && nextSections[blockEnd + 1].level === 2) blockEnd++;

      if (direction === -1) {
        if (index === 0) return;
        const targetIndex = index - 1;
        if (nextSections[targetIndex].level === 2) {
          let prevStart = targetIndex;
          while (prevStart >= 0 && nextSections[prevStart].level === 2) prevStart--;
          const block = nextSections.splice(index, blockEnd - index + 1);
          nextSections.splice(prevStart, 0, ...block);
        } else {
          const block = nextSections.splice(index, blockEnd - index + 1);
          nextSections.splice(targetIndex, 0, ...block);
        }
      } else {
        if (blockEnd === nextSections.length - 1) return;
        const nextStart = blockEnd + 1;
        let nextEnd = nextStart;
        while (nextEnd + 1 < nextSections.length && nextSections[nextEnd + 1].level === 2) nextEnd++;

        const myBlock = nextSections.splice(index, blockEnd - index + 1);
        nextSections.splice(index + (nextEnd - nextStart + 1), 0, ...myBlock);
      }
      onChange({ ...resumeData, sections: nextSections });
    }
  }

  const handleBold = () => {
    const trimmed = selectedText.trim()
    if (!trimmed || !selectedSectionId) { window.alert("请先选中文本"); return }
    const section = resumeData.sections.find((s: ResumeSection) => s.id === selectedSectionId)
    if (!section || !section.content.includes(trimmed)) { window.alert("请先选中文本"); return }
    const wrapped = `**${trimmed}**`
    const newContent = section.content.replace(trimmed, wrapped)
    onChange({ ...resumeData, sections: resumeData.sections.map((s: ResumeSection) => s.id === selectedSectionId ? { ...s, content: newContent } : s) })
    onClearSelection()
  }

  const handleDropTo = (targetSectionId: string) => {
    if (!draggingSectionId || draggingSectionId === targetSectionId) return
    const from = resumeData.sections.findIndex((s: ResumeSection) => s.id === draggingSectionId)
    const to = resumeData.sections.findIndex((s: ResumeSection) => s.id === targetSectionId)
    if (from < 0 || to < 0) return
    const next = [...resumeData.sections];

    const dragSec = next[from];
    const targetSec = next[to];

    if (dragSec?.level === 2) {
      let dragParent = from; while (dragParent >= 0 && next[dragParent]?.level === 2) dragParent--;
      let targetParent = to; while (targetParent >= 0 && next[targetParent]?.level === 2) targetParent--;
      if (dragParent !== targetParent) {
        window.alert("二级模块只能在所属的一级模块内拖拽排序！");
        return;
      }
      if (to === dragParent && from > to) {
        window.alert("二级模块必须放在所属的一级模块之后！");
        return;
      }
      const [moved] = next.splice(from, 1);
      const adjustedTo = from < to ? to - 1 : to;
      next.splice(adjustedTo, 0, moved);
      onChange({ ...resumeData, sections: next }); setDraggingSectionId(null);
      return;
    }

    if (targetSec?.level === 2) {
      window.alert("一级模块只能在一级模块之间排序！");
      return;
    }
    let dragEnd = from;
    while (dragEnd + 1 < next.length && next[dragEnd + 1]?.level === 2) dragEnd++;
    const block = next.splice(from, dragEnd - from + 1);

    const newTo = next.findIndex(s => s.id === targetSectionId);
    next.splice(newTo, 0, ...block);
    onChange({ ...resumeData, sections: next }); setDraggingSectionId(null);
    return;
  }

  const handleDeleteSections = useCallback((idsToArchive: string[]) => {
    const nextSections = resumeData.sections.map(s =>
      idsToArchive.includes(s.id) ? { ...s, isArchived: true } : s
    )
    onChange({ ...resumeData, sections: nextSections })
  }, [resumeData, onChange])

  const handleRestoreSections = useCallback((idsToRestore: string[]) => {
    const nextSections = resumeData.sections.map(s =>
      idsToRestore.includes(s.id) ? { ...s, isArchived: false } : s
    )
    onChange({ ...resumeData, sections: nextSections })
  }, [resumeData, onChange])

  const handleSectionCommit = useCallback((nextSection: ResumeSection) => {
    onChange({ ...resumeData, sections: resumeData.sections.map((s: ResumeSection) => (s.id === nextSection.id ? nextSection : s)) })
  }, [resumeData, onChange])

  const handleMultipleSectionCommit = useCallback((nextSections: ResumeSection[]) => {
    onChange({
      ...resumeData,
      sections: resumeData.sections.map((s: ResumeSection) => {
        const match = nextSections.find(ns => ns.id === s.id)
        return match ? match : s
      })
    })
  }, [resumeData, onChange])

  const handleAddSection = useCallback(() => {
    onChange({ ...resumeData, sections: [...resumeData.sections, { id: `section-${Date.now()}`, title: "自定义模块", content: "" }] })
    setTimeout(() => { const container = document.querySelector('[data-resume-canvas]'); if (container) container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' }) }, 100)
  }, [resumeData, onChange])

  const registerMatch = useCallback((id: string) => {
    const currentIds = matchIdsRef.current
    const existingIndex = currentIds.indexOf(id); if (existingIndex !== -1) return existingIndex
    const newIndex = currentIds.length; matchIdsRef.current = [...currentIds, id]; return newIndex
  }, [])

  const scrollToMatch = useCallback((index: number) => {
    if (matchIdsRef.current.length === 0) return
    const matchId = matchIdsRef.current[index]; if (!matchId) return
    const element = document.getElementById(matchId); if (element) element.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [])

  const handleFind = useCallback(() => {
    if (!findText.trim()) { matchIdsRef.current = []; setTotalMatches(0); setCurrentMatchIndex(0); setMatchedSectionIds([]); return }
    matchIdsRef.current = []; setCurrentMatchIndex(0)
    setTimeout(() => { const count = matchIdsRef.current.length; setTotalMatches(count); if (count > 0) scrollToMatch(0) }, 100)
    setMatchedSectionIds(resumeData.sections.filter((s: ResumeSection) => s.title.toLowerCase().includes(findText.toLowerCase()) || s.content.toLowerCase().includes(findText.toLowerCase())).map((s: ResumeSection) => s.id))
  }, [findText, resumeData.sections, scrollToMatch])

  useEffect(() => {
    if (findText.trim()) handleFind()
    else { matchIdsRef.current = []; setTotalMatches(0); setCurrentMatchIndex(0); setMatchedSectionIds([]) }
  }, [findText, handleFind])

  const handleReplace = (replaceAll: boolean) => {
    if (!findText || !replaceText || matchedSectionIds.length === 0) return
    const firstMatchId = matchedSectionIds[0]
    onChange({
      header: {
        name: resumeData.header.name.split(findText).join(replaceText),
        contact: resumeData.header.contact.split(findText).join(replaceText),
        intention: resumeData.header.intention.split(findText).join(replaceText),
      },
      sections: resumeData.sections.map((section: ResumeSection) => {
        if (!replaceAll && section.id !== firstMatchId) return section
        return { ...section, title: section.title.split(findText).join(replaceText), content: section.content.split(findText).join(replaceText) }
      })
    })
  }

  // ===================== 撤销/重置：回退到原始简历 =====================
  const handleResetResume = async () => {
    if (!job?.id) return
    const confirmed = window.confirm(
      "⚠️ 此操作将删除当前岗位的所有 AI 改写内容，并自动回退到简历库中「启用」状态的原始简历。\n\n此操作不可逆，确定继续吗？"
    )
    if (!confirmed) return

    setIsResetting(true)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/reset_resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id })
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        // 1. 清空所有 localStorage 缓存
        if (wizardStorageKey) localStorage.removeItem(wizardStorageKey)
        try { localStorage.removeItem(`resume_meta_${job.id}`) } catch {}
        try { localStorage.removeItem('resume_initial_draft_cache') } catch {}
        // 2. 通知上层重新加载简历（清空 manualRefinedResume 会触发上层从飞书重新拉取原始简历）
        onUpdateJob({ ...job, manualRefinedResume: "" })
        // 3. 重置向导
        setWizardStep('idle')
        setWizardProgress(DEFAULT_WIZARD_PROGRESS)
        setWizardHidden(false)
        setGrillQueue([])
        setGrillSuggestions([])
        setGrillPanelOpen(false)
        setActiveAtsIds([])
        setActiveSyncIds([])
        alert("✅ 已成功回退到原始简历")
      } else {
        alert("❌ 重置失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch (err: any) {
      alert("❌ 重置失败: " + (err.message || err))
    } finally {
      setIsResetting(false)
    }
  }

  const handleSaveResume = async () => {
    if (!job?.id) return
    setIsSavingResume(true)
    try {
      const mdParts: string[] = []
      for (const section of resumeData.sections) {
        if (!section.title.trim() && !section.content.trim()) continue
        if (section.isArchived) continue
        mdParts.push(`${section.level === 2 ? "##" : "#"} ${section.title}\n\n${section.content.trim()}\n`)
      }
      const resumeMarkdown = mdParts.join("\n").trim()
      const requestBody: any = { job_id: job.id, resume_text: resumeMarkdown, platform: job.platform || "BOSS直聘" }
      if (wizardStep === 'step6') {
        requestBody.follow_status = "待投递"
      }
      const response = await fetch(`${API_BASE}/api/save_manual_resume`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      })
      const data = await response.json()
      if (data.status === "success") {
        const nextJob = { ...job, manualRefinedResume: resumeMarkdown }
        if (wizardStep === 'step6') {
          nextJob.followStatus = "待投递"
        }
        onUpdateJob(nextJob)
        // Step 6 收尾：若当前处于向导 Step 6，则标记完成并自动退出
        if (wizardStep === 'step6') {
          setWizardProgress(p => ({ ...p, savedDone: true }))
          if (wizardStorageKey) saveWizardProgress('step6', { ...wizardProgress, savedDone: true })
          setTimeout(() => {
            setWizardStep('idle')
            setWizardProgress(DEFAULT_WIZARD_PROGRESS)
            setWizardHidden(false)
            if (wizardStorageKey) localStorage.removeItem(wizardStorageKey)
          }, 1500)
          alert("✅ 简历已保存到飞书，向导流程圆满收官！")
        } else {
          alert("✅ 简历已保存到飞书")
        }
      }
    } catch { alert("❌ 保存失败") } finally { setIsSavingResume(false) }
  }

  const handleQAEvaluate = async () => {
    if (!job?.id) return
    setIsQAEvaluating(true)
    try {
      const resumeText = `${resumeData.header.name}\n${resumeData.header.contact}\n${resumeData.header.intention}\n\n${resumeData.sections.map((s: ResumeSection) => `${s.level === 2 ? "## " : "# "}${s.title}\n${s.content}`).join("\n\n")}`
      const response = await fetch(`${API_BASE}/api/qa_evaluate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id, job_description: job.jobDescription, resume_text: resumeText, platform: job.platform || "BOSS直聘" }),
      })
      const data = await response.json()
      if (data.status === "success" && data.qa_report) {
        onQAComplete?.(data.qa_report)
        onUpdateJob({ ...job, secondQaReport: typeof data.qa_report === 'string' ? data.qa_report : JSON.stringify(data.qa_report) })
        alert("✅ QA 评估完成！")
      }
    } catch { alert("❌ 评估失败") } finally { setIsQAEvaluating(false) }
  }


  // 🌟 修复 1：直接使用结构出来的变量，抛弃 `props as any`
  const currentJobLogs = (job && jobLiveLogs?.[job.id]) || []
  const currentJobTask = job && processingJobs?.[job.id]
  const globalStatus = globalTaskStatus

  const agentStates = useMemo(() => {
    const logsStr = currentJobLogs.join("\n")
    // 🌟 修复 2：强制类型断言，明确告诉 TS 这是 "idle" | "active" | "success"，修复 StepBadge 传参报错
    return {
      retriever: (logsStr.includes("Agent 1") ? (logsStr.includes("评估完成") ? "success" : "active") : "idle") as "idle" | "active" | "success",
      rewriter: (logsStr.includes("Agent 2") ? (logsStr.includes("深度重构完成") ? "success" : "active") : "idle") as "idle" | "active" | "success",
      surgeon: (logsStr.includes("Agent 3") ? (logsStr.includes("微创手术完成") ? "success" : "active") : "idle") as "idle" | "active" | "success",
      formatter: (logsStr.includes("Agent 4") ? "active" : "idle") as "idle" | "active" | "success",
    }
  }, [currentJobLogs])

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-border bg-slate-100/60" data-resume-canvas>
      
      {/* 🌟 建议卡片浮层面板 */}
      {diagnosisSuggestions.length > 0 && (
        <div className="absolute right-4 top-20 z-50 w-80 max-h-[70vh] overflow-y-auto rounded-xl border border-amber-200 bg-white/95 backdrop-blur-md shadow-2xl p-4 animate-in slide-in-from-right-4 duration-300">
          <div className="flex items-center justify-between mb-3 border-b border-amber-100 pb-2">
            <h4 className="text-sm font-bold text-amber-800 flex items-center gap-1.5"><Target className="h-4 w-4" /> 靶向微操建议</h4>
            <Button variant="ghost" size="icon" className="h-6 w-6 text-slate-400 hover:text-slate-600" onClick={() => setDiagnosisSuggestions([])}>
              <XCircle className="h-4 w-4" />
            </Button>
          </div>
          <div className="space-y-3">
            {diagnosisSuggestions.map((s, idx) => (
              <div key={idx} className="p-3 bg-amber-50/50 border border-amber-100 rounded-lg">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-semibold text-slate-700 bg-white px-1.5 py-0.5 rounded border border-slate-200">{s.section_title}</span>
                  <span className="text-[10px] font-mono text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">{s.action}</span>
                </div>
                <p className="text-xs text-slate-600 leading-relaxed mb-2.5">{s.reason}</p>
                <div className="flex justify-end">
                  <Button size="sm" className="h-6 px-2.5 text-[10px] bg-amber-500 hover:bg-amber-600 text-white" onClick={() => applyDiagnosisAction(s)}>
                    采纳并去修改
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 🌟 全局向导状态顶栏 */}
      {wizardStep !== 'idle' && !wizardHidden && (
        <div className={`absolute inset-x-4 top-14 z-40 rounded-xl border p-4 shadow-xl backdrop-blur-md transition-all animate-in fade-in slide-in-from-top-4 duration-300 ${
          wizardStep === 'step6'
            ? "border-emerald-200 bg-emerald-50/95"
            : wizardStep === 'step5' || wizardStep === 'step4'
              ? "border-blue-200 bg-blue-50/95"
              : "border-amber-200 bg-amber-50/95"
        }`}>
          <div className="flex flex-col gap-2">
            <div className={`flex items-center justify-between border-b pb-2 ${
              wizardStep === 'step6' ? "border-emerald-100" : wizardStep === 'step5' || wizardStep === 'step4' ? "border-blue-100" : "border-amber-100"
            }`}>
              <h4 className={`text-sm font-bold flex items-center gap-1.5 ${
                wizardStep === 'step6' ? "text-emerald-800" : wizardStep === 'step5' || wizardStep === 'step4' ? "text-blue-800" : "text-amber-800"
              }`}>
                <Target className="h-4 w-4" />
                {wizardStep === 'step1' ? "向导：第一步 - 宏观裁剪" :
                 wizardStep === 'step2' ? "向导：第二步 - 初版改写" :
                 wizardStep === 'step3' ? "向导：第三步 - 深度拷问 Grill-me" :
                 wizardStep === 'step4' ? "向导：第四步 - ATS 全局靶向" :
                 wizardStep === 'step5' ? "向导：第五步 - AI 联动更新" :
                 "向导：第六步 - 保存到飞书"}
              </h4>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100" onClick={() => setWizardHidden(true)}>隐藏向导</Button>
                <Button variant="ghost" size="sm" className="h-6 px-2 text-xs text-rose-500 hover:text-rose-700 hover:bg-rose-50" onClick={() => {
                  if (window.confirm('确定要退出向导吗？\n\n退出后将清除当前进度，下次需要重新开始。')) {
                    setWizardStep('idle')
                    setWizardProgress(DEFAULT_WIZARD_PROGRESS)
                    setWizardHidden(false)
                    if (wizardStorageKey) localStorage.removeItem(wizardStorageKey)
                  }
                }}>退出向导</Button>
              </div>
            </div>

            <p className={`text-xs leading-relaxed ${
              wizardStep === 'step6' ? "text-emerald-700" : wizardStep === 'step5' || wizardStep === 'step4' ? "text-blue-700" : "text-amber-700"
            }`}>
              {wizardStep === 'step1' ? (
                !wizardProgress.pruneDone || !wizardProgress.compressDone ? (
                  <span>正在分析项目去留与经历折叠... 请向下滚动查看展开的红色/紫色裁剪面板，完成采纳或放弃。</span>
                ) : (
                  <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 裁剪完成！点击右侧按钮进入下一步。</span>
                )
              ) : wizardStep === 'step2' ? (
                (!wizardProgress.initialDraftProjectDone || !wizardProgress.initialDraftWorkDone) ? (
                  <span>正在结合 JD 对幸存经历进行基底对齐与结构重组... 请查看蓝色面板，审核并采纳初改。</span>
                ) : (
                  <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 初改完成！点击右侧按钮进入第三步。</span>
                )
              ) : wizardStep === 'step3' ? (
                grillPanelOpen ? (
                  <span>下方是 AI 挑出的「内容单薄」经历，请勾选后逐条深挖补充细节。</span>
                ) : grillQueue.length > 0 ? (
                  <span>正在逐条深挖经历细节... 当前进度：已完成 {grillSuggestions.filter(s => {
                    const sec = resumeData.sections.find(x => x.title.includes(s.section_title) || s.section_title.includes(x.title))
                    return sec?.isGrilled
                  }).length} 段，剩余 {grillQueue.length} 段。</span>
                ) : wizardProgress.grillDone ? (
                  <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 深挖完成！点击右侧按钮进入第四步（ATS）。</span>
                ) : (
                  <span>正在准备深挖建议...</span>
                )
              ) : wizardStep === 'step4' ? (
                (() => {
                  const allLevel2 = resumeData.sections.filter(s => s.level === 2 && !s.isArchived)
                  const doneCount = allLevel2.filter(s => s.isAtsAligned).length
                  const total = allLevel2.length
                  return wizardProgress.atsDone ? (
                    <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 全部经历 ATS 对齐完成（{doneCount}/{total}）！进入第五步 AI 联动更新。</span>
                  ) : (
                    <span>正在为所有经历并行注入 ATS 关键词（最多同时处理 3 段）... 当前进度：{doneCount}/{total} 段已完成。</span>
                  )
                })()
              ) : wizardStep === 'step5' ? (
                (() => {
                  const syncSections = resumeData.sections.filter(s => s.level === 1 && !s.title.includes("项目") && !s.title.includes("工作") && !s.isArchived && (s.title.trim() || s.content.trim()))
                  const doneCount = syncSections.filter(s => s.isSynced).length
                  const total = syncSections.length
                  return wizardProgress.syncDone ? (
                    <span className="font-semibold text-green-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 基础模块联动更新完成（{doneCount}/{total}）！进入第六步保存。</span>
                  ) : (
                    <span>正在基于最新经历自动更新个人总结与专业技能等基础模块... 当前进度：{doneCount}/{total} 模块已完成。</span>
                  )
                })()
              ) : wizardStep === 'step6' ? (
                <span className="font-semibold text-emerald-700 flex items-center gap-1.5"><CheckCircle className="size-3" /> 全部就绪！点击下方高亮的「保存到飞书」按钮完成收官。</span>
              ) : null}
            </p>

            <div className="flex justify-end gap-2 mt-1">
              {wizardStep === 'step1' ? (
                <>
                  <Button size="sm" variant="outline" className="h-7 text-xs border-amber-300 text-amber-700 hover:bg-amber-100" onClick={() => {
                    setWizardProgress(p => ({...p, pruneDone: true, compressDone: true}))
                  }}>一键跳过裁剪</Button>
                  <Button size="sm" className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled={!wizardProgress.pruneDone || !wizardProgress.compressDone}
                    onClick={() => setWizardStep('step2')}>进入第二步 ➔</Button>
                </>
              ) : wizardStep === 'step2' ? (
                <>
                  <Button size="sm" variant="outline" className="h-7 text-xs border-amber-300 text-amber-700 hover:bg-amber-100" onClick={() => {
                    setWizardProgress(p => ({...p, initialDraftProjectDone: true, initialDraftWorkDone: true}))
                  }}>一键跳过初改</Button>
                  <Button size="sm" className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled={!wizardProgress.initialDraftProjectDone || !wizardProgress.initialDraftWorkDone}
                    onClick={() => setWizardStep('step3')}>进入第三步 ➔</Button>
                </>
              ) : wizardStep === 'step3' ? (
                <>
                  <Button size="sm" variant="outline" className="h-7 text-xs border-amber-300 text-amber-700 hover:bg-amber-100" onClick={() => {
                    setGrillQueue([])
                    setGrillPanelOpen(false)
                    setWizardProgress(p => ({...p, grillDone: true}))
                  }}>一键跳过深挖</Button>
                  <Button size="sm" className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled={!wizardProgress.grillDone}
                    onClick={() => setWizardStep('step4')}>进入第四步 ➔</Button>
                </>
              ) : wizardStep === 'step4' ? (
                <>
                  <Button size="sm" variant="outline" className="h-7 text-xs border-blue-300 text-blue-700 hover:bg-blue-100" onClick={() => {
                    setActiveAtsIds([])
                    setWizardProgress(p => ({...p, atsDone: true}))
                  }}>一键跳过ATS</Button>
                  <Button size="sm" className="h-7 text-xs bg-blue-500 hover:bg-blue-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled={!wizardProgress.atsDone}
                    onClick={() => setWizardStep('step5')}>进入第五步 ➔</Button>
                </>
              ) : wizardStep === 'step5' ? (
                <>
                  <Button size="sm" variant="outline" className="h-7 text-xs border-blue-300 text-blue-700 hover:bg-blue-100" onClick={() => {
                    setActiveSyncIds([])
                    setWizardProgress(p => ({...p, syncDone: true}))
                  }}>一键跳过联动更新</Button>
                  <Button size="sm" className="h-7 text-xs bg-blue-500 hover:bg-blue-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled={!wizardProgress.syncDone}
                    onClick={() => setWizardStep('step6')}>进入第六步 ➔</Button>
                </>
              ) : wizardStep === 'step6' ? (
                <Button size="sm" className="h-7 text-xs bg-emerald-500 hover:bg-emerald-600 text-white animate-pulse" onClick={handleSaveResume} disabled={isSavingResume}>
                  {isSavingResume ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Save className="mr-1 h-3 w-3" />}
                  保存到飞书并收官
                </Button>
              ) : null}
            </div>

            {/* Step 3：AI 深挖建议勾选面板 */}
            {wizardStep === 'step3' && grillPanelOpen && (
              <GrillSuggestionPanel
                suggestions={grillSuggestions}
                sections={resumeData.sections}
                isLoading={isLoadingGrillSuggestions}
                onStartGrill={handleStartGrillQueue}
                onSkip={() => {
                  setGrillQueue([])
                  setGrillPanelOpen(false)
                  setWizardProgress(p => ({ ...p, grillDone: true }))
                }}
              />
            )}
          </div>
        </div>
      )}

      {/* 🌟 核心打通：全链路收官成功面板 */}
      {globalStatus === "completed" && currentJobLogs.some(log => log.includes("云端数据落盘成功")) && (
        <div className="absolute inset-x-4 top-14 z-40 rounded-xl border border-emerald-200 bg-emerald-50/95 p-5 text-center shadow-xl backdrop-blur-md animate-in zoom-in-95 duration-300">
          <div className="text-2xl">🎉</div>
          <h4 className="mt-1 text-sm font-bold text-emerald-900">多Agent全链路深度改写圆满收官！</h4>
          <p className="mt-1 text-xs text-emerald-700/80">完美的定制简历已物理同步至飞书云表格。本面板将在 10 秒内自动隐退，为你无缝翻转白盒比对工作台...</p>
        </div>
      )}

      {/* ToolBar */}
      <TooltipProvider delayDuration={200}>
        <div className="flex items-center gap-1 border-b border-border bg-card px-3 py-2 pr-12 shadow-sm">
          <span className="mr-3 text-sm font-semibold text-slate-800">原始简历 · 可编辑</span>
          <Tooltip><TooltipTrigger asChild><Button size="icon" variant="ghost" className="size-8 text-slate-600" onClick={handleBold} onMouseDown={(e: React.MouseEvent<HTMLButtonElement>) => e.preventDefault()}><Bold className="size-4" /></Button></TooltipTrigger><TooltipContent>加粗</TooltipContent></Tooltip>
          <Popover>
            <Tooltip><TooltipTrigger asChild><PopoverTrigger asChild><Button size="icon" variant="ghost" className="size-8 text-slate-600"><Replace className="size-4" /></Button></PopoverTrigger></TooltipTrigger><TooltipContent>查找与替换</TooltipContent></Tooltip>
            <PopoverContent className="w-80 p-4 shadow-xl rounded-xl border-slate-200" align="start">
              <div className="flex flex-col gap-3.5">
                <h4 className="text-sm font-bold text-slate-800">查找与替换</h4>
                <div className="flex flex-col gap-2.5">
                  <div className="relative flex items-center">
                    <Search className="absolute left-2.5 size-4 text-slate-400" />
                    <Input placeholder="要查找的词..." value={findText} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFindText(e.target.value)} className="h-8 pl-8 pr-20 text-xs focus-visible:ring-indigo-500" />
                    {findText && (
                      <div className="absolute right-1 flex items-center gap-0.5 text-[10px] text-slate-400">
                        <span className="mr-1">{totalMatches > 0 ? currentMatchIndex + 1 : 0}/{totalMatches}</span>
                        <Button variant="ghost" size="icon" className="size-6 p-0 hover:bg-slate-100" onClick={() => { if (totalMatches > 0) { const n = currentMatchIndex > 0 ? currentMatchIndex - 1 : totalMatches - 1; setCurrentMatchIndex(n); scrollToMatch(n) } }}><ChevronUp className="size-3" /></Button>
                        <Button variant="ghost" size="icon" className="size-6 p-0 hover:bg-slate-100" onClick={() => { if (totalMatches > 0) { const n = currentMatchIndex < totalMatches - 1 ? currentMatchIndex + 1 : 0; setCurrentMatchIndex(n); scrollToMatch(n) } }}><ChevronDown className="size-3" /></Button>
                      </div>
                    )}
                  </div>
                  <Input placeholder="替换为..." value={replaceText} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setReplaceText(e.target.value)} className="h-8 text-xs focus-visible:ring-indigo-500" />
                </div>
                <div className="flex items-center gap-2">
                  <Button variant="secondary" size="sm" className="flex-1 h-8 text-xs font-medium" onClick={() => handleReplace(false)}>替换</Button>
                  <Button size="sm" className="flex-1 h-8 text-xs bg-indigo-600 hover:bg-indigo-700 font-medium" onClick={() => handleReplace(true)}>全部替换</Button>
                </div>
              </div>
            </PopoverContent>
          </Popover>
          <Separator orientation="vertical" className="mx-2 h-5" />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className={`size-8 hover:bg-indigo-50 hover:text-indigo-600 ${
                  wizardStep === 'step6' ? "text-emerald-600 bg-emerald-50 ring-2 ring-emerald-300 animate-pulse" : "text-slate-600"
                }`}
                onClick={handleSaveResume}
                disabled={isSavingResume}
              >
                {isSavingResume ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>保存到飞书{wizardStep === 'step6' ? "（向导最后一步）" : ""}</TooltipContent>
          </Tooltip>
          <Tooltip><TooltipTrigger asChild><Button size="icon" variant="ghost" className="size-8 text-slate-600 hover:text-purple-600 hover:bg-purple-50" onClick={handleQAEvaluate} disabled={isQAEvaluating}>{isQAEvaluating ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}</Button></TooltipTrigger><TooltipContent>再次 AI 评估</TooltipContent></Tooltip>


          {/* 🌟 全局向导诊断按钮 (替换原有功能) */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className={`size-8 font-bold border ${
                  wizardStep !== 'idle' 
                    ? wizardHidden 
                      ? "text-blue-600 hover:text-blue-700 hover:bg-blue-50 border-blue-200 bg-blue-50/30 animate-pulse" 
                      : "text-slate-400 cursor-not-allowed border-slate-100 bg-slate-50/30"
                    : "text-amber-600 hover:text-amber-700 hover:bg-amber-50 border-amber-100 bg-amber-50/30"
                }`}
                onClick={() => {
                  if (wizardStep !== 'idle' && wizardHidden) {
                    // 向导进行中但被隐藏，点击恢复显示
                    setWizardHidden(false)
                  } else if (wizardStep === 'idle') {
                    // 向导未启动，点击启动新向导
                    handleStartWizard()
                  }
                  // 向导进行中且显示，按钮 disabled，不会触发点击
                }}
                disabled={wizardStep !== 'idle' && !wizardHidden}
              >
                <Target className={`size-4 ${wizardStep !== 'idle' && wizardHidden ? "text-blue-600" : wizardStep !== 'idle' ? "text-slate-400" : "text-amber-600"}`} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <span className="font-semibold text-amber-600">
                {wizardStep !== 'idle' 
                  ? wizardHidden 
                    ? "📋 恢复向导（有未完成进度）" 
                    : "⏳ 向导进行中..."
                  : "🎯 AI 全局扫描向导"}
              </span>
            </TooltipContent>
          </Tooltip>

          {/* 🌟 撤销/重置：回退到原始简历 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="size-8 text-rose-500 hover:text-rose-600 hover:bg-rose-50"
                onClick={handleResetResume}
                disabled={isResetting}
              >
                {isResetting ? <Loader2 className="size-4 animate-spin" /> : <RotateCcw className="size-4" />}
              </Button>
            </TooltipTrigger>
            <TooltipContent><span className="font-semibold text-rose-600">🔄 撤销全部改写，回退原始简历</span></TooltipContent>
          </Tooltip>

          <Separator orientation="vertical" className="mx-2 h-5" />
          <ToolbarButton icon={<ImageIcon className="size-4" />} label="导出图片" onClick={() => onExport("image")} />
          <ToolbarButton icon={<FileDown className="size-4" />} label="导出 PDF" onClick={() => onExport("pdf")} />
          <Separator orientation="vertical" className="mx-2 h-5" />
          <Tooltip><TooltipTrigger asChild><Button size="sm" onClick={() => setIsPreviewOpen(true)} className="ml-auto h-8 gap-1.5 bg-slate-900 text-white hover:bg-slate-800"><Eye className="size-4" />纸张排版预览</Button></TooltipTrigger><TooltipContent>模拟 A4 纸张排版</TooltipContent></Tooltip>
        </div>
      </TooltipProvider>

      {/* 🌟 恢复旧版大白板编辑器区域 */}
      <ScrollArea className="min-h-0 flex-1 bg-slate-100/50">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 p-5 pb-24">
          <div className="w-full bg-white shadow-sm p-8 rounded-xl space-y-3">
            <EditableBlock id="header" hoveredBlock={hoveredBlock} setHoveredBlock={setHoveredBlock}>
              <div className="text-center border-b border-border pb-3">
                <div className="text-xl font-bold text-slate-800 outline-none tracking-wide" contentEditable suppressContentEditableWarning onBlur={(e: React.FocusEvent<HTMLDivElement>) => { const newName = e.currentTarget.innerText.trim(); onChange({ ...resumeData, header: { ...resumeData.header, name: newName } }); }}>{resumeData.header.name}</div>
                <div className="mt-1.5 text-slate-600 text-[13px] outline-none" contentEditable suppressContentEditableWarning onBlur={(e: React.FocusEvent<HTMLDivElement>) => onChange({ ...resumeData, header: { ...resumeData.header, contact: e.currentTarget.innerText.trim() } })}>{resumeData.header.contact}</div>
                <div className="mt-1 text-slate-500 text-[12px] outline-none leading-relaxed" contentEditable suppressContentEditableWarning onBlur={(e: React.FocusEvent<HTMLDivElement>) => onChange({ ...resumeData, header: { ...resumeData.header, intention: e.currentTarget.innerText.trim() } })}>{resumeData.header.intention}</div>
              </div>
            </EditableBlock>
            {(() => {
              const expTexts: string[] = []
              let currentPrimaryTopic = ""
              for (const sec of resumeData.sections) {
                if (sec.level === 1) {
                  currentPrimaryTopic = sec.title || ""
                } else if (sec.level === 2) {
                  if (currentPrimaryTopic.includes("工作") || currentPrimaryTopic.includes("项目") || currentPrimaryTopic.includes("经验")) {
                    expTexts.push(`[${sec.title}]\n${sec.content}`)
                  }
                }
              }
              const localExpContext = expTexts.join("\n\n")

              return resumeData.sections.map((section: ResumeSection, index: number) => {
                if (section.isArchived) return null
                if (!section.title?.trim() && !section.content?.trim()) return null

                let hasLevel2Children = false;
                if (section.level === 1) {
                  for (let j = index + 1; j < resumeData.sections.length; j++) {
                    if (resumeData.sections[j].level === 2) {
                      if (!resumeData.sections[j].isArchived) {
                        hasLevel2Children = true;
                        break;
                      }
                    } else {
                      break;
                    }
                  }
                }

                let activeChildren: ResumeSection[] | undefined = undefined;
                let archivedChildren: ResumeSection[] | undefined = undefined;
                if (section.level === 1) {
                  activeChildren = [];
                  archivedChildren = [];
                  for (let j = index + 1; j < resumeData.sections.length; j++) {
                    if (resumeData.sections[j].level === 2) {
                      if (resumeData.sections[j].isArchived) {
                        archivedChildren.push(resumeData.sections[j]);
                      } else {
                        activeChildren.push(resumeData.sections[j]);
                      }
                    } else {
                      break;
                    }
                  }
                }

                return (
                  <EditableBlock key={section.id} id={section.id} hoveredBlock={hoveredBlock} setHoveredBlock={setHoveredBlock}>
                    <div className={section.level === 2 ? "ml-8" : ""}>
                      <LegacyEditableSection
                        section={section} isMatched={matchedSectionIds.includes(section.id)}
                        hideContent={hasLevel2Children}
                        job={job} experiencesContext={localExpContext}
                        childrenSections={activeChildren}
                        archivedChildrenSections={archivedChildren}
                        onDeleteSections={handleDeleteSections}
                        onRestoreSections={handleRestoreSections}
                        onSelectText={onTextSelect} onCommit={handleSectionCommit} onCommitMultiple={handleMultipleSectionCommit}
                        onDragStart={setDraggingSectionId} onDropTo={handleDropTo}
                        onMoveUp={() => moveSection(index, -1)} onMoveDown={() => moveSection(index, 1)}
                        findText={findText} currentMatchIndex={currentMatchIndex} onRegisterMatch={registerMatch}
                        fullResumeContext={globalResumeMarkdown}
                        activeToolToOpen={activeToolToOpen?.sectionId === section.id ? activeToolToOpen.tool : null}
                        onClearActiveTool={() => setActiveToolToOpen(null)}
                        wizardStep={wizardStep}
                        isAtsActive={activeAtsIds.includes(section.id)}
                        isSyncActive={activeSyncIds.includes(section.id)}
                        onWizardComplete={handleWizardComplete}
                      />
                    </div>
                  </EditableBlock>
                )
              })
            })()}
            <button onClick={handleAddSection} className="w-full mt-4 py-3 border-2 border-dashed border-slate-300 rounded-lg text-slate-500 hover:border-indigo-400 hover:bg-indigo-50/50 hover:text-indigo-600 transition-all flex items-center justify-center gap-2 text-sm font-medium">
              <Plus className="size-4" />添加自定义模块
            </button>
          </div>
        </div>
      </ScrollArea>

      {/* 🌟 纸张预览弹窗 */}
      {isPreviewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs">
          <div className="flex h-[90vh] w-[840px] flex-col rounded-2xl bg-white p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b pb-2">
              <h3 className="text-sm font-bold text-slate-800">👁️ 简历渲染纸张标准排版预览</h3>
              <Button variant="ghost" size="icon" onClick={() => setIsPreviewOpen(false)}><X className="size-4" /></Button>
            </div>
            <div className="flex-1 overflow-y-auto bg-slate-100 p-6 flex justify-center">
              <div className="w-[595px] min-h-[842px] bg-white p-8 shadow-md border border-slate-200 text-[11px] leading-relaxed text-slate-900 font-sans space-y-4">
                <div className="text-center border-b pb-2">
                  <h1 className="text-base font-bold tracking-wide">{job.manualRefinedResume ? "[脱敏姓名]" : resumeData.header.name}</h1>
                  <p className="text-slate-500 text-[10px] mt-1">{resumeData.header.contact}</p>
                  <p className="text-slate-500 text-[10px] mt-0.5">{resumeData.header.intention}</p>
                </div>
                {resumeData.sections.map((m: ResumeSection) => (
                  <div key={m.id} className={`space-y-1 ${m.level === 2 ? "ml-4 mt-2" : "mt-4"}`}>
                    <h2 className={`font-bold ${m.level === 2 ? "text-[11px] text-slate-800 border-none pb-0" : "text-xs border-b border-slate-300 pb-0.5 text-indigo-900"}`}>{m.title}</h2>
                    <p className="whitespace-pre-wrap text-slate-700 text-[10.5px]">{m.content}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// 🌟 辅助组件：ToolbarButton
// ============================================================================
function ToolbarButton({
  icon,
  label,
  onClick
}: {
  icon: React.ReactNode
  label: string
  onClick?: () => void
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button size="icon" variant="ghost" className="size-8 text-slate-600" onClick={onClick}>
          {icon}
          <span className="sr-only">{label}</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function StepBadge({ label, desc, status }: { label: string; desc: string; status: "idle" | "active" | "success" }) {
  return (
    <div className={`flex flex-col gap-1 p-2 rounded-lg border transition-all ${status === "success" ? "bg-emerald-50 border-emerald-200 text-emerald-900" :
      status === "active" ? "bg-indigo-50 border-indigo-200 text-indigo-900 animate-pulse ring-1 ring-indigo-300" :
        "bg-slate-50 border-slate-100 text-slate-400 opacity-60"
      }`}>
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold truncate">{label}</span>
        {status === "success" && <span className="text-[10px] text-emerald-600 font-bold">✅</span>}
        {status === "active" && <Loader2 className="h-2.5 w-2.5 animate-spin text-indigo-600" />}
      </div>
      <span className="text-[9px] leading-tight opacity-80">{desc}</span>
    </div>
  )
}
