"use client"

import { Target, CalendarDays, Search, Send } from "lucide-react"
import type { GoalData } from "../types"

interface GoalTrackerCardProps {
  goals: GoalData
}

function ProgressBar({ percent, tone }: { percent: number; tone: "bg-primary" | "bg-sky-500" | "bg-emerald-500" }) {
  const clamped = Math.min(Math.max(percent, 0), 100)
  return (
    <div
      className="h-2 w-full overflow-hidden rounded-full bg-muted/60"
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={`h-full rounded-full transition-all duration-500 ${tone}`} style={{ width: `${clamped}%` }} />
    </div>
  )
}

export function GoalTrackerCard({ goals }: GoalTrackerCardProps) {
  const items: Array<{
    icon: typeof CalendarDays
    title: string
    value: string
    percent: number
    label: string
    tone: "bg-primary" | "bg-sky-500" | "bg-emerald-500"
  }> = [
    {
      icon: CalendarDays,
      title: "周期进度",
      value: `第 ${goals.days_elapsed} / ${goals.plan_days} 天`,
      percent: goals.time_progress_percent,
      label: `时间进度 ${Math.round(goals.time_progress_percent)}%`,
      tone: "bg-primary",
    },
    {
      icon: Search,
      title: "每日抓取目标",
      value: `${goals.today_crawled} / ${goals.daily_crawl_target} 条`,
      percent: goals.daily_crawl_progress,
      label: `完成 ${Math.round(goals.daily_crawl_progress)}%`,
      tone: "bg-sky-500",
    },
    {
      icon: Send,
      title: "每日投递目标",
      value: `${goals.today_delivered} / ${goals.daily_deliver_target} 个`,
      percent: goals.daily_deliver_progress,
      label: `完成 ${Math.round(goals.daily_deliver_progress)}%`,
      tone: "bg-emerald-500",
    },
  ]

  return (
    <section className="rounded-xl border border-border/70 bg-card p-4 shadow-xs">
      <div className="flex items-center gap-2">
        <Target className="size-4 text-primary" />
        <span className="text-xs font-semibold text-foreground">求职目标跟踪</span>
        <span className="text-[11px] text-muted-foreground">
          （目标编辑在「配置大盘 → 飞书集成中心」）
        </span>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {items.map((it) => {
          const Icon = it.icon
          return (
            <div key={it.title} className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Icon className="size-3.5" />
                  {it.title}
                </div>
                <span className="font-mono text-xs font-semibold text-foreground tabular-nums">{it.value}</span>
              </div>
              <ProgressBar percent={it.percent} tone={it.tone} />
              <p className="text-[11px] text-muted-foreground">{it.label}</p>
            </div>
          )
        })}
      </div>
    </section>
  )
}
