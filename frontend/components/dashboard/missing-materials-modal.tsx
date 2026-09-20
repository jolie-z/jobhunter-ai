"use client"

import React, { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { AlertCircle, Edit3, Zap, Loader2, ArrowRight } from "lucide-react"
import { cn } from "@/lib/utils"
import type { JobData } from "@/types/job"

interface MissingMaterialsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: JobData | null
  materialStatus?: {
    has_pdf?: boolean
    has_image?: boolean
    has_greeting?: boolean
    has_url?: boolean
    has_custom_json?: boolean
    platform?: string
  } | null
  onEnterCustomDetail: (job: JobData) => void
  onAutoHealSuccess: () => Promise<void> | void
}

export function MissingMaterialsModal({
  open,
  onOpenChange,
  job,
  materialStatus,
  onEnterCustomDetail,
  onAutoHealSuccess,
}: MissingMaterialsModalProps) {
  const [isHealing, setIsHealing] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  if (!job) return null

  const handleAutoHeal = async () => {
    setIsHealing(true)
    setErrorMsg(null)
    try {
      const res = await fetch("http://127.0.0.1:8000/api/automation/auto-heal-and-approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: job.id }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        onOpenChange(false)
        await onAutoHealSuccess?.()
      } else {
        setErrorMsg(data.detail || data.message || "自动补全物料失败，请进入定制面板手动生成")
      }
    } catch (e: any) {
      setErrorMsg("网络请求异常，请检查后端服务是否正常运行")
    } finally {
      setIsHealing(false)
    }
  }

  const handleGoToDetail = () => {
    onOpenChange(false)
    onEnterCustomDetail(job)
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !isHealing && onOpenChange(v)}>
      <DialogContent className="sm:max-w-[480px] p-6 gap-5 bg-white border border-slate-200 shadow-xl rounded-2xl">
        <DialogHeader className="gap-2 text-left">
          <div className="flex items-center gap-3">
            <div className="size-10 rounded-xl bg-amber-50 border border-amber-200 flex items-center justify-center shrink-0">
              <AlertCircle className="size-5 text-amber-600" />
            </div>
            <div>
              <DialogTitle className="text-base font-bold text-slate-900">
                该岗位暂未生成专属简历物料
              </DialogTitle>
              <DialogDescription className="text-xs text-slate-500 mt-0.5">
                【{job.companyName} - {job.jobTitle}】缺少投递所需的简历附件
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* 状态检测标签 */}
        <div className="bg-slate-50 rounded-xl p-3.5 border border-slate-100 flex flex-col gap-2">
          <p className="text-[11px] font-medium text-slate-600">物料检测状态：</p>
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border",
                materialStatus?.has_pdf || materialStatus?.has_image
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : "bg-red-50 border-red-200 text-red-600 font-semibold"
              )}
            >
              {materialStatus?.has_pdf || materialStatus?.has_image ? "✓ 简历文件已就绪" : "✗ 缺少 PDF/图片简历"}
            </span>

            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border",
                materialStatus?.has_greeting
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : "bg-amber-50 border-amber-200 text-amber-700"
              )}
            >
              {materialStatus?.has_greeting ? "✓ 专属打招呼语" : "— 缺招呼语 (将套用海投通用语)"}
            </span>
          </div>
        </div>

        {errorMsg && (
          <div className="px-3 py-2 bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg">
            {errorMsg}
          </div>
        )}

        {/* 双选择操作卡片 */}
        <div className="flex flex-col gap-3">
          {/* 选项 1: 进入定制面板精修 */}
          <button
            type="button"
            onClick={handleGoToDetail}
            disabled={isHealing}
            className="group relative flex items-start gap-3.5 p-3.5 rounded-xl border border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/40 text-left transition-all cursor-pointer shadow-xs disabled:opacity-50"
          >
            <div className="size-9 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600 shrink-0 group-hover:scale-105 transition-transform">
              <Edit3 className="size-4.5" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-800 group-hover:text-blue-600 transition-colors">
                  ✏️ 进入定制面板精修 (推荐)
                </span>
                <ArrowRight className="size-3.5 text-slate-400 group-hover:text-blue-600 group-hover:translate-x-0.5 transition-all" />
              </div>
              <p className="text-[11px] text-slate-500 mt-1 leading-relaxed">
                打开定制工作台，人工核对经历亮点、微调文字并手动生成导出简历附件。
              </p>
            </div>
          </button>

          {/* 选项 2: 一键快速补齐并放行 */}
          <button
            type="button"
            onClick={handleAutoHeal}
            disabled={isHealing}
            className="group relative flex items-start gap-3.5 p-3.5 rounded-xl border border-orange-200 bg-orange-50/50 hover:border-orange-400 hover:bg-orange-50 text-left transition-all cursor-pointer shadow-xs disabled:opacity-50"
          >
            <div className="size-9 rounded-lg bg-orange-100 border border-orange-300 flex items-center justify-center text-orange-600 shrink-0 group-hover:scale-105 transition-transform">
              {isHealing ? (
                <Loader2 className="size-4.5 animate-spin text-orange-600" />
              ) : (
                <Zap className="size-4.5" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-orange-950 group-hover:text-orange-700 transition-colors">
                  ⚡ 一键快速补齐并放行
                </span>
                {isHealing && (
                  <span className="text-[10px] text-orange-600 font-semibold animate-pulse">
                    正在秒级渲染上传...
                  </span>
                )}
              </div>
              <p className="text-[11px] text-orange-900/70 mt-1 leading-relaxed">
                系统基于改写/基准内容自动直出 PDF 并上传飞书，打招呼语缺省时自动套用全局海投语，直接放行进「待投递」队列。
              </p>
            </div>
          </button>
        </div>

        {/* 底部取消 */}
        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={isHealing}
            className="px-4 py-1.5 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
          >
            取消
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
