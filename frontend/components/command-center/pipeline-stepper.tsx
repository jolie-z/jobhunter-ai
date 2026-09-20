"use client"

import { useMemo } from "react"
import {
  Check,
  Layers,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
} from "lucide-react"
import { usePipelineStore } from "@/store/pipeline-store"
import { cn } from "@/lib/utils"
import { STAGES_META, StageKey } from "./types"
import { computeStageStats } from "./stepper-stats"
import { isJobDelivered, isJobReadyToDeliver, isJobRejected, isJobWaitingReview } from "./job-predicates"
import { ActiveResumeSelector } from "./active-resume-selector"

interface PipelineStepperProps {
  configStatus: Record<string, boolean>
  onOpenConfig: (stageKey: StageKey) => void
  onRefreshStatus?: () => void
  isRefreshing?: boolean
}

export function PipelineStepper({
  configStatus,
  onOpenConfig,
  onRefreshStatus,
  isRefreshing,
}: PipelineStepperProps) {
  const pipelineStatus = usePipelineStore((s) => s.status)
  const currentStage = usePipelineStore((s) => s.currentStage)
  const stageStatus = usePipelineStore((s) => s.stageStatus)
  const scrapeProgress = usePipelineStore((s) => s.scrapeProgress)
  const hardCleanProgress = usePipelineStore((s) => s.hardCleanProgress)
  const aiScoutProgress = usePipelineStore((s) => s.aiScoutProgress)
  const feishuSyncProgress = usePipelineStore((s) => s.feishuSyncProgress)
  const jobs = usePipelineStore((s) => s.jobs)

  const jobList = useMemo(() => Object.values(jobs), [jobs])

  // 岗位类阶段统计集中缓存：实时计算各阶段的分子、分母与活跃状态（Q10 拆分批次 2：纯函数抽离 stepper-stats.ts）
  const stageStats = useMemo(
    () => computeStageStats(jobList, feishuSyncProgress?.total),
    [jobList, feishuSyncProgress]
  )

  // 计算各阶段的实时进度与状态信息
  const getStageInfo = (key: StageKey) => {
    const isOverallRunning = pipelineStatus === "running"
    const totalScraped = Object.values(scrapeProgress).reduce((acc, cur) => acc + (typeof cur?.current === 'number' ? cur.current : 0), 0)
    const isPipelineActive =
      pipelineStatus !== "idle" ||
      currentStage !== null ||
      totalScraped > 0 ||
      hardCleanProgress !== null ||
      feishuSyncProgress !== null

    if (!isPipelineActive) {
      switch (key) {
        case "scraping":
          return { summary: "多平台抓取", percent: 0, isActive: false, isCompleted: false }
        case "cleaning":
          return { summary: "规则清洗与初筛", percent: 0, isActive: false, isCompleted: false }
        case "feishu_sync":
          return { summary: "多维表格线索同步", percent: 0, isActive: false, isCompleted: false }
        case "evaluating":
          return { summary: "八维多因子打分", percent: 0, isActive: false, isCompleted: false }
        case "deep_eval":
          return { summary: "A/B 级深度画像诊断", percent: 0, isActive: false, isCompleted: false }
        case "rewriting":
          return { summary: "定向定制精修简历", percent: 0, isActive: false, isCompleted: false }
        case "greeting":
          return { summary: "高情商开场白话术", percent: 0, isActive: false, isCompleted: false }
        case "review":
          return {
            summary: stageStats.pendingCount > 0 ? `${stageStats.pendingCount} 岗位待老板审批` : "老板人工审批断点",
            percent: stageStats.pendingCount > 0 ? 100 : 0,
            isActive: stageStats.pendingCount > 0,
            isCompleted: false,
          }
        case "delivering":
          return {
            summary: stageStats.deliveredCount > 0 ? `${stageStats.deliveredCount} 岗位已投递` : "平台白名单自动投递",
            percent: stageStats.deliveredCount > 0 ? 100 : 0,
            isActive: false,
            isCompleted: stageStats.deliveredCount > 0,
          }
        default:
          return { summary: "就绪", percent: 0, isActive: false, isCompleted: false }
      }
    }

    switch (key) {
      case "scraping": {
        const entries = Object.entries(scrapeProgress)
        const total = entries.length
        const done = entries.filter(([, p]) => p.total > 0 && p.current >= p.total).length
        const percent = total > 0 ? Math.round((done / total) * 100) : 0
        const isCurrent = currentStage === "scraping" && isOverallRunning
        const isDone = stageStatus.scraping === "done" || (total > 0 && done >= total)
        return {
          summary: entries.length === 0 ? "多平台抓取" : `${done}/${total} 平台抓取完毕`,
          percent,
          isActive: isCurrent,
          isCompleted: isDone,
        }
      }
      case "cleaning": {
        const total = hardCleanProgress?.total || 0
        const cur = hardCleanProgress?.current || 0
        const percent = total > 0 ? Math.round((cur / total) * 100) : 0
        const isCurrent = currentStage === "cleaning" && isOverallRunning
        const isDone = stageStatus.cleaning === "done" || (total > 0 && cur >= total)
        return {
          summary: cur === 0 ? "规则清洗与初筛" : `已初筛 ${cur}/${total} 岗位`,
          percent,
          isActive: isCurrent,
          isCompleted: isDone,
        }
      }
      case "feishu_sync": {
        const total = feishuSyncProgress?.total || 0
        const cur = feishuSyncProgress?.current || 0
        const percent = total > 0 ? Math.round((cur / total) * 100) : 0
        const isCurrent = currentStage === "feishu_sync" && isOverallRunning
        const isDone = stageStatus.feishu_sync === "done" || (total > 0 && cur >= total)
        return {
          summary: total > 0 ? `已写入 ${cur}/${total} 岗位` : "多维表格线索同步",
          percent,
          isActive: isCurrent,
          isCompleted: isDone,
        }
      }
      case "evaluating": {
        const total = stageStats.evalTotal
        const done = stageStats.evalDone
        const percent = total > 0 ? Math.round((done / total) * 100) : 0
        const isActive = stageStats.isEvaluatingRunning || (currentStage === "evaluating" && isOverallRunning)
        const isDone = stageStatus.evaluating === "done" || (total > 0 && done >= total)
        let summary = "八维多因子打分"
        if (total > 0 || done > 0) {
          summary = `已评估 ${done}/${total || done} 岗位`
        } else if (stageStatus.evaluating === "done") {
          summary = "已完成多维打分"
        }
        return { summary, percent, isActive, isCompleted: isDone }
      }
      case "deep_eval": {
        const total = stageStats.deepEvalTotal
        const done = stageStats.deepEvalDone
        const percent = total > 0 ? Math.round((done / total) * 100) : 0
        const isActive = stageStats.isDeepEvalRunning || (currentStage === "deep_eval" && isOverallRunning)
        const isDone = total > 0 && done >= total
        let summary = "A/B 级深度画像诊断"
        if (total > 0 || done > 0) {
          summary = `已诊断 ${done}/${total || done} 岗位`
        } else if (stageStatus.deep_eval === "done") {
          summary = "已完成画像诊断"
        }
        return { summary, percent, isActive, isCompleted: isDone }
      }
      case "rewriting": {
        const total = stageStats.rewriteTotal
        const done = stageStats.rewriteDone
        const percent = total > 0 ? Math.round((done / total) * 100) : 0
        const isActive = stageStats.isRewritingRunning || (currentStage === "rewriting" && isOverallRunning)
        const isDone = total > 0 && done >= total
        let summary = "定向定制精修简历"
        if (total > 0 || done > 0) {
          summary = `已改写 ${done}/${total || done} 份`
        } else if (stageStatus.rewriting === "done") {
          summary = "已生成定制简历"
        }
        return { summary, percent, isActive, isCompleted: isDone }
      }
      case "greeting": {
        const total = stageStats.greetingTotal
        const done = stageStats.greetingDone
        const percent = total > 0 ? Math.round((done / total) * 100) : 0
        const isActive = stageStats.isGreetingRunning || (currentStage === "greeting" && isOverallRunning)
        const isDone = total > 0 && done >= total
        let summary = "高情商开场白话术"
        if (total > 0 || done > 0) {
          summary = `已生成 ${done}/${total || done} 条`
        } else if (stageStatus.greeting === "done") {
          summary = "已生成招呼话术"
        }
        return { summary, percent, isActive, isCompleted: isDone }
      }
      case "review": {
        const count = stageStats.pendingCount
        const readyCount = stageStats.readyToDeliverCount
        const deliveredCount = stageStats.deliveredCount
        const isActive = count > 0
        const isDone = count === 0 && (readyCount > 0 || deliveredCount > 0)
        let summary = "老板人工审批断点"
        if (count > 0) {
          summary = `${count} 岗位待老板审批`
        } else if (readyCount > 0 || deliveredCount > 0) {
          summary = "审批已全部放行"
        }
        return {
          summary,
          // 待审批中不拉满进度条：100% + isCompleted=false 会渲染成绿色「已完成」观感，
          // 语义实为「全部汇齐、等老板动手」；汇齐即 100% 的信号由 isDone 唯一表达
          percent: isActive ? 60 : isDone ? 100 : 0,
          isActive,
          isCompleted: isDone,
        }
      }
      case "delivering": {
        const count = stageStats.deliveredCount
        const total = stageStats.readyToDeliverCount + count
        const percent = total > 0 ? Math.round((count / total) * 100) : (count > 0 ? 100 : 0)
        const isActive = stageStats.isDeliveringRunning || (currentStage === "delivering" && isOverallRunning)
        const isDone = (total > 0 && count >= total) || (stageStatus.delivering === "done" && count > 0)
        let summary = "平台白名单自动投递"
        if (total > 0) {
          summary = `已投递 ${count}/${total} 岗位`
        } else if (count > 0) {
          summary = `${count} 岗位已投递`
        }
        return {
          summary,
          percent,
          isActive,
          isCompleted: isDone,
        }
      }
      default:
        return { summary: "就绪", percent: 0, isActive: false, isCompleted: false }
    }
  }

  const unconfiguredRequired = STAGES_META.filter(
    (s) => s.requiredConfig && !configStatus[s.key]
  )

  return (
    <div id="pipeline-stepper-section" className="w-full rounded-2xl border border-border/80 bg-card p-4 shadow-sm space-y-3.5 transition-all">
      {/* 顶部标题与全链路基准简历全局选择器 */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-border/50 pb-3">
        <div className="flex items-center gap-2.5 flex-wrap">
          <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20 font-bold shrink-0">
            <Layers className="h-3.5 w-3.5" />
          </div>
          <h2 className="text-xs font-semibold text-foreground tracking-tight">
            全链路执行导轨
          </h2>

          {/* 规则配置就绪状态指示 */}
          {unconfiguredRequired.length > 0 ? (
            <div className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 px-2.5 py-1 text-[11px] font-medium text-amber-700 dark:text-amber-300">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0" />
              <span>待配置核心规则:</span>
              {unconfiguredRequired.map((s, idx) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => onOpenConfig(s.key)}
                  className="underline hover:text-amber-900 dark:hover:text-white font-bold ml-1 transition-colors"
                >
                  {s.label}{idx < unconfiguredRequired.length - 1 ? "、" : ""}
                </button>
              ))}
            </div>
          ) : (
            <div className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
              <CheckCircle2 className="h-3.5 w-3.5" />
              <span>全链路核心规则全部就绪</span>
            </div>
          )}

          {/* 重新探测刷新按钮 */}
          {onRefreshStatus && (
            <button
              type="button"
              onClick={onRefreshStatus}
              className="flex h-6 w-6 items-center justify-center rounded-md border border-border/70 bg-muted/40 text-muted-foreground transition-all hover:bg-muted hover:text-foreground active:scale-95 ml-1"
              title="点击即时重新探测全链路规则就绪状态"
            >
              <RefreshCw className={cn("h-3 w-3", isRefreshing && "animate-spin text-violet-500")} />
            </button>
          )}
        </div>

        {/* 🌟 全链路基准简历全局统一选择器 */}
        <ActiveResumeSelector />
      </div>

      {/* 9 阶段卡片网格 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-9 gap-2">
        {STAGES_META.map((stage, idx) => {
          const info = getStageInfo(stage.key)
          const isRequired = stage.requiredConfig
          const isConfigured = configStatus[stage.key]
          const isActive = info.isActive
          // 防御性访问：先提取值再比较，避免可选链与比较运算符的语法冲突
          const currentStageStatus = stageStatus[stage.key]
          const isDone = info.isCompleted || (pipelineStatus !== "idle" && currentStageStatus === "done")

          return (
            <div
              key={stage.key}
              onClick={() => onOpenConfig(stage.key)}
              className={cn(
                "group relative flex flex-col justify-between rounded-xl border p-3 cursor-pointer transition-all duration-200 hover:shadow-md active:scale-[0.98]",
                isActive
                  ? "border-violet-500/60 bg-violet-500/5 ring-2 ring-violet-500/20 shadow-sm"
                  : isDone
                  ? "border-emerald-500/30 bg-emerald-500/[0.02]"
                  : isRequired && !isConfigured
                  ? "border-amber-500/40 bg-amber-500/[0.02] hover:border-amber-500"
                  : "border-border/80 bg-card hover:bg-muted/30"
              )}
            >
              {/* 顶部：序号 + 标题 + 规则配置徽标 */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <div
                      className={cn(
                        "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-mono font-bold transition-colors",
                        isDone
                          ? "bg-emerald-500 text-white"
                          : isActive
                          ? "bg-violet-600 text-white animate-pulse"
                          : "bg-muted text-muted-foreground"
                      )}
                    >
                      {isDone ? <Check className="h-3 w-3" /> : idx + 1}
                    </div>
                    <span className="text-xs font-semibold text-foreground tracking-tight">
                      {stage.label}
                    </span>
                  </div>

                  <span className="text-sm">{stage.icon}</span>
                </div>

                {/* 规则配置状态标签（针对 4 大必配核心模块） */}
                {isRequired ? (
                  <div className="mb-2">
                    {isConfigured ? (
                      <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-medium bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                        <Check className="h-2.5 w-2.5" />
                        已配置规则
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30 animate-pulse">
                        <AlertTriangle className="h-2.5 w-2.5 text-amber-500" />
                        必配规则 (待配置)
                      </span>
                    )}
                  </div>
                ) : (
                  <div className="mb-2">
                    <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground bg-muted/50">
                      自动流转
                    </span>
                  </div>
                )}

                {/* 中部：状态简述与实时分子分母 */}
                <p className={cn(
                  "text-[11px] truncate mb-3 transition-colors",
                  isActive ? "text-violet-600 dark:text-violet-400 font-medium" : "text-muted-foreground"
                )}>
                  {info.summary}
                </p>
              </div>

              {/* 底部：实时进度指示条 */}
              <div className="h-1.5 w-full bg-muted/60 rounded-full overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-500",
                    isDone
                      ? "bg-emerald-500"
                      : isActive
                      ? "bg-violet-500 animate-pulse"
                      : info.percent > 0
                      ? "bg-violet-500/50"
                      : "bg-transparent"
                  )}
                  style={{
                    width: isDone ? "100%" : `${Math.max(info.percent, isActive ? 15 : 0)}%`,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
