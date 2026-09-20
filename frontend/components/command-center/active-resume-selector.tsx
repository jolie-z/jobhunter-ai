"use client"

import { useState, useEffect, useCallback } from "react"
import { FileText, ExternalLink, AlertCircle, Check, ChevronsUpDown, Loader2, Send } from "lucide-react"
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

export function ActiveResumeSelector() {
  const [activeResume, setActiveResume] = useState<ActiveResumeMeta>({
    title: "默认基准简历",
    status: "启用",
    word_count: 0,
  })
  const [massApplyResume, setMassApplyResume] = useState<ActiveResumeMeta>({
    title: "海投通用简历",
    status: "启用",
    word_count: 0,
  })
  const [allResumes, setAllResumes] = useState<ActiveResumeMeta[]>([])
  
  // 控制哪个下拉面板展开
  const [openDropdown, setOpenDropdown] = useState<"active" | "mass" | null>(null)
  const [switchingActive, setSwitchingActive] = useState(false)
  const [switchingMass, setSwitchingMass] = useState(false)
  const [loading, setLoading] = useState(true)

  const fetchResumes = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/eval-config`)
      const result = await res.json()
      if (result.code === 0 && result.data) {
        if (result.data.active_resume) setActiveResume(result.data.active_resume)
        if (result.data.mass_apply_resume) {
          setMassApplyResume(result.data.mass_apply_resume)
        } else if (result.data.active_resume) {
          setMassApplyResume(result.data.active_resume)
        }
        if (result.data.all_resumes) setAllResumes(result.data.all_resumes)
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchResumes()
  }, [fetchResumes])

  // 1. 切换全链路基准简历
  const handleSelectActiveResume = async (target: ActiveResumeMeta) => {
    if (!target.record_id || target.record_id === activeResume.record_id) {
      setOpenDropdown(null)
      return
    }

    setSwitchingActive(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/activate-resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: target.record_id }),
      })
      const result = await res.json()
      if (result.code === 0) {
        toast.success(`全链路基准简历已切换为：${target.title}`)
        setActiveResume(result.data?.active_resume || target)
        if (result.data?.all_resumes) setAllResumes(result.data.all_resumes)
      } else {
        toast.error(result.msg || "切换简历失败")
      }
    } catch {
      toast.error("网络异常，无法切换简历")
    } finally {
      setSwitchingActive(false)
      setOpenDropdown(null)
    }
  }

  // 2. 切换海投专属简历
  const handleSelectMassResume = async (target: ActiveResumeMeta) => {
    if (!target.record_id || target.record_id === massApplyResume.record_id) {
      setOpenDropdown(null)
      return
    }

    setSwitchingMass(true)
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/set-mass-apply-resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: target.record_id }),
      })
      const result = await res.json()
      if (result.code === 0) {
        toast.success(`海投专属简历已切换为：${target.title}`)
        setMassApplyResume(result.data?.mass_apply_resume || target)
        if (result.data?.all_resumes) setAllResumes(result.data.all_resumes)
      } else {
        toast.error(result.msg || "设置海投简历失败")
      }
    } catch {
      toast.error("网络异常，无法设置海投简历")
    } finally {
      setSwitchingMass(false)
      setOpenDropdown(null)
    }
  }

  const activeTitle = activeResume?.title || "默认基准简历"
  const activeWords = activeResume?.word_count || 0

  const massTitle = massApplyResume?.title || activeTitle || "海投通用简历"
  const massWords = massApplyResume?.word_count || activeWords || 0

  return (
    <div className="flex items-center gap-2.5 flex-wrap">
      {/* ─── 1. 全链路基准简历选择器 ─── */}
      <div className="flex items-center gap-1.5">
        <div className="flex items-center gap-1 text-xs text-muted-foreground font-medium shrink-0">
          <FileText className="h-3.5 w-3.5 text-emerald-500" />
          <span>全链路基准简历:</span>
        </div>

        {/* 下拉按钮 */}
        <div className="relative inline-block">
          <button
            type="button"
            onClick={() => setOpenDropdown(openDropdown === "active" ? null : "active")}
            disabled={switchingActive || loading || allResumes.length === 0}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-800 dark:text-emerald-300 hover:bg-emerald-500/15 transition-all text-left max-w-[190px] truncate cursor-pointer shadow-2xs",
              switchingActive && "opacity-60 cursor-wait",
              (loading || allResumes.length === 0) && "cursor-default opacity-80"
            )}
          >
            {switchingActive ? (
              <Loader2 className="h-3 w-3 animate-spin text-emerald-500 shrink-0" />
            ) : (
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shrink-0" />
            )}
            <span className="truncate font-mono font-semibold">{activeTitle}</span>
            {activeWords > 0 && (
              <span className="text-[10px] text-emerald-700/70 dark:text-emerald-400/70 shrink-0 font-mono">
                ({activeWords.toLocaleString()}字)
              </span>
            )}
            {allResumes.length > 1 && (
              <ChevronsUpDown className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0 ml-0.5" />
            )}
          </button>

          {/* 下拉浮层 */}
          {openDropdown === "active" && allResumes.length > 0 && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setOpenDropdown(null)}
              />
              <div className="absolute right-0 sm:left-0 top-full mt-1.5 z-50 w-72 rounded-2xl border border-border/80 bg-popover p-1.5 shadow-xl animate-in fade-in zoom-in-95 duration-150">
                <div className="px-2 py-1.5 text-[10px] font-semibold text-muted-foreground border-b border-border/40 mb-1">
                  选择切换全链路基准简历（AI认知底稿）：
                </div>
                <div className="max-h-56 overflow-y-auto space-y-0.5">
                  {allResumes.map((item) => {
                    const isSelected = item.record_id === activeResume.record_id
                    return (
                      <button
                        key={item.record_id || item.title}
                        type="button"
                        onClick={() => handleSelectActiveResume(item)}
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

        {/* 提示 Tooltip */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button" className="text-muted-foreground/60 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors p-0.5">
              <AlertCircle className="h-3.5 w-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
            <p className="font-semibold text-emerald-400 mb-0.5">📄 全链路基准简历机制：</p>
            <p className="text-zinc-300 text-[11px]">
              决定了全链路拿哪份简历去做 <strong>AI 初步评估 / 深度评估画像 / 定制改写 / 打招呼语生成</strong>。此简历是全链路能力的真实基准底稿，切换后即刻全局生效。
            </p>
          </TooltipContent>
        </Tooltip>
      </div>

      {/* 分割线 */}
      <div className="hidden md:block h-3.5 w-px bg-border/60" />

      {/* ─── 2. 海投简历选择器 ─── */}
      <div className="flex items-center gap-1.5">
        <div className="flex items-center gap-1 text-xs text-muted-foreground font-medium shrink-0">
          <Send className="h-3.5 w-3.5 text-blue-500" />
          <span>海投简历:</span>
        </div>

        {/* 下拉按钮 */}
        <div className="relative inline-block">
          <button
            type="button"
            onClick={() => setOpenDropdown(openDropdown === "mass" ? null : "mass")}
            disabled={switchingMass || loading || allResumes.length === 0}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-xl border border-blue-500/30 bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-800 dark:text-blue-300 hover:bg-blue-500/15 transition-all text-left max-w-[190px] truncate cursor-pointer shadow-2xs",
              switchingMass && "opacity-60 cursor-wait",
              (loading || allResumes.length === 0) && "cursor-default opacity-80"
            )}
          >
            {switchingMass ? (
              <Loader2 className="h-3 w-3 animate-spin text-blue-500 shrink-0" />
            ) : (
              <span className="h-1.5 w-1.5 rounded-full bg-blue-500 shrink-0" />
            )}
            <span className="truncate font-mono font-semibold">{massTitle}</span>
            {massWords > 0 && (
              <span className="text-[10px] text-blue-700/70 dark:text-blue-400/70 shrink-0 font-mono">
                ({massWords.toLocaleString()}字)
              </span>
            )}
            {allResumes.length > 1 && (
              <ChevronsUpDown className="h-3 w-3 text-blue-600 dark:text-blue-400 shrink-0 ml-0.5" />
            )}
          </button>

          {/* 下拉浮层 */}
          {openDropdown === "mass" && allResumes.length > 0 && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setOpenDropdown(null)}
              />
              <div className="absolute right-0 sm:left-0 top-full mt-1.5 z-50 w-72 rounded-2xl border border-border/80 bg-popover p-1.5 shadow-xl animate-in fade-in zoom-in-95 duration-150">
                <div className="px-2 py-1.5 text-[10px] font-semibold text-muted-foreground border-b border-border/40 mb-1">
                  选择指定海投专属简历（物料生成底稿）：
                </div>
                <div className="max-h-56 overflow-y-auto space-y-0.5">
                  {allResumes.map((item) => {
                    const isSelected = item.record_id === (massApplyResume.record_id || activeResume.record_id)
                    return (
                      <button
                        key={item.record_id || item.title}
                        type="button"
                        onClick={() => handleSelectMassResume(item)}
                        className={cn(
                          "w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-xl text-xs text-left transition-colors",
                          isSelected
                            ? "bg-blue-500/10 text-blue-800 dark:text-blue-300 font-medium"
                            : "hover:bg-muted text-foreground/80"
                        )}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span
                            className={cn(
                              "h-1.5 w-1.5 rounded-full shrink-0",
                              isSelected ? "bg-blue-500" : "bg-muted-foreground/40"
                            )}
                          />
                          <span className="truncate font-mono">{item.title}</span>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0 text-[10px] text-muted-foreground font-mono">
                          {item.word_count ? `${item.word_count}字` : ""}
                          {isSelected && (
                            <Check className="h-3.5 w-3.5 text-blue-500" />
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

        {/* 提示 Tooltip */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button type="button" className="text-muted-foreground/60 hover:text-blue-600 dark:hover:text-blue-400 transition-colors p-0.5">
              <AlertCircle className="h-3.5 w-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
            <p className="font-semibold text-blue-400 mb-0.5">🚀 海投专属简历机制：</p>
            <p className="text-zinc-300 text-[11px]">
              专用于 <strong>C / D 级普通海投通道</strong>。当岗位无需深度定制时，系统将直接挂载此简历生成的 PDF 附件投递给 HR。
            </p>
          </TooltipContent>
        </Tooltip>
      </div>

      {/* ─── 3. 前往简历库外链 ─── */}
      <a
        href="/strategy?section=resume"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-600 dark:text-violet-400 hover:text-violet-700 hover:underline transition-colors shrink-0 ml-0.5"
      >
        <span>前往简历库</span>
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  )
}
