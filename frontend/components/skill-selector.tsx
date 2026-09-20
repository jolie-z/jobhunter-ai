"use client"

import { API_BASE } from "@/lib/api"
import React, { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Upload,
  Loader2,
  Sparkles,
  Info,
} from "lucide-react"
import { SkillDetailDialog } from "./skill-selector/skill-detail-dialog"
import { SkillUploadDialog } from "./skill-selector/skill-upload-dialog"


export interface SkillMeta {
  id: string
  name: string
  version: string
  description?: string
  file?: string
  is_package?: boolean
  references_count?: number
  reference_names?: string[]
  is_official?: boolean
  compatible?: boolean
}

export interface AuditReport {
  main_entry?: string
  references_count?: number
  references?: string[]
  ignored_scripts_count?: number
  ignored_scripts?: string[]
  mode_used?: string
  source?: string
  total_valid_size_kb?: number
}

interface SkillSelectorProps {
  selectedSkill: string | null
  onChange: (skillId: string) => void
  className?: string
  compact?: boolean
}

/**
 * 将底层代码标识符（如 resume_rewrite）转换为自然精炼的业务剧本文案
 */
export function getSkillDisplayName(skillId: string | null | undefined, skillList: SkillMeta[] = []): string {
  if (!skillId || skillId === "resume_rewrite") {
    const found = skillList.find(s => s.id === "resume_rewrite")
    if (found && found.name && found.name !== "resume_rewrite") {
      return found.name
    }
    return "官方剧本"
  }
  const found = skillList.find(s => s.id === skillId)
  if (found) {
    if (found.name === "resume_rewrite") return "官方剧本"
    return found.name
  }
  return skillId.replace(/^(custom_|skill_)/, "")
}

/**
 * Skill Selector 智能体剧本选择器
 * 支持紧凑模式（作战调度工具栏）与标准模式，集成多格式本地导入 (.md / .zip / 文件夹) 与 GitHub 一键同步
 */
