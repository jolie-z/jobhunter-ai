"use client"

import { useMemo } from "react"
import {
  DownloadCloud,
  Filter,
  Share2,
  Brain,
  FileCheck,
  Truck,
  Send,
  ArrowRight,
  TrendingUp,
} from "lucide-react"
import { usePipelineStore } from "@/store/pipeline-store"
import { cn } from "@/lib/utils"
import { isJobDelivered, isJobReadyToDeliver, isJobRejected, isJobWaitingReview } from "./job-predicates"

export function MissionFunnelCard() {
  const pipelineStatus = usePipelineStore((s) => s.status)
  const currentStage = usePipelineStore((s) => s.currentStage)
  const scrapeProgress = usePipelineStore((s) => s.scrapeProgress)
  const hardCleanProgress = usePipelineStore((s) => s.hardCleanProgress)
  const feishuSyncProgress = usePipelineStore((s) => s.feishuSyncProgress)
  const jobs = usePipelineStore((s) => s.jobs)

  const jobList = useMemo(() => Object.values(jobs), [jobs])

  // 当次任务岗位池（严格隔离历史存量待投递/已投递/历史受阻岗位）
  const currentRunJobs = useMemo(
    () => jobList.filter((j) => j.is_current_run !== false),
    [jobList]
  )

  const passedJobs = useMemo(
    () => currentRunJobs.filter((j) => !isJobRejected(j)),
    [currentRunJobs]
  )

  const rawScrapeSum = useMemo(
    () => Object.values(scrapeProgress).reduce((acc, cur) => {
      const current = typeof cur?.current === 'number' ? cur.current : 0
      return acc + current
    }, 0),
    [scrapeProgress]
  )

  // 判定当前是否有正在运行或当次任务已启动的链路
  const isPipelineActive =
    pipelineStatus !== "idle" ||
    currentStage !== null ||
    rawScrapeSum > 0 ||
    hardCleanProgress !== null ||
    feishuSyncProgress !== null

  const totalScraped = rawScrapeSum > 0 ? rawScrapeSum : (isPipelineActive ? currentRunJobs.length : 0)
  const cleanedCount = hardCleanProgress?.total ?? (totalScraped > 0 ? totalScraped : currentRunJobs.length)
  const syncedCount = feishuSyncProgress?.current ?? (isPipelineActive ? passedJobs.length : 0)
  const evaluatedCount = useMemo(
    () => isPipelineActive ? passedJobs.filter((j) => (j.score !== undefined && j.score !== null) || !!j.grade || isJobWaitingReview(j) || isJobReadyToDeliver(j) || isJobDelivered(j) || j.status === "error").length : 0,
    [passedJobs, isPipelineActive]
  )
  const pendingReviewCount = useMemo(() => jobList.filter(isJobWaitingReview).length, [jobList])
  const readyToDeliverCount = useMemo(() => jobList.filter(isJobReadyToDeliver).length, [jobList])
  const deliveredCount = useMemo(() => jobList.filter(isJobDelivered).length, [jobList])

  const deliveryRate = evaluatedCount > 0 ? Math.round((deliveredCount / evaluatedCount) * 100) : 0

  const funnelSteps = [
    {
      id: "scraped",
      label: "全网抓取",
      icon: DownloadCloud,
      count: totalScraped,
      unit: "条",
      color: "text-blue-500",
      bg: "bg-blue-500/10",
      borderColor: "border-blue-500/20",
    },
    {
      id: "cleaned",
      label: "规则清洗",
      icon: Filter,
      count: cleanedCount,
      unit: "条",
      color: "text-indigo-500",
      bg: "bg-indigo-500/10",
      borderColor: "border-indigo-500/20",
    },
    {
      id: "synced",
      label: "飞书同步",
      icon: Share2,
      count: syncedCount,
      unit: "条",
      color: "text-violet-500",
      bg: "bg-violet-500/10",
      borderColor: "border-violet-500/20",
    },
    {
      id: "evaluated",
      label: "AI 评估",
      icon: Brain,
      count: evaluatedCount,
      unit: "个",
      color: "text-purple-500",
      bg: "bg-purple-500/10",
      borderColor: "border-purple-500/20",
    },
    {
      id: "review",
      label: "待审批",
      icon: FileCheck,
      count: pendingReviewCount,
      unit: "个",
      color: "text-amber-500",
      bg: "bg-amber-500/10",
      borderColor: "border-amber-500/20",
      highlight: pendingReviewCount > 0,
    },
    {
      id: "ready_to_deliver",
      label: "待投递",
      icon: Truck,
      count: readyToDeliverCount,
      unit: "个",
      color: "text-blue-500",
      bg: "bg-blue-500/10",
      borderColor: "border-blue-500/20",
      highlight: readyToDeliverCount > 0,
    },
    {
      id: "delivered",
      label: "成功投递",
      icon: Send,
      count: deliveredCount,
      unit: "个",
      color: "text-emerald-500",
      bg: "bg-emerald-500/10",
      borderColor: "border-emerald-500/20",
      highlight: deliveredCount > 0,
    },
  ]

  return (
    <div className="w-full rounded-2xl border border-border/80 bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3.5">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-violet-500" />
          <h2 className="text-xs font-semibold text-foreground tracking-tight">
            全链路转化漏斗
          </h2>
          <span className="text-[11px] text-muted-foreground">
            实时流转数据
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground">综合投递率:</span>
          <span className="text-xs font-bold font-mono text-emerald-600 dark:text-emerald-400">
            {deliveryRate}%
          </span>
        </div>
      </div>

      {/* 漏斗横向指标网格 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2.5">
        {funnelSteps.map((step, idx) => {
          const Icon = step.icon
          return (
            <div
              key={step.id}
              className={cn(
                "relative flex flex-col justify-between rounded-xl border p-3 transition-all hover:border-foreground/20",
                step.borderColor,
                step.highlight ? "bg-muted/40 shadow-sm" : "bg-card"
              )}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-medium text-muted-foreground">
                  {step.label}
                </span>
                <div className={cn("flex h-6 w-6 items-center justify-center rounded-lg", step.bg, step.color)}>
                  <Icon className="h-3.5 w-3.5" />
                </div>
              </div>

              <div className="flex items-baseline gap-1">
                <span className="text-lg font-bold font-mono tracking-tight text-foreground">
                  {step.count}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {step.unit}
                </span>
              </div>

              {/* 连接箭头 */}
              {idx < funnelSteps.length - 1 && (
                <div className="hidden md:block absolute -right-2 top-1/2 -translate-y-1/2 z-10 text-muted-foreground/40">
                  <ArrowRight className="h-3 w-3" />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
