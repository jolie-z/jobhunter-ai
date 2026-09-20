"use client"

import { Clock, Info, Sunrise, Sunset, Sparkles } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface DeliveryScheduleCardProps {
  massDeliverTime: string
  onChangeMassDeliverTime: (time: string) => void
  customDeliverMode?: "immediate" | "scheduled"
  onChangeCustomDeliverMode?: (mode: "immediate" | "scheduled") => void
  customDeliverTime: string
  onChangeCustomDeliverTime: (time: string) => void
}

export function DeliveryScheduleCard({
  massDeliverTime,
  onChangeMassDeliverTime,
  customDeliverTime,
  onChangeCustomDeliverTime,
}: DeliveryScheduleCardProps) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3.5">
      {/* 顶栏标题与说明 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-400">
            <Clock className="h-3.5 w-3.5" />
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            每日双时段定时投递
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors cursor-help p-0.5 rounded-full hover:bg-muted"
              >
                <Info className="h-3.5 w-3.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
              【双波次自动投递】：系统每天将在设定的两个黄金时段自动唤醒，扫描「待投递」队列中的全部就绪岗位并依次串行投递。若当前队列为空则自动跳过；亦可随时在看板手动点击「立即执行投递」。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[11px] text-muted-foreground hidden sm:inline-flex items-center gap-1">
          <Sparkles className="h-3 w-3 text-blue-500" />
          自动扫描「待投递」队列 · 串行安全发射
        </span>
      </div>

      {/* 两个定时发射波次 */}
      <div className="space-y-2.5">
        {/* 时段一：上午发射时段 */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 rounded-xl border border-border/60 bg-background/60 p-3 hover:border-amber-500/30 transition-colors">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400">
              <Sunrise className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-foreground">
                  上午发射时段 (波次一)
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground">
                准点扫描待投递队列，命中工作日早间 HR 活跃期
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-end sm:self-auto">
            <span className="text-xs text-muted-foreground">每天定时</span>
            <input
              type="time"
              value={massDeliverTime || "10:00"}
              onChange={(e) => onChangeMassDeliverTime(e.target.value)}
              className="h-8 w-24 rounded-lg border border-border bg-background px-2 text-center text-xs font-mono font-semibold text-foreground focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500/30"
            />
            <span className="text-xs text-muted-foreground">准点发射</span>
          </div>
        </div>

        {/* 时段二：下午发射时段 */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 rounded-xl border border-border/60 bg-background/60 p-3 hover:border-blue-500/30 transition-colors">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400">
              <Sunset className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold text-foreground">
                  下午发射时段 (波次二)
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground">
                自动补发午间及全天新放行岗位，命中下午沟通高峰
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-end sm:self-auto">
            <span className="text-xs text-muted-foreground">每天定时</span>
            <input
              type="time"
              value={customDeliverTime || "14:30"}
              onChange={(e) => onChangeCustomDeliverTime(e.target.value)}
              className="h-8 w-24 rounded-lg border border-border bg-background px-2 text-center text-xs font-mono font-semibold text-foreground focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/30"
            />
            <span className="text-xs text-muted-foreground">准点发射</span>
          </div>
        </div>
      </div>
    </div>
  )
}