export function SkillSelector({ selectedSkill, onChange, className, compact = false }: SkillSelectorProps) {
  const [skills, setSkills] = useState<SkillMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [isUploadOpen, setIsUploadOpen] = useState(false)
  const [selectedSkillDetail, setSelectedSkillDetail] = useState<SkillMeta | null>(null)

  useEffect(() => {
    loadSkills()
  }, [])

  const loadSkills = async () => {
    try {
      let res = await fetch(`${API_BASE}/api/resume-editor/skills/`)
      if (!res.ok) {
        res = await fetch(`${API_BASE}/resume-editor/skills/`)
      }
      const data = await res.json()
      if (data.success) {
        const rawSkills: SkillMeta[] = data.skills || []
        const filteredSkills = rawSkills.filter(
          (s) => !s.id.startsWith("greeting_") && s.id !== "greeting_writer"
        )
        setSkills(filteredSkills)
        if (!selectedSkill && data.current_skill_id) {
          const isValidCurrent = filteredSkills.some(s => s.id === data.current_skill_id)
          if (isValidCurrent) {
            onChange(data.current_skill_id)
          } else if (filteredSkills.length > 0) {
            onChange(filteredSkills[0].id)
          }
        }
      }
    } catch (error) {
      console.error("加载技能失败:", error)
    } finally {
      setLoading(false)
    }
  }

  const handleSkillChange = (skillId: string) => {
    onChange(skillId)
    const skill = skills.find(s => s.id === skillId)
    if (skill) {
      setSelectedSkillDetail(skill)
    }
  }

  const handleDeleteSkill = async (skillId: string) => {
    if (!confirm(`确定要彻底删除该自定义技能吗？`)) return
    try {
      let res = await fetch(`${API_BASE}/api/resume-editor/skills/${skillId}`, { method: "DELETE" })
      if (!res.ok && res.status === 404) {
        res = await fetch(`${API_BASE}/resume-editor/skills/${skillId}`, { method: "DELETE" })
      }
      const data = await res.json()
      if (data.success) {
        setSelectedSkillDetail(null)
        loadSkills()
      } else {
        alert(`删除失败：${data.detail || data.error}`)
      }
    } catch (e) {
      alert(`删除异常：${e}`)
    }
  }

  if (loading) {
    return (
      <div className={`flex items-center gap-1.5 px-2 py-1 ${className}`}>
        <Loader2 className="size-3.5 animate-spin text-amber-500" />
        <span className="text-[11px] text-muted-foreground">加载剧本...</span>
      </div>
    )
  }

  return (
    <div className={`flex items-center gap-1.5 ${className}`}>
      {/* 🌟 1. Skill 核心选择器 */}
      {compact ? (
        /* 紧凑工具栏模式：一体化微胶囊，与「自定义」「带入诊断」「执行改写」完美对齐 */
        <Select value={selectedSkill || "resume_rewrite"} onValueChange={handleSkillChange}>
          <SelectTrigger
            size="sm"
            className="!h-6.5 !py-0 !px-2 !text-xs !leading-none !gap-1 text-amber-950 bg-white/85 hover:bg-white border border-amber-200/80 hover:border-amber-300 rounded-lg shadow-2xs transition-all focus:ring-0 focus:ring-offset-0 shrink-0 [&_svg]:!size-3"
            title={`当前改写剧本：${getSkillDisplayName(selectedSkill, skills)}（点击切换或查看详情）`}
          >
            <Sparkles className="size-3 text-amber-500 shrink-0" />
            <span className="truncate max-w-[65px] sm:max-w-[85px] font-medium text-xs leading-none">
              {getSkillDisplayName(selectedSkill, skills)}
            </span>
          </SelectTrigger>
          <SelectContent align="start" className="max-h-[300px] text-xs p-1">
            {skills.map((skill) => (
              <SelectItem key={skill.id} value={skill.id} className="text-xs py-1.5 cursor-pointer">
                <div className="flex items-center gap-1.5 truncate">
                  <span>{getSkillDisplayName(skill.id, skills)}</span>
                  {skill.is_package && (
                    <span className="rounded bg-purple-50 px-1 py-0.2 text-[10px] text-purple-600 font-normal">
                      多文件
                    </span>
                  )}
                  {skill.is_official ? (
                    <span className="rounded bg-amber-50 px-1 py-0.2 text-[10px] text-amber-700 font-normal">
                      官方
                    </span>
                  ) : (
                    <span className="rounded bg-indigo-50 px-1 py-0.2 text-[10px] text-indigo-600 font-normal">
                      自定义
                    </span>
                  )}
                </div>
              </SelectItem>
            ))}
            <div className="border-t border-slate-100 mt-1 pt-1 px-1">
              <button
                type="button"
                className="w-full flex items-center justify-center gap-1 py-1 text-[11px] text-amber-700 hover:text-amber-800 hover:bg-amber-50/80 rounded transition-colors"
                onClick={(e) => {
                  e.stopPropagation()
                  const current = skills.find((s) => s.id === selectedSkill) || skills[0]
                  if (current) setSelectedSkillDetail(current)
                }}
              >
                <Info className="size-3" />
                <span>查看当前剧本详情与参考资料</span>
              </button>
            </div>
          </SelectContent>
        </Select>
      ) : (
        /* 标准完整卡片模式（用于 Canvas 或全屏对话框） */
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white/80 px-2 py-1 shadow-xs transition-colors hover:border-amber-300">
          <Sparkles className="size-3.5 text-amber-500 shrink-0 ml-0.5" />
          <Select value={selectedSkill || "resume_rewrite"} onValueChange={handleSkillChange}>
            <SelectTrigger className="h-7 w-[140px] border-none bg-transparent px-1 py-0 text-xs font-medium text-slate-800 shadow-none focus:ring-0 focus:ring-offset-0 truncate">
              <SelectValue placeholder="选择 Skill 剧本">
                {getSkillDisplayName(selectedSkill, skills)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="max-h-[280px] text-xs">
              {skills.map((skill) => (
                <SelectItem key={skill.id} value={skill.id} className="text-xs py-1.5">
                  <div className="flex items-center gap-1.5 truncate">
                    <span>{getSkillDisplayName(skill.id, skills)}</span>
                    {skill.is_package && (
                      <span className="rounded bg-purple-50 px-1 py-0.2 text-[10px] text-purple-600 font-normal">多文件</span>
                    )}
                    {skill.is_official ? (
                      <span className="rounded bg-amber-50 px-1 py-0.2 text-[10px] text-amber-700 font-normal">官方</span>
                    ) : (
                      <span className="rounded bg-indigo-50 px-1 py-0.2 text-[10px] text-indigo-600 font-normal">自定义</span>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            size="icon"
            variant="ghost"
            className="size-5 text-slate-400 hover:text-amber-700 hover:bg-amber-50 rounded-sm"
            title="查看当前 Skill 详情与 Reference 资料"
            onClick={() => {
              const current = skills.find((s) => s.id === selectedSkill) || skills[0]
              if (current) setSelectedSkillDetail(current)
            }}
          >
            <Info className="size-3" />
          </Button>
        </div>
      )}

      {/* 🌟 2. 自定义导入按钮 */}
      <Button
        size="sm"
        variant="outline"
        className={`h-6.5 ${
          compact
            ? "px-2 text-amber-900 bg-white/80 hover:bg-white border-amber-200/80 hover:border-amber-300"
            : "px-2.5 text-slate-600 border-dashed hover:border-indigo-400 hover:text-indigo-600 hover:bg-indigo-50/50"
        } gap-1 text-xs rounded-lg transition-all active:scale-[0.98] shadow-2xs`}
        title="导入自定义 Skill 技能包 (.md / .zip / GitHub)"
        onClick={() => setIsUploadOpen(true)}
      >
        <Upload className="size-3 text-amber-600" />
        <span className="hidden sm:inline font-medium">自定义</span>
      </Button>

      {/* 🌟 3. 独立解耦的上传弹窗 */}
      <SkillUploadDialog
        open={isUploadOpen}
        onOpenChange={setIsUploadOpen}
        onSuccess={async (newSkillId) => {
          await loadSkills()
          if (newSkillId) onChange(newSkillId)
        }}
      />

      {/* 🌟 4. 独立解耦的详情弹窗 */}
      <SkillDetailDialog
        open={!!selectedSkillDetail}
        onOpenChange={(open) => !open && setSelectedSkillDetail(null)}
        skillDetail={selectedSkillDetail}
        onDeleteSkill={handleDeleteSkill}
      />
    </div>
  )
}
