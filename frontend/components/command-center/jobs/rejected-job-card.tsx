"use client"

import React, { useState } from "react"
import {
  Bot,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Building2,
  MapPin,
  Clock,
  SlidersHorizontal,
  ExternalLink
} from "lucide-react"
import { PipelineJob, usePipelineStore } from "@/store/pipeline-store"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"
import { getPlatformTheme } from "../types"

interface RejectedJobCardProps {
  job: PipelineJob
}

// 格式化时间，保证完整显示日期与时间（例如："08-27 14:30"）
function formatFullDateTime(timeStr?: string): string {
  if (!timeStr) return ""
  try {
    const trimmed = timeStr.trim()
    const parts = trimmed.split(" ")
    if (parts.length === 2) {
      const [d, t] = parts
      const datePart = d.length > 5 ? d.slice(5) : d
      const timePart = t.length >= 8 ? t : t.slice(0, 5)
      return `${datePart} ${timePart}`
    }
    if (trimmed.includes("T")) {
      const datePart = trimmed.slice(5, 10)
      const timePart = trimmed.slice(11, 16)
      return `${datePart} ${timePart}`
    }
    return trimmed.slice(5, 19)
  } catch {
    return timeStr
  }
}

// memo：岗位池大时避免无关岗位更新触发本卡片重渲染
export const RejectedJobCard = React.memo(function RejectedJobCard({ job }: RejectedJobCardProps) {
  const [showJd, setShowJd] = useState(false)
  const [processing, setProcessing] = useState(false)
  const updateJob = usePipelineStore((s) => s.updateJob)
  const removeJob = usePipelineStore((s) => s.removeJob)
  const pipelineTaskId = usePipelineStore((s) => s.pipelineTaskId)
  const platTheme = getPlatformTheme(job.platform)

  const isManual = job.reject_type === "manual"
  const isAi = job.reject_type === "ai" || (!isManual && !!job.status && job.status.includes("ai"))
  const jobLink = job.job_url || ""
  const customPanelUrl = `/?job_id=${encodeURIComponent(job.job_id)}`

  // 放行并推送到下一阶段
  const handleUnreject = async () => {
    setProcessing(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/processor/unreject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.job_id,
          job_link: jobLink || undefined,
          pipeline_task_id: pipelineTaskId || undefined,
        }),
      })
      const data = await res.json()
      if (res.ok && (data.status === "success" || data.code === 0)) {
        toast.success("✅ 岗位已放行，正在启动 AI 评估与流转...")
        // 放行后将岗位状态转为 running/AI初评中
        updateJob(job.job_id, {
          status: "running",
          node: "evaluate_node",
          sub_status: "ai_eval",
          reject_reason: undefined,
          reject_type: undefined,
        })
      } else {
        toast.error(`放行失败: ${data.message || data.detail || "未知错误"}`)
      }
    } catch {
      toast.error("网络错误，放行失败")
    } finally {
      setProcessing(false)
    }
  }

  // 确认淘汰（彻底归档）
  const handleConfirmReject = async () => {
    setProcessing(true)
    try {
      const res = await fetch(`${API_BASE}/api/v1/processor/confirm-reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.job_id,
          job_link: jobLink || undefined,
        }),
      })
      const data = await res.json()
      if (res.ok && (data.status === "success" || data.code === 0)) {
        removeJob(job.job_id)
        toast.info("已确认淘汰并归档")
      } else {
        toast.error(`操作失败: ${data.message || data.detail || "未知错误"}`)
      }
    } catch {
      toast.error("网络错误，操作失败")
    } finally {
      setProcessing(false)
    }
  }

  return (
    <div className="bg-card border border-border/80 rounded-xl p-4 shadow-xs flex flex-col gap-3 transition-all hover:shadow-md hover:border-border">
      {/* 顶栏：标签 + 岗位名称 + 薪资 + 操作按钮 */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            {/* 淘汰类型 Tag */}
            <span
              className={cn(
                "text-[10px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 border shrink-0",
                isManual
                  ? "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/20"
                  : isAi
                    ? "bg-purple-500/10 text-purple-700 dark:text-purple-300 border-purple-500/20"
                    : "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20"
              )}
            >
              {isManual ? <XCircle className="h-3 w-3" /> : isAi ? <Bot className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
              {isManual ? "人工拒绝" : isAi ? "AI排雷" : "规则拦截"}
            </span>

            {/* 岗位标题 */}
            <h3 className="text-xs sm:text-sm font-bold text-foreground truncate max-w-[220px]" title={job.job_name}>
              {job.job_name}
            </h3>

            {/* 薪资 */}
            {job.salary && (
              <span className="text-xs sm:text-sm font-bold text-rose-500 shrink-0">
                {job.salary}
              </span>
            )}
          </div>

          {/* 公司 & 城市 */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground font-medium">
            <span className="flex items-center gap-1 truncate max-w-[160px]">
              <Building2 className="h-3 w-3 shrink-0" />
              {job.company_name || "未知企业"}
            </span>
            {job.city && (
              <>
                <span className="text-muted-foreground/40">|</span>
                <span className="flex items-center gap-0.5 shrink-0">
                  <MapPin className="h-3 w-3" />
                  {job.city}
                </span>
              </>
            )}
            {job.platform && (
              <span className={cn("rounded px-1.5 py-0.2 text-[9px] font-medium border shrink-0", platTheme.bg, platTheme.text, platTheme.border)}>
                {platTheme.name}
              </span>
            )}
            {job.crawl_time && (
              <>
                <span className="text-muted-foreground/40">|</span>
                <span className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground/80 shrink-0" title={`入库抓取时间: ${job.crawl_time}`}>
                  <Clock className="h-2.5 w-2.5" />
                  抓取: {formatFullDateTime(job.crawl_time)}
                </span>
              </>
            )}
          </div>
        </div>

        {/* 右侧：操作按钮 */}
        <div className="flex items-center gap-1.5 shrink-0">
          <a
            href={customPanelUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex h-7 items-center gap-1 rounded-lg border border-border/80 bg-background px-2 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground transition-all active:scale-95 shadow-xs"
            title="新标签页打开定制面板"
          >
            <SlidersHorizontal className="h-3 w-3" />
            定制面板 ↗
          </a>

          <button
            onClick={handleUnreject}
            disabled={processing}
            className="flex h-7 items-center gap-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 px-2.5 text-[11px] font-medium text-white shadow-xs transition-all active:scale-95 disabled:opacity-50"
          >
            <CheckCircle2 className="h-3 w-3" />
            放行并推送
          </button>

          <button
            onClick={handleConfirmReject}
            disabled={processing}
            className="flex h-7 items-center gap-1 rounded-lg border border-border bg-background px-2 text-[11px] text-muted-foreground hover:bg-rose-50 hover:text-rose-600 hover:border-rose-200 transition-all active:scale-95 disabled:opacity-50"
          >
            <XCircle className="h-3 w-3" />
            确认淘汰
          </button>
        </div>
      </div>

      {/* 死因高亮警示条（对应图3） */}
      <div className="rounded-lg bg-rose-500/10 border border-rose-500/20 px-3 py-2 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-1.5">
        <ShieldAlert className="h-3.5 w-3.5 shrink-0 mt-0.5 text-rose-500" />
        <div className="flex-1">
          <span className="font-semibold">死因: </span>
          <span>{job.reject_reason || (isManual ? "老板人工审批拒绝" : isAi ? "触发 AI 侦察兵排雷规则" : "触发硬性清洗规则")}</span>
          {job.last_action_time && (
            <span className="font-mono text-[10px] opacity-75 ml-2">
              (判定于 {formatFullDateTime(job.last_action_time)})
            </span>
          )}
        </div>
      </div>

      {/* 展开 JD 全文查看是否误杀 */}
      {job.jd_text && (
        <div>
          <button
            onClick={() => setShowJd(!showJd)}
            className="flex items-center gap-1 text-[11px] font-medium text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
          >
            {showJd ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {showJd ? "收起 JD 详情" : "▶ 展开 JD 全文查看是否误杀"}
          </button>

          {showJd && (
            <div className="mt-2 p-3 rounded-lg bg-muted/40 border border-border/60 text-xs text-muted-foreground whitespace-pre-wrap max-h-60 overflow-y-auto leading-relaxed">
              {job.jd_text}
            </div>
          )}
        </div>
      )}
    </div>
  )
})
