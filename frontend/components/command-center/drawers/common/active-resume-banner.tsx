"use client"

import { useState } from "react"
import { FileText, ExternalLink, Info, Check, ChevronsUpDown, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import { API_BASE } from "@/lib/api"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface ActiveResumeMeta {
  record_id?: string
  title?: string
  word_count?: number
  status?: string
}

interface ActiveResumeBannerProps {
  resume?: ActiveResumeMeta
  allResumes?: ActiveResumeMeta[]
  phaseName?: string
  onActiveResumeChange?: (newResume: ActiveResumeMeta) => void
}

export function ActiveResumeBanner({
  resume,
  allResumes = [],
  phaseName = "评估",
  onActiveResumeChange,
}: ActiveResumeBannerProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [switching, setSwitching] = useState(false)

  const currentRecordId = resume?.record_id || ""
  const title = resume?.title || "默认基准简历"
  const wordCount = resume?.word_count || 0

  const handleSelectResume = async (target: ActiveResumeMeta) => {
    if (!target.record_id || target.record_id === currentRecordId) {
      setIsOpen(false)
      return
    }

    setSwitching(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/activate-resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: target.record_id }),
      })
      const result = await res.json()
      if (result.code === 0) {
        toast.success(`已切换当前基准简历为：${target.title}`)
        if (onActiveResumeChange) {
          onActiveResumeChange(result.data?.active_resume || target)
        }
      } else {
        toast.error(result.msg || "切换简历失败")
      }
    } catch {
      toast.error("网络异常，无法切换简历")
    } finally {
      setSwitching(false)
      setIsOpen(false)
    }
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-gradient-to-r from-violet-500/5 via-card to-card p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs">
      <div className="flex items-center gap-2.5 flex-1 min-w-0">
        <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-violet-500/10 text-violet-600 dark:text-violet-400 border border-violet-500/20 font-bold shrink-0">
          <FileText className="h-3.5 w-3.5" />
        </div>

        <div className="flex items-center gap-2 flex-wrap min-w-0 flex-1">
          <span className="text-xs font-semibold text-foreground shrink-0">
            当前锚定基准简历
          </span>

          {/* 下拉选择器 */}
          <div className="relative inline-block">
            <button
              type="button"
              onClick={() => setIsOpen(!isOpen)}
              disabled={switching || allResumes.length === 0}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-800 dark:text-emerald-300 hover:bg-emerald-500/15 transition-all text-left max-w-xs truncate cursor-pointer shadow-2xs",
                switching && "opacity-60 cursor-wait",
                allResumes.length === 0 && "cursor-default opacity-80"
              )}
            >
              {switching ? (
                <Loader2 className="h-3 w-3 animate-spin text-emerald-500 shrink-0" />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shrink-0" />
              )}
              <span className="truncate font-mono">{title}</span>
              {wordCount > 0 && (
                <span className="text-[10px] text-emerald-700/70 dark:text-emerald-400/70 shrink-0 font-mono">
                  ({wordCount.toLocaleString()}字)
                </span>
              )}
              {allResumes.length > 1 && (
                <ChevronsUpDown className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0 ml-0.5" />
              )}
            </button>

            {/* 下拉浮层 */}
            {isOpen && allResumes.length > 0 && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setIsOpen(false)}
                />
                <div className="absolute left-0 top-full mt-1.5 z-50 w-72 rounded-2xl border border-border/80 bg-popover p-1.5 shadow-xl animate-in fade-in zoom-in-95 duration-150">
                  <div className="px-2 py-1.5 text-[10px] font-semibold text-muted-foreground border-b border-border/40 mb-1">
                    选择切换基准简历版本：
                  </div>
                  <div className="max-h-56 overflow-y-auto space-y-0.5">
                    {allResumes.map((item) => {
                      const isSelected = item.record_id === currentRecordId
                      return (
                        <button
                          key={item.record_id || item.title}
                          type="button"
                          onClick={() => handleSelectResume(item)}
                          className={cn(
                            "w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-xl text-xs text-left transition-colors",
                            isSelected
                              ? "bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 font-medium"
                              : "hover:bg-muted text-foreground/80"
                          )}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <span
                              className={cn(
                                "h-1.5 w-1.5 rounded-full shrink-0",
                                isSelected ? "bg-emerald-500" : "bg-muted-foreground/40"
                              )}
                            />
                            <span className="truncate font-mono">{item.title}</span>
                          </div>

                          <div className="flex items-center gap-1.5 shrink-0 text-[10px] text-muted-foreground font-mono">
                            {item.word_count ? `${item.word_count}字` : ""}
                            {isSelected && (
                              <Check className="h-3.5 w-3.5 text-emerald-500" />
                            )}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </>
            )}
          </div>

          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
              <p className="font-semibold text-zinc-100 mb-0.5">📄 基准简历锚定机制：</p>
              <p className="text-zinc-300 text-[11px]">
                {phaseName}将 100% 以当前选中的基准简历作为真实能力底稿，对照目标岗位 JD 进行真实差距核验与打分。可在此直接下拉切换。
              </p>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      <a
        href="/strategy?section=resume"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-600 dark:text-violet-400 hover:text-violet-700 hover:underline transition-colors shrink-0 self-start sm:self-auto"
      >
        <span>前往简历库</span>
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  )
}
