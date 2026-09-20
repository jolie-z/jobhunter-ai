"use client"

import { Stethoscope, Info } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface DeepModuleItem {
  key: string
  name: string
  icon: string
  desc: string
}

interface DeepModulesGridProps {
  modules: DeepModuleItem[]
}

export function DeepModulesGrid({ modules }: DeepModulesGridProps) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card p-4.5 space-y-3.5 shadow-xs">
      {/* 顶栏 */}
      <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
        <div className="flex items-center gap-2">
          <Stethoscope className="h-4 w-4 text-violet-500" />
          <span className="font-semibold text-foreground text-xs">
            深度体检 6 大核心诊断输出矩阵
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
              <p className="font-semibold text-zinc-100 mb-0.5">🔬 深度评估与初评的本质区别：</p>
              <p className="text-zinc-300 text-[11px]">
                初评只负责给出 0~100 综合分值；深度评估则输出这 6 份极具实战价值的逐行审计、致命硬伤推演与破局计划。
              </p>
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[10px] text-muted-foreground font-mono">
          全量输出 6 项专业报告
        </span>
      </div>

      {/* 6 大卡片 2 列网格 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {modules.map((mod) => (
          <div
            key={mod.key}
            className="p-3 rounded-xl border border-border/60 bg-muted/15 hover:bg-muted/30 transition-all space-y-1"
          >
            <div className="flex items-center gap-1.5">
              <span className="text-sm">{mod.icon}</span>
              <span className="font-medium text-foreground text-xs">{mod.name}</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {mod.desc}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
