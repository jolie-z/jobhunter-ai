"use client"

import React, { useMemo, useEffect, useState } from "react"
import { Loader2, CheckCircle2, AlertTriangle, Terminal, X } from "lucide-react"
import { useGlobalTerminalStore } from "@/store/global-terminal-store"
import type { JobData } from "@/types/job"

interface GlobalTaskActivityBarProps {
  globalTaskStatus: "idle" | "running" | "completed" | "interrupted"
  processingJobs: Record<string, string>
  jobLiveLogs: Record<string, string[]>
  jobs: JobData[]
  onDismiss?: () => void
}

const TASK_LABEL_MAP: Record<string, string> = {
  evaluate: "8维初评",
  deep_eval: "深度评估",
  deep_evaluate: "深度评估",
  rewrite: "定制改写",
  greeting: "打招呼语",
  wave_pipeline: "三波次流水线",
  mass_apply: "一键海投",
}

export function GlobalTaskActivityBar({
  globalTaskStatus,
  processingJobs,
  jobLiveLogs,
  jobs,
  onDismiss,
}: GlobalTaskActivityBarProps) {
  const setOpenTerminal = useGlobalTerminalStore((state) => state.setOpen)
  const [visible, setVisible] = useState(false)
  const [fadeExit, setFadeExit] = useState(false)

  const activeJobIds = useMemo(() => Object.keys(processingJobs), [processingJobs])
  const isRunning = globalTaskStatus === "running" || activeJobIds.length > 0
  const isCompleted = globalTaskStatus === "completed"
  const isInterrupted = globalTaskStatus === "interrupted"

  // 记录一次批量任务的最大总量，以便计算真实进度条比例
  const [maxJobCount, setMaxJobCount] = useState(1)

  useEffect(() => {
    if (activeJobIds.length > maxJobCount) {
      setMaxJobCount(activeJobIds.length)
    }
    if (isRunning) {
      setVisible(true)
      setFadeExit(false)
    } else if (isCompleted) {
      setVisible(true)
      const timer = setTimeout(() => {
        setFadeExit(true)
        setTimeout(() => {
          setVisible(false)
          setMaxJobCount(1)
        }, 300)
      }, 3500)
      return () => clearTimeout(timer)
    } else if (isInterrupted) {
      setVisible(true)
    } else {
      setVisible(false)
      setMaxJobCount(1)
    }
  }, [isRunning, isCompleted, isInterrupted, activeJobIds.length])

  // 提取当前正在活跃处理的岗位及最新一条日志
  const currentActiveInfo = useMemo(() => {
    // 优先寻找有最新日志的正在处理岗位
    let currentId = activeJobIds[0] || ""
    let latestLog = ""
    let currentStep = 1
    let totalStep = Math.max(maxJobCount, 1)

    for (const id of activeJobIds) {
      const logs = jobLiveLogs[id]
      if (logs && logs.length > 0) {
        currentId = id
        latestLog = logs[logs.length - 1]
        // 尝试从日志中解析类似 "正在处理 2/5" 或 "[2/4]"
        const fractionMatch = latestLog.match(/(?:正在处理\s*)?(\d+)\s*[\/之]\s*(\d+)/)
        if (fractionMatch) {
          currentStep = parseInt(fractionMatch[1], 10)
          totalStep = parseInt(fractionMatch[2], 10)
        }
        break
      }
    }

    if (!latestLog && currentId) {
      latestLog = "正在等待后台流水线调度..."
    }

    // 从全局列表中反查真实企业名与岗位名
    let displayTarget = "目标岗位"
    if (currentId) {
      const cleanId = currentId.split("-").pop() || currentId
      const targetJob = jobs.find(
        (j) => j.id === currentId || j.id.endsWith(cleanId) || (cleanId && j.id.includes(cleanId))
      )
      if (targetJob) {
        displayTarget = `${targetJob.companyName} · ${targetJob.jobTitle}`
      } else {
        displayTarget = `职位 ${cleanId.slice(0, 8)}...`
      }
    }

    const currentTaskType = processingJobs[currentId] || "evaluate"
    const phaseLabel = TASK_LABEL_MAP[currentTaskType] || "AI 处理"

    // 规整当前进度百分比
    const pct = Math.min(100, Math.max(10, Math.round((currentStep / totalStep) * 100)))

    // 清洗机器日志中的多余机器 ID 前缀
    const cleanLog = latestLog
      .replace(/^正在处理\s*\d+\/\d+[:：]\s*[a-zA-Z0-9_\-\.]+[\s\.]*/, "")
      .replace(/^\[\d+\/\d+\]\s*/, "")
      .trim() || latestLog

    return {
      currentId,
      displayTarget,
      phaseLabel,
      currentStep,
      totalStep,
      percent: pct,
      logText: cleanLog,
    }
  }, [activeJobIds, jobLiveLogs, jobs, processingJobs, maxJobCount])

  if (!visible) return null

  return (
    <aside
      className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-40 w-[440px] max-w-[calc(100vw-32px)] rounded-2xl bg-zinc-950/92 dark:bg-zinc-900/95 text-white shadow-2xl border border-zinc-800/80 backdrop-blur-md px-4 py-3 flex flex-col gap-2.5 transition-all duration-300 ${
        fadeExit ? "opacity-0 translate-y-2 scale-95" : "opacity-100 translate-y-0 scale-100 animate-in fade-in slide-in-from-bottom-4"
      }`}
      role="status"
      aria-live="polite"
    >
      {isCompleted ? (
        <div className="flex items-center justify-between py-0.5">
          <div className="flex items-center gap-2">
            <span className="flex size-5 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400">
              <CheckCircle2 className="size-3.5" />
            </span>
            <span className="text-xs font-semibold text-emerald-300">
              所有选定岗位已全部完成 AI 评估与处理
            </span>
          </div>
          <button
            onClick={() => setOpenTerminal(true)}
            className="flex items-center gap-1 text-[10px] font-mono text-zinc-400 hover:text-zinc-200 bg-zinc-800/80 px-2 py-1 rounded transition-colors"
          >
            <Terminal className="size-3" />
            <span>日志 ⌘J</span>
          </button>
        </div>
      ) : isInterrupted ? (
        <div className="flex items-center justify-between py-0.5">
          <div className="flex items-center gap-2">
            <span className="flex size-5 items-center justify-center rounded-full bg-amber-500/20 text-amber-400">
              <AlertTriangle className="size-3.5" />
            </span>
            <span className="text-xs font-semibold text-amber-300">
              后台服务连接曾中断，可点击单卡片重试
            </span>
          </div>
          <button
            onClick={() => {
              setFadeExit(true)
              setTimeout(() => setVisible(false), 300)
              onDismiss?.()
            }}
            className="text-zinc-400 hover:text-zinc-200 p-0.5"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ) : (
        <>
          {/* 顶栏：运行态指示 + 阶段胶囊 + 进度比例 + 终端快捷入口 */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="relative flex size-2 shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full size-2 bg-blue-500" />
              </span>
              <span className="text-xs font-semibold text-zinc-100 shrink-0">AI 任务流处理中</span>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/20 text-blue-300 border border-blue-500/30 truncate">
                {currentActiveInfo.phaseLabel}
              </span>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <span className="text-[11px] font-mono font-medium text-zinc-300">
                {currentActiveInfo.currentStep}/{currentActiveInfo.totalStep}
                <span className="text-zinc-500 ml-1">({currentActiveInfo.percent}%)</span>
              </span>
              <button
                onClick={() => setOpenTerminal(true)}
                className="flex items-center gap-1 text-[10px] font-mono text-zinc-300 hover:text-white bg-zinc-800/90 hover:bg-zinc-700/90 px-2 py-0.5 rounded transition-all shadow-xs border border-zinc-700/50"
                title="点击呼出白盒终端 (快捷键 ⌘J)"
              >
                <Terminal className="size-3" />
                <span>⌘J</span>
              </button>
            </div>
          </div>

          {/* 中栏：平滑渐变流光细进度条 */}
          <div className="h-1.5 w-full bg-zinc-800/90 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-500 via-indigo-400 to-violet-500 transition-all duration-300 rounded-full"
              style={{ width: `${currentActiveInfo.percent}%` }}
            />
          </div>

          {/* 底栏：真实公司岗位名 + 细粒度微进度日志 */}
          <div className="flex items-center gap-2 text-[11px] min-w-0 text-zinc-400 leading-none">
            <Loader2 className="size-3 animate-spin text-blue-400 shrink-0" />
            <span
              className="font-semibold text-blue-200 truncate max-w-[170px] shrink-0"
              title={currentActiveInfo.displayTarget}
            >
              {currentActiveInfo.displayTarget}
            </span>
            <span className="text-zinc-600 shrink-0">·</span>
            <span
              className="text-zinc-300/90 truncate flex-1 font-mono text-[10.5px]"
              title={currentActiveInfo.logText}
            >
              {currentActiveInfo.logText}
            </span>
          </div>
        </>
      )}
    </aside>
  )
}
