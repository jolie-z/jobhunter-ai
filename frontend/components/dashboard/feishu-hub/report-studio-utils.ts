export function getNextDailyRun(timeStr: string, enabled: boolean): string {
  if (!enabled) return "推送已停用"
  const [h, m] = (timeStr || "21:00").split(":").map(Number)
  const now = new Date()
  const target = new Date(now)
  target.setHours(h, m, 0, 0)

  if (now > target) {
    return `下次推送: 明天 ${timeStr}`
  } else {
    const diffHours = Math.max(0, (target.getTime() - now.getTime()) / (1000 * 60 * 60)).toFixed(1)
    return `下次推送: 今晚 ${timeStr} (约 ${diffHours} 小时后)`
  }
}

export function getNextWeeklyRun(timeStr: string, enabled: boolean): string {
  if (!enabled) return "推送已停用"
  const [h, m] = (timeStr || "09:00").split(":").map(Number)
  const now = new Date()
  const day = now.getDay()

  if (day === 1) {
    const target = new Date(now)
    target.setHours(h, m, 0, 0)
    if (now < target) {
      return `下次推送: 今天(周一) ${timeStr}`
    }
  }
  return `下次推送: 下周一 ${timeStr}`
}

export function getNextMonthlyRun(timeStr: string, enabled: boolean): string {
  if (!enabled) return "推送已停用"
  const [h, m] = (timeStr || "09:00").split(":").map(Number)
  const now = new Date()
  const nextMonth = new Date(now.getFullYear(), now.getMonth() + 1, 1, h, m)
  const month = nextMonth.getMonth() + 1
  return `下次推送: ${month}月1日 ${timeStr}`
}

export function getWeekdayLabel(dateStr?: string): string {
  if (!dateStr) return "今天"
  try {
    const dt = new Date(dateStr)
    const days = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    return days[dt.getDay()] || "今天"
  } catch {
    return "今天"
  }
}

export interface ChannelMetricItem {
  name: string
  count: number
  stock: number
  rate: number
  rateLabel: string
  status: { text: string; bg: string; dot: string }
}

export function adaptChannelList(
  activeType: "daily" | "weekly" | "monthly",
  report: any,
  crawl: any,
  totalCrawled: number
): ChannelMetricItem[] {
  if (activeType === "monthly") {
    return (report?.platform_roi || []).map((r: any) => {
      const pRate = r.pass_rate ?? 0
      const isHigh = r.crawled >= 15 && pRate >= 80
      const isLow = r.crawled > 0 && pRate < 80
      const isStable = r.crawled >= 10 && pRate >= 80
      const isZero = r.crawled === 0
      return {
        name: r.platform,
        count: r.crawled ?? 0,
        stock: r.total_in_stock ?? 0,
        rate: pRate,
        rateLabel: `${pRate}%`,
        status: isHigh
          ? { text: "高潜主力", bg: "bg-purple-50 text-purple-700", dot: "bg-purple-500" }
          : isLow
          ? { text: "质量偏低", bg: "bg-amber-50 text-amber-700", dot: "bg-amber-500" }
          : isStable
          ? { text: "稳定来源", bg: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" }
          : !isZero
          ? { text: "补充长尾", bg: "bg-sky-50 text-sky-700", dot: "bg-sky-500" }
          : { text: "暂无增量", bg: "bg-slate-100 text-slate-500", dot: "bg-slate-400" },
      }
    })
  }

  return (crawl?.platforms || []).map((item: any) => {
    const count = item.period_count !== undefined ? item.period_count : item.today
    const pct = totalCrawled > 0 ? Math.round((count / totalCrawled) * 1000) / 10 : 0
    return {
      name: item.name,
      count,
      stock: item.total ?? 0,
      rate: pct,
      rateLabel: totalCrawled > 0 ? `${pct.toFixed(1)}%` : "-",
      status:
        count > 0
          ? { text: "活跃", bg: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" }
          : { text: "静默", bg: "bg-slate-100 text-slate-500", dot: "bg-slate-400" },
    }
  })
}
