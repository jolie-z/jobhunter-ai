"use client"

import { useState, useMemo } from "react"
import {
  Search,
  CheckCircle2,
  AlertCircle,
  Building2,
  Image as ImageIcon,
  FileText,
  MessageSquare,
  Activity,
  RefreshCw,
  Clock,
} from "lucide-react"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface DeliveredJobItem {
  job_id: string
  job_name: string
  company_name: string
  platform: string
  grade: string
  salary?: string
  city?: string
  has_image?: boolean
  has_pdf?: boolean
  has_greeting?: boolean
  status: "delivered" | "error" | "processing" | "pending"
  error_msg?: string
}

interface DeliveryLiveStreamCardProps {
  jobs: DeliveredJobItem[]
  onRefresh: () => void
  loading?: boolean
}

const PLATFORM_LABELS: Record<string, string> = {
  boss: "BOSS直聘",
  liepin: "猎聘",
  "51job": "前程无忧",
  zhilian: "智联招聘",
}

const GRADE_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  A: { bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400", border: "border-emerald-500/20" },
  B: { bg: "bg-blue-500/10", text: "text-blue-600 dark:text-blue-400", border: "border-blue-500/20" },
  C: { bg: "bg-amber-500/10", text: "text-amber-600 dark:text-amber-400", border: "border-amber-500/20" },
  D: { bg: "bg-orange-500/10", text: "text-orange-600 dark:text-orange-400", border: "border-orange-500/20" },
  E: { bg: "bg-rose-500/10", text: "text-rose-600 dark:text-rose-400", border: "border-rose-500/20" },
  F: { bg: "bg-zinc-500/10", text: "text-zinc-600 dark:text-zinc-400", border: "border-zinc-500/20" },
}

