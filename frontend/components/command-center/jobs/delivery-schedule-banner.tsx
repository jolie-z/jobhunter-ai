"use client"

import React from "react"
import { Clock, Globe, Sparkles, HelpCircle } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface DeliveryScheduleBannerProps {
  deliverySchedule?: {
    mass_time?: string
    custom_time?: string
  }
  totalReadyJobs: number
  onOpenScrapeConfig?: () => void
}

export function DeliveryScheduleBanner({
  deliverySchedule,
  totalReadyJobs,
  onOpenScrapeConfig,
}: DeliveryScheduleBannerProps) {
  const morningTime = deliverySchedule?.mass_time || "10:00"
  const afternoonTime = deliverySchedule?.custom_time || "14:00"

  const handleOpenScrape = () => {
    if (onOpenScrapeConfig) {
      onOpenScrapeConfig()
    } else {
      window.dispatchEvent(
        new CustomEvent("open-stage-config-drawer", {
          detail: { stageKey: "scraping" },
        })
      )
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-blue-500/20 bg-gradient-to-r from-blue-50/70 via-indigo-50/40 to-background dark:from-blue-950/20 dark:via-indigo-950/15 dark:to-card p-3.5 text-xs text-foreground shadow-2xs transition-all">
      {/* 顶部主信息：定时投递排期与当前队列就绪情况 */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5 pb-2.5 border-b border-blue-500/10 dark:border-blue-500/15">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-blue-600/10 text-blue-600 dark:text-blue-400 shrink-0">
            <Clock className="h-3.5 w-3.5" />
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold text-foreground">
              每日双波次自动投递排期：
            </span>
            <div className="inline-flex items-center gap-1.5 font-mono text-[11px]">
              <span className="rounded-md bg-blue-500/10 px-2 py-0.5 font-bold text-blue-600 dark:text-blue-400">
                波次一 {morningTime}
              </span>
              <span className="text-muted-foreground">/</span>
              <span className="rounded-md bg-indigo-500/10 px-2 py-0.5 font-bold text-indigo-600 dark:text-indigo-400">
                波次二 {afternoonTime}
              </span>
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="text-muted-foreground hover:text-foreground transition-colors cursor-help p-0.5 rounded-full inline-flex"
                >
                  <HelpCircle className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                系统每天到达指定投递时间时，将自动唤醒并扫描「待投递」队列中的全部就绪岗位执行串行安全发射。您也可随时点击右上角「立即执行投递」立即发射。
              </TooltipContent>
            </Tooltip>
          </div>
        </div>

        <div className="flex items-center gap-1.5 text-muted-foreground shrink-0 text-[11px]">
          <Sparkles className="h-3 w-3 text-blue-500 shrink-0" />
          <span>当前队列就绪：</span>
          <strong className="text-blue-600 dark:text-blue-400 font-semibold">{totalReadyJobs}</strong>
          <span>个岗位将在预定时间自动发射</span>
        </div>
      </div>

      {/* 底部保障提醒与平台托管面板入口 */}
      <div className="mt-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] text-muted-foreground leading-relaxed">
        <div className="flex items-start sm:items-center gap-2">
          <Globe className="h-3.5 w-3.5 text-sky-500 shrink-0 mt-0.5 sm:mt-0" />
          <p>
            <strong className="text-foreground font-medium">投递环境保障建议：</strong>
            投递期间请保持 Edge 常驻打开 BOSS直聘、智联招聘、猎聘、51Job 四大平台并处于已登录状态；建议每天关闭 Edge 再重新启动，以释放浏览器内存并保持会话稳定。
          </p>
        </div>

        <button
          type="button"
          onClick={handleOpenScrape}
          className="self-end sm:self-auto inline-flex items-center gap-1 rounded-lg border border-sky-500/30 bg-sky-500/10 hover:bg-sky-500/20 px-2.5 py-1 text-[11px] font-medium text-sky-700 dark:text-sky-300 transition-all cursor-pointer shrink-0 active:scale-95 shadow-2xs"
          title="点击打开平台抓取设置面板，查看四大平台的登录状态与一键拉取/关闭浏览器"
        >
          <span>查看平台登录状态 / 启停</span>
          <span className="font-mono text-xs">➔</span>
        </button>
      </div>
    </div>
  )
}
