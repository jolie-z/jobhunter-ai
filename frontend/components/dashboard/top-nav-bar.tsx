"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Sparkles, Mic, Beaker, Globe, TerminalSquare, Loader2, Zap, Briefcase, Trash2, Upload, Rocket } from "lucide-react"
import { cn } from "@/lib/utils"
import { API_BASE } from "@/lib/api"
import type { GlobalView } from "@/app/page"
import { useTerminalStore } from "@/store/terminal-store"
import { useSetupGuide } from "@/components/dashboard/setup-guide/setup-guide-provider"

interface TopNavBarProps {
  currentView: GlobalView
  onMainTabChange: (tab: "immersive" | "interview") => void
  statusCounts: Record<string, number>
  isTrashBinOpen?: boolean
  trashBinCount?: number
  onToggleTrashBin?: () => void
  globalTaskStatus?: "idle" | "running" | "completed" | "interrupted"
}

export function TopNavBar({
  currentView,
  onMainTabChange,
  isTrashBinOpen = false,
  trashBinCount = 0,
  onToggleTrashBin,
  globalTaskStatus = "idle",
}: TopNavBarProps) {
  const isImmersive = currentView !== "interview-camp"

  const { mode, restoreFromMinimize, minimize } = useTerminalStore()
  const isTerminalOpen = mode !== "minimize"

  // 🌟 新手引导入口（未完成配置时按钮带提醒小点）
  const { openGuide, incomplete: setupIncomplete } = useSetupGuide()

  // 🌟 Token 消耗实时徽标
  const [tokenStats, setTokenStats] = useState<{
    today_tokens: number
    month_tokens: number
    total_tokens: number
    today_cost_cny: number
    month_cost_cny: number
    total_cost_cny: number
  } | null>(null)

  useEffect(() => {
    const fetchTokens = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/analytics/tokens`)
        const json = await res.json()
        if (json.code === 0 && json.data) {
          setTokenStats(json.data)
        }
      } catch {
        // 静默失败，不影响主流程
      }
    }
    fetchTokens()
    const interval = setInterval(fetchTokens, 30000) // 每 30 秒刷新一次
    return () => clearInterval(interval)
  }, [])

  return (
    <header className="sticky top-0 z-40 w-full h-14 bg-white/90 backdrop-blur-xl border-b border-slate-100 flex items-center justify-between px-6 shrink-0">
      {/* Left: Logo & 配置大盘入口 */}
      <div className="flex items-center gap-5">
        {/* 🌟 用 Link 包裹 Logo，点击即可回首页（v0 风格：Sparkles 方块 + 渐变 AI 字样） */}
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <div className="size-7 rounded-lg bg-slate-900 flex items-center justify-center">
            <Sparkles className="size-3.5 text-white" />
          </div>
          <span className="text-sm font-bold tracking-tight text-slate-900">
            JobHunter <span className="text-blue-600">AI</span>
          </span>
        </Link>
        {/* 🌟 配置大盘入口 */}
        <Link
          href="/strategy"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-all"
        >
          <Beaker className="size-3.5" />
          配置大盘
        </Link>

        {/* 🌟 全景数据大盘入口 (New Analytics Dashboard) */}
        <Link
          href="/analytics"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-all"
        >
          <Globe className="size-3.5" />
          数据大盘
        </Link>

        {/* 🌟 在线简历回写入口（/resume-editor 与本站同一 Next 应用，直接站内跳转；
            其后端 resume_server.py 需单独启动，端口见 backend/resume_server.py） */}
        <Link
          href="/resume-editor"
          target="_blank"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-emerald-600 hover:text-emerald-800 hover:bg-emerald-50 transition-all"
        >
          <Upload className="size-3.5" />
          在线简历同步
        </Link>

        {/* 🌟 全链路指挥中心入口 */}
        <Link
          href="/prototype/command-center"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-all"
        >
          <Zap className="size-3.5" />
          全自动全链路中心
        </Link>

        {/* 🌟 新手引导入口 */}
        <button
          type="button"
          onClick={openGuide}
          className={cn(
            "relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all",
            setupIncomplete
              ? "text-amber-600 bg-amber-50 hover:bg-amber-100"
              : "text-slate-400 hover:text-slate-700 hover:bg-slate-50"
          )}
        >
          <Rocket className="size-3.5" />
          新手引导
          {setupIncomplete && (
            <span className="absolute -top-0.5 -right-0.5 flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex size-2 rounded-full bg-amber-500" />
            </span>
          )}
        </button>
      </div>

      {/* Center: Main Tabs（v0 风格 pill） */}
      <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
        <button
          onClick={() => onMainTabChange("immersive")}
          className={cn(
            "flex items-center gap-1.5 h-7 px-3 rounded-md text-xs font-medium transition-all",
            isImmersive
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-400 hover:text-slate-700"
          )}
        >
          <Briefcase className="size-3.5" />
          沉浸工作台
        </button>
        <button
          onClick={() => onMainTabChange("interview")}
          className={cn(
            "flex items-center gap-1.5 h-7 px-3 rounded-md text-xs font-medium transition-all",
            !isImmersive
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-400 hover:text-slate-700"
          )}
        >
          <Mic className="size-3.5" />
          面试训练营(升级中)
        </button>
      </div>

      {/* Right: 工具栏区 */}
      <div className="flex items-center gap-2">
        {/* 🌟 Token 消耗实时徽标 */}
        {tokenStats && (
          <Link
            href="/analytics"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-50 text-amber-700 hover:bg-amber-100 transition-all"
            title={`本月: ${tokenStats.month_tokens.toLocaleString()} tokens / ¥${tokenStats.month_cost_cny?.toFixed(2) ?? "0.00"} | 累计: ${tokenStats.total_tokens.toLocaleString()} tokens / ¥${tokenStats.total_cost_cny?.toFixed(2) ?? "0.00"}`}
          >
            <Zap className="size-3.5" />
            <span>
              {tokenStats.today_tokens >= 1000
                ? `${(tokenStats.today_tokens / 1000).toFixed(1)}K`
                : tokenStats.today_tokens.toLocaleString()}
              {" / "}
              ¥{tokenStats.today_cost_cny?.toFixed(2) ?? "0.00"}
            </span>
          </Link>
        )}

        {/* 🌟 任务控制台与拦截站切换按钮 */}
        <div className="flex items-center gap-1.5 bg-slate-50 p-1 rounded-xl border border-slate-100">
          {onToggleTrashBin && (
            <button
              onClick={onToggleTrashBin}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all relative border shrink-0",
                isTrashBinOpen
                  ? "bg-rose-50 text-rose-700 border-rose-200 shadow-xs"
                  : "text-slate-600 bg-white hover:text-slate-900 hover:bg-slate-50/80 border-slate-200/80 shadow-xs"
              )}
              aria-label="打开拦截回收站"
            >
              <Trash2 className="size-3.5 text-rose-500" />
              <span>拦截站</span>
              {trashBinCount > 0 && (
                <span className="rounded-full bg-rose-50 text-rose-600 border border-rose-200/80 px-1.5 text-[10px] font-semibold leading-none py-0.5 ml-0.5">
                  {trashBinCount > 99 ? '99+' : trashBinCount}
                </span>
              )}
            </button>
          )}

          <button
            onClick={isTerminalOpen ? minimize : restoreFromMinimize}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all shrink-0",
              isTerminalOpen
                ? "bg-blue-50 text-blue-700 shadow-sm"
                : "text-slate-500 hover:text-slate-800 hover:bg-white"
            )}
            aria-label="切换岗位爬取与清洗控制台"
          >
            {globalTaskStatus === "running" ? (
              <Loader2 className="size-3.5 animate-spin text-blue-500" />
            ) : (
              <TerminalSquare className="size-3.5" />
            )}
            岗位爬取与清洗
          </button>
        </div>
      </div>
    </header>
  )
}