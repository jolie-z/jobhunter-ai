"use client"

import {
  Search,
  CheckCircle2,
  Sparkles,
  Layers,
  ShieldAlert,
  Clock,
  AlertTriangle,
  Truck,
  Send
} from "lucide-react"
import { usePipelineStore } from "@/store/pipeline-store"
import { cn } from "@/lib/utils"
import {
  isJobRejected,
  isJobFailed,
} from "./job-predicates"
import { DeliveryScheduleBanner } from "./jobs/delivery-schedule-banner"
import { JobCard } from "./jobs/job-card"
import { RejectedJobCard } from "./jobs/rejected-job-card"
import { FailedJobCard } from "./jobs/failed-job-card"
import { FailedBatchBar } from "./jobs/failed-batch-bar"
import { useBoardActions } from "./jobs/use-board-actions"
import { useBoardFilters } from "./jobs/use-board-filters"
import { StageKey } from "./types"
import { useState, useCallback, useEffect } from "react"

interface LiveJobsBoardProps {
  onOpenConfig?: (stageKey: StageKey) => void
}

export function LiveJobsBoard({ onOpenConfig }: LiveJobsBoardProps = {}) {
  const deliverySchedule = usePipelineStore((s) => s.deliverySchedule)
  const {
    filterTab,
    setFilterTab,
    searchInput,
    setSearchInput,
    allJobs,
    rejectedJobs,
    waitingJobs,
    readyToDeliverJobs,
    evaluatingJobs,
    deliveredJobs,
    failedJobs,
    filteredJobs,
  } = useBoardFilters()

  // 选中的失败岗位集合
  const [selectedFailedJobIds, setSelectedFailedJobIds] = useState<Set<string>>(new Set())

  // Tab 切换时自动清空勾选
  useEffect(() => {
    setSelectedFailedJobIds(new Set())
  }, [filterTab])

  // 批量与单个审批/投递业务操作
  const {
    batchLoading,
    deliveringBatch,
    approvingJobIds,
    batchRetryingFailed,
    batchDismissingFailed,
    cancellingJobIds,
    handleCancelDelivery,
    handleApprove,
    handleBatchApprove,
    handleTriggerDeliverAll,
    handleTriggerDeliverSingle,
    handleRetryFailedJob,
    handleDismissFailedJob,
    handleBatchRetryFailedJobs,
    handleBatchDismissFailedJobs,
  } = useBoardActions(waitingJobs, readyToDeliverJobs)

  // 失败岗位单选切换
  const handleToggleSelectFailedJob = useCallback((jobId: string) => {
    setSelectedFailedJobIds((prev) => {
      const next = new Set(prev)
      if (next.has(jobId)) {
        next.delete(jobId)
      } else {
        next.add(jobId)
      }
      return next
    })
  }, [])

  // 失败岗位全选
  const handleSelectAllFailedJobs = useCallback(() => {
    setSelectedFailedJobIds(new Set(failedJobs.map((j) => j.job_id)))
  }, [failedJobs])

  // 清空选中
  const handleClearFailedSelection = useCallback(() => {
    setSelectedFailedJobIds(new Set())
  }, [])

  // 按平台快捷勾选
  const handleSelectFailedByPlatform = useCallback((platformKey: string) => {
    const matchedIds = failedJobs
      .filter((job) => {
        const raw = (job.platform || "").toLowerCase()
        if (platformKey === "51job") return raw.includes("51") || raw.includes("前程")
        if (platformKey === "zhilian") return raw.includes("智联") || raw.includes("zhilian")
        if (platformKey === "boss") return raw.includes("boss")
        if (platformKey === "liepin") return raw.includes("猎聘") || raw.includes("liepin")
        return false
      })
      .map((j) => j.job_id)
    setSelectedFailedJobIds(new Set(matchedIds))
  }, [failedJobs])

  // 批量重试回调
  const handleTriggerBatchRetry = useCallback(async () => {
    const ids = Array.from(selectedFailedJobIds)
    if (ids.length === 0) return
    const ok = await handleBatchRetryFailedJobs(ids)
    if (ok) {
      setSelectedFailedJobIds(new Set())
    }
  }, [selectedFailedJobIds, handleBatchRetryFailedJobs])

  // 批量放弃回调
  const handleTriggerBatchDismiss = useCallback(async () => {
    const ids = Array.from(selectedFailedJobIds)
    if (ids.length === 0) return
    const ok = await handleBatchDismissFailedJobs(ids)
    if (ok) {
      setSelectedFailedJobIds(new Set())
    }
  }, [selectedFailedJobIds, handleBatchDismissFailedJobs])

  return (
    <div className="w-full rounded-2xl border border-border/80 bg-card p-5 shadow-xs flex flex-col min-h-[440px]">
      {/* 顶栏：7 大主 Tab 筛选与批量操作 */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 pb-3 border-b border-border/60">
        {/* Tab 按钮组 */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0 scrollbar-none">
          {/* 全部岗位 */}
          <button
            onClick={() => setFilterTab("all")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all shrink-0 cursor-pointer",
              filterTab === "all"
                ? "bg-foreground text-background shadow-xs"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <Layers className="h-3.5 w-3.5" />
            全部岗位
            <span className="text-[10px] opacity-70">({allJobs.length})</span>
          </button>

          {/* 淘汰岗位 */}
          <button
            onClick={() => setFilterTab("rejected")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all shrink-0 cursor-pointer",
              filterTab === "rejected"
                ? "bg-rose-500 text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <ShieldAlert className="h-3.5 w-3.5" />
            淘汰岗位
            {rejectedJobs.length > 0 && (
              <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-600 text-[10px] text-white px-1 font-bold">
                {rejectedJobs.length}
              </span>
            )}
          </button>

          {/* 评估/改写/投递中 */}
          <button
            onClick={() => setFilterTab("evaluating")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all shrink-0 cursor-pointer",
              filterTab === "evaluating"
                ? "bg-violet-600 text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <Sparkles className="h-3.5 w-3.5" />
            评估/改写/投递中
            {evaluatingJobs.length > 0 && (
              <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-violet-500 text-[10px] text-white px-1 font-bold">
                {evaluatingJobs.length}
              </span>
            )}
          </button>

          {/* 待审批 */}
          <button
            onClick={() => setFilterTab("review")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all shrink-0 cursor-pointer",
              filterTab === "review"
                ? "bg-amber-500 text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <Clock className="h-3.5 w-3.5" />
            待审批
            {waitingJobs.length > 0 && (
              <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 text-[10px] text-white px-1 font-bold animate-pulse">
                {waitingJobs.length}
              </span>
            )}
          </button>

          {/* 待投递（就绪流转 Tab） */}
          <button
            onClick={() => setFilterTab("ready_to_deliver")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all shrink-0 cursor-pointer",
              filterTab === "ready_to_deliver"
                ? "bg-blue-600 text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <Truck className="h-3.5 w-3.5" />
            待投递
            {readyToDeliverJobs.length > 0 && (
              <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-blue-500 text-[10px] text-white px-1 font-bold">
                {readyToDeliverJobs.length}
              </span>
            )}
          </button>

          {/* 已投递 */}
          <button
            onClick={() => setFilterTab("delivered")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all shrink-0 cursor-pointer",
              filterTab === "delivered"
                ? "bg-emerald-600 text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            已投递
            {deliveredJobs.length > 0 && (
              <span className="text-[10px] opacity-70">({deliveredJobs.length})</span>
            )}
          </button>

          {/* 执行失败 */}
          <button
            onClick={() => setFilterTab("failed")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all shrink-0 cursor-pointer",
              filterTab === "failed"
                ? "bg-rose-700 text-white shadow-xs"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            执行失败
            {failedJobs.length > 0 && (
              <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 text-[10px] text-white px-1 font-bold">
                {failedJobs.length}
              </span>
            )}
          </button>
        </div>

        {/* 右侧：批量操作与搜索 */}
        <div className="flex items-center gap-2 shrink-0">
          {/* 待投递专属批量触发按钮：仅切到待投递 Tab 且有待投递岗位时显示 */}
          {filterTab === "ready_to_deliver" && readyToDeliverJobs.length > 0 && (
            <button
              onClick={handleTriggerDeliverAll}
              disabled={deliveringBatch}
              className="flex items-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
            >
              <Send className="h-3.5 w-3.5" />
              {deliveringBatch ? "正在自动投递…" : `立即执行投递 (${readyToDeliverJobs.length})`}
            </button>
          )}

          {/* 待审批专属批量放行按钮：仅切到待审批 Tab 且有待审批岗位时显示 */}
          {filterTab === "review" && waitingJobs.length > 0 && (
            <button
              onClick={() => handleBatchApprove(waitingJobs)}
              disabled={batchLoading}
              className="flex items-center gap-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              {batchLoading ? "放行中…" : `一键放行全部 (${waitingJobs.length})`}
            </button>
          )}

          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="搜索岗位/公司/平台…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="h-8 w-44 sm:w-52 rounded-lg border border-border/80 bg-background pl-8 pr-2.5 text-xs text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
        </div>
      </div>

      {/* 待投递 Tab 专属：定时投递排期提醒与 Edge 平台常驻保障横幅 */}
      {filterTab === "ready_to_deliver" && (
        <DeliveryScheduleBanner
          deliverySchedule={deliverySchedule}
          totalReadyJobs={readyToDeliverJobs.length}
          onOpenScrapeConfig={() => onOpenConfig?.("scraping")}
        />
      )}

      {/* 智能导流 Banner：仅在非待投递 Tab 下且待审批已清空、待投递有岗位时提示 */}
      {filterTab !== "ready_to_deliver" && waitingJobs.length === 0 && readyToDeliverJobs.length > 0 && (
        <div className="mb-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 p-3 text-xs text-blue-700 dark:text-blue-300">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-blue-500 shrink-0" />
            <span>
              <strong>🎉 待审批已全部放行！</strong> 当前有 <strong>{readyToDeliverJobs.length}</strong> 个岗位在「待投递」队列中就绪。
            </span>
          </div>
          <div className="flex items-center gap-2 self-end sm:self-auto">
            <button
              onClick={() => setFilterTab("ready_to_deliver")}
              className="rounded-md border border-blue-500/30 bg-background/80 px-2.5 py-1 text-[11px] font-medium text-foreground hover:bg-background transition-all cursor-pointer"
            >
              查看待投递
            </button>
            <button
              onClick={handleTriggerDeliverAll}
              disabled={deliveringBatch}
              className="flex items-center gap-1 rounded-md bg-blue-600 hover:bg-blue-500 px-3 py-1 text-[11px] font-semibold text-white shadow-xs transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
            >
              <Send className="h-3 w-3" />
              {deliveringBatch ? "正在自动投递…" : "立即发射全部"}
            </button>
          </div>
        </div>
      )}

      {/* 执行失败 Tab 专属：批量治理控制条（全选/批量重试/批量放弃/平台快捷筛选） */}
      {filterTab === "failed" && failedJobs.length > 0 && (
        <FailedBatchBar
          failedJobs={failedJobs}
          selectedJobIds={selectedFailedJobIds}
          onSelectAll={handleSelectAllFailedJobs}
          onClearSelection={handleClearFailedSelection}
          onSelectByPlatform={handleSelectFailedByPlatform}
          onBatchRetry={handleTriggerBatchRetry}
          onBatchDismiss={handleTriggerBatchDismiss}
          isRetrying={batchRetryingFailed}
          isDismissing={batchDismissingFailed}
        />
      )}

      {/* 岗位卡片列表 */}
      {filteredJobs.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center py-16 text-center">
          <div className="h-12 w-12 rounded-full bg-muted/60 flex items-center justify-center text-muted-foreground mb-3">
            <Sparkles className="h-6 w-6" />
          </div>
          <p className="text-xs font-semibold text-foreground">暂无符合条件的流转岗位</p>
          <p className="text-[11px] text-muted-foreground mt-1 max-w-xs leading-relaxed">
            启动全链路任务后，各平台新采集与各节点流转的岗位将在此处实时入池。
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3.5">
          {filteredJobs.map((job) => {
            if (isJobRejected(job)) {
              return <RejectedJobCard key={job.job_id} job={job} />
            }

            if (isJobFailed(job)) {
              return (
                <FailedJobCard
                  key={job.job_id}
                  job={job}
                  selected={selectedFailedJobIds.has(job.job_id)}
                  onToggleSelect={handleToggleSelectFailedJob}
                  onRetry={handleRetryFailedJob}
                  onDismiss={handleDismissFailedJob}
                />
              )
            }

            return (
              <JobCard
                key={job.job_id}
                job={job}
                isApproving={Boolean(approvingJobIds?.[job.job_id])}
                isCancelling={Boolean(cancellingJobIds?.[job.job_id])}
                onApprove={handleApprove}
                onDeliverSingle={handleTriggerDeliverSingle}
                onCancelDelivery={handleCancelDelivery}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}
