"use client"

import { Building2, ArrowUpRight, TrendingUp } from "lucide-react"
import type { PlatformStat } from "../types"

interface PlatformMatrixCardProps {
  platforms: PlatformStat[]
}

// 统一采用克制且有辨识度的平台配色（避免高饱和刺眼）
const PLATFORM_THEME: Record<string, { badge: string; color: string; bg: string }> = {
  "BOSS直聘": { badge: "BOSS", color: "text-sky-600 dark:text-sky-400", bg: "bg-sky-500/10 border-sky-500/20" },
  "猎聘": { badge: "猎聘", color: "text-amber-600 dark:text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" },
  "51job": { badge: "前程", color: "text-orange-600 dark:text-orange-400", bg: "bg-orange-500/10 border-orange-500/20" },
  "智联招聘": { badge: "智联", color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-500/10 border-blue-500/20" },
  "小红书": { badge: "RED", color: "text-rose-600 dark:text-rose-400", bg: "bg-rose-500/10 border-rose-500/20" },
  "其他平台": { badge: "其他", color: "text-slate-600 dark:text-slate-400", bg: "bg-slate-500/10 border-slate-500/20" },
}

const DEFAULT_THEME = {
  badge: "其他",
  color: "text-slate-600 dark:text-slate-400",
  bg: "bg-slate-500/10 border-slate-500/20",
}

export function PlatformMatrixCard({ platforms: rawPlatforms }: PlatformMatrixCardProps) {
  // 防御性归一化与数据合并（避免大小写、别名与零星脏数据割裂）
  const normalizedMap = new Map<string, PlatformStat>()

  for (const p of rawPlatforms) {
    let name = p.platform?.trim() || "其他平台"
    const lower = name.toLowerCase()
    if (lower.includes("boss") || name.includes("直聘")) name = "BOSS直聘"
    else if (lower.includes("51") || name.includes("前程")) name = "51job"
    else if (name.includes("猎聘") || lower.includes("liepin")) name = "猎聘"
    else if (name.includes("智联") || lower.includes("zhilian") || lower.includes("zhaopin")) name = "智联招聘"
    else if (name.includes("红书") || lower.includes("xhs")) name = "小红书"
    else if (name === "未知" || name === "其他" || name === "其他平台") name = "其他平台"

    // 过滤完全无数据的空项
    if (
      (p.crawl_count || 0) === 0 &&
      (p.push_count || 0) === 0 &&
      (p.deliver_count || 0) === 0
    ) {
      continue
    }

    const existing = normalizedMap.get(name)
    if (existing) {
      existing.crawl_count += p.crawl_count || 0
      existing.push_count += p.push_count || 0
      existing.deliver_count += p.deliver_count || 0
      existing.interview_count += p.interview_count || 0
      existing.offer_count += p.offer_count || 0
      existing.deliver_rate = Number(
        (existing.crawl_count > 0 ? (existing.deliver_count / existing.crawl_count) * 100 : 0).toFixed(1)
      )
    } else {
      normalizedMap.set(name, {
        platform: name,
        crawl_count: p.crawl_count || 0,
        push_count: p.push_count || 0,
        deliver_count: p.deliver_count || 0,
        interview_count: p.interview_count || 0,
        offer_count: p.offer_count || 0,
        deliver_rate: Number(
          (p.crawl_count > 0 ? ((p.deliver_count || 0) / p.crawl_count) * 100 : 0).toFixed(1)
        ),
      })
    }
  }

  // 排序：主流平台按抓取量倒序，"其他平台" 始终置于末尾
  const platforms = Array.from(normalizedMap.values()).sort((a, b) => {
    if (a.platform === "其他平台") return 1
    if (b.platform === "其他平台") return -1
    return b.crawl_count - a.crawl_count
  })

  const totalCrawl = platforms.reduce((acc, cur) => acc + cur.crawl_count, 0)
  const totalDeliver = platforms.reduce((acc, cur) => acc + cur.deliver_count, 0)
  const totalInterview = platforms.reduce((acc, cur) => acc + cur.interview_count, 0)

  return (
    <div className="flex h-full flex-col justify-between rounded-2xl border border-border/70 bg-card p-5 shadow-xs">
      <div>
        {/* 卡片头部 */}
        <div className="flex items-center justify-between pb-3 border-b border-border/50">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Building2 className="size-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold tracking-tight text-foreground">各招聘渠道转化矩阵</h2>
              <p className="text-[11px] text-muted-foreground">横向对比各平台的线索质量与面试产出</p>
            </div>
          </div>

          <span className="rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-xs text-muted-foreground">
            {platforms.length} 个渠道
          </span>
        </div>

        {/* 渠道矩阵表 */}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border/40 text-[11px] text-muted-foreground">
                <th className="pb-2 font-medium">招聘平台</th>
                <th className="pb-2 text-right font-medium">抓取</th>
                <th className="pb-2 text-right font-medium">推送</th>
                <th className="pb-2 text-right font-medium">实投</th>
                <th className="pb-2 text-right font-medium">面试</th>
                <th className="pb-2 text-right font-medium">Offer</th>
                <th className="pb-2 text-right font-medium">实投转化率</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {platforms.map((p) => {
                const theme = PLATFORM_THEME[p.platform] || DEFAULT_THEME
                return (
                  <tr key={p.platform} className="transition-colors hover:bg-muted/40">
                    <td className="py-2.5">
                      <div className="flex items-center gap-2">
                        <span
                          className={`flex h-6 w-11 items-center justify-center rounded-md border text-[10px] font-bold ${theme.bg} ${theme.color}`}
                        >
                          {theme.badge}
                        </span>
                        <span className="font-medium text-foreground">{p.platform}</span>
                      </div>
                    </td>
                    <td className="py-2.5 text-right font-mono font-medium text-foreground tabular-nums">
                      {p.crawl_count.toLocaleString()}
                    </td>
                    <td className="py-2.5 text-right font-mono text-muted-foreground tabular-nums">
                      {p.push_count.toLocaleString()}
                    </td>
                    <td className="py-2.5 text-right font-mono font-medium text-primary tabular-nums">
                      {p.deliver_count.toLocaleString()}
                    </td>
                    <td className="py-2.5 text-right font-mono font-medium text-amber-600 dark:text-amber-400 tabular-nums">
                      {p.interview_count.toLocaleString()}
                    </td>
                    <td className="py-2.5 text-right font-mono font-bold text-rose-600 dark:text-rose-400 tabular-nums">
                      {p.offer_count.toLocaleString()}
                    </td>
                    <td className="py-2.5 text-right">
                      <span
                        className={`inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 font-mono text-[11px] font-semibold ${
                          p.deliver_rate > 0
                            ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                            : "text-muted-foreground"
                        }`}
                      >
                        {p.deliver_rate}%
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 底部各平台抓取占比条 */}
      <div className="mt-4 pt-3 border-t border-border/40 space-y-2">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground">渠道抓取贡献度分布</span>
          <span className="font-mono text-muted-foreground">
            总计 {totalCrawl.toLocaleString()} 条线索 / {totalDeliver.toLocaleString()} 次实投
          </span>
        </div>

        {totalCrawl > 0 && (
          <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
            {platforms.map((p, idx) => {
              const theme = PLATFORM_THEME[p.platform] || DEFAULT_THEME
              const widthPct = ((p.crawl_count / totalCrawl) * 100).toFixed(1)
              const colorClasses = [
                "bg-sky-500",
                "bg-amber-500",
                "bg-orange-500",
                "bg-blue-500",
                "bg-rose-500",
              ]
              const bgClass = colorClasses[idx % colorClasses.length]

              return (
                <div
                  key={p.platform}
                  className={`h-full ${bgClass} transition-all duration-300`}
                  style={{ width: `${widthPct}%` }}
                  title={`${p.platform}: ${p.crawl_count} 条 (${widthPct}%)`}
                />
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
