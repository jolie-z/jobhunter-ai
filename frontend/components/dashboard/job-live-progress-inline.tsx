"use client"

import React, { useMemo } from "react"
import { Loader2, CheckCircle2, ChevronRight, Check } from "lucide-react"
import { cn } from "@/lib/utils"

export interface JobProgressInfo {
  subStage?: number
  totalStages?: number
  stageTitle?: string
  message?: string
  updatedAt?: number
}

interface JobLiveProgressInlineProps {
  taskType?: string
  progressInfo?: JobProgressInfo
  latestLog?: string
  className?: string
}

export function JobLiveProgressInline({
  taskType = "evaluate",
  progressInfo,
  latestLog,
  className,
}: JobLiveProgressInlineProps) {
  // 根据任务类型动态匹配 4 阶段标准业务流程
  const stages = useMemo(() => {
    if (taskType === "deep_evaluate") {
      return ["JD解析", "深度画像", "能力审计", "回写归档"]
    }
    if (taskType === "rewrite") {
      return ["母本对齐", "逐段重塑", "破冰招呼", "回写归档"]
    }
    if (taskType === "mass_apply") {
      return ["母本校验", "高清渲染", "招呼装配", "入队待投"]
    }
    if (taskType === "approve") {
      return ["物料校验", "高清渲染", "飞书归档", "放行待投"]
    }
    // 默认 evaluate 全链路波次
    return ["8维初评", "门禁打分", "深度画像", "定制改写"]
  }, [taskType])

  const currentStage = Math.max(1, Math.min(progressInfo?.subStage || 1, 4))
  const isCompleted =
    progressInfo?.subStage === 4 &&
    (progressInfo?.message?.includes("完成") ||
      progressInfo?.message?.includes("成功") ||
      progressInfo?.stageTitle?.includes("完成"))

  // 显示的动态日志文本
  const displayLog =
    progressInfo?.message ||
    latestLog ||
    progressInfo?.stageTitle ||
    "流水线自动流转中..."

  return (
    <div
      className={cn(
        "flex flex-col justify-center gap-1.5 w-full py-1.5 px-3 relative overflow-hidden",
        "bg-gradient-to-r from-blue-50/70 via-indigo-50/40 to-blue-50/70 dark:from-blue-950/20 dark:via-indigo-950/20 dark:to-blue-950/20",
        "border border-blue-200/70 dark:border-blue-800/40 rounded-xl shadow-2xs",
        "transition-all duration-300 animate-in fade-in select-none",
        className
      )}
    >
      {/* 顶栏微光流光 */}
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-blue-500/40 to-transparent animate-pulse" />

      {/* 上层：全景标准工序流水线胶囊 */}
      <div className="flex items-center justify-between gap-1 w-full">
        {stages.map((label, idx) => {
          const stepNum = idx + 1
          const isPassed = stepNum < currentStage || (stepNum === 4 && isCompleted)
          const isCurrent = stepNum === currentStage && !isCompleted

          return (
            <React.Fragment key={label}>
              <div
                className={cn(
                  "inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium tracking-tight transition-all duration-300 shrink-0",
                  isPassed
                    ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 font-semibold"
                    : isCurrent
                    ? "bg-blue-600 text-white shadow-xs font-semibold ring-1 ring-blue-400/40"
                    : "bg-blue-100/60 text-blue-800/80 dark:bg-blue-900/30 dark:text-blue-200/80"
                )}
              >
                {isPassed ? (
                  <Check className="size-2.5 stroke-[3] text-emerald-600 dark:text-emerald-400 shrink-0" />
                ) : null}
                <span>{label}</span>
              </div>

              {/* 连线箭头 */}
              {idx < stages.length - 1 && (
                <ChevronRight className="size-2.5 text-blue-400/60 shrink-0 mx-0.5" />
              )}
            </React.Fragment>
          )
        })}
      </div>

      {/* 下层：当前微观执行状态与动态日志 */}
      <div className="flex items-center justify-between gap-2 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          {isCompleted ? (
            <CheckCircle2 className="size-3 text-emerald-600 shrink-0" />
          ) : (
            <Loader2 className="size-3 text-blue-600 animate-spin shrink-0" />
          )}
          <span
            className={cn(
              "text-[11px] truncate font-medium",
              isCompleted ? "text-emerald-700 font-semibold" : "text-slate-700 dark:text-slate-200"
            )}
            title={displayLog}
          >
            {displayLog}
          </span>
        </div>

        <span className="text-[9px] font-mono text-blue-600/80 dark:text-blue-300 bg-blue-100/50 dark:bg-blue-900/40 px-1.5 py-0.5 rounded shrink-0">
          {isCompleted ? "已就绪" : "流转中"}
        </span>
      </div>
    </div>
  )
}
