"use client"

import { Briefcase, Sparkles, Inbox, Send, Users, Award, TrendingUp, ArrowUpRight } from "lucide-react"
import type { OverviewStats } from "../types"

interface KpiMetricsGridProps {
  ov: OverviewStats
}

export function KpiMetricsGrid({ ov }: KpiMetricsGridProps) {
  const totalPool = ov.feishu_total || ov.total_crawled || 0
  const crawlDelta = ov.today_crawled - ov.yesterday_crawled
  const deliverRate = totalPool > 0 ? ((ov.total_delivered / totalPool) * 100).toFixed(1) : "0.0"
  const interviewRate = ov.total_delivered > 0 ? ((ov.total_interview / ov.total_delivered) * 100).toFixed(1) : "0.0"
  const offerRate = ov.total_interview > 0 ? ((ov.total_offer / ov.total_interview) * 100).toFixed(1) : "0.0"

  const cards = [
    {
      title: "岗位总资产",
      value: totalPool.toLocaleString(),
      subLabel: `多维表格 ${ov.feishu_total || 0} · 本地 ${ov.total_crawled || 0}`,
      icon: Briefcase,
      badge: ov.a_grade_count > 0 ? `A级 ${ov.a_grade_count} 个` : undefined,
      badgeColor: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20",
      accentGlow: "group-hover:border-blue-500/30",
    },
    {
      title: "今日新增抓取",
      value: ov.today_crawled.toLocaleString(),
      subLabel: `昨日 ${ov.yesterday_crawled} 条`,
      icon: Sparkles,
      badge: crawlDelta >= 0 ? `+${crawlDelta}` : `${crawlDelta}`,
      badgeColor:
        crawlDelta >= 0
          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20"
          : "bg-muted text-muted-foreground border-border",
      accentGlow: "group-hover:border-emerald-500/30",
    },
    {
      title: "待投递候选池",
      value: (ov.total_pending || 0).toLocaleString(),
      subLabel: "初筛完成 · 人工复核待定",
      icon: Inbox,
      badge: "蓄势待发",
      badgeColor: "bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20",
      accentGlow: "group-hover:border-violet-500/30",
    },
    {
      title: "累计实投战果",
      value: ov.total_delivered.toLocaleString(),
      subLabel: `全池转化率 ${deliverRate}%`,
      icon: Send,
      badge: `${deliverRate}% 投出`,
      badgeColor: "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/20",
      accentGlow: "group-hover:border-sky-500/30",
    },
    {
      title: "进入面试流程",
      value: ov.total_interview.toLocaleString(),
      subLabel: `实投面试率 ${interviewRate}%`,
      icon: Users,
      badge: `${interviewRate}% 邀约`,
      badgeColor: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
      accentGlow: "group-hover:border-amber-500/30",
    },
    {
      title: "斩获录取 Offer",
      value: ov.total_offer.toLocaleString(),
      subLabel: `终面转化率 ${offerRate}%`,
      icon: Award,
      badge: ov.total_offer > 0 ? "胜券在握" : "冲刺中",
      badgeColor: "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20",
      accentGlow: "group-hover:border-rose-500/30",
    },
  ]

  return (
    <section className="space-y-4">
      {/* 6 列网格指标卡 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map((c) => {
          const Icon = c.icon
          return (
            <div
              key={c.title}
              className={`group relative flex flex-col justify-between rounded-xl border border-border/70 bg-card p-4 shadow-xs transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm ${c.accentGlow}`}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-muted-foreground">{c.title}</span>
                  <div className="flex size-6 items-center justify-center rounded-md bg-muted/60 text-muted-foreground group-hover:text-foreground transition-colors">
                    <Icon className="size-3.5" />
                  </div>
                </div>

                <div className="mt-2.5 flex items-baseline gap-2">
                  <span className="font-mono text-2xl font-bold tracking-tight text-foreground tabular-nums">
                    {c.value}
                  </span>
                  {c.badge && (
                    <span
                      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${c.badgeColor}`}
                    >
                      {c.badge}
                    </span>
                  )}
                </div>
              </div>

              <div className="mt-3 border-t border-border/40 pt-2">
                <p className="truncate text-[11px] text-muted-foreground" title={c.subLabel}>
                  {c.subLabel}
                </p>
              </div>
            </div>
          )
        })}
      </div>

      {/* 转化率微型全景横幅 (Conversion Health Ribbon) */}
      <div className="rounded-xl border border-border/70 bg-card p-4 shadow-xs">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="size-4 text-primary" />
            <span className="text-xs font-semibold text-foreground">求职全链路漏斗转化健康度</span>
            <span className="text-[11px] text-muted-foreground hidden md:inline">
              (岗位池 → 投递 → 面试 → Offer 流转比例)
            </span>
          </div>

          <div className="flex items-center gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-primary" />
              <span className="text-muted-foreground">实投率</span>
              <span className="font-mono font-semibold text-foreground">{deliverRate}%</span>
            </div>
            <div className="h-3 w-px bg-border" />
            <div className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-amber-500" />
              <span className="text-muted-foreground">面试率</span>
              <span className="font-mono font-semibold text-foreground">{interviewRate}%</span>
            </div>
            <div className="h-3 w-px bg-border" />
            <div className="flex items-center gap-1.5">
              <span className="size-2 rounded-full bg-emerald-500" />
              <span className="text-muted-foreground">Offer率</span>
              <span className="font-mono font-semibold text-foreground">{offerRate}%</span>
            </div>
          </div>
        </div>

        {/* 堆叠进度条 */}
        <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-muted/60">
          <div
            className="h-full bg-primary transition-all duration-500"
            style={{ width: `${Math.min(Number(deliverRate), 100)}%` }}
            title={`实投率: ${deliverRate}%`}
          />
          <div
            className="h-full bg-amber-500 transition-all duration-500"
            style={{ width: `${Math.min(Number(interviewRate), 100)}%` }}
            title={`面试率: ${interviewRate}%`}
          />
          <div
            className="h-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${Math.min(Number(offerRate), 100)}%` }}
            title={`Offer率: ${offerRate}%`}
          />
        </div>
      </div>
    </section>
  )
}
