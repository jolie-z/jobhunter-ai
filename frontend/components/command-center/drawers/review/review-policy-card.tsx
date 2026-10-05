"use client"

import { Shield, Info } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface ReviewPolicyCardProps {
  massApplyMaxHeadcount: number
  onChangeHeadcount: (val: number) => void
}

export function ReviewPolicyCard({
  massApplyMaxHeadcount,
  onChangeHeadcount,
}: ReviewPolicyCardProps) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 px-4 py-3 shadow-xs backdrop-blur-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
      {/* 左侧：标题与感叹号说明 */}
      <div className="flex items-center gap-1.5">
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-violet-500/10 text-violet-600 dark:text-violet-400 shrink-0">
          <Shield className="h-3.5 w-3.5" />
        </div>
        <span className="text-xs font-semibold text-foreground tracking-tight">
          大公司海投拦截门槛
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
            【海投拦截】针对 C-F 级海投岗位，若所属公司员工规模达到或超过此门槛人数，系统将自动拦截并挂起在【海投拦截】待审批中，防止误投知名大厂；【精投审批】A/B 级岗位则默认全部强制人工复核。
          </TooltipContent>
        </Tooltip>
      </div>

      {/* 右侧：单行极简数字输入 */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-muted-foreground">企业规模 ≥</span>
        <input
          type="number"
          min={0}
          step={100}
          value={massApplyMaxHeadcount}
          onChange={(e) => onChangeHeadcount(Math.min(10000, Math.max(1, Number(e.target.value) || 1)))}
          className="h-7 w-20 rounded-lg border border-border bg-background px-2 text-center text-xs font-mono font-medium text-foreground focus:border-violet-500 focus:outline-none"
        />
        <span className="text-[11px] text-muted-foreground">人转人工审核</span>
      </div>
    </div>
  )
}
