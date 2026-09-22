"use client"

// 简历库主体模块渲染区（从 resume-builder/index.tsx 拆出，Q-M4-6 行数治理）
// 个人信息置顶 + 动态模块（summary/工作/项目/教育/附加/自定义）+ 找回缺失模块 + 新增自定义模块

import { Button } from "@/components/ui/button"
import { ModuleCard } from "./module-card"
import { PersonalInfo } from "./personal-info"
import { ExperienceList } from "./experience-list"
import { MarkdownEditor } from "./markdown-editor"
import { AiModuleSyncInline } from "./ai-module-sync-inline"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import {
  Plus, Loader2, Wand2, Sparkles, Briefcase, FolderGit2, GraduationCap, Wrench, User
} from 'lucide-react'

type ResumeModulesRendererProps = {
  formattingModuleId: string | null
  handleFormatMarkdown: (id: string, title: string, content: string, onChange: (val: string) => void) => Promise<void>
  activeSyncModuleId: string | null
  setActiveSyncModuleId: (id: string | null) => void
}

const MODULE_TITLES: Record<string, string> = {
  summary: "个人总结",
  workExperience: "工作经历",
  personalProjects: "项目经历",
  education: "教育经历",
  additional: "附加信息"
}

export function ResumeModulesRenderer({
  formattingModuleId,
  handleFormatMarkdown,
  activeSyncModuleId,
  setActiveSyncModuleId,
}: ResumeModulesRendererProps) {
  const {
    resumeData,
    updateSummary,
    updateAdditional,
    moveModuleUp,
    moveModuleDown,
    addModule,
    removeModule,
    addCustomModule,
    updateModuleTitle,
    updateWorkExperience,
    updateProject,
    updateEducation
  } = useResumeV2Store()

  const renderSyncButtons = (id: string, title: string, value: string, onChange: (val: string) => void) => (
    <div className="flex justify-end gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={formattingModuleId === id}
        className="h-8 text-xs bg-amber-50 text-amber-600 hover:bg-amber-100 border border-amber-200 shadow-sm transition-all"
        onClick={() => handleFormatMarkdown(id, title, value, onChange)}
      >
        {formattingModuleId === id ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5 mr-1.5" />}
        {formattingModuleId === id ? "排版中..." : "自动排版"}
      </Button>
      <Button
        variant="secondary"
        size="sm"
        className="h-8 text-xs bg-indigo-50 text-indigo-600 hover:bg-indigo-100 border border-indigo-200 shadow-sm transition-all"
        onClick={() => setActiveSyncModuleId(activeSyncModuleId === id ? null : id)}
      >
        <Sparkles className="h-3.5 w-3.5 mr-1.5" />
        {activeSyncModuleId === id ? "收起联动更新" : "AI 联动更新"}
      </Button>
    </div>
  )

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6 sm:py-8">
      {/* 1. 个人信息 (永远置顶) */}
      <ModuleCard id="module-anchor-personalInfo" title="个人信息" icon={<User className="h-4 w-4" />} isFixed={true}>
        <PersonalInfo />
      </ModuleCard>

      {/* 动态渲染其余模块 (deduplicated to avoid duplicate React keys) */}
      {[...new Set(resumeData?.moduleOrder || ["summary", "workExperience", "personalProjects", "education", "additional"])]
        .filter(modKey => modKey !== 'personalInfo')
        .map((modKey, idx, arr) => {
          const title = resumeData?.moduleTitles?.[modKey] || MODULE_TITLES[modKey] || modKey;

          const anchorId = `module-anchor-${modKey}`;

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
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<Sparkles className="h-4 w-4" />} {...commonProps}>
                <div className="flex flex-col gap-3">
                  <MarkdownEditor
                    value={resumeData?.summary || ""}
                    onChange={updateSummary}
                    placeholder={`在此填写${title}的内容...`}
                    minHeight="min-h-[96px]"
                  />
                  {renderSyncButtons(modKey, title, resumeData?.summary || "", updateSummary)}
                  {activeSyncModuleId === modKey && (
                    <AiModuleSyncInline
                      moduleTitle={title}
                      currentContent={resumeData?.summary || ""}
                      experiencesContext={context}
                      onAccept={(newContent) => {
                        updateSummary(newContent)
                        setActiveSyncModuleId(null)
                      }}
                      onCancel={() => setActiveSyncModuleId(null)}
                    />
                  )}
                </div>
              </ModuleCard>
            );
          }

          if (modKey === "workExperience") {
            return (
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<Briefcase className="h-4 w-4" />} {...commonProps}>
                <ExperienceList type="workExperience" />
              </ModuleCard>
            );
          }

          if (modKey === "personalProjects") {
            return (
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<FolderGit2 className="h-4 w-4" />} {...commonProps}>
                <ExperienceList type="personalProjects" />
              </ModuleCard>
            );
          }

          if (modKey === "education") {
            return (
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<GraduationCap className="h-4 w-4" />} {...commonProps}>
                <ExperienceList type="education" />
              </ModuleCard>
            );
          }

          if (modKey === "additional") {
            const additionalValue = resumeData?.additional?.technicalSkills?.join('\n') || "";
            const additionalOnChange = (val: string) => updateAdditional({ technicalSkills: val.split('\n') });
            // 技能概述：解析阶段承接的散文/描述性文字（七项修复#2），独立编辑不与技能清单混淆
            const overviewValue = resumeData?.additional?.skillOverview || "";
            const overviewOnChange = (val: string) => updateAdditional({ skillOverview: val });
            return (
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<Wrench className="h-4 w-4" />} {...commonProps}>
                <div className="flex flex-col gap-3">
                  <div>
                    <div className="mb-1 text-[11px] font-medium text-muted-foreground">技能概述（描述性文字）</div>
                    <MarkdownEditor
                      value={overviewValue}
                      onChange={overviewOnChange}
                      placeholder="技能概述（描述性文字，可选；简历上传时自动保留于此）"
                      minHeight="min-h-[60px]"
                    />
                  </div>
                  <div>
                    <div className="mb-1 text-[11px] font-medium text-muted-foreground">技能清单</div>
                    <MarkdownEditor
                      value={additionalValue}
                      onChange={additionalOnChange}
                      placeholder="专业技能，支持 Markdown"
                      minHeight="min-h-[120px]"
                    />
                  </div>
                  {renderSyncButtons(modKey, title, additionalValue, additionalOnChange)}
                  {activeSyncModuleId === modKey && (
                    <AiModuleSyncInline
                      moduleTitle={title}
                      currentContent={additionalValue}
                      experiencesContext={context}
                      onAccept={(newContent) => {
                        updateAdditional({ technicalSkills: newContent.split('\n') })
                        setActiveSyncModuleId(null)
                      }}
                      onCancel={() => setActiveSyncModuleId(null)}
                    />
                  )}
                </div>
              </ModuleCard>
            );
          }

          // 渲染完全自定义的模块
          return (
            <ModuleCard key={modKey} id={anchorId} title={title} icon={<FolderGit2 className="h-4 w-4" />} {...commonProps}>
              <ExperienceList type="custom" moduleKey={modKey} />
            </ModuleCard>
          );
        })}

      {/* 新增一级模块按钮 */}
      <div className="flex justify-center mt-2 mb-8">
        <div className="flex gap-2">
          {["summary", "workExperience", "personalProjects", "education", "additional"].filter(k => !(resumeData?.moduleOrder || []).includes(k)).map(missingKey => (
            <Button
              key={missingKey}
              variant="outline"
              className="border-dashed text-muted-foreground bg-transparent hover:bg-muted/50"
              onClick={() => addModule(missingKey)}
            >
              <Plus className="mr-1 h-4 w-4" />
              找回 {{ summary: "个人总结", workExperience: "工作经历", personalProjects: "项目经历", education: "教育经历", additional: "专业技能" }[missingKey]}
            </Button>
          ))}

          <Button
            variant="outline"
            className="border-dashed border-primary/50 text-primary bg-primary/5 hover:bg-primary/10"
            onClick={() => {
              addCustomModule("新自定义模块");
            }}
          >
            <Plus className="mr-1 h-4 w-4" />
            新增任意一级模块
          </Button>
        </div>
      </div>
    </div>
  )
}
