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
import { resumeBlockedTask, terminateBlockedTask } from "@/store/blocked-task-actions"
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
  // 终止后对账窗口（0928 事故修复）：后端确认无运行中协程即复位本地 running 态
  const [abortPending, setAbortPending] = useState(false)
  const componentAliveRef = useRef(true)
  useEffect(() => {
    componentAliveRef.current = true
    return () => { componentAliveRef.current = false }
  }, [])

  // 统一管理所有定时器
  const timersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())

  // 执行模式与每日定时调度（读自后端 autopilot 配置，真实持久化）

  // 节假日数据（chinese-calendar）覆盖状态与一键更新

  const pipelineStatus = usePipelineStore((s) => s.status)
  const currentStage = usePipelineStore((s) => s.currentStage)
  const startPipeline = usePipelineStore((s) => s.startPipeline)

  // 每日定时调度面板（Q10 拆分批次 1 抽离至 use-schedule-panel.ts）
  const {
    mode, setMode, dailyTime, setDailyTime, scheduledEnabled, setScheduledEnabled,
    scheduleLoadFailed, retryLoadSchedule,
    startDate, setStartDate, endDate, setEndDate, skipNonWorkdays, setSkipNonWorkdays,
    savingSchedule, scheduleMsg, holidayStatus, updatingHoliday,
    showHolidayUpdate, handleUpdateHolidayData, handleSaveSchedule,
  } = useSchedulePanel()
  const scheduleLoading = scheduledEnabled === null

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

  // 启动全链路（2026-11-05 双击确认防误触）：全链路是分钟级真实动作面（抓取→评估→
  // 投递），单击即发射对焦点键盘激活（回车/空格触发 click，无鼠标痕迹）/触控板误触
  // 形同虚设——后端 confirm 守卫由本函数代填，拦不住"合法但非本意"的请求。改为
  // 两段式：首击进入待确认态（按钮变「再次点击确认」），400ms~5s 窗口内的二击才
  // 真正发射，超时自动回退。键盘长按 repeat（<400ms 连击）与超 5s 的滞后二击均被滤除。
  const [startConfirming, setStartConfirming] = useState(false)
  const startConfirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const startConfirmAtRef = useRef(0)
  useEffect(() => () => {
    if (startConfirmTimerRef.current) clearTimeout(startConfirmTimerRef.current)
  }, [])

  const resetStartConfirm = () => {
    setStartConfirming(false)
    startConfirmAtRef.current = 0
    if (startConfirmTimerRef.current) {
      clearTimeout(startConfirmTimerRef.current)
      startConfirmTimerRef.current = null
    }
  }

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
    if (pipelineStatus === "running" || pipelineStatus === "blocked" || starting) return
    // 第一击：进入待确认态；5 秒无二击自动回退（误触单发就此终结）
    if (!startConfirming) {
      setStartConfirming(true)
      startConfirmAtRef.current = Date.now()
      if (startConfirmTimerRef.current) clearTimeout(startConfirmTimerRef.current)
      startConfirmTimerRef.current = setTimeout(resetStartConfirm, 5000)
      return
    }
    // 二击最小间隔守卫（R1-P2）：键盘长按 repeat 可在百毫秒内连发两次 click，
    // 间隔 <400ms 的「二击」按机器节奏处理——视为 repeat 噪音，忽略但不退出待确认态
    if (Date.now() - startConfirmAtRef.current < 400) return
    resetStartConfirm()
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

  // 继续任务（blocked 态主按钮）：与阻塞横幅共用同一入口（blocked-task-actions），
  // 受理后横幅转进行时态、SSE 重连（含刷新恢复场景的 pipelineTaskId 补建）
  const [resuming, setResuming] = useState(false)
  const handleResume = async () => {
    if (resuming) return
    setResuming(true)
    try {
      await resumeBlockedTask()
    } finally {
      setResuming(false)
    }
  }

  // 终止阻塞任务：链路已收尾（无运行中协程），此处是放弃继续这条链路的显式出口
  const handleTerminateBlocked = () => {
    if (!window.confirm(
      "确定终止并关闭该阻塞任务？\n剩余「待AI初筛」岗位将保留在清洗池，可稍后在清洗面板手动重跑 AI 排雷。"
    )) return
    terminateBlockedTask()
  }

  // 终止后对账（0928 事故修复）：轮询后端 current-pipeline，确认协程已不存在即复位本地
  // running 态——防「幽灵任务」（后端重启/崩溃后无协程、永远等不到 SSE end）把界面永久
  // 卡在 running。绑定发起终止时的 taskId：SSE end 先到或用户已开新任务即短路，绝不误洗新任务。
  const reconcileAfterAbort = async (abortedTaskId: string) => {
    for (let i = 0; i < 10; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      if (!componentAliveRef.current) return
      const snapshot = usePipelineStore.getState()
      if (snapshot.status !== "running" || snapshot.pipelineTaskId !== abortedTaskId) {
        setAbortPending(false)
        return
      }
      try {
        const res = await fetch(`${API_BASE}/api/automation/current-pipeline`)
        const data = await res.json()
        // data 缺失/data:null = 后端无运行任务，与 running:false 同义（防御式，code-review R1-P1）
        if (res.ok && (!data?.data || data?.data?.running === false)) {
          // 复位前必须取 fetch 后的新鲜快照：fetch 期间 SSE end 可能已到达（code-review R2-P2 不采纳，正确性优先）
          const latest = usePipelineStore.getState()
          if (latest.status === "running" && latest.pipelineTaskId === abortedTaskId) {
            usePipelineStore.getState().reset()
            toast.success("后端已确认无运行中任务，界面已复位")
          }
          setAbortPending(false)
          return
        }
      } catch {
        // 网络抖动：继续重试
      }
    }
    if (!componentAliveRef.current) return
    setAbortPending(false)
    toast.error("后端任务收尾超时，请稍后刷新页面核对实际状态")
  }

  // 终止任务
  const handleAbort = async () => {
    if (aborting || abortPending) return
    if (!window.confirm("确定终止本次全链路任务？\n各平台爬虫与状态机将在安全点收尾，并生成执行报告。")) return
    setAborting(true)
    setAbortMsg("")
    try {
      // 终止静默失效根治①（2026-10-23 工单）：不信任 store 的 pipelineTaskId——
      // 页面长开可能持有上一轮僵尸 ID，后端按 ID 精确匹配会静默忽略。先取后端权威运行 ID
      let authoritativeId = ""
      try {
        const curRes = await fetch(`${API_BASE}/api/automation/current-pipeline`)
        if (!curRes.ok) throw new Error(`HTTP ${curRes.status}`)
        const curData = await curRes.json()
        if (curData?.data?.running !== true) {
          toast.error("当前无运行中的全链路任务，终止未下达")
          setAbortMsg("当前无运行中的全链路任务")
          return
        }
        authoritativeId = String(curData?.data?.task_id || "")
      } catch {
        toast.error("无法获取当前任务状态，终止未下达（请检查后端连接）")
        setAbortMsg("终止未下达：无法确认运行中任务")
        return
      }
      const res = await fetch(`${API_BASE}/api/automation/abort`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: authoritativeId }),
      })
      const data = await res.json()
      if (res.ok && data?.aborted !== false) {
        setAbortMsg(data.message || "终止指令已下达")
        const timer = setTimeout(() => setAbortMsg(""), 5000)
        timersRef.current.add(timer)
        // 指令已被后端受理：进入对账窗口（非静默重置，SSE end 仍是第一复位来源）。
        // 对账用后端响应的实际 task_id——后端对 ID 不匹配已降级终止当前登记任务，
        // 实际终止对象可能与本地 store 持有的 ID 不同
        setAbortPending(true)
        void reconcileAfterAbort(data?.task_id || authoritativeId)
      } else {
        // 终止静默失效根治②：失败必须显式报错并复位按钮，禁止当成功处理。
        // 红字不设自动清除（成功路径才 5 秒淡出）——错误需持续可见直至用户下一步操作
        const reason = data?.detail || data?.message || `HTTP ${res.status}`
        toast.error(`终止未生效：${reason}`)
        setAbortMsg(`终止未生效：${reason}`)
      }
    } catch {
      toast.error("终止失败：网络异常")
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
                      : pipelineStatus === "blocked"
                        ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
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
                        : pipelineStatus === "blocked"
                          ? "bg-amber-500 animate-pulse"
                          : pipelineStatus === "done"
                            ? "bg-blue-500"
                            : pipelineStatus === "error"
                              ? "bg-red-500"
                              : "bg-muted-foreground/50"
                    )}
                  />
                  {pipelineStatus === "running"
                    ? `正在执行: ${currentStageLabel}`
                    : pipelineStatus === "blocked"
                      ? "已暂停 · LLM 异常"
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

          {/* 启动 / 终止 / 继续按钮 */}
          {pipelineStatus === "running" ? (
            <button
              onClick={handleAbort}
              disabled={aborting || abortPending}
              className="flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-3.5 py-1.5 text-xs font-medium text-red-600 transition-all hover:bg-red-500/20 active:scale-95 disabled:opacity-50"
              title={abortPending ? "终止指令已受理，正在等待后端收尾/对账" : "终止本次全链路任务"}
            >
              <Square className="h-3.5 w-3.5 fill-current" />
              {aborting || abortPending ? "终止中…" : "终止任务"}
            </button>
          ) : pipelineStatus === "blocked" ? (
            // 阻塞态：主按钮转「继续任务」，旁边保留小的终止入口——
            // 绝不能出现「任务完成但按钮又能重新启动」的误导组合
            <div className="flex items-center gap-2">
              <button
                onClick={handleResume}
                disabled={resuming}
                className="flex items-center gap-1.5 rounded-lg bg-amber-600 px-3.5 py-1.5 text-xs font-medium text-white shadow-sm shadow-amber-500/25 transition-all hover:bg-amber-500 active:scale-95 disabled:opacity-50"
                title="重新评估遗留的待AI初筛岗位，并继续飞书推送等后续链路"
              >
                <Play className="h-3.5 w-3.5 fill-current" />
                {resuming ? "启动中…" : "继续任务"}
              </button>
              <button
                onClick={handleTerminateBlocked}
                className="flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1.5 text-xs font-medium text-red-600 transition-all hover:bg-red-500/20 active:scale-95"
                title="放弃继续这条链路（遗留岗位保留在清洗池）"
              >
                <Square className="h-3 w-3 fill-current" />
                终止
              </button>
            </div>
          ) : (
            <button
              onClick={handleStart}
              disabled={starting}
              className={cn(
                "flex items-center gap-2 rounded-lg px-4 py-1.5 text-xs font-medium text-white shadow-sm transition-all active:scale-95",
                startConfirming
                  ? "bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-500 hover:to-red-500 shadow-red-500/25 animate-pulse"
                  : allConfigured
                    ? "bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 shadow-violet-500/25"
                    : "bg-amber-600 hover:bg-amber-500 cursor-pointer shadow-amber-500/25"
              )}
              title={startConfirming
                ? "5 秒内再次点击确认启动（误触保护）"
                : allConfigured
                  ? "启动全链路任务（需点击两次确认）"
                  : `点击立即配置未就绪规则: ${missingConfigs.map((s) => s.label).join("、")}`}
            >
              {allConfigured ? <Play className="h-3.5 w-3.5 fill-current" /> : <Settings2 className="h-3.5 w-3.5" />}
              {starting
                ? "启动中…"
                : startConfirming
                  ? "再次点击确认启动"
                  : allConfigured
                    ? "启动全链路"
                    : `待配置规则 (${missingConfigs.length})`}
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
                onClick={() => !scheduleLoading && setScheduledEnabled(!scheduledEnabled)}
                disabled={scheduleLoading}
                title={scheduleLoading ? "正在读取当前定时配置…" : undefined}
                className={cn(
                  "relative h-5 w-9 rounded-full transition-colors",
                  scheduleLoading && "animate-pulse",
                  !scheduleLoading && scheduledEnabled && "bg-amber-500",
                  !scheduleLoading && !scheduledEnabled && "bg-muted"
                )}
              >
                {scheduleLoading ? (
                  // 加载中渲染中性横条（不呈现开/关任何一侧），读到结果后才出现滑块——彻底消除首帧「关→开」跳变
                  <span className="absolute inset-x-1.5 top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-muted-foreground/40" />
                ) : (
                  <span
                    className={cn(
                      "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform shadow-sm",
                      scheduledEnabled ? "left-[18px]" : "left-0.5"
                    )}
                  />
                )}
              </button>
              <span className={cn("text-[11px]", scheduledEnabled ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground")}>
                {scheduleLoading
                  ? scheduleLoadFailed
                    ? "定时配置读取失败"
                    : "读取配置中…"
                  : scheduledEnabled
                    ? `开启 · 每天 ${dailyTime} 采集评估（停在待审批，投递由发射时间控制）`
                    : "已关闭"}
              </span>
              {scheduleLoading && scheduleLoadFailed && (
                <button
                  onClick={retryLoadSchedule}
                  className="flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 transition-all hover:bg-amber-500/20 active:scale-95 dark:text-amber-300"
                >
                  <RefreshCw className="h-3 w-3" />
                  重试
                </button>
              )}
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
              disabled={savingSchedule || scheduleLoading}
              title={scheduleLoading ? "定时配置读取完成前不可保存" : undefined}
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
