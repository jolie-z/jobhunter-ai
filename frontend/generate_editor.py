import re

wizard_ui_str = """
  // ========== AI 向导状态与函数 (从 V1 保留) ==========
  const [wizardStep, setWizardStep] = useState<WizardStep>('idle')
  const [wizardProgress, setWizardProgress] = useState<WizardProgress>(DEFAULT_WIZARD_PROGRESS)
  const [wizardHidden, setWizardHidden] = useState(false)

  const saveWizardProgress = useCallback((step: WizardStep, progress: WizardProgress) => {
    if (typeof window === 'undefined') return
    const key = job?.id ? `wizard_${job.id}` : null
    if (!key) return
    localStorage.setItem(key, JSON.stringify({ wizardStep: step, progress }))
  }, [job?.id])

  useEffect(() => {
    if (wizardStep !== 'idle') saveWizardProgress(wizardStep, wizardProgress)
  }, [wizardStep, wizardProgress, saveWizardProgress])

  const handleStartWizard = () => {
    if (typeof window !== 'undefined' && job?.id) {
      const saved = localStorage.getItem(`wizard_${job.id}`)
      if (saved) {
        try {
          const data = JSON.parse(saved)
          if (data.wizardStep && data.wizardStep !== 'idle') {
            setWizardStep(data.wizardStep)
            setWizardProgress({ ...DEFAULT_WIZARD_PROGRESS, ...data.progress })
            setWizardHidden(false)
            return
          }
        } catch (e) { console.warn(e) }
      }
    }
    const fresh: WizardProgress = {
      pruneDone: false, compressDone: false, initialDraftProjectDone: false, initialDraftWorkDone: false,
      grillDone: false, atsDone: false, syncDone: false, savedDone: false
    }
    setWizardProgress(fresh)
    setWizardStep('step1')
    setWizardHidden(false)
  }

  const handleWizardComplete = useCallback((
    tool: 'prune' | 'compress' | 'initial_draft_project' | 'initial_draft_work' | 'grill_item_done' | 'ats_item_done' | 'sync_item_done',
    sectionId?: string
  ) => {
    if (tool === 'grill_item_done' && sectionId) {
      setWizardProgress(p => ({ ...p, grillDone: true })) // Simplify logic for V2 for now
    } else if (tool === 'ats_item_done' && sectionId) {
      setWizardProgress(p => ({ ...p, atsDone: true }))
    } else if (tool === 'sync_item_done' && sectionId) {
      setWizardProgress(p => ({ ...p, syncDone: true }))
    } else {
      setWizardProgress(p => ({ ...p, [`${tool}Done`]: true }))
    }
  }, [])
  // ===================================================
"""

