import React, { useEffect, useState } from "react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { useStrategyStore } from "@/hooks/use-strategy-store"
import { PersonalInfoCard } from "../resume-builder/v2/personal-info-card"
import { SummaryCard } from "../resume-builder/v2/summary-card"
import { ExperienceCard } from "../resume-builder/v2/experience-card"
import { EducationCard } from "../resume-builder/v2/education-card"
import { ProjectCard } from "../resume-builder/v2/project-card"
import { AdditionalInfoCard } from "../resume-builder/v2/additional-info-card"
import { Button } from "@/components/ui/button"
import { Save, AlertCircle } from "lucide-react"

export function JsonResumeEditor() {
  const { resumeData } = useResumeV2Store()
  const { editingItem, handleSave, section } = useStrategyStore()
  const [isSaving, setIsSaving] = useState(false)

  // 保存走 handleSave：内部会做 v2 store 归属校验后写回「结构化数据」，
  // 编辑器与画布读写的是同一份 v2 数据，无需旧版 cache 桥接
  const onSaveClick = async () => {
    setIsSaving(true)
    try {
      setTimeout(async () => {
          await handleSave()
      }, 0)
    } finally {
      setIsSaving(false)
    }
  }

  if (section !== 'resume') return null

  if (!resumeData || !editingItem) {
    return (
      <div className="flex flex-col items-center justify-center h-[50vh] text-muted-foreground space-y-4">
        <AlertCircle className="w-12 h-12" />
        <p>未检测到结构化简历数据 (JSON)。请上传一份新的简历以解析。</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-slate-50/50">
      {/* 顶部工具栏 */}
      <div className="flex-none p-4 border-b bg-background flex items-center justify-between z-10 sticky top-0 shadow-sm">
        <div>
          <h2 className="text-lg font-bold text-slate-800">
            {editingItem.name || "未命名简历"}
          </h2>
          <p className="text-sm text-slate-500">V2 纯 JSON 结构化编辑器</p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={onSaveClick} disabled={isSaving} className="gap-2">
            <Save className="w-4 h-4" />
            {isSaving ? "保存中..." : "保存变更"}
          </Button>
        </div>
      </div>

      {/* 核心滚动编辑区 */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 space-y-8">
        <div className="max-w-4xl mx-auto space-y-8 pb-32">
          <PersonalInfoCard />
          <SummaryCard />
          <ExperienceCard />
          <ProjectCard />
          <EducationCard />
          <AdditionalInfoCard />
        </div>
      </div>
    </div>
  )
}
