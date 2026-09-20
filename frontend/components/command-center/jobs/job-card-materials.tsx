"use client"

import React from "react"
import {
  FileText,
  Image as ImageIcon,
  MessageSquare,
  CheckCircle2,
} from "lucide-react"
import { PipelineJob } from "@/store/pipeline-store"
import { cn } from "@/lib/utils"
import { formatFullDateTime } from "../types"
import { isGreetingSupportedPlatform } from "@/lib/platform-utils"

interface JobCardMaterialsProps {
  job: PipelineJob
  isWaiting: boolean
  isReadyToDeliver: boolean
  isDelivered: boolean
  isCustomJob: boolean
  isZhilian: boolean
  /** 长图简历为 BOSS 微聊专属物料，仅 BOSS 卡片展示 */
  isBoss?: boolean
  /** 平台是否具备微聊/IM打招呼外发能力（若未传则按 job.platform 自动计算） */
  supportsGreeting?: boolean
  resendingGreeting?: boolean
  onPreview: (tab: "resume" | "greeting") => void
  onResendGreeting?: (e: React.MouseEvent) => void
}

export const JobCardMaterials = React.memo(function JobCardMaterials({
  job,
  isWaiting,
  isReadyToDeliver,
  isDelivered,
  isCustomJob,
  isZhilian,
  isBoss = false,
  supportsGreeting,
  resendingGreeting,
  onPreview,
  onResendGreeting,
}: JobCardMaterialsProps) {
  const canSendGreeting = supportsGreeting ?? isGreetingSupportedPlatform(job.platform)

  // 已送达物料对称原则：BOSS 微聊只发长图，PDF 简历仅附件投递平台展示；
  // 智联记录缺字段时兜底展示（后端缺省即视为已送达 PDF）
  const showPdfResume =
    !isBoss &&
    (isZhilian ? (job.delivery_materials?.pdf ?? true) : Boolean(job.delivery_materials?.pdf))

  return (
    <>
      {/* 精投 / 海投物料就绪提示 & Double Check 快捷核验按钮 */}
      {(isWaiting || isReadyToDeliver) && (
        <div className="flex items-center gap-1.5 flex-wrap mt-2.5">
          <button
            type="button"
            onClick={() => onPreview("resume")}
            className={cn(
              "rounded px-2 py-0.5 text-[10px] font-medium flex items-center gap-1 border transition-all cursor-pointer active:scale-95 shadow-2xs hover:brightness-95",
              isCustomJob
                ? "bg-amber-500/10 hover:bg-amber-500/20 text-amber-800 dark:text-amber-200 border-amber-500/35"
                : "bg-blue-500/10 hover:bg-blue-500/20 text-blue-700 dark:text-blue-300 border-blue-500/25"
            )}
            title="点击核验投递简历 (A4高清排版/PDF预览)"
          >
            <FileText className="h-2.5 w-2.5" />
            <span>{isCustomJob ? "专属定制简历" : "通用海投简历"}</span>
            <span className="text-[9px] opacity-75 underline decoration-dotted font-normal">预览</span>
          </button>

          {canSendGreeting && (
            <button
              type="button"
              onClick={() => onPreview("greeting")}
              className="rounded px-2 py-0.5 text-[10px] font-medium flex items-center gap-1 border bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-500/25 transition-all cursor-pointer active:scale-95 shadow-2xs"
              title="点击核验投递时的微聊打招呼语"
            >
              <MessageSquare className="h-2.5 w-2.5" />
              <span>欢迎语</span>
              <span className="text-[9px] opacity-75 underline decoration-dotted font-normal">核验</span>
            </button>
          )}
        </div>
      )}

      {/* 已投递物料展示区 */}
      {isDelivered && (
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-1.5 rounded-lg bg-emerald-500/5 border border-emerald-500/20 px-2 py-1 text-[10px] text-emerald-700 dark:text-emerald-300 font-medium">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="opacity-75">已送达:</span>
            {/* PDF 简历为附件投递平台专属物料：BOSS 微聊只发长图，严格屏蔽 */}
            {showPdfResume && (
              <button
                type="button"
                onClick={() => onPreview("resume")}
                className="inline-flex items-center gap-0.5 bg-emerald-500/10 hover:bg-emerald-500/20 px-1.5 py-0.5 rounded transition-all cursor-pointer"
                title="点击回看投递的 PDF 简历"
              >
                <FileText className="h-2.5 w-2.5" /> PDF简历
              </button>
            )}
            {/* 长图简历为 BOSS 微聊专属物料：智联/51job/猎聘均为纯附件 PDF 投递，严格屏蔽 */}
            {isBoss && job.delivery_materials?.image && (
              <button
                type="button"
                onClick={() => onPreview("resume")}
                className="inline-flex items-center gap-0.5 bg-emerald-500/10 hover:bg-emerald-500/20 px-1.5 py-0.5 rounded transition-all cursor-pointer"
                title="点击回看长图简历"
              >
                <ImageIcon className="h-2.5 w-2.5" /> 长图简历
              </button>
            )}
            {/* 微聊即时送达欢迎语（完全依据真实回执判定，杜绝假阳性）：精投为专用欢迎语，海投为通用欢迎语 */}
            {Boolean(job.delivery_materials?.greeting) && (
              <button
                type="button"
                onClick={() => onPreview("greeting")}
                className="inline-flex items-center gap-0.5 bg-emerald-500/10 hover:bg-emerald-500/20 px-1.5 py-0.5 rounded transition-all cursor-pointer"
                title={isCustomJob ? "点击回看送达的专用打招呼语" : "点击回看送达的通用打招呼语"}
              >
                <MessageSquare className="h-2.5 w-2.5" /> {isCustomJob ? "专用欢迎语" : "通用欢迎语"}
              </button>
            )}
            {/* 🌟 真实回执：配置了打招呼语但引擎未确认微聊送达 —— 点击唤起预览弹窗复核打招呼语内容 */}
            {Boolean(job.delivery_materials?.greeting_failed) && (
              <button
                type="button"
                onClick={() => onPreview("greeting")}
                className="inline-flex items-center gap-0.5 bg-amber-500/15 hover:bg-amber-500/25 px-1.5 py-0.5 rounded text-amber-700 dark:text-amber-400 border border-amber-500/30 transition-all cursor-pointer"
                title="附件简历已投递，但打招呼语未成功送达。点击回看/复核打招呼语内容"
              >
                <MessageSquare className="h-2.5 w-2.5" />
                打招呼未送达
              </button>
            )}
            {!job.delivery_materials?.pdf && !job.delivery_materials?.image && !job.delivery_materials?.greeting && (
              <span className="inline-flex items-center gap-0.5">
                <CheckCircle2 className="h-2.5 w-2.5" /> 快捷投递沟通
              </span>
            )}
          </div>
          {job.last_action_time && (
            <span className="font-mono text-[9px] opacity-80 shrink-0" title={`送达时间: ${job.last_action_time}`}>
              🚀 {formatFullDateTime(job.last_action_time)} 送达
            </span>
          )}
        </div>
      )}
    </>
  )
})
