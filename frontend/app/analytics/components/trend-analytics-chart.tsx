"use client"

import { useState, useEffect, useCallback } from "react"
import { TrendingUp, Loader2 } from "lucide-react"
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts"
import { API_BASE } from "@/lib/api"
import type { TrendPoint } from "../types"

interface TrendAnalyticsChartProps {
  initialTrend?: TrendPoint[]
}

// 定制现代化悬浮微玻璃窗 Tooltip
function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload || !payload.length) return null

  return (
    <div className="rounded-xl border border-border/80 bg-background/95 p-3 shadow-lg backdrop-blur-md text-xs space-y-1.5 min-w-[140px]">
      <p className="font-semibold text-foreground border-b border-border/40 pb-1 font-mono">{label}</p>
      {payload.map((entry: any, index: number) => (
        <div key={`item-${index}`} className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-muted-foreground">{entry.name}</span>
          </div>
          <span className="font-mono font-bold text-foreground tabular-nums">
            {Number(entry.value).toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  )
}

export function TrendAnalyticsChart({ initialTrend = [] }: TrendAnalyticsChartProps) {
  const [range, setRange] = useState<string>("daily")
  const [trend, setTrend] = useState<TrendPoint[]>(initialTrend)
  const [isSwitching, setIsSwitching] = useState<boolean>(false)

  // 当外部初始数据到达或发生变化时同步
  useEffect(() => {
    if (initialTrend && initialTrend.length > 0) {
      setTrend(initialTrend)
    }
  }, [initialTrend])

  // 原地异步拉取指定颗粒度时序数据（绝不触发全局全屏 loading）
  const switchRange = useCallback(async (newRange: string) => {
    if (newRange === range && trend.length > 0) return
    setRange(newRange)
    setIsSwitching(true)
    try {
      const res = await fetch(`${API_BASE}/api/v2/analytics/trend?range=${newRange}`).then((r) => r.json())
      if (res?.code === 0 && res.data?.trend) {
        setTrend(res.data.trend)
      }
    } catch (e) {
      console.error("[TrendChart] switchRange error:", e)
    } finally {
      setIsSwitching(false)
    }
  }, [range, trend.length])

  const totalCrawled = trend.reduce((acc, cur) => acc + (cur.crawled || 0), 0)
  const totalDelivered = trend.reduce((acc, cur) => acc + (cur.delivered || 0), 0)
  const totalInterviewed = trend.reduce((acc, cur) => acc + (cur.interviewed || 0), 0)

  const ranges = [
    { key: "daily", label: "日趋势" },
    { key: "weekly", label: "周汇总" },
    { key: "monthly", label: "月透视" },
  ]

  const metrics = [
    { label: "抓取总量", value: totalCrawled, color: "#38bdf8", dotColor: "bg-sky-400" },
    { label: "投递总量", value: totalDelivered, color: "#818cf8", dotColor: "bg-indigo-400" },
    { label: "面试总量", value: totalInterviewed, color: "#34d399", dotColor: "bg-emerald-400" },
  ]

  return (
    <section className="rounded-2xl border border-border/70 bg-card p-5 shadow-xs">
      {/* 头部与范围切换器 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pb-4 border-b border-border/50">
        <div className="flex items-center gap-2">
          <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <TrendingUp className="size-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold tracking-tight text-foreground">求职时序趋势分析</h2>
            <p className="text-[11px] text-muted-foreground">多时间跨度下的「抓取 · 投递 · 面试」复合漏斗走势</p>
          </div>
        </div>

        {/* 粒度选择（原地无感切换） */}
        <div className="flex items-center gap-1 rounded-lg border border-border/60 bg-muted/60 p-0.5">
          {ranges.map((r) => (
            <button
              key={r.key}
              onClick={() => switchRange(r.key)}
              disabled={isSwitching}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-all ${
                range === r.key
                  ? "bg-card text-foreground shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* 区间指标徽标与局部加载指示 */}
      <div className="my-4 flex flex-wrap items-center justify-between gap-4 sm:gap-6">
        <div className="flex flex-wrap items-center gap-4 sm:gap-6">
          {metrics.map((m) => (
            <div key={m.label} className="flex items-center gap-2">
              <span className={`size-2 rounded-full ${m.dotColor}`} />
              <span className="text-xs text-muted-foreground">{m.label}</span>
              <span className="font-mono text-sm font-bold text-foreground tabular-nums">
                {m.value.toLocaleString()}
              </span>
            </div>
          ))}
        </div>

        {isSwitching && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin text-primary" />
            <span>切换时序数据中...</span>
          </div>
        )}
      </div>

      {/* 图表渲染区（带平滑透明度微过渡） */}
      <div className={`h-[250px] w-full pt-2 transition-opacity duration-300 ${isSwitching ? "opacity-50" : "opacity-100"}`}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={trend} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
            <defs>
              <linearGradient id="colorCrawled" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
              </linearGradient>
              <linearGradient id="colorDelivered" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#818cf8" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#818cf8" stopOpacity={0.0} />
              </linearGradient>
              <linearGradient id="colorInterviewed" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#34d399" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#34d399" stopOpacity={0.0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border/40" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: "currentColor" }}
              className="text-muted-foreground"
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "currentColor" }}
              className="text-muted-foreground"
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="crawled"
              name="抓取量"
              stroke="#38bdf8"
              fill="url(#colorCrawled)"
              strokeWidth={2}
            />
            <Area
              type="monotone"
              dataKey="delivered"
              name="实投量"
              stroke="#818cf8"
              fill="url(#colorDelivered)"
              strokeWidth={2}
            />
            <Area
              type="monotone"
              dataKey="interviewed"
              name="面试量"
              stroke="#34d399"
              fill="url(#colorInterviewed)"
              strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}
