"use client"

import { Info, Image as ImageIcon, FileText, Sparkles } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export function ReviewMaterialGuideCard() {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-3.5 shadow-xs backdrop-blur-xs space-y-2.5">
      {/* 极简顶栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-amber-500/10 text-amber-600 dark:text-amber-400">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            平台物料格式与放行要求
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
              各平台投递通道机制不同：BOSS直聘需在微聊发送图片长图+打招呼语；猎聘与智联招聘需提交PDF附件+打招呼语；51job需提交PDF附件。精投岗位需在定制面板完成对应物料保存后方可点亮放行按钮。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[10px] text-muted-foreground">
          物料齐备自动点亮放行
        </span>
      </div>

      {/* 3 平台极简行内胶囊 */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {/* BOSS直聘 */}
        <div className="flex items-center justify-between rounded-xl border border-cyan-500/20 bg-cyan-500/[0.04] px-3 py-2">
          <div className="flex items-center gap-2 min-w-0">
            <ImageIcon className="h-3.5 w-3.5 text-cyan-600 dark:text-cyan-400 shrink-0" />
            <div className="space-y-0.5 min-w-0">
              <div className="flex items-center gap-1">
                <span className="text-xs font-semibold text-foreground">BOSS 直聘</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3 w-3 text-zinc-400" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                    微聊沟通仅支持图片附件发送。需在定制面板点击「保存图片」回写飞书「图片保存」字段，并生成打招呼语后方可放行。
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="flex items-center gap-1 text-[10px] font-mono text-cyan-700 dark:text-cyan-300 truncate">
                <span>图片长图</span>
                <span>+</span>
                <span>打招呼语</span>
              </div>
            </div>
          </div>
        </div>

        {/* 猎聘 / 智联招聘 */}
        <div className="flex items-center justify-between rounded-xl border border-amber-500/20 bg-amber-500/[0.04] px-3 py-2">
          <div className="flex items-center gap-2 min-w-0">
            <FileText className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
            <div className="space-y-0.5 min-w-0">
              <div className="flex items-center gap-1">
                <span className="text-xs font-semibold text-foreground">猎聘 / 智联</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3 w-3 text-zinc-400" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                    猎聘与智联招聘（2026新版微聊）均需上传 PDF 附件并附带专属打招呼语。需在定制面板点击「保存 PDF」回写飞书「PDF备份」字段，并生成打招呼语后方可放行。
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="flex items-center gap-1 text-[10px] font-mono text-amber-700 dark:text-amber-300 truncate">
                <span>PDF 附件</span>
                <span>+</span>
                <span>打招呼语</span>
              </div>
            </div>
          </div>
        </div>

        {/* 前程无忧 (51job) */}
        <div className="flex items-center justify-between rounded-xl border border-blue-500/20 bg-blue-500/[0.04] px-3 py-2">
          <div className="flex items-center gap-2 min-w-0">
            <FileText className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400 shrink-0" />
            <div className="space-y-0.5 min-w-0">
              <div className="flex items-center gap-1">
                <span className="text-xs font-semibold text-foreground">前程无忧 (51job)</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3 w-3 text-zinc-400" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
                    前程无忧通过标准职位附件通道直接投递 PDF 简历，无需打招呼语。需在定制面板点击「保存 PDF」生成物料后方可放行。
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="flex items-center gap-1 text-[10px] font-mono text-blue-700 dark:text-blue-300 truncate">
                <span>PDF 附件</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
