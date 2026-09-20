"use client"

import Link from "next/link"
import { ArrowLeft, BarChart3, RefreshCw, Radio, ExternalLink, Cpu } from "lucide-react"

interface AnalyticsHeaderProps {
  onRefresh: () => void
  refreshing: boolean
  lastSyncTime: string
  activeSection: string
  onSectionChange: (section: string) => void
}

export function AnalyticsHeader({
  onRefresh,
  refreshing,
  lastSyncTime,
  activeSection,
  onSectionChange,
}: AnalyticsHeaderProps) {
  const scrollTo = (id: string, name: string) => {
    onSectionChange(name)
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/70 bg-background/80 backdrop-blur-xl transition-all">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        {/* 左侧：返回 + 标题 + 实时状态 */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title="返回工作台"
          >
            <ArrowLeft className="size-4" />
          </Link>

          <div className="h-4 w-px bg-border/80" />

          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <BarChart3 className="size-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold tracking-tight text-foreground">全景数据大盘</span>
                <span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                  <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  实时同步
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 中间/右侧：视图锚点与功能快捷操作 */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* 视图锚点胶囊 */}
          <div className="flex items-center rounded-lg bg-muted/60 p-1 border border-border/50 text-xs font-medium">
            <button
              onClick={() => scrollTo("section-overview", "overview")}
              className={`rounded-md px-3 py-1 transition-all ${
                activeSection === "overview"
                  ? "bg-card text-foreground shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              求职漏斗
            </button>
            <button
              onClick={() => scrollTo("section-token", "token")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1 transition-all ${
                activeSection === "token"
                  ? "bg-card text-foreground shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Cpu className="size-3" />
              算力与成本
            </button>
          </div>

          <div className="h-4 w-px bg-border/80 hidden sm:block" />

          {/* 飞书集成中心直达胶囊 */}
          <Link
            href="/strategy?section=feishu"
            className="hidden sm:flex items-center gap-1.5 rounded-lg border border-border/70 bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground hover:border-border hover:text-foreground hover:bg-muted/40 transition-all"
            title="前往配置大盘管理飞书战报与自动化定时推送"
          >
            <Radio className="size-3 text-blue-500" />
            <span>飞书推送调度</span>
            <ExternalLink className="size-3 opacity-60" />
          </Link>

          {/* 刷新按钮 */}
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 rounded-lg border border-border/70 bg-card px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-all disabled:opacity-50"
            title={lastSyncTime ? `上次同步: ${lastSyncTime}（点击清理缓存并重新拉取）` : "重新拉取数据"}
          >
            <RefreshCw className={`size-3.5 ${refreshing ? "animate-spin text-primary" : ""}`} />
            <span className="hidden md:inline">{refreshing ? "刷新中..." : "重新计算"}</span>
          </button>
        </div>
      </div>
    </header>
  )
}
