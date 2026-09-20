"use client"

import { Sparkles, Check, ExternalLink, ShieldCheck, FolderGit2, Info } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface SkillItem {
  id: string
  name: string
  version?: string
  description?: string
  is_official?: boolean
  is_package?: boolean
  references_count?: number
  file?: string
}

interface SkillSelectorCardProps {
  skills: SkillItem[]
  currentSkillId: string
  onSelectSkill: (skillId: string) => void
}

export function SkillSelectorCard({
  skills,
  currentSkillId,
  onSelectSkill,
}: SkillSelectorCardProps) {
  return (
    <div className="rounded-2xl border border-border/80 bg-card p-4 space-y-3 shadow-xs">
      {/* 标题栏 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/50 pb-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-violet-500/10 text-violet-600 dark:text-violet-400 border border-violet-500/20 font-bold shrink-0">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <div className="flex items-center gap-1.5">
            <h3 className="font-semibold text-foreground text-xs tracking-tight">
              改写 Skill 引擎选择
            </h3>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors cursor-pointer">
                  <Info className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                <p className="font-semibold text-zinc-100 mb-0.5">🧩 改写 Skill 引擎说明：</p>
                <p className="text-zinc-300 text-[11px]">
                  选择驱动本次定制简历改写的提示词 SOP 与排版规范。支持单选官方内置的标准精修技能，或用户在简历库中维护上传的自定义技能。
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>

        {/* 快捷上传入口 */}
        <a
          href="/strategy?section=resume"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-600 dark:text-violet-400 hover:text-violet-700 hover:underline transition-colors shrink-0 self-start sm:self-auto"
        >
          <span>上传 / 导入自定义 Skill</span>
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>

      {/* 精简版 Skill 卡片列表 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {skills.map((skill) => {
          const isSelected = skill.id === currentSkillId || (!currentSkillId && skill.id === "resume_rewrite")
          const isOfficial = skill.is_official !== false && (skill.id === "resume_rewrite" || !skill.id.startsWith("custom_"))

          return (
            <button
              key={skill.id}
              type="button"
              onClick={() => onSelectSkill(skill.id)}
              className={cn(
                "flex items-center justify-between p-3 rounded-xl border text-left transition-all relative group cursor-pointer",
                isSelected
                  ? "border-violet-500/70 bg-violet-500/10 ring-1 ring-violet-500/30 shadow-2xs"
                  : "border-border/70 hover:border-border hover:bg-muted/40"
              )}
            >
              <div className="flex items-center gap-2.5 min-w-0 pr-2">
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-xl font-bold shrink-0 border",
                    isOfficial
                      ? "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-500/20"
                      : "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20"
                  )}
                >
                  {isOfficial ? <ShieldCheck className="h-4 w-4" /> : <FolderGit2 className="h-4 w-4" />}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-foreground text-xs truncate">
                      {skill.name || skill.id}
                    </span>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="text-muted-foreground/60 hover:text-foreground inline-flex items-center cursor-pointer">
                          <Info className="h-3 w-3" />
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                        <p className="font-semibold text-zinc-100 mb-0.5">📋 {skill.name || skill.id} 规范详情：</p>
                        <p className="text-zinc-300 text-[11px]">
                          {skill.description || (isOfficial ? "严格遵循猎头五要素子弹点、STAR公式、全保留工作经历、加粗核心技术与量化商业战果。" : "自定义 Prompt 提示词与知识库资料包。")}
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </div>

                  <div className="flex items-center gap-2 text-[10px] text-muted-foreground/70 font-mono mt-0.5">
                    <span>{isOfficial ? "官方预置" : "自定义"}</span>
                    <span>·</span>
                    <span>{skill.id}</span>
                    {skill.is_package && (
                      <>
                        <span>·</span>
                        <span className="text-violet-600 dark:text-violet-400">📦 {skill.references_count || 0} 资料</span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* 选中指示圆圈 */}
              <div
                className={cn(
                  "flex h-4 w-4 items-center justify-center rounded-full shrink-0 transition-all",
                  isSelected
                    ? "bg-violet-600 text-white shadow-xs"
                    : "border border-muted-foreground/30 group-hover:border-muted-foreground/60"
                )}
              >
                {isSelected && <Check className="h-2.5 w-2.5 stroke-[3]" />}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
