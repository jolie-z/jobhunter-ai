"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Sparkles, Mic, SlidersHorizontal, Globe, TerminalSquare, Loader2, Zap, Briefcase, Trash2, Upload, Rocket, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { API_BASE } from "@/lib/api"
import type { GlobalView } from "@/app/page"
import { useTerminalStore } from "@/store/terminal-store"
import { useSetupGuide } from "@/components/dashboard/setup-guide/setup-guide-provider"
import { UpdateBadge } from "@/components/dashboard/update-badge"

interface TopNavBarProps {
  currentView: GlobalView
  onMainTabChange: (tab: "immersive" | "interview") => void
  statusCounts: Record<string, number>
  isTrashBinOpen?: boolean
  trashBinCount?: number
  onToggleTrashBin?: () => void
  globalTaskStatus?: "idle" | "running" | "completed" | "interrupted"
}

// 🌟 顶部导览工具岛（与简历库工具栏同款交互：默认仅图标，hover 滑出名称）
type NavLinkItem = {
  key: string
  label: string
  icon: LucideIcon
  href: string
  external?: boolean
  iconClass: string
  textClass: string
  expandWidth: string
  title: string
}

const NAV_LINKS: NavLinkItem[] = [
  {
    key: "strategy",
    label: "配置大盘",
    icon: SlidersHorizontal,
    href: "/strategy",
    iconClass: "text-slate-500 group-hover:text-blue-600",
    textClass: "text-slate-700 group-hover:text-blue-600",
    expandWidth: "group-hover:max-w-[72px]",
    title: "配置大盘：系统底层配置 / 飞书中台 / 基准简历库",
  },
  {
    key: "analytics",
    label: "数据大盘",
    icon: Globe,
    href: "/analytics",
    iconClass: "text-slate-500 group-hover:text-blue-600",
    textClass: "text-slate-700 group-hover:text-blue-600",
    expandWidth: "group-hover:max-w-[72px]",
    title: "数据大盘：全网招聘情报与趋势洞察分析",
  },
  {
    key: "resume-sync",
    label: "在线简历同步",
    icon: Upload,
    href: "/resume-editor",
    external: true,
    iconClass: "text-emerald-600",
    textClass: "text-emerald-700",
    expandWidth: "group-hover:max-w-[96px]",
    title: "在线简历同步：与飞书云文档简历库双向同步（需单独启动 resume_server）",
  },
  {
    key: "pipeline",
    label: "全自动全链路中心",
    icon: Zap,
    href: "/prototype/command-center",
    iconClass: "text-blue-600",
    textClass: "text-blue-700",
    expandWidth: "group-hover:max-w-[124px]",
    title: "全链路执行导轨与自动化投递中枢",
  },
]

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
    <header className="sticky top-0 z-40 w-full h-14 bg-white/90 backdrop-blur-xl border-b border-slate-100 flex items-center justify-between px-4 sm:px-6 shrink-0 select-none">
      {/* Left: Logo & 导览工具岛（默认仅图标，hover 滑出名称） */}
      <div className="flex items-center gap-3 min-w-0">
        {/* 🌟 用 Link 包裹 Logo，点击即可回首页（v0 风格：Sparkles 方块 + 渐变 AI 字样） */}
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity shrink-0">
          <div className="size-7 rounded-lg bg-slate-900 flex items-center justify-center">
            <Sparkles className="size-3.5 text-white" />
          </div>
          <span className="text-sm font-bold tracking-tight text-slate-900">
            JobHunter <span className="text-blue-600">AI</span>
          </span>
        </Link>

        <div className="w-px h-5 bg-slate-200/80 shrink-0" />

        {/* 🌟 导览工具岛（简历库工具栏同款 hover 展开） */}
        <div className="flex items-center gap-0.5 bg-slate-100/80 p-0.5 rounded-lg border border-slate-200/60 shrink-0">
          {NAV_LINKS.map((item) => {
            const Icon = item.icon
            return (
              <Link
                key={item.key}
                href={item.href}
                target={item.external ? "_blank" : undefined}
                rel={item.external ? "noopener noreferrer" : undefined}
                className="group h-8 px-2 rounded-md hover:bg-white hover:shadow-xs transition-all flex items-center cursor-pointer shrink-0"
                title={item.title}
                aria-label={item.label}
              >
                <Icon className={cn("size-4 shrink-0 transition-colors", item.iconClass)} />
                <span
                  className={cn(
                    "max-w-0 overflow-hidden opacity-0 group-hover:opacity-100 group-hover:ml-1.5 text-xs font-medium whitespace-nowrap transition-all duration-200",
                    item.expandWidth,
                    item.textClass,
                  )}
                >
                  {item.label}
                </span>
              </Link>
            )
          })}

          {/* 🌟 新手引导入口（工作台指南 / 飞书指南 / 反馈 均收在其弹窗内，顶栏不再重复放置） */}
          <button
            type="button"
            onClick={openGuide}
            className="group relative h-8 px-2 rounded-md hover:bg-white hover:shadow-xs transition-all flex items-center cursor-pointer shrink-0"
            title="新手引导：配置体检 · 工作台指南 · 飞书接入指南 · 反馈"
            aria-label="新手引导"
          >
            <Rocket
              className={cn(
                "size-4 shrink-0 transition-colors",
                setupIncomplete ? "text-amber-600" : "text-slate-500 group-hover:text-slate-800",
              )}
            />
            <span
              className={cn(
                "max-w-0 overflow-hidden opacity-0 group-hover:max-w-[72px] group-hover:opacity-100 group-hover:ml-1.5 text-xs font-medium whitespace-nowrap transition-all duration-200",
                setupIncomplete ? "text-amber-700" : "text-slate-700",
              )}
            >
              新手引导
            </span>
            {setupIncomplete && (
              <span className="absolute top-0.5 right-0.5 flex size-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex size-2 rounded-full bg-amber-500" />
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Center: Main Tabs（v0 风格 pill） */}
      <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1 shrink-0">
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
      <div className="flex items-center gap-2 shrink-0">
        {/* 🌟 新版本下载角标（策略通道下发；无更新/无桌面壳不渲染） */}
        <UpdateBadge />

        {/* 🌟 Token 消耗实时徽标 */}
        {tokenStats && (
          <Link
            href="/analytics"
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200/80 hover:bg-amber-100 transition-all font-mono"
            title={`本月: ${tokenStats.month_tokens.toLocaleString()} tokens / ¥${tokenStats.month_cost_cny?.toFixed(2) ?? "0.00"} | 累计: ${tokenStats.total_tokens.toLocaleString()} tokens / ¥${tokenStats.total_cost_cny?.toFixed(2) ?? "0.00"}`}
          >
            <Zap className="size-3.5 text-amber-500" />
            <span>
              {tokenStats.today_tokens >= 1000
                ? `${(tokenStats.today_tokens / 1000).toFixed(1)}K`
                : tokenStats.today_tokens.toLocaleString()}
              {" / "}
              ¥{tokenStats.today_cost_cny?.toFixed(2) ?? "0.00"}
            </span>
          </Link>
        )}

        {/* 🌟 右侧工具岛：拦截站 & 岗位爬取与清洗（默认仅图标，hover 滑出名称） */}
        <div className="flex items-center gap-0.5 bg-slate-100/80 p-0.5 rounded-lg border border-slate-200/60">
          {onToggleTrashBin && (
            <button
              onClick={onToggleTrashBin}
              className={cn(
                "group h-8 px-2 rounded-md transition-all flex items-center cursor-pointer shrink-0 relative border",
                isTrashBinOpen
                  ? "bg-rose-50 text-rose-700 shadow-xs border-rose-200"
                  : "border-transparent hover:bg-white hover:shadow-xs",
              )}
              title={`拦截站：已拦截 ${trashBinCount} 条不合规任务`}
              aria-label="打开拦截回收站"
            >
              <Trash2 className="size-4 shrink-0 text-rose-500" />
              <span
                className={cn(
                  "max-w-0 overflow-hidden opacity-0 group-hover:max-w-[56px] group-hover:opacity-100 group-hover:ml-1.5 text-xs font-medium whitespace-nowrap transition-all duration-200",
                  isTrashBinOpen ? "text-rose-700" : "text-slate-700",
                )}
              >
                拦截站
              </span>
              {trashBinCount > 0 && (
                <span className="rounded-full bg-rose-50 text-rose-600 border border-rose-200/80 px-1 text-[10px] font-semibold leading-none py-0.5 ml-1 shrink-0 font-mono">
                  {trashBinCount > 99 ? '99+' : trashBinCount}
                </span>
              )}
            </button>
          )}

          <button
            onClick={isTerminalOpen ? minimize : restoreFromMinimize}
            className={cn(
              "group h-8 px-2 rounded-md transition-all flex items-center cursor-pointer shrink-0 border",
              isTerminalOpen
                ? "bg-blue-50 text-blue-700 shadow-xs border-blue-200/80"
                : "border-transparent hover:bg-white hover:shadow-xs",
            )}
            title="岗位爬取与清洗控制台"
            aria-label="切换岗位爬取与清洗控制台"
          >
            {globalTaskStatus === "running" ? (
              <Loader2 className="size-4 shrink-0 animate-spin text-blue-500" />
            ) : (
              <TerminalSquare className={cn("size-4 shrink-0 transition-colors", isTerminalOpen ? "text-blue-600" : "text-slate-500 group-hover:text-slate-800")} />
            )}
            <span
              className={cn(
                "overflow-hidden text-xs font-medium whitespace-nowrap transition-all duration-200",
                isTerminalOpen
                  ? "max-w-[110px] opacity-100 ml-1.5 text-blue-700"
                  : "max-w-0 opacity-0 group-hover:max-w-[110px] group-hover:opacity-100 group-hover:ml-1.5 text-slate-700",
              )}
            >
              岗位爬取与清洗
            </span>
          </button>
        </div>
      </div>
    </header>
  )
}