new_content = """"use client"

import { useState, useMemo, useEffect, useCallback, useRef } from "react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import type { JobData } from "@/types/job"
import type { ResumeDataV2 } from "@/types/resume"
import { Button } from "@/components/ui/button"
import { ModuleCard } from "../resume-builder/module-card"
import { PersonalInfo } from "../resume-builder/personal-info"
import { ExperienceList } from "../resume-builder/experience-list"
import { MarkdownEditor } from "../resume-builder/markdown-editor"
import { AiModuleSyncInline } from "../resume-builder/ai-module-sync-inline"
import { Wand2, Sparkles, Loader2, Plus, Briefcase, FolderGit2, GraduationCap, Wrench, User, Target, ChevronRight, CheckCircle2, ChevronDown } from "lucide-react"

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

export interface V2ResumeEditorProps {
  job?: JobData | null
  selectedText?: string
  selectedSectionId?: string | null
  onClearSelection?: () => void
  onTextSelect?: (text: string, sectionId: string | null) => void
  processingJobs?: Record<string, string>
  jobLiveLogs?: Record<string, string[]>
  globalTaskStatus?: "idle" | "running" | "completed"
}

export function V2ResumeEditor({
  job,
  selectedText,
  selectedSectionId,
  onClearSelection,
  onTextSelect,
  processingJobs,
  jobLiveLogs,
  globalTaskStatus
}: V2ResumeEditorProps) {
  const { 
    resumeData, updateSummary, updateAdditional, 
    moveModuleUp, moveModuleDown, addModule, removeModule, 
    addCustomModule, updateModuleTitle 
  } = useResumeV2Store()

  const [activeSyncModuleId, setActiveSyncModuleId] = useState<string | null>(null)
  const [formattingModuleId, setFormattingModuleId] = useState<string | null>(null)

  const handleFormatMarkdown = async (id: string, title: string, content: string, onChange: (val: string) => void) => {
    if (!content.trim()) return
    setFormattingModuleId(id)
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"}/api/strategy/format_markdown`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_title: title, current_content: content })
      })
      const data = await res.json()
      if (data.status === "success" && data.data?.formatted_content) {
        onChange(data.data.formatted_content)
      }
    } catch (e) {
      console.error("Format markdown failed:", e)
    } finally {
      setFormattingModuleId(null)
    }
  }

""" + wizard_ui_str + """

  return (
    <div className="flex h-full w-full overflow-hidden bg-background relative">
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6 sm:py-8">
          
          <div className="flex justify-between items-center bg-indigo-50/50 p-3 rounded-lg border border-indigo-100 mb-2">
            <div>
              <h3 className="text-sm font-semibold text-indigo-900 flex items-center gap-1.5"><Sparkles className="w-4 h-4 text-indigo-600"/> AI 深度改写引擎</h3>
              <p className="text-xs text-indigo-700/70 mt-1">按照标准工业流水线，对您的简历进行深度对齐与优化</p>
            </div>
            {wizardStep === 'idle' ? (
              <Button size="sm" className="bg-indigo-600 hover:bg-indigo-700 shadow-sm h-8" onClick={handleStartWizard}>
                启动六步深度改写 ➔
              </Button>
            ) : (
              <Button variant="outline" size="sm" className="h-8 border-indigo-200 text-indigo-700 bg-white" onClick={() => {
                setWizardStep('idle')
                setWizardProgress(DEFAULT_WIZARD_PROGRESS)
              }}>
                中止重写
              </Button>
            )}
          </div>

          {/* 1. 个人信息 (永远置顶) */}
          <ModuleCard title="个人信息" icon={<User className="h-4 w-4" />} isFixed={true}>
            <PersonalInfo />
          </ModuleCard>

          {/* 动态渲染其余模块 */}
          {(resumeData?.moduleOrder || ["summary", "workExperience", "personalProjects", "education", "additional"])
            .filter(modKey => modKey !== 'personalInfo')
            .map((modKey, idx, arr) => {
              const title = resumeData?.moduleTitles?.[modKey] || {
                summary: "个人总结",
                workExperience: "工作经历",
                personalProjects: "项目经历",
                education: "教育经历",
                additional: "附加信息"
              }[modKey] || modKey;

              const context = JSON.stringify({
                workExperience: resumeData?.workExperience,
                personalProjects: resumeData?.personalProjects
              });

              const isFirst = idx === 0;
              const isLast = idx === arr.length - 1;
              const commonProps = {
                isFixed: false,
                canMoveUp: !isFirst,
                canMoveDown: !isLast,
                onMoveUp: () => moveModuleUp(modKey),
                onMoveDown: () => moveModuleDown(modKey),
                onDelete: () => removeModule(modKey),
                onTitleChange: (newTitle: string) => updateModuleTitle(modKey, newTitle)
              };

              if (modKey === "summary") {
                return (
                  <ModuleCard key={modKey} title={title} icon={<Sparkles className="h-4 w-4" />} {...commonProps}>
                    <div className="flex flex-col gap-3">
                      <MarkdownEditor
                        value={resumeData?.summary || ""}
                        onChange={updateSummary}
                        placeholder={`在此填写${title}的内容...`}
                        minHeight="min-h-[96px]"
                      />
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" size="sm" onClick={() => handleFormatMarkdown(modKey, title, resumeData?.summary || "", updateSummary)}>
                          自动排版
                        </Button>
                      </div>
                    </div>
                  </ModuleCard>
                );
              }

              if (modKey === "workExperience") {
                return (
                  <ModuleCard key={modKey} title={title} icon={<Briefcase className="h-4 w-4" />} {...commonProps}>
                    <ExperienceList type="workExperience" wizardStep={wizardStep} onWizardComplete={handleWizardComplete} />
                  </ModuleCard>
                );
              }

              if (modKey === "personalProjects") {
                return (
                  <ModuleCard key={modKey} title={title} icon={<FolderGit2 className="h-4 w-4" />} {...commonProps}>
                    <ExperienceList type="personalProjects" wizardStep={wizardStep} onWizardComplete={handleWizardComplete} />
                  </ModuleCard>
                );
              }

              if (modKey === "education") {
                return (
                  <ModuleCard key={modKey} title={title} icon={<GraduationCap className="h-4 w-4" />} {...commonProps}>
                    <ExperienceList type="education" wizardStep={wizardStep} onWizardComplete={handleWizardComplete} />
                  </ModuleCard>
                );
              }

              if (modKey === "additional") {
                return (
                  <ModuleCard key={modKey} title={title} icon={<Wrench className="h-4 w-4" />} {...commonProps}>
                    <div className="flex flex-col gap-3">
                      <MarkdownEditor
                        value={resumeData?.additional?.technicalSkills?.join('\\n') || ""}
                        onChange={(val) => updateAdditional({ technicalSkills: val.split('\\n') })}
                        placeholder="专业技能，支持 Markdown"
                        minHeight="min-h-[120px]"
                      />
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" size="sm" onClick={() => handleFormatMarkdown(modKey, title, resumeData?.additional?.technicalSkills?.join('\\n') || "", (val) => updateAdditional({ technicalSkills: val.split('\\n') }))}>
                          自动排版
                        </Button>
                      </div>
                    </div>
                  </ModuleCard>
                );
              }

              return (
                <ModuleCard key={modKey} title={title} icon={<FolderGit2 className="h-4 w-4" />} {...commonProps}>
                  <ExperienceList type="custom" moduleKey={modKey} wizardStep={wizardStep} onWizardComplete={handleWizardComplete} />
                </ModuleCard>
              );
            })}

          {/* 新增一级模块按钮 */}
          <div className="flex justify-center mt-2 mb-8">
            <div className="flex gap-2">
              {["summary", "workExperience", "personalProjects", "education", "additional"].filter(k => !(resumeData?.moduleOrder || []).includes(k)).map(missingKey => (
                <Button key={missingKey} variant="outline" onClick={() => addModule(missingKey)}>
                  <Plus className="mr-1 h-4 w-4" /> 找回模块
                </Button>
              ))}
              <Button variant="outline" onClick={() => addCustomModule("新自定义模块")}>
                <Plus className="mr-1 h-4 w-4" /> 新增任意一级模块
              </Button>
            </div>
          </div>
        </div>
      </main>

      {/* 向导浮窗 */}
      {wizardStep !== 'idle' && !wizardHidden && (
        <div className="absolute right-4 bottom-4 w-80 bg-white rounded-xl shadow-2xl border border-indigo-100 overflow-hidden flex flex-col z-50 animate-in slide-in-from-bottom-5">
          <div className="bg-gradient-to-r from-indigo-500 to-indigo-600 px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-white" />
              <span className="font-semibold text-white text-sm">六步深度改写向导</span>
            </div>
            <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-white/80 hover:bg-white/20 hover:text-white rounded-full" onClick={() => setWizardHidden(true)}>×</Button>
          </div>
          
          <div className="p-4 flex flex-col gap-4 text-sm bg-indigo-50/30">
            {wizardStep === 'step1' && (
              <>
                <div className="font-medium text-slate-800">第一步：经历瘦身 (Prune)</div>
                <p className="text-xs text-slate-500 leading-relaxed">请点击工作/项目经历中的"经历瘦身"，移除无关紧要的描述。</p>
                <Button size="sm" className="w-full mt-2" onClick={() => setWizardStep('step2')}>已完成，进入下一步 ➔</Button>
              </>
            )}
            {wizardStep === 'step2' && (
              <>
                <div className="font-medium text-slate-800">第二步：初稿生成</div>
                <p className="text-xs text-slate-500 leading-relaxed">让 AI 为您的每个经历生成一个专业的初稿。</p>
                <Button size="sm" className="w-full mt-2" onClick={() => setWizardStep('step3')}>已完成，进入下一步 ➔</Button>
              </>
            )}
            {wizardStep === 'step3' && (
              <>
                <div className="font-medium text-slate-800">第三步：深度拷问 (Grill)</div>
                <p className="text-xs text-slate-500 leading-relaxed">点击经历面板上的"深度拷问"，提供更多的背景数据与业务价值。</p>
                <Button size="sm" className="w-full mt-2" onClick={() => setWizardStep('step4')}>已完成，进入下一步 ➔</Button>
              </>
            )}
            {wizardStep === 'step4' && (
              <>
                <div className="font-medium text-slate-800">第四步：JD 靶向对齐 (ATS)</div>
                <p className="text-xs text-slate-500 leading-relaxed">点击"ATS对齐"，让 AI 自动将简历关键词向当前岗位的 JD 靠拢。</p>
                <Button size="sm" className="w-full mt-2" onClick={() => setWizardStep('step5')}>已完成，进入下一步 ➔</Button>
              </>
            )}
            {wizardStep === 'step5' && (
              <>
                <div className="font-medium text-slate-800">第五步：其他模块 AI 联动</div>
                <p className="text-xs text-slate-500 leading-relaxed">使用"AI 联动更新"同步更新您的个人总结与技能清单。</p>
                <Button size="sm" className="w-full mt-2" onClick={() => setWizardStep('step6')}>已完成，进入下一步 ➔</Button>
              </>
            )}
            {wizardStep === 'step6' && (
              <>
                <div className="font-medium text-slate-800">第六步：自动排版与保存</div>
                <p className="text-xs text-slate-500 leading-relaxed">点击左上角的"保存并同步"和右上角的排版工具，完成最终版本。</p>
                <Button size="sm" className="w-full mt-2" onClick={() => {
                  setWizardStep('idle')
                  setWizardProgress(DEFAULT_WIZARD_PROGRESS)
                }}>🎉 完成向导</Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
"""

with open(filepath, "w") as f:
    f.write(new_content)

print("Generated new V2ResumeEditor in place.")