export function DeliveryLiveStreamCard({
  jobs,
  onRefresh,
  loading = false,
}: DeliveryLiveStreamCardProps) {
  const [searchQuery, setSearchQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState<"all" | "delivered" | "error">("all")

  const deliveredCount = useMemo(() => jobs.filter((j) => j.status === "delivered").length, [jobs])
  const errorCount = useMemo(() => jobs.filter((j) => j.status === "error").length, [jobs])

  const filteredJobs = useMemo(() => {
    return jobs.filter((j) => {
      if (statusFilter !== "all" && j.status !== statusFilter) return false
      if (!searchQuery.trim()) return true
      const q = searchQuery.toLowerCase()
      return (
        (j.job_name || "").toLowerCase().includes(q) ||
        (j.company_name || "").toLowerCase().includes(q) ||
        (j.platform || "").toLowerCase().includes(q)
      )
    })
  }, [jobs, statusFilter, searchQuery])

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3.5">
      {/* 头部控制栏：状态统计 + 过滤 + 搜索 + 刷新 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
        {/* 状态统计 Pills */}
        <div className="inline-flex items-center rounded-xl bg-muted/60 p-0.5 border border-border/50 text-xs">
          <button
            type="button"
            onClick={() => setStatusFilter("all")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 font-medium transition-all cursor-pointer",
              statusFilter === "all"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Activity className="h-3.5 w-3.5" />
            <span>全量投递流水</span>
            <span className="ml-0.5 rounded-full bg-muted px-1.5 py-0.2 text-[10px] font-mono">
              {jobs.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setStatusFilter("delivered")}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 font-medium transition-all cursor-pointer",
              statusFilter === "delivered"
                ? "bg-background text-emerald-600 dark:text-emerald-400 shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span>已成功投递</span>
            <span className="ml-0.5 rounded-full bg-emerald-500/10 px-1.5 py-0.2 text-[10px] font-mono font-medium">
              {deliveredCount}
            </span>
          </button>

          {errorCount > 0 && (
            <button
              type="button"
              onClick={() => setStatusFilter("error")}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 font-medium transition-all cursor-pointer",
                statusFilter === "error"
                  ? "bg-background text-rose-600 dark:text-rose-400 shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <AlertCircle className="h-3.5 w-3.5" />
              <span>异常与熔断</span>
              <span className="ml-0.5 rounded-full bg-rose-500/10 px-1.5 py-0.2 text-[10px] font-mono font-medium">
                {errorCount}
              </span>
            </button>
          )}
        </div>

        {/* 搜索与刷新 */}
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索岗位或公司..."
              className="h-8 w-44 rounded-lg border border-border/80 bg-background/80 pl-8 pr-2.5 text-xs placeholder:text-muted-foreground/60 focus:border-blue-500 focus:outline-none"
            />
          </div>

          <button
            type="button"
            onClick={onRefresh}
            title="刷新投递流水"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/70 bg-background text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin text-blue-500")} />
          </button>
        </div>
      </div>

      {/* 岗位卡片列表 */}
      {filteredJobs.length === 0 ? (
        <div className="flex items-center justify-center py-10 text-center rounded-xl border border-dashed border-border/60 bg-muted/20 text-xs text-muted-foreground">
          当前暂无投递记录（将在任务执行后实时呈现）
        </div>
      ) : (
        <div className="space-y-2.5 max-h-[340px] overflow-y-auto pr-1">
          {filteredJobs.map((job) => {
            const gradeStyle = GRADE_STYLES[job.grade?.toUpperCase() || "B"] || GRADE_STYLES.B
            const plat = (job.platform || "boss").toLowerCase()

            return (
              <div
                key={job.job_id}
                className="rounded-xl border border-border/70 bg-background/80 p-3 transition-all space-y-2 hover:border-border"
              >
                {/* 第 1 行：评级 + 岗位名 + 平台 + 薪资 + 公司名 + 投递状态 */}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] font-bold font-mono border shrink-0",
                        gradeStyle.bg,
                        gradeStyle.text,
                        gradeStyle.border
                      )}
                    >
                      {job.grade || "B"}
                    </span>
                    <span className="text-xs font-bold text-foreground">
                      {job.job_name}
                    </span>
                    <span className="rounded-md bg-muted px-2 py-0.5 text-[11px] text-muted-foreground font-medium shrink-0">
                      {PLATFORM_LABELS[plat] || plat}
                    </span>
                    {job.salary && (
                      <span className="text-amber-600 dark:text-amber-400 font-mono text-xs font-semibold shrink-0">
                        {job.salary}
                      </span>
                    )}
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                      <span>{job.company_name}</span>
                    </span>
                  </div>

                  {/* 投递结果徽章 */}
                  {job.status === "delivered" ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 px-2.5 py-0.5 text-xs font-medium shrink-0">
                      <CheckCircle2 className="h-3 w-3" />
                      <span>已成功投递</span>
                    </span>
                  ) : job.status === "error" ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/20 px-2.5 py-0.5 text-xs font-medium shrink-0 cursor-help">
                          <AlertCircle className="h-3 w-3" />
                          <span>投递异常 / 超时</span>
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                        {job.error_msg || "投递执行异常或遇到超时看门狗熔断。"}
                      </TooltipContent>
                    </Tooltip>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 px-2.5 py-0.5 text-xs font-medium shrink-0 font-mono">
                      <Clock className="h-3 w-3 animate-spin" />
                      <span>投递执行中...</span>
                    </span>
                  )}
                </div>

                {/* 第 2 行：物料搭载审计指示器（全文字无截断） */}
                <div className="flex items-center justify-between gap-2 pt-2 border-t border-border/40 text-xs text-muted-foreground flex-wrap">
                  <div className="flex items-center gap-3.5 flex-wrap">
                    <span className="text-[11px] text-muted-foreground font-medium">物料搭载审计：</span>
                    {/* 图片搭载 */}
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-[11px] font-medium",
                        job.has_image
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-muted-foreground/50"
                      )}
                    >
                      <ImageIcon className="h-3.5 w-3.5" />
                      <span>{job.has_image ? "长图简历已随附" : "未携带长图"}</span>
                    </span>

                    {/* PDF 搭载 */}
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-[11px] font-medium",
                        job.has_pdf
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-muted-foreground/50"
                      )}
                    >
                      <FileText className="h-3.5 w-3.5" />
                      <span>{job.has_pdf ? "PDF 附件已随附" : "未携带 PDF"}</span>
                    </span>

                    {/* 打招呼语搭载 */}
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-[11px] font-medium",
                        job.has_greeting
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-muted-foreground/50"
                      )}
                    >
                      <MessageSquare className="h-3.5 w-3.5" />
                      <span>{job.has_greeting ? "打招呼语已发送" : "未带打招呼语"}</span>
                    </span>
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
