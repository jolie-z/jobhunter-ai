"use client"

import { useState, useMemo } from "react"
import {
  Search,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Send,
  Building2,
  Image as ImageIcon,
  FileText,
  MessageSquare,
  Sparkles,
  Lock,
  Edit3,
  RefreshCw,
  Info,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface PendingReviewJob {
  job_id: string
  job_name: string
  company_name: string
  company_scale?: string
  platform: string
  grade: string
  salary?: string
  city?: string
  job_url?: string
  has_image?: boolean
  has_pdf?: boolean
  has_greeting?: boolean
  greeting_text?: string
  is_custom?: boolean
  status?: string
}

interface ReviewPendingJobsCardProps {
  jobs: PendingReviewJob[]
  onApprove: (jobId: string, action: "approve" | "reject") => Promise<void>
  onBatchApprove: (action: "approve" | "reject", targetJobs: PendingReviewJob[]) => Promise<void>
  onRefresh: () => void
  loading?: boolean
}

const PLATFORM_LABELS: Record<string, string> = {
  boss: "BOSS",
  liepin: "猎聘",
  "51job": "51job",
  zhilian: "智联",
}

const GRADE_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  A: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400", border: "border-emerald-500/20" },
  B: { bg: "bg-blue-500/10", text: "text-blue-600 dark:text-blue-400", border: "border-blue-500/20" },
  C: { bg: "bg-amber-500/10", text: "text-amber-600 dark:text-amber-400", border: "border-amber-500/20" },
  D: { bg: "bg-orange-500/10", text: "text-orange-600 dark:text-orange-400", border: "border-orange-500/20" },
  E: { bg: "bg-rose-500/10", text: "text-rose-600 dark:text-rose-400", border: "border-rose-500/20" },
  F: { bg: "bg-zinc-500/10", text: "text-zinc-600 dark:text-zinc-400", border: "border-zinc-500/20" },
}

