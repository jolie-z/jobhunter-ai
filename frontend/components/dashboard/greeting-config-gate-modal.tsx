"use client"

import React from "react"
import { useRouter } from "next/navigation"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { MessageSquareText, ArrowRight, AlertCircle, Building2, Briefcase } from "lucide-react"
import type { JobData } from "@/types/job"

interface GreetingConfigGateModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selectedJobs?: JobData[]
}

export function GreetingConfigGateModal({
  open,
  onOpenChange,
  selectedJobs = [],
}: GreetingConfigGateModalProps) {
  const router = useRouter()

  const handleGoToConfig = () => {
    onOpenChange(false)
    router.push("/prototype/command-center?drawer=greeting")
  }

  // 提取需要打招呼语的直聊平台岗位
  const directChatJobs = selectedJobs.filter(
    (j) => j.platform?.includes("BOSS") || j.platform?.includes("猎聘") || j.platform?.includes("智联")
  )
  const displayJobs = directChatJobs.length > 0 ? directChatJobs : selectedJobs

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px] p-6 gap-5 bg-white border border-slate-200/90 shadow-2xl rounded-2xl animate-in fade-in zoom-in-95 duration-200">
        <DialogHeader className="gap-2.5 text-left">
          <div className="flex items-start gap-3.5">
            <div className="size-11 rounded-xl bg-amber-50 border border-amber-200/80 flex items-center justify-center shrink-0 shadow-xs">
              <MessageSquareText className="size-5 text-amber-600" />
            </div>
            <div className="space-y-1">
              <DialogTitle className="text-base font-bold text-slate-900 tracking-tight">
                尚未配置「海投通用打招呼语」
              </DialogTitle>
              <DialogDescription className="text-xs text-slate-500 leading-relaxed">
                一键海投需要使用您统一预设的标准破冰问候语与招聘方建立初步沟通。
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* 核心提示与业务说明 */}
        <div className="rounded-xl border border-amber-100 bg-amber-50/50 p-4 space-y-3">
          <div className="flex items-start gap-2 text-xs text-amber-800/90">
            <AlertCircle className="size-4 text-amber-600 shrink-0 mt-0.5" />
            <span className="leading-snug">
              直聊平台（BOSS直聘、猎聘、智联招聘等）要求在发起投递沟通时发送第一句问候语。统一预设开场白可杜绝机械化硬编码，极大提升 HR 首聊回复率。
            </span>
          </div>

          <div className="pt-2 border-t border-amber-200/40 flex items-center justify-between text-[11px] text-amber-900/80">
            <span>配置入口</span>
            <span className="font-semibold text-amber-700 bg-amber-100/60 px-2 py-0.5 rounded-md">
              全链路中心 ➔ 打招呼语模块
            </span>
          </div>
        </div>

        {/* 本次涉及岗位预览 */}
        {selectedJobs.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] text-slate-500 px-0.5">
              <span>本次待海投岗位预览：</span>
              <span className="font-medium text-slate-700">共已选 {selectedJobs.length} 个</span>
            </div>
            <div className="max-h-[140px] overflow-y-auto space-y-1.5 pr-1">
              {displayJobs.slice(0, 3).map((job) => (
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
                  <span className="text-[10px] text-slate-400 shrink-0 ml-2 font-mono">
                    {job.platform || "直聊"}
                  </span>
                </div>
              ))}
              {displayJobs.length > 3 && (
                <p className="text-[10px] text-center text-slate-400 pt-0.5">
                  … 以及其余 {displayJobs.length - 3} 个岗位
                </p>
              )}
            </div>
          </div>
        )}

        {/* 底部行动操作 */}
        <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-100">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="px-4 py-2 rounded-xl text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors"
          >
            暂不配置
          </button>
          <button
            type="button"
            onClick={handleGoToConfig}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 shadow-sm shadow-blue-500/20 active:scale-[0.98] transition-all"
          >
            <span>前往配置打招呼语</span>
            <ArrowRight className="size-3.5" />
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
