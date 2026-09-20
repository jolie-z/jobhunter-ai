import React, { useState } from "react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Sparkles, Briefcase, FolderGit2, GraduationCap, Wrench, User, Scale, FileText, RotateCcw, Scissors, Trash2, Plus, Wand2 } from "lucide-react"

import { ModuleCard } from "@/components/dashboard/resume-builder/module-card"
import { PersonalInfo } from "@/components/dashboard/resume-builder/personal-info"
import { ExperienceList } from "@/components/dashboard/resume-builder/experience-list"
import { MarkdownEditor } from "@/components/dashboard/resume-builder/markdown-editor"
import { WorkRestoreBin } from "@/components/dashboard/resume-builder/work-restore-bin"
import { ProjectTrashBin } from "@/components/dashboard/resume-builder/project-trash-bin"
import { AiModuleSyncInline } from "@/components/dashboard/resume-builder/ai-module-sync-inline"

import { WorkCompressPanel, WorkInitialDraftPanel, ProjectPrunePanel, ProjectInitialDraftPanel } from "./editor-wizard-panels"
import { useWizardPanelAutoOpen } from "../hooks/use-wizard-panel-auto-open"

import type { JobData } from "@/types/job"
import type { WizardStep } from "../hooks/use-ai-wizard"

export interface EditorModuleRendererProps {
  job?: JobData | null
              handleFormatMarkdown: (id: string, title: string, content: string, onChange: (val: string) => void) => void

  compressOpen: boolean
  setCompressOpen: (open: boolean) => void
  pruneOpen: boolean
  setPruneOpen: (open: boolean) => void
  trashOpen: boolean
  setTrashOpen: (open: boolean) => void
  workRestoreOpen: boolean
  setWorkRestoreOpen: (open: boolean) => void
  workInitialDraftOpen: boolean
  setWorkInitialDraftOpen: (open: boolean) => void
  projectInitialDraftOpen: boolean
  setProjectInitialDraftOpen: (open: boolean) => void
  
  wizardStep?: WizardStep
  wizardProgress?: any
  handleWizardComplete?: (step: string, sectionId?: string) => void
  syncQueue?: string[]
  atsQueue?: string[]
  grillQueue?: string[]
}

