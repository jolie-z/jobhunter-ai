"use client"

import { Sliders, FileText, Info, Sparkles, CheckCircle2 } from "lucide-react"
import { Switch } from "@/components/ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface RewriteCollaborationCardProps {
  includeDiagnosis: boolean
  onIncludeDiagnosisChange: (val: boolean) => void
}

export function RewriteCollaborationCard({
  includeDiagnosis,
  onIncludeDiagnosisChange,
}: RewriteCollaborationCardProps) {
  return (
    <div className="rounded-2xl border border-border/80 bg-card p-4 space-y-3 shadow-xs">
      {/* 标题栏 */}
      <div className="flex items-center gap-2 border-b border-border/50 pb-2.5">
        <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 font-bold shrink-0">
          <Sliders className="h-3.5 w-3.5" />
        </div>
        <div className="flex items-center gap-1.5">
          <h3 className="font-semibold text-foreground text-xs tracking-tight">
            改写协同机制与产物导出归档
          </h3>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors cursor-pointer">
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
              <p className="font-semibold text-zinc-100 mb-0.5">⚙️ 改写协同与产物导出机制：</p>
              <p className="text-zinc-300 text-[11px]">
                控制是否将深度评估的避坑报告带入改写 Prompt，并明确 Markdown 预览生成与最终 PDF/图片保存到飞书多维表格附件的用户授权边界。
              </p>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* 极简网格条目 */}
      <div className="space-y-2">
        {/* 1. 带入深度体检诊断开关 */}
        <div className="flex items-center justify-between p-2.5 rounded-xl border border-border/70 bg-muted/20 gap-3">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 shrink-0">
              <Sparkles className="h-3 w-3" />
            </div>
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="font-semibold text-foreground text-xs truncate">
                带入深度体检诊断报告上下文
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors cursor-pointer">
                    <Info className="h-3 w-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                  <p className="font-semibold text-zinc-100 mb-0.5">⚡ 深度体检协同机制：</p>
                  <p className="text-zinc-300 text-[11px]">
                    开启后，改写引擎将上一阶段产出的「高杠杆匹配点」与「致命硬伤避坑提示」自动注入 Prompt，使改写成品既精准放大王牌战果，又杜绝踩雷。
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>

          <Switch
            checked={includeDiagnosis}
            onCheckedChange={onIncludeDiagnosisChange}
          />
        </div>

        {/* 2. 导出与飞书归档机制 */}
        <div className="flex items-center justify-between p-2.5 rounded-xl border border-indigo-500/20 bg-indigo-500/5 text-indigo-900 dark:text-indigo-200">
          <div className="flex items-center gap-2 min-w-0">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20 shrink-0">
              <FileText className="h-3 w-3" />
            </div>
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="font-semibold text-foreground text-xs truncate">
                产物生成与飞书附件回写
              </span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" className="text-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-200 transition-colors cursor-pointer">
                    <Info className="h-3 w-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
                  <p className="font-semibold text-zinc-100 mb-0.5">📄 产物生成与归档流程：</p>
                  <p className="text-zinc-300 text-[11px]">
                    AI 改写完成后将自动生成结构化 Markdown 预览；最终的 PDF/图片导出与飞书多维表格「定制简历」附件回写权限，由用户在岗位卡片上自主确认触发。
                  </p>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>

          <div className="flex items-center gap-1 text-[10px] text-emerald-700 dark:text-emerald-400 font-medium shrink-0 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
            <CheckCircle2 className="h-3 w-3" />
            <span>用户自主确认导出</span>
          </div>
        </div>
      </div>
    </div>
  )
}
