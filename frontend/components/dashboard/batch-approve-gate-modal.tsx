"use client"

import React from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { AlertTriangle, CheckCircle2, ArrowRight, ShieldCheck, Sparkles } from "lucide-react"
import type { JobData } from "@/types/job"

export interface NotReadyJobItem {
  job: JobData
  missing: string[]
}

interface BatchApproveGateModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  readyJobs: JobData[]
  notReadyJobs: NotReadyJobItem[]
  // 确认即「物料齐全直接批准 + 缺料自愈后批准」全量放行（与弹窗文案一致），无需额外选项
  onConfirmApprove: () => void
}

export function BatchApproveGateModal({
  open,
  onOpenChange,
  readyJobs,
  notReadyJobs,
  onConfirmApprove,
}: BatchApproveGateModalProps) {
  const totalCount = readyJobs.length + notReadyJobs.length
  const hasMissing = notReadyJobs.length > 0

  const handleConfirm = () => {
    onOpenChange(false)
    onConfirmApprove()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] p-6 gap-4 bg-background/95 backdrop-blur-md border border-border/80 shadow-2xl rounded-2xl">
        <DialogHeader className="gap-2.5 text-left">
          <div className="flex items-center gap-3">
            <div
              className={`size-11 rounded-xl flex items-center justify-center shrink-0 border ${
                hasMissing
                  ? "bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400"
                  : "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
              }`}
            >
              {hasMissing ? (
                <AlertTriangle className="size-5" />
              ) : (
                <ShieldCheck className="size-5" />
              )}
            </div>
            <div>
              <DialogTitle className="text-base font-bold text-foreground">
                批量批准投递 · 物料智能预检
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground mt-0.5">
                已选中 {totalCount} 个岗位，正在接入投递放行流水线
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* 预检状态卡片 */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-muted/50 border border-border/60 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-medium text-foreground">预检结果：</span>
              <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold">
                <CheckCircle2 className="size-3.5" />
                {readyJobs.length} 个物料齐全
              </span>
              {hasMissing && (
                <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400 font-semibold">
                  · {notReadyJobs.length} 个暂缺物料附件
                </span>
              )}
            </div>
          </div>

          {/* 缺料岗位清单（若存在） */}
          {hasMissing && (
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 space-y-2">
              <div className="flex items-center justify-between text-[11px] text-amber-800 dark:text-amber-300 font-medium">
                <span>待自动补齐专属物料的岗位清单：</span>
                <span className="text-[10px] text-muted-foreground">
                  共 {notReadyJobs.length} 岗
                </span>
              </div>
              <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1">
                {notReadyJobs.map(({ job, missing }) => (
                  <div
                    key={job.id}
                    className="flex items-center justify-between py-1 px-2 rounded-lg bg-background/80 border border-border/50 text-[11px]"
                  >
                    <div className="truncate max-w-[280px]">
                      <span className="font-medium text-foreground">
                        {job.companyName}
                      </span>
                      <span className="text-muted-foreground ml-1.5">
                        {job.jobTitle}
                      </span>
                    </div>
                    <span className="text-[10px] text-amber-600 dark:text-amber-400 font-mono shrink-0 ml-2">
                      缺 {missing.join("/")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 自愈说明提示 */}
          <div className="flex items-start gap-2 p-3 rounded-xl bg-blue-500/5 border border-blue-500/20 text-xs text-muted-foreground leading-relaxed">
            <Sparkles className="size-4 text-blue-500 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-blue-600 dark:text-blue-400 mb-0.5">
                实时自愈与 SSE 批量任务流
              </p>
              <p className="text-[11px]">
                点击确认后，系统将自动派发批处理任务并打开实时进度流。若岗位尚未导出附件，系统将基于定制简历秒级渲染高保真
                PDF + 长图并上传飞书，全部放行入队「待投递」。
              </p>
            </div>
          </div>
        </div>

        {/* 底部操作按钮 */}
        <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-border/60">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="px-4 py-2 rounded-xl text-xs font-medium text-muted-foreground hover:bg-muted active:scale-95 transition-all cursor-pointer"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 shadow-sm active:scale-95 transition-all cursor-pointer"
          >
            <span>{hasMissing ? "一键自动补齐并批准 ➔" : "立即批准入队「待投递」 ➔"}</span>
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
