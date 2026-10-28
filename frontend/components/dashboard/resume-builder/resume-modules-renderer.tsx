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
  Plus, Loader2, Wand2, Sparkles, Briefcase, FolderGit2, GraduationCap, Wrench, User, AlertTriangle
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
    updateEducation,
    confirmModule
  } = useResumeV2Store()

  // 解析置信度（_meta.confidence）：low 模块显示「待确认」角标（与 v2-resume-editor 同款）
  const confidenceMap = resumeData?._meta?.confidence ?? {}

  const pendingBadge = (modKey: string) => {
    if (confidenceMap[modKey] !== "low") return null
    return (
      <span
        role="button"
        tabIndex={0}
        onClick={(e) => { e.stopPropagation(); confirmModule(modKey) }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); confirmModule(modKey) } }}
        title="AI 解析置信度低，建议对照原文核实；点击确认知悉"
        className="cursor-pointer select-none inline-flex items-center gap-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 px-1.5 py-px text-[10px] font-medium hover:bg-amber-200 transition-colors"
      >
        <AlertTriangle className="h-2.5 w-2.5" />
        待确认
      </span>
    )
  }

  // 编辑失焦即视为「用户已确认」；confirmModule 内部幂等，非 low 模块零副作用
  const confirmWrapProps = (modKey: string) => ({
    onBlurCapture: () => confirmModule(modKey),
  })

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
              <div key={modKey} {...confirmWrapProps(modKey)}>
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<Sparkles className="h-4 w-4" />} headerTools={pendingBadge(modKey)} {...commonProps}>
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
              </div>
            );
          }

          if (modKey === "workExperience") {
            return (
              <div key={modKey} {...confirmWrapProps(modKey)}>
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<Briefcase className="h-4 w-4" />} headerTools={pendingBadge(modKey)} {...commonProps}>
                <ExperienceList type="workExperience" />
              </ModuleCard>
              </div>
            );
          }

          if (modKey === "personalProjects") {
            return (
              <div key={modKey} {...confirmWrapProps(modKey)}>
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<FolderGit2 className="h-4 w-4" />} headerTools={pendingBadge(modKey)} {...commonProps}>
                <ExperienceList type="personalProjects" />
              </ModuleCard>
              </div>
            );
          }

          if (modKey === "education") {
            return (
              <div key={modKey} {...confirmWrapProps(modKey)}>
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<GraduationCap className="h-4 w-4" />} headerTools={pendingBadge(modKey)} {...commonProps}>
                <ExperienceList type="education" />
              </ModuleCard>
              </div>
            );
          }

          if (modKey === "additional") {
            // 2026-10-08 用户裁决：技能清单（technicalSkills 词条罗列）与技能概述内容重复，整体移除。
            // 对齐 v2 编辑器与打印组件的原文保真单框模式：skillOverview 优先展示与编辑；
            // 旧数据无 overview 字段时回退 technicalSkills 词表（行为不变）。
            // 判定用「字段是否为 string」而非内容非空——否则清空输入框会翻转模式、词表幽灵回填。
            const hasOverview = typeof resumeData?.additional?.skillOverview === "string"
            const skillsText = hasOverview
              ? (resumeData?.additional?.skillOverview || "")
              : (resumeData?.additional?.technicalSkills?.join('\n') || "")
            const writeSkills = (val: string) => {
              if (hasOverview) updateAdditional({ skillOverview: val })
              else updateAdditional({ technicalSkills: val.split('\n') })
            }
            return (
              <div key={modKey} {...confirmWrapProps(modKey)}>
              <ModuleCard key={modKey} id={anchorId} title={title} icon={<Wrench className="h-4 w-4" />} headerTools={pendingBadge(modKey)} {...commonProps}>
                <div className="flex flex-col gap-3">
                  {hasOverview && (
                    <div className="mb-1 text-[11px] font-medium text-muted-foreground">技能概述（描述性文字）</div>
                  )}
                  <MarkdownEditor
                    value={skillsText}
                    onChange={writeSkills}
                    placeholder={hasOverview ? "技能概述（描述性文字，可选；简历上传时自动保留于此）" : "专业技能，支持 Markdown"}
                    minHeight="min-h-[120px]"
                  />
                  {renderSyncButtons(modKey, title, skillsText, writeSkills)}
                  {activeSyncModuleId === modKey && (
                    <AiModuleSyncInline
                      moduleTitle={title}
                      currentContent={skillsText}
                      experiencesContext={context}
                      onAccept={(newContent) => {
                        writeSkills(newContent)
                        setActiveSyncModuleId(null)
                      }}
                      onCancel={() => setActiveSyncModuleId(null)}
                    />
                  )}
                </div>
              </ModuleCard>
              </div>
            );
          }

          // 渲染完全自定义的模块
          return (
            <div key={modKey} {...confirmWrapProps(modKey)}>
            <ModuleCard key={modKey} id={anchorId} title={title} icon={<FolderGit2 className="h-4 w-4" />} headerTools={pendingBadge(modKey)} {...commonProps}>
              <ExperienceList type="custom" moduleKey={modKey} />
            </ModuleCard>
            </div>
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