export function ReviewPendingJobsCard({
  jobs,
  onApprove,
  onBatchApprove,
  onRefresh,
  loading = false,
}: ReviewPendingJobsCardProps) {
  const [tab, setTab] = useState<"custom" | "mass">("custom")
  const [searchQuery, setSearchQuery] = useState("")
  const [operatingId, setOperatingId] = useState<string | null>(null)
  const [batchOperating, setBatchOperating] = useState(false)

  // 1. 分类：精投岗位（按 grade A/B 或 is_custom 判定）vs 大公司海投拦截（其余等级）
  const customJobs = useMemo(
    () => jobs.filter((j) => (j.grade && ["A", "B"].includes(j.grade.toUpperCase())) || j.is_custom),
    [jobs]
  )
  const massJobs = useMemo(
    () => jobs.filter((j) => !customJobs.some((cj) => cj.job_id === j.job_id)),
    [jobs, customJobs]
  )

  const currentTabJobs = tab === "custom" ? customJobs : massJobs

  // 2. 搜索过滤
  const filteredJobs = useMemo(() => {
    if (!searchQuery.trim()) return currentTabJobs
    const q = searchQuery.toLowerCase()
    return currentTabJobs.filter(
      (j) =>
        (j.job_name || "").toLowerCase().includes(q) ||
        (j.company_name || "").toLowerCase().includes(q) ||
        (j.platform || "").toLowerCase().includes(q)
    )
  }, [currentTabJobs, searchQuery])

  // 3. 物料安检校验算法
  const checkMaterialReady = (job: PendingReviewJob): { ready: boolean; hint: string } => {
    const isCustom = (job.grade && ["A", "B"].includes(job.grade.toUpperCase())) || job.is_custom
    if (!isCustom) {
      return { ready: true, hint: "海投岗位：使用全局预置海投简历物料与通用话术，可直接放行。" }
    }

    const plat = (job.platform || "boss").toLowerCase()
    if (plat === "boss") {
      const ok = Boolean(job.has_image && job.has_greeting)
      if (ok) return { ready: true, hint: "物料已齐备：长图与打招呼语均已就绪，可放行。" }
      const missing = []
      if (!job.has_image) missing.push("图片长图")
      if (!job.has_greeting) missing.push("打招呼语")
      return {
        ready: false,
        hint: `⚠️ 无法放行：BOSS直聘需具备图片与打招呼语。当前缺失【${missing.join("、")}】，请前往定制面板保存。`,
      }
    }

    if (plat === "liepin" || plat === "zhilian" || plat.includes("智联") || plat.includes("猎聘")) {
      const ok = Boolean(job.has_pdf && job.has_greeting)
      if (ok) return { ready: true, hint: "物料已齐备：PDF与打招呼语均已就绪，可放行。" }
      const missing = []
      if (!job.has_pdf) missing.push("PDF附件")
      if (!job.has_greeting) missing.push("打招呼语")
      const platName = plat.includes("liepin") || plat.includes("猎聘") ? "猎聘" : "智联招聘"
      return {
        ready: false,
        hint: `⚠️ 无法放行：${platName}需具备PDF与打招呼语。当前缺失【${missing.join("、")}】，请前往定制面板保存。`,
      }
    }

    // 51job
    const ok = Boolean(job.has_pdf)
    if (ok) return { ready: true, hint: "物料已齐备：PDF附件已就绪，可放行。" }
    return {
      ready: false,
      hint: "⚠️ 无法放行：前程无忧(51job)需具备【PDF附件】。请前往定制面板保存 PDF。",
    }
  }

  // 批量就绪岗位
  const readyJobsInCurrentTab = useMemo(
    () => filteredJobs.filter((j) => checkMaterialReady(j).ready),
    [filteredJobs]
  )

  const handleSingleApprove = async (jobId: string, action: "approve" | "reject") => {
    setOperatingId(jobId)
    try {
      await onApprove(jobId, action)
    } finally {
      setOperatingId(null)
    }
  }

  const handleBatch = async (action: "approve" | "reject") => {
    const target = action === "approve" ? readyJobsInCurrentTab : filteredJobs
    if (target.length === 0) return
    setBatchOperating(true)
    try {
      await onBatchApprove(action, target)
    } finally {
      setBatchOperating(false)
    }
  }

  const openCustomWorkspace = (jobId: string) => {
    window.open(`/?job_id=${jobId}`, "_blank")
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-3.5 shadow-xs backdrop-blur-xs space-y-3">
      {/* 头部控制栏：极简 Tabs + 搜索 + 刷新 + 批量按钮 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        {/* 顶部分类切换 Pills */}
        <div className="inline-flex items-center rounded-xl bg-muted/60 p-0.5 border border-border/50 text-[11px]">
          <button
            type="button"
            onClick={() => setTab("custom")}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-medium transition-all cursor-pointer",
              tab === "custom"
                ? "bg-background text-emerald-600 dark:text-emerald-400 shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Sparkles className="h-3 w-3" />
            <span>精投岗位</span>
            <span className="ml-0.5 rounded-full bg-emerald-500/10 px-1.5 py-0.2 text-[10px] font-mono font-medium">
              {customJobs.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setTab("mass")}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-medium transition-all cursor-pointer",
              tab === "mass"
                ? "bg-background text-amber-600 dark:text-amber-400 shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Building2 className="h-3 w-3" />
            <span>海投拦截</span>
            <span className="ml-0.5 rounded-full bg-amber-500/10 px-1.5 py-0.2 text-[10px] font-mono font-medium">
              {massJobs.length}
            </span>
          </button>
        </div>

        {/* 搜索与批量操作栏 */}
        <div className="flex items-center gap-1.5">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索岗位/公司..."
              className="h-7 w-32 sm:w-36 rounded-lg border border-border/80 bg-background/80 pl-6.5 pr-2 text-[11px] placeholder:text-muted-foreground/60 focus:border-violet-500 focus:outline-none"
            />
          </div>

          <button
            type="button"
            onClick={onRefresh}
            title="刷新"
            className="flex h-7 w-7 items-center justify-center rounded-lg border border-border/70 bg-background text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin text-violet-500")} />
          </button>

          {readyJobsInCurrentTab.length > 0 && (
            <button
              type="button"
              onClick={() => handleBatch("approve")}
              disabled={batchOperating}
              className="inline-flex h-7 items-center gap-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 px-2 text-[11px] font-medium text-white shadow-xs transition-all active:scale-95 cursor-pointer disabled:opacity-50"
            >
              <Send className="h-2.5 w-2.5" />
              <span>{batchOperating ? "放行中" : `批量放行(${readyJobsInCurrentTab.length})`}</span>
            </button>
          )}
        </div>
      </div>

      {/* 岗位卡片列表 */}
      {filteredJobs.length === 0 ? (
        <div className="flex items-center justify-center py-8 text-center rounded-xl border border-dashed border-border/60 bg-muted/20 text-xs text-muted-foreground">
          {tab === "custom" ? "当前暂无待审批的精投岗位" : "当前暂无触发拦截的海投岗位"}
        </div>
      ) : (
        <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
          {filteredJobs.map((job) => {
            const { ready, hint } = checkMaterialReady(job)
            const isOperating = operatingId === job.job_id
            const gradeStyle = GRADE_STYLES[job.grade?.toUpperCase() || "B"] || GRADE_STYLES.B
            const plat = (job.platform || "boss").toLowerCase()

            return (
              <div
                key={job.job_id}
                className={cn(
                  "rounded-xl border p-2.5 transition-all space-y-2",
                  ready
                    ? "border-border/70 bg-background/80 hover:border-border"
                    : "border-amber-500/30 bg-amber-500/[0.02]"
                )}
              >
                {/* 第 1 行：岗位名 + 评级 + 平台 + 薪资 + 公司名 + 定制入口 */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
                    <span
                      className={cn(
                        "px-1 py-0.2 rounded text-[10px] font-bold font-mono border shrink-0",
                        gradeStyle.bg,
                        gradeStyle.text,
                        gradeStyle.border
                      )}
                    >
                      {job.grade || "B"}
                    </span>
                    <span className="text-xs font-semibold text-foreground truncate max-w-[130px]">
                      {job.job_name}
                    </span>
                    {job.job_url && (
                      <a
                        href={job.job_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-muted-foreground hover:text-foreground shrink-0"
                        title="原始链接"
                      >
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                    <span className="rounded bg-muted px-1.5 py-0.2 text-[10px] text-muted-foreground shrink-0">
                      {PLATFORM_LABELS[plat] || plat}
                    </span>
                    {job.salary && (
                      <span className="text-amber-600 dark:text-amber-400 font-mono text-[10px] font-medium shrink-0">
                        {job.salary}
                      </span>
                    )}
                    <span className="text-[11px] text-muted-foreground flex items-center gap-0.5 truncate max-w-[120px]">
                      <Building2 className="h-3 w-3 shrink-0" />
                      {job.company_name}
                    </span>
                    {job.company_scale && (
                      <span className="rounded bg-muted/70 px-1.5 py-0.2 text-[9px] text-muted-foreground shrink-0 border border-border/40">
                        {job.company_scale}
                      </span>
                    )}
                  </div>

                  {/* 直达定制面板快捷按钮 */}
                  <button
                    type="button"
                    onClick={() => openCustomWorkspace(job.job_id)}
                    className="inline-flex items-center gap-1 rounded-md border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-600 dark:text-violet-400 hover:bg-violet-500/20 active:scale-95 transition-all cursor-pointer shrink-0"
                  >
                    <Edit3 className="h-2.5 w-2.5" />
                    <span>定制面板</span>
                  </button>
                </div>

                {/* 第 2 行：极简物料状态点 + 操作按钮组 */}
                <div className="flex items-center justify-between gap-2 pt-1.5 border-t border-border/40 text-[11px]">
                  {/* 物料极简标签 */}
                  <div className="flex items-center gap-2">
                    {plat === "boss" ? (
                      <>
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 text-[10px] font-medium",
                            job.has_image
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-amber-600 dark:text-amber-400"
                          )}
                        >
                          <ImageIcon className="h-3 w-3" />
                          <span>{job.has_image ? "长图已就绪" : "长图未存"}</span>
                        </span>
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 text-[10px] font-medium",
                            job.has_greeting
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-amber-600 dark:text-amber-400"
                          )}
                        >
                          <MessageSquare className="h-3 w-3" />
                          <span>{job.has_greeting ? "招呼语就绪" : "招呼语未成"}</span>
                        </span>
                      </>
                    ) : (plat === "liepin" || plat === "zhilian" || plat.includes("智联") || plat.includes("猎聘")) ? (
                      <>
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 text-[10px] font-medium",
                            job.has_pdf
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-amber-600 dark:text-amber-400"
                          )}
                        >
                          <FileText className="h-3 w-3" />
                          <span>{job.has_pdf ? "PDF已就绪" : "PDF未存"}</span>
                        </span>
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 text-[10px] font-medium",
                            job.has_greeting
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-amber-600 dark:text-amber-400"
                          )}
                        >
                          <MessageSquare className="h-3 w-3" />
                          <span>{job.has_greeting ? "招呼语就绪" : "招呼语未成"}</span>
                        </span>
                      </>
                    ) : (
                      <span
                        className={cn(
                          "inline-flex items-center gap-1 text-[10px] font-medium",
                          job.has_pdf
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-amber-600 dark:text-amber-400"
                        )}
                      >
                        <FileText className="h-3 w-3" />
                        <span>{job.has_pdf ? "PDF已就绪" : "PDF未存"}</span>
                      </span>
                    )}
                  </div>

                  {/* 放行与拒绝 */}
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      type="button"
                      onClick={() => handleSingleApprove(job.job_id, "reject")}
                      disabled={isOperating}
                      className="inline-flex h-6 items-center gap-0.5 rounded-md border border-border px-1.5 text-[10px] text-muted-foreground hover:bg-rose-50 hover:text-rose-600 hover:border-rose-200 transition-all active:scale-95 cursor-pointer disabled:opacity-50"
                    >
                      <XCircle className="h-2.5 w-2.5" />
                      <span>拒绝</span>
                    </button>

                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span>
                          <button
                            type="button"
                            onClick={() => ready && handleSingleApprove(job.job_id, "approve")}
                            disabled={!ready || isOperating}
                            className={cn(
                              "inline-flex h-6 items-center gap-1 rounded-md px-2 text-[10px] font-semibold transition-all",
                              ready
                                ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-xs active:scale-95 cursor-pointer"
                                : "bg-muted text-muted-foreground/60 border border-border/50 cursor-not-allowed opacity-60"
                            )}
                          >
                            {ready ? (
                              <Send className="h-2.5 w-2.5" />
                            ) : (
                              <Lock className="h-2.5 w-2.5" />
                            )}
                            <span>{isOperating ? "放行中" : ready ? "确认放行" : "待补齐物料"}</span>
                          </button>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                        {hint}
                      </TooltipContent>
                    </Tooltip>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
