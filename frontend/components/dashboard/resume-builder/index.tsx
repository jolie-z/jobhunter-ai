"use client"

import { useState } from "react"
import { useStrategyStore } from "@/hooks/use-strategy-store"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { ResumeSidebar } from "./resume-sidebar"
import { ModuleNav, type ModuleNavItem } from "./module-nav"
import { useResumeBuilderActions } from "./use-resume-builder-actions"
import { ResumeBuilderToolbar } from "./resume-builder-toolbar"
import { ResumeModulesRenderer } from "./resume-modules-renderer"
import { SkillArtifactsSheet } from "../features/v2-resume-editor/components/skill-artifacts-sheet"

export function ResumeBuilder() {
  const store = useStrategyStore()
  const {
    resumes,
    setResumes,
    editingItem,
    setEditingItem,
    handleDelete,
    handleCreateNew,
    handleDuplicate,
    fetchConfig,
    hasUnsavedChanges
  } = store

  const { resumeData, setResumeData } = useResumeV2Store()

  // AI 联动更新状态
  const [activeSyncModuleId, setActiveSyncModuleId] = useState<string | null>(null)

  // 🌟 Skill 智能体作战中枢状态
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [artifactsOpen, setArtifactsOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)

  const activeId = editingItem?.record_id || ""

  const actions = useResumeBuilderActions({
    activeId,
    resumeName: editingItem?.name || "",
    selectedSkill,
    setArtifactsOpen,
  })

  // 🌟 模块导览数据：个人信息固定置顶 + 按 moduleOrder 动态生成，随模块增删/排序/改名实时变化
  const navItems: ModuleNavItem[] = [
    { key: "personalInfo", title: "个人信息" },
    ...[...new Set(resumeData?.moduleOrder || [])]
      .filter(modKey => modKey !== 'personalInfo')
      .map(modKey => ({
        key: modKey,
        title: resumeData?.moduleTitles?.[modKey] || {
          summary: "个人总结",
          workExperience: "工作经历",
          personalProjects: "项目经历",
          education: "教育经历",
          additional: "附加信息"
        }[modKey] || modKey
      }))
  ]

  const handleSelect = (id: string) => {
    if (id !== activeId && hasUnsavedChanges() && !window.confirm('当前简历有未保存的修改，切换后将丢失。确定要切换吗？')) return
    const item = resumes.find(r => r.record_id === id)
    if (item) setEditingItem(item)
  }

  const handleRename = (id: string, name: string) => {
    if (editingItem?.record_id === id) {
      setEditingItem({ ...editingItem, name })
    }
    // 不可变更新：直接下标改 resumes[idx].name 变异了 state 数组，订阅方可能不刷新
    setResumes(prev => prev.map(r => (r.record_id === id ? { ...r, name } : r)))
  }

  const handleDeleteResume = (id: string) => {
    const item = resumes.find(r => r.record_id === id)
    if (item) handleDelete({ stopPropagation: () => { } } as any, item)
  }

  const activeName = editingItem?.name || "简历"

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <ResumeSidebar
        resumes={resumes.map(r => ({ id: r.record_id || '', name: r.name, status: r.status }))}
        activeId={activeId}
        onSelect={handleSelect}
        onRename={handleRename}
        onDuplicate={handleDuplicate}
        onDelete={handleDeleteResume}
        onCreate={handleCreateNew}
      />

      <div className="flex flex-1 flex-col min-w-0 overflow-hidden relative">
        <ResumeBuilderToolbar
          actions={actions}
          selectedSkill={selectedSkill}
          onSelectSkill={setSelectedSkill}
          previewOpen={previewOpen}
          setPreviewOpen={setPreviewOpen}
          onOpenArtifacts={() => setArtifactsOpen(true)}
        />

        <main className="flex-1 overflow-y-auto">
          <ResumeModulesRenderer
            formattingModuleId={actions.formattingModuleId}
            handleFormatMarkdown={actions.handleFormatMarkdown}
            activeSyncModuleId={activeSyncModuleId}
            setActiveSyncModuleId={setActiveSyncModuleId}
          />
        </main>

        {/* 🌟 模块导览条：悬停展开，点击平滑滚动到对应模块 */}
        <ModuleNav items={navItems} />

        {/* 🌟 Skill 作战产物库抽屉 */}
        <SkillArtifactsSheet
          open={artifactsOpen}
          onOpenChange={setArtifactsOpen}
          jobId={activeId}
          jobTitle={editingItem?.name || "母版简历"}
          onFillSuccess={(parsedJson) => {
            if (parsedJson) {
              setResumeData(parsedJson)
              fetchConfig(activeId)
            }
          }}
        />
      </div>
    </div>
  )
}