export function EditorModuleRenderer({
  job, handleFormatMarkdown,
  compressOpen, setCompressOpen, pruneOpen, setPruneOpen, trashOpen, setTrashOpen,
  workRestoreOpen, setWorkRestoreOpen, workInitialDraftOpen, setWorkInitialDraftOpen,
  projectInitialDraftOpen, setProjectInitialDraftOpen,
  wizardStep, wizardProgress, handleWizardComplete, syncQueue, atsQueue, grillQueue
}: EditorModuleRendererProps) {
  
  const {
    resumeData, updateSummary, updateAdditional,
    moveModuleUp, moveModuleDown, addModule, removeModule,
    addCustomModule, updateModuleTitle,
    updateWorkExperience,
    archiveWorkExperience,
    restoreWorkExperience, restoreProject
  } = useResumeV2Store()

  const [manualSyncOpen, setManualSyncOpen] = useState<Record<string, boolean>>({});

  useWizardPanelAutoOpen({
    wizardStep,
    hasWork: (resumeData?.workExperience?.length ?? 0) > 0,
    hasProjects: (resumeData?.personalProjects?.length ?? 0) > 0,
    initialDraftWorkDone: Boolean(wizardProgress?.initialDraftWorkDone),
    initialDraftProjectDone: Boolean(wizardProgress?.initialDraftProjectDone),
    syncQueue,
    setPruneOpen,
    setCompressOpen,
    setWorkInitialDraftOpen,
    setProjectInitialDraftOpen,
    setManualSyncOpen,
  });

  return (
    <>
      <ModuleCard id="personalInfo" title="个人信息" icon={<User className="h-4 w-4" />} isFixed={true}>
        <PersonalInfo />
      </ModuleCard>

      {[...new Set(resumeData?.moduleOrder || ["summary", "workExperience", "personalProjects", "education", "additional"])]
        .filter(modKey => modKey !== 'personalInfo')
        .map((modKey, idx, arr) => {
          const title = resumeData?.moduleTitles?.[modKey] || {
            summary: "个人总结",
            workExperience: "工作经历",
            personalProjects: "项目经历",
            education: "教育经历",
            additional: "附加信息"
          }[modKey] || modKey;

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
              <div data-section-id="summary" key={modKey}>
                <ModuleCard id={modKey} title={title} icon={<Sparkles className="h-4 w-4" />} {...commonProps}>
                <div className="flex flex-col gap-3">
                  <MarkdownEditor
                    value={resumeData?.summary || ""}
                    onChange={updateSummary}
                    placeholder={`在此填写${title}的内容...`}
                    minHeight="min-h-[96px]"
                  />
                  <div className="flex justify-end gap-2 mt-2">
                    <Button variant="outline" size="sm" onClick={() => handleFormatMarkdown(modKey, title, resumeData?.summary || "", updateSummary)}>
                      <Wand2 className="h-3.5 w-3.5 mr-1" />
                      自动排版
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="h-8 text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border border-indigo-200 shadow-sm transition-all"
                      onClick={() => setManualSyncOpen(prev => ({ ...prev, [modKey]: !prev[modKey] }))}
                    >
                      <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                      {manualSyncOpen[modKey] ? "收起联动更新" : "AI 联动更新"}
                    </Button>
                  </div>
                  {(manualSyncOpen[modKey]) && (
                    <AiModuleSyncInline
                      moduleTitle={title}
                      currentContent={resumeData?.summary || ""}
                      experiencesContext={job?.jobDescription || ""}
                      onAccept={(newContent) => {
                        updateSummary(newContent)
                        setManualSyncOpen(prev => ({ ...prev, [modKey]: false }))
                        if (wizardStep === 'step5') {
                          handleWizardComplete?.('sync_item_done', modKey)
                        }
                      }}
                      onCancel={() => {
                        setManualSyncOpen(prev => ({ ...prev, [modKey]: false }))
                        if (wizardStep === 'step5') {
                          handleWizardComplete?.('sync_item_cancel', modKey)
                        }
                      }}
                    />
                  )}
                </div>
              </ModuleCard>
              </div>
            );
          }

          if (modKey === "workExperience") {
            return (
              <ModuleCard 
                id={modKey} 
                key={modKey} 
                title={title} 
                icon={<Briefcase className="h-4 w-4" />} 
                headerTools={
                  <TooltipProvider delayDuration={200}>
                    <div className="flex items-center gap-1">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="sm" onClick={() => setCompressOpen(true)} className="h-6 w-6 p-0 text-purple-600 hover:text-purple-700 hover:bg-purple-50/80 transition-all">
                            <Scale className="h-3.5 w-3.5" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>AI判断工作经历重写or略写</TooltipContent>
                      </Tooltip>

                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="sm" onClick={() => setWorkInitialDraftOpen(true)} className="h-6 w-6 p-0 text-blue-600 hover:text-blue-700 hover:bg-blue-50/80 transition-all">
                            <FileText className="h-3.5 w-3.5" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>AI 初步改写 (结构与重点)</TooltipContent>
                      </Tooltip>

                      {resumeData?.workExperience && resumeData.workExperience.filter(w => w.originalContent).length > 0 && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="sm" onClick={() => setWorkRestoreOpen(true)} className="h-6 w-6 p-0 text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-all">
                              <div className="relative">
                                <RotateCcw className="h-3.5 w-3.5" />
                                <span className="absolute -top-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-slate-800 text-[8px] text-white">
                                  {resumeData.workExperience.filter(w => w.originalContent).length}
                                </span>
                              </div>
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>工作经历快照还原</TooltipContent>
                        </Tooltip>
                      )}
                    </div>
                  </TooltipProvider>
                }
                {...commonProps}
              >
                <WorkCompressPanel
                  open={compressOpen}
                  setOpen={setCompressOpen}
                  job={job}
                  wizardStep={wizardStep}
                  handleWizardComplete={handleWizardComplete}
                />
                
                {workRestoreOpen && (
                  <div className="mb-4">
                    <WorkRestoreBin
                      compressedWorks={(resumeData?.workExperience || [])
                        .map((w, idx) => ({ ...w, _originalIdx: idx }))
                        .filter(w => w && w.originalContent)
                        .map(w => ({ id: String(w._originalIdx), title: w?.company || "", content: Array.isArray(w?.description) ? w.description.join('\n') : (w?.description || ""), originalContent: w?.originalContent }))}
                      onRestore={(idsToRestore: any[]) => {
                        idsToRestore.forEach(id => {
                          const idx = parseInt(id);
                          const target = resumeData?.workExperience[idx];
                          if (target && target.originalContent) {
                            updateWorkExperience(idx, { description: target.originalContent.split('\n'), originalContent: undefined });
                          }
                        });
                        setWorkRestoreOpen(false);
                      }}
                      onCancel={() => setWorkRestoreOpen(false)}
                    />
                  </div>
                )}

                <WorkInitialDraftPanel
                  open={workInitialDraftOpen}
                  setOpen={setWorkInitialDraftOpen}
                  job={job}
                  wizardStep={wizardStep}
                  handleWizardComplete={handleWizardComplete}
                />
                <ExperienceList type="workExperience" wizardStep={wizardStep} atsQueue={atsQueue} syncQueue={syncQueue} grillQueue={grillQueue} onWizardComplete={handleWizardComplete} />
              </ModuleCard>
            );
          }

          if (modKey === "personalProjects") {
            return (
              <ModuleCard 
                id={modKey} 
                key={modKey} 
                title={title} 
                icon={<FolderGit2 className="h-4 w-4" />} 
                headerTools={
                  <TooltipProvider delayDuration={200}>
                    <div className="flex items-center gap-1">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="sm" onClick={() => setPruneOpen(true)} className="h-6 w-6 p-0 text-red-600 hover:text-red-700 hover:bg-red-50/80 transition-all">
                            <Scissors className="h-3.5 w-3.5" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>AI剪除项目经历</TooltipContent>
                      </Tooltip>

                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="sm" onClick={() => setProjectInitialDraftOpen(true)} className="h-6 w-6 p-0 text-blue-600 hover:text-blue-700 hover:bg-blue-50/80 transition-all">
                            <FileText className="h-3.5 w-3.5" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>AI 初步改写 (结构与重点)</TooltipContent>
                      </Tooltip>

                      {resumeData?.archivedProjects && resumeData.archivedProjects.length > 0 && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="sm" onClick={() => setTrashOpen(true)} className="h-6 w-6 p-0 text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-all">
                              <div className="relative">
                                <Trash2 className="h-3.5 w-3.5" />
                                <span className="absolute -top-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-slate-800 text-[8px] text-white">
                                  {resumeData.archivedProjects.length}
                                </span>
                              </div>
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>项目回收站 (可恢复)</TooltipContent>
                        </Tooltip>
                      )}
                    </div>
                  </TooltipProvider>
                }
                {...commonProps}
              >
                <ProjectPrunePanel
                  open={pruneOpen}
                  setOpen={setPruneOpen}
                  job={job}
                  wizardStep={wizardStep}
                  handleWizardComplete={handleWizardComplete}
                />

                {trashOpen && (
                  <div className="mb-4">
                    <ProjectTrashBin
                      archivedProjects={(resumeData?.archivedProjects || [])
                        .map((p, idx) => ({ p, _originalIdx: idx }))
                        .filter(({ p }) => Boolean(p))
                        .map(({ p, _originalIdx }) => ({ id: String(_originalIdx), title: p.name || "", content: Array.isArray(p.description) ? p.description.join('\n') : (p.description || "") }))}
                      onRestore={(idsToRestore: any[]) => {
                        const sortedIds = idsToRestore.map(id => parseInt(id)).sort((a, b) => b - a);
                        sortedIds.forEach(idx => restoreProject(idx));
                        setTrashOpen(false);
                      }}
                      onCancel={() => setTrashOpen(false)}
                    />
                  </div>
                )}

                <ProjectInitialDraftPanel
                  open={projectInitialDraftOpen}
                  setOpen={setProjectInitialDraftOpen}
                  job={job}
                  wizardStep={wizardStep}
                  handleWizardComplete={handleWizardComplete}
                />
                <ExperienceList type="personalProjects" wizardStep={wizardStep} atsQueue={atsQueue} syncQueue={syncQueue} grillQueue={grillQueue} onWizardComplete={handleWizardComplete} />
              </ModuleCard>
            );
          }

          if (modKey === "education") {
            return (
              <ModuleCard id={modKey} key={modKey} title={title} icon={<GraduationCap className="h-4 w-4" />} {...commonProps}>
                <ExperienceList type="education" wizardStep={wizardStep} atsQueue={atsQueue} syncQueue={syncQueue} grillQueue={grillQueue} onWizardComplete={handleWizardComplete} />
              </ModuleCard>
            );
          }

          if (modKey === "additional") {
            return (
              <div data-section-id="additional" key={modKey}>
                <ModuleCard id={modKey} title={title} icon={<Wrench className="h-4 w-4" />} {...commonProps}>
                <div className="flex flex-col gap-3">
                  <MarkdownEditor
                    value={resumeData?.additional?.technicalSkills?.join('\n') || ""}
                    onChange={(val: string) => updateAdditional({ technicalSkills: val.split('\n') })}
                    placeholder="专业技能，支持 Markdown"
                    minHeight="min-h-[120px]"
                  />
                  <div className="flex justify-end gap-2 mt-2">
                    <Button variant="outline" size="sm" onClick={() => handleFormatMarkdown(modKey, title, resumeData?.additional?.technicalSkills?.join('\n') || "", (val: string) => updateAdditional({ technicalSkills: val.split('\n') }))}>
                      <Wand2 className="h-3.5 w-3.5 mr-1" />
                      自动排版
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      className="h-8 text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border border-indigo-200 shadow-sm transition-all"
                      onClick={() => setManualSyncOpen(prev => ({ ...prev, [modKey]: !prev[modKey] }))}
                    >
                      <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                      {manualSyncOpen[modKey] ? "收起联动更新" : "AI 联动更新"}
                    </Button>
                  </div>
                  {(manualSyncOpen[modKey]) && (
                    <AiModuleSyncInline
                      moduleTitle={title}
                      currentContent={resumeData?.additional?.technicalSkills?.join('\n') || ""}
                      experiencesContext={job?.jobDescription || ""}
                      onAccept={(newContent) => {
                        updateAdditional({ technicalSkills: newContent.split('\n') })
                        setManualSyncOpen(prev => ({ ...prev, [modKey]: false }))
                        if (wizardStep === 'step5') {
                          handleWizardComplete?.('sync_item_done', modKey)
                        }
                      }}
                      onCancel={() => {
                        setManualSyncOpen(prev => ({ ...prev, [modKey]: false }))
                        if (wizardStep === 'step5') {
                          handleWizardComplete?.('sync_item_cancel', modKey)
                        }
                      }}
                    />
                  )}
                </div>
              </ModuleCard>
              </div>
            );
          }

          return (
            <ModuleCard id={modKey} key={modKey} title={title} icon={<FolderGit2 className="h-4 w-4" />} {...commonProps}>
              <ExperienceList type="custom" moduleKey={modKey} wizardStep={wizardStep} atsQueue={atsQueue} syncQueue={syncQueue} grillQueue={grillQueue} onWizardComplete={handleWizardComplete} />
            </ModuleCard>
          );
        })}

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
    </>
  )
}
