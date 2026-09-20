"use client"

import { useState, useEffect, useRef } from "react"
import { Save, RefreshCw } from "lucide-react"
import { SkillSelectorCard, SkillItem } from "./rewrite/skill-selector-card"
import { RewritePromptCard } from "./rewrite/rewrite-prompt-card"
import { RewriteCollaborationCard } from "./rewrite/rewrite-collaboration-card"
import { useStageConfig, saveStageConfig } from "./use-stage-config"

interface RewriteConfigPanelProps {
  onSaved: () => void
}

interface RewriteConfigData {
  skills?: SkillItem[]
  current_skill_id?: string
  include_diagnosis?: boolean
  prompt_rules?: string[]
}

export function RewriteConfigPanel({ onSaved }: RewriteConfigPanelProps) {
  const { data, loading } = useStageConfig<RewriteConfigData>(
    "/api/pipeline/rewrite-config",
    "读取简历改写规则配置异常"
  )

  const [currentSkillId, setCurrentSkillId] = useState("resume_rewrite")
  const [includeDiagnosis, setIncludeDiagnosis] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState("")
  // 保存成功提示自动清除定时器（组件卸载时清理，防止 setState 泄漏）
  const saveMsgTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (saveMsgTimer.current) clearTimeout(saveMsgTimer.current)
    }
  }, [])

  // 首次加载后同步一次后端现值；此后以本地编辑为准，重开面板自然重置
  const [synced, setSynced] = useState(false)
  useEffect(() => {
    if (synced || !data) return
    setSynced(true)
    if (data.current_skill_id) setCurrentSkillId(data.current_skill_id)
    if (data.include_diagnosis !== undefined) setIncludeDiagnosis(data.include_diagnosis)
  }, [data, synced])

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg("")
    const ok = await saveStageConfig(
      "/api/pipeline/rewrite-config",
      "POST",
      { skill_id: currentSkillId, include_diagnosis: includeDiagnosis },
      "简历改写规则已保存生效"
    )
    if (ok) {
      setSaveMsg("简历改写规则已保存生效")
      if (saveMsgTimer.current) clearTimeout(saveMsgTimer.current)
      saveMsgTimer.current = setTimeout(() => setSaveMsg(""), 3000)
      onSaved()
    }
    setSaving(false)
  }

  if (loading) {
    return (
      <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin mr-2 text-violet-500" />
        正在加载简历改写技能库与 SOP 规范...
      </div>
    )
  }

  return (
    <div className="space-y-3.5 text-xs select-none">
      {/* 1. 顶层：Skill 引擎选择与自定义管理 */}
      <SkillSelectorCard
        skills={data?.skills || []}
        currentSkillId={currentSkillId}
        onSelectSkill={(id) => setCurrentSkillId(id)}
      />

      {/* 2. 中间：改写协同机制与产物导出归档 */}
      <RewriteCollaborationCard
        includeDiagnosis={includeDiagnosis}
        onIncludeDiagnosisChange={setIncludeDiagnosis}
      />

      {/* 3. 底部：改写 Prompt 核心红线与排版规范 */}
      <RewritePromptCard promptRules={data?.prompt_rules || []} />

      {/* 保存栏 */}
      <div className="flex items-center justify-between pt-2 border-t border-border/60">
        <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
          {saveMsg}
        </span>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-700 active:scale-95 transition-all shadow-sm cursor-pointer disabled:opacity-50"
        >
          {saving ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          <span>{saving ? "正在保存..." : "保存改写规则"}</span>
        </button>
      </div>
    </div>
  )
}
