"use client"

import { useState, useEffect, useRef } from "react"
import Link from "next/link"
import {
  Zap,
  Play,
  Square,
  ArrowLeft,
  Clock,
  Calendar,
  Sparkles,
  Settings2,
  RefreshCw,
  AlertTriangle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { usePipelineStore } from "@/store/pipeline-store"
import { STAGES_META, StageKey } from "./types"
import { API_BASE } from "@/lib/api"
import { useSchedulePanel } from "./use-schedule-panel"

interface CommandHeaderProps {
  allConfigured: boolean
  configStatus: Record<string, boolean>
  onOpenConfig?: (stageKey: StageKey) => void
}

// 双执行模式：手动即时（点按钮立即跑）+ 每日定时调度（后端 APScheduler 真实生效，保存即热更新）
export function CommandHeader({
  allConfigured,
  configStatus,
  onOpenConfig,
}: CommandHeaderProps) {
  const [starting, setStarting] = useState(false)
  const [aborting, setAborting] = useState(false)
  const [abortMsg, setAbortMsg] = useState("")
  
  // 统一管理所有定时器
  const timersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())

  // 执行模式与每日定时调度（读自后端 autopilot 配置，真实持久化）

  // 节假日数据（chinese-calendar）覆盖状态与一键更新

  const pipelineStatus = usePipelineStore((s) => s.status)
  const currentStage = usePipelineStore((s) => s.currentStage)
  const pipelineTaskId = usePipelineStore((s) => s.pipelineTaskId)
  const startPipeline = usePipelineStore((s) => s.startPipeline)

  // 每日定时调度面板（Q10 拆分批次 1 抽离至 use-schedule-panel.ts）
  const {
    mode, setMode, dailyTime, setDailyTime, scheduledEnabled, setScheduledEnabled,
    startDate, setStartDate, endDate, setEndDate, skipNonWorkdays, setSkipNonWorkdays,
    savingSchedule, scheduleMsg, holidayStatus, updatingHoliday,
    showHolidayUpdate, handleUpdateHolidayData, handleSaveSchedule,
  } = useSchedulePanel()

  // Token 消耗统计
  const [tokenStats, setTokenStats] = useState<{
    today_tokens: number
    month_tokens: number
    total_tokens: number
    today_cost_cny: number
  } | null>(null)

  const [isLoading, setIsLoading] = useState(true)
  const [configError, setConfigError] = useState<string | null>(null)

  // Token 消耗统计拉取（定时配置与节假日已移入 use-schedule-panel）
  useEffect(() => {
    setIsLoading(true)
    setConfigError(null)
    
    fetch(`${API_BASE}/api/analytics/tokens`).then(r => r.json()).then((tokenRes) => {
      if (tokenRes.code === 0 && tokenRes.data) setTokenStats(tokenRes.data)
      setIsLoading(false)
    }).catch(() => {
      setConfigError("加载配置失败")
      setIsLoading(false)
    })
  }, [])

  useEffect(() => {
    return () => {
      // 清理所有定时器
      timersRef.current.forEach(timer => clearTimeout(timer))
      timersRef.current.clear()
    }
  }, [])

  // 启动全链路
  const handleStart = async () => {
    if (!allConfigured) {
      const missing = STAGES_META.filter((s) => s.requiredConfig && !configStatus[s.key])
      if (missing.length > 0) {
        // 门禁拦截必须有声：静默 return 曾让新机用户误以为"代码没跑/没 push"（0926 排查教训）。
        // 名称列表截断展示，防 9 项全缺时撑爆 toast；「等 N 项」指前 3 项之外的剩余数量。
        const names = missing.map((s) => s.label)
        const shown = names.slice(0, 3).join(" / ")
        const restCount = names.length - 3
        const suffix = restCount > 0 ? ` 等 ${restCount} 项` : ""
        toast.warning(`有 ${names.length} 项配置未完成（${shown}${suffix}），已打开第一个配置面板`)
        if (onOpenConfig) {
          onOpenConfig(missing[0].key)
        }
        // 平滑滚动至执行导轨
        const el = document.getElementById("pipeline-stepper-section")
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" })
        }
      }
      return
    }
    if (pipelineStatus === "running" || starting) return
    setStarting(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/trigger`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      })
      const data = await res.json()
      if (res.ok && data.pipeline_task_id) {
        startPipeline(data.pipeline_task_id)
      } else {
        toast.error("启动失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      toast.error("启动失败：无法连接后端服务")
    } finally {
      setStarting(false)
    }
  }

  // 终止任务
  const handleAbort = async () => {
    if (aborting) return
    if (!window.confirm("确定终止本次全链路任务？\n各平台爬虫与状态机将在安全点收尾，并生成执行报告。")) return
    setAborting(true)
    setAbortMsg("")
    try {
      const res = await fetch(`${API_BASE}/api/automation/abort`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: pipelineTaskId || "" }),
      })
      const data = await res.json()
      if (res.ok) {
        setAbortMsg(data.message || "终止指令已下达")
        const timer = setTimeout(() => setAbortMsg(""), 5000)
        timersRef.current.add(timer)
      } else {
        setAbortMsg("终止失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      setAbortMsg("终止失败：网络异常")
    } finally {
      setAborting(false)
      // timersRef.current 已在 res.ok 分支添加，此处无需重复清理
    }
  }

  const currentStageLabel = STAGES_META.find((s) => s.key === currentStage)?.label || currentStage
  const missingConfigs = STAGES_META.filter((s) => s.requiredConfig && !configStatus[s.key])

  return (
    <header className="sticky top-0 z-30 w-full border-b border-border/60 bg-background/95 backdrop-blur-xl transition-all">
      <div className="flex h-16 items-center justify-between px-6 gap-4">
        {/* 左侧：Logo & 返回主页 */}
        <div className="flex items-center gap-3.5 shrink-0">
          <Link
            href="/"
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-border/80 bg-muted/40 text-muted-foreground transition-all hover:bg-muted hover:text-foreground active:scale-95"
            title="返回沉浸工作台"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>

          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-violet-600 to-indigo-600 shadow-md shadow-violet-500/20 text-white">
              <Zap className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-sm font-semibold tracking-tight text-foreground">
                  全链路指挥中心
                </h1>
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium border transition-colors",
                    pipelineStatus === "running"
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                      : pipelineStatus === "done"
                        ? "border-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-400"
                        : pipelineStatus === "error"
                          ? "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
                          : "border-border bg-muted/50 text-muted-foreground"
                  )}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      pipelineStatus === "running"
                        ? "bg-emerald-500 animate-pulse"
                        : pipelineStatus === "done"
                          ? "bg-blue-500"
                          : pipelineStatus === "error"
                            ? "bg-red-500"
                            : "bg-muted-foreground/50"
                    )}
                  />
                  {pipelineStatus === "running"
                    ? `正在执行: ${currentStageLabel}`
                    : pipelineStatus === "done"
                      ? "任务完成 · 待命"
                      : pipelineStatus === "error"
                        ? "任务异常 · 请查看日志"
                        : "就绪"}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Auto-JobHunter Agentic Orchestrator
              </p>
            </div>
          </div>
        </div>

        {/* 中间：执行模式双通道切换 */}
        <div className="flex items-center gap-1.5 rounded-xl border border-border/80 bg-muted/30 p-1">
          <button
            onClick={() => setMode("immediate")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-all",
              mode === "immediate"
                ? "bg-background text-foreground shadow-sm shadow-black/5 font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Play className="h-3.5 w-3.5 text-violet-500" />
            手动即时模式
          </button>
          <button
            onClick={() => setMode("scheduled")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-all",
              mode === "scheduled"
                ? "bg-background text-foreground shadow-sm shadow-black/5 font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Clock className="h-3.5 w-3.5 text-amber-500" />
            每日定时调度
          </button>
        </div>

        {/* 右侧：操作区 & 状态指示 */}
        <div className="flex items-center gap-3">

          {/* Token 消耗浮窗 */}
          {tokenStats && (
            <div
              className="hidden lg:flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-2.5 py-1 text-[11px] text-amber-700 dark:text-amber-300"
              title={`今日 Token: ${tokenStats.today_tokens.toLocaleString()} | 估算: ¥${tokenStats.today_cost_cny.toFixed(2)}`}
            >
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              <span>今日 Token: {tokenStats.today_tokens.toLocaleString()}</span>
            </div>
          )}

          {/* 启动 / 终止按钮 */}
          {pipelineStatus === "running" ? (
            <button
              onClick={handleAbort}
              disabled={aborting}
              className="flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-3.5 py-1.5 text-xs font-medium text-red-600 transition-all hover:bg-red-500/20 active:scale-95 disabled:opacity-50"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
              {aborting ? "终止中…" : "终止任务"}
            </button>
          ) : (
            <button
              onClick={handleStart}
              disabled={starting}
              className={cn(
                "flex items-center gap-2 rounded-lg px-4 py-1.5 text-xs font-medium text-white shadow-sm transition-all active:scale-95",
                allConfigured
                  ? "bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 shadow-violet-500/25"
                  : "bg-amber-600 hover:bg-amber-500 cursor-pointer shadow-amber-500/25"
              )}
              title={allConfigured ? "启动全链路任务" : `点击立即配置未就绪规则: ${missingConfigs.map((s) => s.label).join("、")}`}
            >
              {allConfigured ? <Play className="h-3.5 w-3.5 fill-current" /> : <Settings2 className="h-3.5 w-3.5" />}
              {starting ? "启动中…" : allConfigured ? "启动全链路" : `待配置规则 (${missingConfigs.length})`}
            </button>
          )}

          {abortMsg && (
            <span className="text-[11px] font-medium text-red-500 animate-fade-in">
              {abortMsg}
            </span>
          )}
        </div>
      </div>

      {/* 节假日数据提醒横幅：仅在每日定时调度模式下显示；包缺失随时提醒，下一年安排未收录则 12 月透出一键更新 */}
      {mode === "scheduled" && showHolidayUpdate && holidayStatus && (
        <div className="flex items-center justify-between gap-3 border-t border-amber-500/25 bg-amber-500/[0.07] px-6 py-2 text-xs animate-in slide-in-from-top-1 duration-200">
          <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>
              {!holidayStatus.installed
                ? "后端环境未安装节假日数据包（chinese-calendar），跳过周末与节假日功能未生效"
                : holidayStatus.stale_critical
                  ? `节假日数据仅覆盖至 ${holidayStatus.covered_year} 年，已无法覆盖今年 —— 跳过逻辑退化为只跳周末，周中法定节假日不会拦截`
                  : `国务院已发布 ${holidayStatus.next_year} 年放假安排，更新后定时任务才能正确跳过明年的节假日与调休补班`}
            </span>
          </div>
          <button
            onClick={handleUpdateHolidayData}
            disabled={updatingHoliday}
            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1 text-[11px] font-medium text-amber-700 transition-all hover:bg-amber-500/25 active:scale-95 disabled:opacity-50 dark:text-amber-300"
          >
            <RefreshCw className={cn("h-3 w-3", updatingHoliday && "animate-spin")} />
            {updatingHoliday ? "更新中…" : holidayStatus.installed ? `更新 ${holidayStatus.next_year} 年节假日数据` : "安装节假日数据包"}
          </button>
        </div>
      )}

      {/* 定时配置展开栏（真实后端：cron_time + 总开关，保存即热更新 APScheduler） */}
      {mode === "scheduled" && (
        <div className="flex items-center justify-between gap-4 border-t border-border/40 bg-amber-500/[0.02] px-6 py-2.5 text-xs text-muted-foreground animate-in slide-in-from-top-1 duration-200">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5 text-amber-500" />
              <span>周期范围:</span>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="rounded border border-border/80 bg-background px-2 py-0.5 text-xs font-mono text-foreground"
                title="留空 = 不限开始日期"
              />
              <span>至</span>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="rounded border border-border/80 bg-background px-2 py-0.5 text-xs font-mono text-foreground"
                title="留空 = 不限结束日期"
              />
            </div>

            <div className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-amber-500" />
              <span>每日执行时间:</span>
              <input
                type="time"
                value={dailyTime}
                onChange={(e) => setDailyTime(e.target.value)}
                className="rounded border border-border/80 bg-background px-2 py-0.5 text-xs font-mono text-foreground"
              />
            </div>

            <label
              className="flex items-center gap-1.5 cursor-pointer select-none"
              title="周末与法定节假日 HR 不在岗，自动跳过采集与发射；调休补班的周六日照常执行"
            >
              <input
                type="checkbox"
                checked={skipNonWorkdays}
                onChange={(e) => setSkipNonWorkdays(e.target.checked)}
                className="h-3.5 w-3.5 accent-amber-500 cursor-pointer"
              />
              <span className={skipNonWorkdays ? "text-foreground" : ""}>跳过周末与节假日</span>
            </label>

            <div className="flex items-center gap-1.5">
              <span className="text-[11px]">定时开关:</span>
              <button
                onClick={() => setScheduledEnabled(!scheduledEnabled)}
                className={cn(
                  "relative h-5 w-9 rounded-full transition-colors",
                  scheduledEnabled ? "bg-amber-500" : "bg-muted"
                )}
              >
                <span
                  className={cn(
                    "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform shadow-sm",
                    scheduledEnabled ? "left-[18px]" : "left-0.5"
                  )}
                />
              </button>
              <span className={cn("text-[11px]", scheduledEnabled ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground")}>
                {scheduledEnabled
                  ? `开启 · 每天 ${dailyTime} 采集评估（停在待审批，投递由发射时间控制）`
                  : "已关闭"}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2.5 shrink-0">
            {scheduleMsg && (
              <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                {scheduleMsg}
              </span>
            )}
            <button
              onClick={handleSaveSchedule}
              disabled={savingSchedule}
              className="flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-[11px] font-medium text-amber-700 dark:text-amber-300 transition-all hover:bg-amber-500/20 active:scale-95 disabled:opacity-50"
            >
              <Clock className="h-3 w-3" />
              {savingSchedule ? "保存中…" : "保存定时配置"}
            </button>
          </div>
        </div>
      )}
    </header>
  )
}
