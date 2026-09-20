"use client"

import { useState } from "react"
import { DollarSign, ChevronDown, Check } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

export const STANDARD_SALARY_TIERS = [
  "不限",
  "3K以下",
  "3-5K",
  "5-10K",
  "10-15K",
  "15-20K",
  "20-30K",
  "30-50K",
  "50K以上",
] as const

export type StandardSalaryTier = (typeof STANDARD_SALARY_TIERS)[number]

export const PLATFORM_SALARY_MAP: Record<
  StandardSalaryTier,
  { boss: string; liepin: string; "51job": string; zhilian: string; xhs: string }
> = {
  "不限": { boss: "不限", liepin: "不限", "51job": "不限", zhilian: "不限", xhs: "全量" },
  "3K以下": { boss: "3K以下", liepin: "8千以下", "51job": "8千以下", zhilian: "4K以下", xhs: "全量" },
  "3-5K": { boss: "3-5K", liepin: "8千以下", "51job": "8千以下", zhilian: "4K-6K", xhs: "全量" },
  "5-10K": { boss: "5-10K", liepin: "8-10K", "51job": "8-10K", zhilian: "8K-10K", xhs: "全量" },
  "10-15K": { boss: "10-15K", liepin: "10-15K", "51job": "10-15K", zhilian: "10K-15K", xhs: "全量" },
  "15-20K": { boss: "15-20K", liepin: "15-20K", "51job": "15-20K", zhilian: "15K-25K", xhs: "全量" },
  "20-30K": { boss: "20-30K", liepin: "20-30K", "51job": "20-30K", zhilian: "25K-35K", xhs: "全量" },
  "30-50K": { boss: "30-50K", liepin: "30-50K", "51job": "30-40K", zhilian: "35K-50K", xhs: "全量" },
  "50K以上": { boss: "50K以上", liepin: "50K以上", "51job": "40-50K", zhilian: "50K以上", xhs: "全量" },
}

interface SalaryMappingPopoverProps {
  value: string
  onChange: (salary: string) => void
  placeholder?: string
  className?: string
  buttonClassName?: string
}

export function SalaryMappingPopover({
  value,
  onChange,
  placeholder = "选择薪资",
  className,
  buttonClassName,
}: SalaryMappingPopoverProps) {
  const [open, setOpen] = useState(false)
  const currentTier = (value || "不限") as StandardSalaryTier
  const currentMapping = PLATFORM_SALARY_MAP[currentTier] || PLATFORM_SALARY_MAP["不限"]

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center justify-between gap-1.5 rounded-lg border border-border/80 bg-background px-2.5 py-1.5 text-xs text-foreground font-medium shadow-xs transition-all hover:bg-muted/50 hover:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-500",
            buttonClassName
          )}
        >
          <span className="flex items-center gap-1.5 truncate">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 font-bold text-[11px] shrink-0 font-sans">
              ¥
            </span>
            <span className={cn("truncate", !value && "text-muted-foreground")}>
              {value || placeholder}
            </span>
          </span>
          <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        sideOffset={6}
        className={cn("w-88 p-3 shadow-xl rounded-xl border border-border bg-popover text-popover-foreground z-50 space-y-3", className)}
      >
        {/* 标题与说明 */}
        <div className="flex items-center justify-between border-b border-border/60 pb-2">
          <div className="flex items-center gap-1.5">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 font-bold text-[11px] shrink-0 font-sans">
              ¥
            </span>
            <span className="text-xs font-semibold">薪资档位与多平台映射</span>
          </div>
          <span className="text-[10px] text-muted-foreground">自动翻译各平台筛选</span>
        </div>

        {/* 档位选择网格 */}
        <div className="grid grid-cols-3 gap-1.5">
          {STANDARD_SALARY_TIERS.map((tier) => {
            const isSelected = (value || "不限") === tier
            return (
              <button
                key={tier}
                type="button"
                onClick={() => {
                  onChange(tier)
                  setOpen(false)
                }}
                className={cn(
                  "flex items-center justify-between rounded-md px-2 py-1.5 text-xs transition-all",
                  isSelected
                    ? "bg-amber-500 text-white font-semibold shadow-xs"
                    : "bg-muted/40 text-foreground hover:bg-amber-500/10 hover:text-amber-600 dark:hover:bg-amber-500/20"
                )}
              >
                <span>{tier}</span>
                {isSelected && <Check className="h-3 w-3" />}
              </button>
            )
          })}
        </div>

        {/* 当前档位在 4 大平台的映射预览卡片 */}
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 space-y-1.5">
          <div className="flex items-center justify-between text-[11px] font-semibold text-amber-700 dark:text-amber-300">
            <span>当前选中: {currentTier}</span>
            <span className="text-[10px] text-muted-foreground font-normal">多平台搜索实际参数</span>
          </div>

          <div className="grid grid-cols-2 gap-1.5 text-[11px]">
            <div className="flex items-center justify-between rounded bg-background/80 px-2 py-1 border border-border/50">
              <span className="text-muted-foreground">BOSS直聘:</span>
              <span className="font-mono font-medium text-foreground">{currentMapping.boss}</span>
            </div>
            <div className="flex items-center justify-between rounded bg-background/80 px-2 py-1 border border-border/50">
              <span className="text-muted-foreground">智联招聘:</span>
              <span className="font-mono font-medium text-foreground">{currentMapping.zhilian}</span>
            </div>
            <div className="flex items-center justify-between rounded bg-background/80 px-2 py-1 border border-border/50">
              <span className="text-muted-foreground">51job:</span>
              <span className="font-mono font-medium text-foreground">{currentMapping["51job"]}</span>
            </div>
            <div className="flex items-center justify-between rounded bg-background/80 px-2 py-1 border border-border/50">
              <span className="text-muted-foreground">猎聘:</span>
              <span className="font-mono font-medium text-foreground">{currentMapping.liepin}</span>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
