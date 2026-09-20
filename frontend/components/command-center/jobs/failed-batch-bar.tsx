"use client"

import React, { useMemo } from "react"
import { RotateCcw, Trash2, CheckSquare, Square, Sparkles, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { PipelineJob } from "@/store/pipeline-store"

interface FailedBatchBarProps {
  failedJobs: PipelineJob[]
  selectedJobIds: Set<string>
  onSelectAll: () => void
  onClearSelection: () => void
  onSelectByPlatform: (platformKey: string) => void
  onBatchRetry: () => void
  onBatchDismiss: () => void
  isRetrying?: boolean
  isDismissing?: boolean
}

export const FailedBatchBar = React.memo(function FailedBatchBar({
  failedJobs,
  selectedJobIds,
  onSelectAll,
  onClearSelection,
  onSelectByPlatform,
  onBatchRetry,
  onBatchDismiss,
  isRetrying = false,
  isDismissing = false,
}: FailedBatchBarProps) {
  const totalCount = failedJobs.length
  const selectedCount = selectedJobIds.size
  const isAllSelected = totalCount > 0 && selectedCount === totalCount

  // 按平台统计失败岗位数量，用于快捷预设芯片
  const platformStats = useMemo(() => {
    const stats: Record<string, { label: string; count: number }> = {}
    failedJobs.forEach((job) => {
      const rawPlat = (job.platform || "other").toLowerCase()
      let key = "other"
      let label = "其他"
      if (rawPlat.includes("51") || rawPlat.includes("前程")) {
        key = "51job"
        label = "51Job"
      } else if (rawPlat.includes("智联") || rawPlat.includes("zhilian")) {
        key = "zhilian"
        label = "智联招聘"
      } else if (rawPlat.includes("boss")) {
        key = "boss"
        label = "BOSS直聘"
      } else if (rawPlat.includes("猎聘") || rawPlat.includes("liepin")) {
        key = "liepin"
        label = "猎聘"
      }
      if (!stats[key]) {
        stats[key] = { label, count: 0 }
      }
      stats[key].count += 1
    })
    return Object.entries(stats).sort((a, b) => b[1].count - a[1].count)
  }, [failedJobs])

  if (totalCount === 0) return null

  return (
    <div className="mb-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-xl border border-rose-500/20 bg-rose-500/5 px-3.5 py-2.5 text-xs transition-all">
      {/* 左侧：全选控制与平台快捷预设 */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={isAllSelected ? onClearSelection : onSelectAll}
          className="flex items-center gap-1.5 font-semibold text-foreground hover:text-rose-600 transition-colors cursor-pointer select-none"
        >
          {isAllSelected ? (
            <CheckSquare className="h-4 w-4 text-rose-600 dark:text-rose-400" />
          ) : (
            <Square className="h-4 w-4 text-muted-foreground" />
          )}
          <span>{isAllSelected ? "取消全选" : "全选"}</span>
          <span className="text-[11px] text-muted-foreground font-normal">
            ({selectedCount}/{totalCount})
          </span>
        </button>

        <span className="hidden sm:inline-block h-3.5 w-px bg-border/80 mx-0.5" />

        {/* 智能预设标签 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] text-muted-foreground flex items-center gap-0.5">
            <Sparkles className="h-3 w-3 text-rose-500" /> 快捷:
          </span>
          {platformStats.map(([key, item]) => (
            <button
              key={key}
              type="button"
              onClick={() => onSelectByPlatform(key)}
              className="rounded-md border border-rose-500/20 bg-background/80 px-2 py-0.5 text-[10px] font-medium text-muted-foreground hover:text-foreground hover:border-rose-500/40 hover:bg-rose-50/50 dark:hover:bg-rose-950/20 transition-all cursor-pointer"
            >
              {item.label} ({item.count})
            </button>
          ))}
          {selectedCount > 0 && (
            <button
              type="button"
              onClick={onClearSelection}
              className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded transition-colors cursor-pointer"
              title="清空当前所有选中"
            >
              <X className="h-2.5 w-2.5" /> 清空
            </button>
          )}
        </div>
      </div>

      {/* 右侧：批量执行动作按钮 */}
      <div className="flex items-center gap-2 self-end sm:self-auto shrink-0">
        <button
          type="button"
          onClick={onBatchDismiss}
          disabled={selectedCount === 0 || isDismissing || isRetrying}
          className="flex h-7 items-center gap-1 rounded-md border border-rose-300 dark:border-rose-900/60 bg-background px-2.5 text-[11px] font-medium text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-all active:scale-95 disabled:opacity-40 disabled:pointer-events-none cursor-pointer shadow-xs"
          title="将选中的岗位批量放弃并移出看板"
        >
          <Trash2 className="h-3 w-3" />
          {isDismissing ? "放弃中…" : `批量放弃 (${selectedCount})`}
        </button>

        <button
          type="button"
          onClick={onBatchRetry}
          disabled={selectedCount === 0 || isRetrying || isDismissing}
          className="flex h-7 items-center gap-1 rounded-md bg-rose-600 hover:bg-rose-500 px-3 text-[11px] font-semibold text-white shadow-xs transition-all active:scale-95 disabled:opacity-40 disabled:pointer-events-none cursor-pointer"
          title="将选中的岗位送入标准投递编排引擎重试（按BOSS->智联->猎聘->51job串行排队）"
        >
          <RotateCcw className={cn("h-3 w-3", isRetrying && "animate-spin")} />
          {isRetrying ? "编排拉起中…" : `批量重试 (${selectedCount})`}
        </button>
      </div>
    </div>
  )
})
