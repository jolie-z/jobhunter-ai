"use client"

import { usePipelineStore } from "@/store/pipeline-store"
import { PLATFORM_NAMES } from "../types"
import {  Activity, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"

export function ScrapeLiveProgressBanner() {
  const status = usePipelineStore((s) => s.status)
  const currentStage = usePipelineStore((s) => s.currentStage)
  const scrapeProgress = usePipelineStore((s) => s.scrapeProgress)
  const taskId = usePipelineStore((s) => s.pipelineTaskId)

  const progressEntries = Object.entries(scrapeProgress)
  const isScrapingActive = status === "running" && (currentStage === "scraping" || !currentStage)

  if (progressEntries.length === 0 && !isScrapingActive) {
    return null
  }

  const totalCurrent = progressEntries.reduce((acc, [, p]) => acc + (p.current || 0), 0)
  const totalTarget = progressEntries.reduce((acc, [, p]) => acc + (p.total || 0), 0)

  return (
    <div className="rounded-xl border border-violet-500/30 bg-violet-500/[0.04] p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isScrapingActive ? (
            <Activity className="h-4 w-4 text-violet-600 dark:text-violet-400 animate-pulse" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
          )}
          <span className="text-xs font-semibold text-foreground">
            {isScrapingActive ? "🔥 本轮任务实时抓取流水" : "✓ 上轮任务抓取完成"}
          </span>
          {taskId && (
            <span className="rounded bg-muted px-1.5 py-0.2 font-mono text-[10px] text-muted-foreground">
              {taskId}
            </span>
          )}
        </div>

        <div className="text-xs font-medium text-foreground">
          本轮已入库: <span className="font-bold text-violet-600 dark:text-violet-400 font-mono">{totalCurrent}</span>
          {totalTarget > 0 && <span className="text-muted-foreground font-mono"> / {totalTarget} 条</span>}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {["boss", "liepin", "51job", "zhilian"].map((plat) => {
          const prog = scrapeProgress[plat]
          const current = prog?.current ?? 0
          const total = prog?.total ?? 0
          const pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0

          return (
            <div key={plat} className="rounded-lg border border-border/80 bg-card p-2 text-xs space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-foreground text-[11px]">
                  {PLATFORM_NAMES[plat] || plat}
                </span>
                <span className="font-mono text-[11px] font-bold text-foreground">
                  {current}{total > 0 ? `/${total}` : "条"}
                </span>
              </div>

              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full transition-all duration-300",
                    pct >= 100 ? "bg-emerald-500" : "bg-violet-600"
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
