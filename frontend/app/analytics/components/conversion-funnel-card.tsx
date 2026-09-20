"use client"

import { Filter, Layers, CheckCircle2 } from "lucide-react"
import type { FunnelStage } from "../types"

interface ConversionFunnelCardProps {
  funnel: FunnelStage[]
  totalCrawled: number
}

// 统一采用克制的高级色板（Indigo / Sky / Amber / Emerald / Zinc）
const STAGE_TONES: Record<string, { bar: string; text: string; bg: string }> = {
  "新线索": { bar: "bg-indigo-500", text: "text-indigo-600 dark:text-indigo-400", bg: "bg-indigo-500/10" },
  "已完成初步评估": { bar: "bg-sky-500", text: "text-sky-600 dark:text-sky-400", bg: "bg-sky-500/10" },
  "已深度初步评估": { bar: "bg-cyan-500", text: "text-cyan-600 dark:text-cyan-400", bg: "bg-cyan-500/10" },
  "简历人工复核": { bar: "bg-amber-500", text: "text-amber-600 dark:text-amber-400", bg: "bg-amber-500/10" },
  "待投递": { bar: "bg-amber-500", text: "text-amber-600 dark:text-amber-400", bg: "bg-amber-500/10" },
  "已投递": { bar: "bg-blue-600", text: "text-blue-600 dark:text-blue-400", bg: "bg-blue-500/10" },
  "面试中": { bar: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-500/10" },
  "已获Offer": { bar: "bg-emerald-600", text: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-500/10" },
}

const DEFAULT_TONE = {
  bar: "bg-slate-400 dark:bg-slate-500",
  text: "text-muted-foreground",
  bg: "bg-muted",
}

export function ConversionFunnelCard({ funnel, totalCrawled }: ConversionFunnelCardProps) {
  const maxCount = Math.max(...funnel.map((s) => s.count), 1)

  return (
    <div className="flex h-full flex-col justify-between rounded-2xl border border-border/70 bg-card p-5 shadow-xs">
      <div>
        {/* 卡片头部 */}
        <div className="flex items-center justify-between pb-3 border-b border-border/50">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Layers className="size-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold tracking-tight text-foreground">求职流转漏斗</h2>
              <p className="text-[11px] text-muted-foreground">全生命周期岗位状态流向分布</p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 rounded-lg bg-muted/60 px-2.5 py-1 text-xs">
            <span className="text-muted-foreground">抓取池底量:</span>
            <span className="font-mono font-semibold text-foreground tabular-nums">
              {totalCrawled.toLocaleString()}
            </span>
          </div>
        </div>

        {/* 漏斗数据列表 */}
        <div className="mt-4 space-y-2.5">
          {funnel.length === 0 ? (
            <div className="py-12 text-center text-xs text-muted-foreground">
              暂无漏斗流转数据
            </div>
          ) : (
            funnel.map((item) => {
              const tone = STAGE_TONES[item.stage] || DEFAULT_TONE
              const ratio = Math.max((item.count / maxCount) * 100, item.count > 0 ? 3 : 0)

              return (
                <div
                  key={item.stage}
                  className="group rounded-xl p-2 transition-colors hover:bg-muted/40"
                >
                  <div className="flex items-center justify-between gap-3 text-xs mb-1.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={`size-2 rounded-full ${tone.bar}`} />
                      <span className="truncate font-medium text-foreground">{item.stage}</span>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <span className="font-mono font-bold text-foreground tabular-nums">
                        {item.count.toLocaleString()}
                      </span>
                      <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-mono font-medium ${tone.bg} ${tone.text}`}>
                        {item.percent}%
                      </span>
                    </div>
                  </div>

                  {/* 微进度条 */}
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ease-out ${tone.bar}`}
                      style={{ width: `${ratio}%` }}
                    />
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* 底部备注 */}
      <div className="mt-4 pt-3 border-t border-border/40 flex items-center justify-between text-[11px] text-muted-foreground">
        <div className="flex items-center gap-1">
          <CheckCircle2 className="size-3 text-emerald-500" />
          <span>规则引擎自适应判定各阶段流转</span>
        </div>
        <span>共 {funnel.length} 个流转阶段</span>
      </div>
    </div>
  )
}
