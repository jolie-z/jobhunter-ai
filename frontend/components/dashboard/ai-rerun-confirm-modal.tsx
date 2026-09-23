"use client"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { RefreshCw, AlertCircle, Building2, Briefcase } from "lucide-react"
import type { JobData } from "@/types/job"
import { AI_ARTIFACT_LABELS, type AiArtifactKind } from "@/lib/ai-artifacts"

interface AiRerunConfirmModalProps {
  open: boolean
  kind: AiArtifactKind | null
  /** 命中「已存在产物」的岗位列表 */
  existingJobs: JobData[]
  /** 批量场景传入本次已选岗位总数；单岗位场景不传（按"该岗位"表述） */
  totalCount?: number
  onConfirm: () => void
  onCancel: () => void
}

/**
 * 重复发起 AI 任务二次确认弹窗（AI初评/深度评估/简历改写/打招呼语通用）：
 * 检测到岗位已存在对应产物时，再次发起将覆盖旧结果并消耗 Token，需用户明确确认。
 */
export function AiRerunConfirmModal({
  open,
  kind,
  existingJobs,
  totalCount,
  onConfirm,
  onCancel,
}: AiRerunConfirmModalProps) {
  if (!kind) return null
  const label = AI_ARTIFACT_LABELS[kind]
  const isBatch = typeof totalCount === "number" && totalCount > 1

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="sm:max-w-[500px] p-6 gap-5 bg-white border border-slate-200/90 shadow-2xl rounded-2xl animate-in fade-in zoom-in-95 duration-200">
        <DialogHeader className="gap-2.5 text-left">
          <div className="flex items-start gap-3.5">
            <div className="size-11 rounded-xl bg-amber-50 border border-amber-200/80 flex items-center justify-center shrink-0 shadow-xs">
              <RefreshCw className="size-5 text-amber-600" />
            </div>
            <div className="space-y-1">
              <DialogTitle className="text-base font-bold text-slate-900 tracking-tight">
                再次发起「{label}」确认
              </DialogTitle>
              <DialogDescription className="text-xs text-slate-500 leading-relaxed">
                检测到{isBatch ? `已选 ${totalCount} 个岗位中的 ${existingJobs.length} 个` : "该岗位"}
                已存在「{label}」结果，是否要再次发起「{label}」？再次发起将消耗 Token。
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* 覆盖提示 */}
        <div className="rounded-xl border border-amber-100 bg-amber-50/50 p-4 space-y-2">
          <div className="flex items-start gap-2 text-xs text-amber-800/90">
            <AlertCircle className="size-4 text-amber-600 shrink-0 mt-0.5" />
            <span className="leading-snug">
              再次发起会用新生成结果覆盖该岗位现有的「{label}」产物，旧结果不可恢复。若只是想查看已有结果，请选择「取消」。
            </span>
          </div>
        </div>

        {/* 命中岗位预览 */}
        {existingJobs.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] text-slate-500 px-0.5">
              <span>已存在「{label}」结果的岗位：</span>
              <span className="font-medium text-slate-700">
                共 {existingJobs.length} 个{isBatch ? ` / 已选 ${totalCount} 个` : ""}
              </span>
            </div>
            <div className="max-h-[140px] overflow-y-auto space-y-1.5 pr-1">
              {existingJobs.slice(0, 5).map((job) => (
                <div
                  key={job.id}
                  className="flex items-center justify-between p-2 rounded-lg bg-slate-50 border border-slate-100 text-xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Building2 className="size-3.5 text-slate-400 shrink-0" />
                    <span className="font-medium text-slate-800 truncate max-w-[150px]">
                      {job.companyName}
                    </span>
                    <span className="text-slate-300">·</span>
                    <Briefcase className="size-3.5 text-slate-400 shrink-0" />
                    <span className="text-slate-600 truncate max-w-[140px]">
                      {job.jobTitle}
                    </span>
                  </div>
                </div>
              ))}
              {existingJobs.length > 5 && (
                <p className="text-[10px] text-center text-slate-400 pt-0.5">
                  … 以及其余 {existingJobs.length - 5} 个岗位
                </p>
              )}
            </div>
          </div>
        )}

        {/* 底部行动操作 */}
        <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-100">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-xl text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-amber-600 hover:bg-amber-700 shadow-sm shadow-amber-500/20 active:scale-[0.98] transition-all"
          >
            <RefreshCw className="size-3.5" />
            <span>确认，再次发起</span>
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
