"use client"

import React, { useState } from "react"
import {
  AlertTriangle,
  RotateCcw,
  Building2,
  MapPin,
  Briefcase,
  GraduationCap,
  Clock,
  ExternalLink,
  Lightbulb,
  SlidersHorizontal,
  ChevronDown,
  ChevronUp,
  Trash2,
  Stethoscope
} from "lucide-react"
import { PipelineJob, usePipelineStore } from "@/store/pipeline-store"
import { API_BASE } from "@/lib/api"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { GRADE_COLOR_MAP, getPlatformTheme } from "../types"
import { FailedJobCheckbox } from "./failed-job-checkbox"
import { FailedDiagnosisReport } from "./failed-diagnosis-report"

interface FailedJobCardProps {
  job: PipelineJob
  selected?: boolean
  onToggleSelect?: (jobId: string) => void
  onRetry?: (job: PipelineJob) => void
  onDismiss?: (job: PipelineJob) => void
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
      return `${datePart} ${t.slice(0, 5)}`
    }
    if (trimmed.includes("T")) {
      return `${trimmed.slice(5, 10)} ${trimmed.slice(11, 16)}`
    }
    return trimmed.slice(5, 16)
  } catch {
    return timeStr
  }
}

export const FailedJobCard = React.memo(function FailedJobCard({
  job,
  selected = false,
  onToggleSelect,
  onRetry,
  onDismiss,
}: FailedJobCardProps) {
  const [retrying, setRetrying] = useState(false)
  const [dismissing, setDismissing] = useState(false)
  const [showDetail, setShowDetail] = useState(false)
  const [diagLoading, setDiagLoading] = useState(false)
  const platTheme = getPlatformTheme(job.platform)
  const platDisplayName = platTheme.name

  // 防御性访问 failure_info 字段
  const failureInfo = job.failure_info || {}
  const canRetry = failureInfo?.can_retry !== false
  const stepName = failureInfo?.step || (job.node === "delivery_node" ? "自动投递阶段" : "数据处理/评估阶段")
  const reasonText = failureInfo?.reason || "流水线节点处理超时或网络连接异常"
  const suggestionText = failureInfo?.suggestion || "建议检查对应平台浏览器登录态是否过期，或点击右下角重试按钮重新发起该岗位流水线。"

  const customPanelUrl = `/?job_id=${encodeURIComponent(job.job_id)}`
  const failTime = job.last_action_time || (failureInfo as any)?.failed_at || ""
  const failureCount = (failureInfo as any)?.failure_count || 1
  const triageNote = (failureInfo as any)?.triage_note || ""
  const isPersistent = (failureInfo as any)?.triage === "persistent"
  const healLog: any[] = (failureInfo as any)?.heal_log || []
  const [diagnosis, setDiagnosis] = useState<any>((failureInfo as any)?.diagnosis || null)

  const normalizedGrade = job.grade ? job.grade.toUpperCase() : ""
  const gradeStyle = normalizedGrade ? GRADE_COLOR_MAP[normalizedGrade] : null

  // AI 诊断官（L3）：读取后端日志 + 引擎失败日志 → LLM 产出死因/分类/修复工单
  const handleDiagnose = async () => {
    setDiagLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/diagnose-failure`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.job_id }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success" && data.data) {
        setDiagnosis(data.data)
        toast.success("🔬 AI 诊断完成")
      } else {
        toast.error(`诊断失败: ${data.detail || data.message || "未知错误"}`)
      }
    } catch {
      toast.error("网络异常，无法连接诊断服务")
    } finally {
      setDiagLoading(false)
    }
  }

  // 重启/重试此岗位
  const handleRetry = async () => {
    if (onRetry) {
      onRetry(job)
      return
    }
    setRetrying(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/retry-failed-job`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.job_id,
          job_url: job.job_url || "",
          pipeline_task_id: job.pipeline_task_id || "",
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        toast.success(`⚡ 岗位【${job.job_name}】已重新加入流水线重试`)
        const st = usePipelineStore.getState()
        if (st.jobs[job.job_id]) {
          st.updateJob(job.job_id, {
            status: "running",
            node: "delivery_node",
            sub_status: "delivering",
            failure_info: undefined,
            last_action_desc: "正在自动重试投递中…",
          })
        }
      } else {
        toast.error(`重试启动失败: ${data.detail || data.message || "未知错误"}`)
      }
    } catch {
      toast.error("网络异常，无法连接后端重试服务")
    } finally {
      setRetrying(false)
    }
  }

  // 放弃此岗位（移出指挥中心）
  const handleDismiss = async () => {
    setDismissing(true)
    try {
      if (onDismiss) {
        await onDismiss(job)
        return
      }
      const res = await fetch(`${API_BASE}/api/automation/dismiss-failed-job`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: job.job_id,
          job_url: job.job_url || "",
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        const jobTitle = job.job_name || job.company_name || "受阻岗位"
        toast.info(`🗑️ 已放弃【${jobTitle}】：跟进状态改为「已放弃投递」，不会再自动投递`)
        const st = usePipelineStore.getState()
        const nextJobs = { ...st.jobs }
        delete nextJobs[job.job_id]
        usePipelineStore.setState({ jobs: nextJobs })
      } else {
        toast.error("放弃操作失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      toast.error("网络异常，无法连接后端放弃服务")
    } finally {
      setDismissing(false)
    }
  }

  return (
    <div
      className={cn(
        "group relative flex flex-col justify-between rounded-xl border p-4 transition-all duration-200 hover:shadow-md",
        selected
          ? "border-rose-500 bg-rose-500/[0.04] shadow-xs dark:bg-rose-950/20"
          : "border-rose-500/30 bg-card hover:border-rose-500/50"
      )}
    >
      <div className="space-y-3">
        {/* 头部：公司 & 平台 Logo + 岗位标题 + 薪资与评级 */}
        <div className="flex items-start justify-between gap-3">
          {/* 左侧：多选框 + 平台微图标 + 公司名 + 岗位名 */}
          <div className="flex items-start gap-2.5 min-w-0 flex-1">
            {onToggleSelect && (
              <div className="pt-2 shrink-0">
                <FailedJobCheckbox
                  checked={Boolean(selected)}
                  onChange={() => onToggleSelect(job.job_id)}
                />
              </div>
            )}

            <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-white font-bold text-[11px] shadow-xs", platTheme.badgeBg)}>
              {platDisplayName.slice(0, 2)}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[12px] font-semibold text-foreground/90 flex items-center gap-1 truncate max-w-[200px]" title={job.company_name}>
                  <Building2 className="h-3 w-3 text-muted-foreground shrink-0" />
                  {job.company_name || "未知企业"}
                </span>
                <span className={cn("rounded-full px-1.5 py-0.2 text-[9px] font-medium border shrink-0", platTheme.bg, platTheme.text, platTheme.border)}>
                  {platDisplayName}
                </span>
              </div>

              {/* 岗位标题与外链 */}
              <div className="flex items-center gap-1.5 mt-1">
                <h3 className="text-xs sm:text-sm font-bold text-foreground truncate group-hover:text-rose-600 dark:group-hover:text-rose-400 transition-colors" title={job.job_name}>
                  {job.job_name}
                </h3>
                {job.job_url && (
                  <a
                    href={job.job_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-muted-foreground hover:text-foreground transition-colors p-0.5 shrink-0"
                    title="新窗口查看原始职位详情"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            </div>
          </div>

          {/* 右侧：薪资 & 评级 */}
          <div className="flex flex-col items-end shrink-0 gap-1">
            {job.salary && (
              <span className="text-xs sm:text-sm font-bold text-rose-600 dark:text-rose-400 font-mono">
                {job.salary}
              </span>
            )}
            {gradeStyle ? (
              <div className="flex items-center gap-1">
                <span className={cn("flex h-5 min-w-[20px] px-1 items-center justify-center rounded-full text-[10px] font-black border", gradeStyle.bg, gradeStyle.text, gradeStyle.border)}>
                  {normalizedGrade}
                </span>
                {job.score !== undefined && job.score !== null && (
                  <span className="text-[9px] font-bold text-muted-foreground">
                    {job.score}分
                  </span>
                )}
              </div>
            ) : (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-600 dark:text-rose-400 font-semibold border border-rose-500/20">
                受阻待办
              </span>
            )}
          </div>
        </div>

        {/* 基础属性标签栏：地点、经验、学历、规模、抓取时间、受阻时间 */}
        <div className="flex flex-wrap items-center gap-1.5">
          {job.city && (
            <span className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              <MapPin className="h-2.5 w-2.5" />
              {job.city}
            </span>
          )}
          {job.experience && (
            <span className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              <Briefcase className="h-2.5 w-2.5" />
              {job.experience}
            </span>
          )}
          {job.education && (
            <span className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              <GraduationCap className="h-2.5 w-2.5" />
              {job.education}
            </span>
          )}
          {job.company_scale && (
            <span className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              <Building2 className="h-2.5 w-2.5" />
              {job.company_scale}
            </span>
          )}
          {job.crawl_time && (
            <span className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground font-mono" title={`岗位入库抓取时间: ${job.crawl_time}`}>
              <Clock className="h-2.5 w-2.5 text-muted-foreground/70" />
              抓取: {formatFullDateTime(job.crawl_time)}
            </span>
          )}
          {failTime && (
            <span className="inline-flex items-center gap-1 rounded bg-rose-500/10 border border-rose-500/20 px-1.5 py-0.5 text-[10px] text-rose-700 dark:text-rose-300 font-mono font-medium" title={`发生受阻时间: ${failTime}`}>
              <AlertTriangle className="h-2.5 w-2.5 text-rose-500" />
              受阻: {formatFullDateTime(failTime)}
            </span>
          )}
        </div>

        {/* 统一故障诊断与自愈分析面板 */}
        <div className="rounded-lg bg-rose-500/[0.04] dark:bg-rose-950/20 border border-rose-500/20 p-2.5 space-y-2">
          {/* 阶段与分诊标签栏 */}
          <div className="flex items-center justify-between gap-2 flex-wrap text-[10px]">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="px-1.5 py-0.5 rounded font-semibold bg-rose-500/15 text-rose-800 dark:text-rose-200 border border-rose-500/30 flex items-center gap-1">
                <AlertTriangle className="h-2.5 w-2.5" />
                {stepName}受阻
              </span>

              {triageNote ? (
                <span
                  className={cn(
                    "px-1.5 py-0.5 rounded font-medium border",
                    isPersistent
                      ? "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/20"
                      : "bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/20"
                  )}
                >
                  🩺 {triageNote}
                  {failureCount > 1 && ` · 失败${failureCount}次`}
                </span>
              ) : (
                <span className="px-1.5 py-0.5 rounded font-medium bg-muted/60 text-muted-foreground border border-border/60">
                  失败 {failureCount} 次
                </span>
              )}
            </div>

            {failTime && (
              <span className="font-mono text-[9px] text-muted-foreground/80">
                {formatFullDateTime(failTime)}
              </span>
            )}
          </div>

          {/* 异常原因简报 */}
          <div className="rounded bg-background/80 border border-rose-500/15 p-2 text-xs font-mono text-rose-900 dark:text-rose-200 leading-relaxed break-all select-text">
            {reasonText}
          </div>

          {/* 推进建议 */}
          <div className="flex items-start gap-1.5 text-[11px] text-amber-800 dark:text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded p-2">
            <Lightbulb className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
            <div className="flex-1 leading-snug">
              <span className="font-semibold">推进建议：</span>
              <span>{suggestionText}</span>
            </div>
          </div>

          {/* 自愈历史记录 (如有) */}
          {healLog.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 pt-0.5 text-[9px]">
              <span className="text-muted-foreground">自愈记录:</span>
              {healLog.map((h, i) => (
                <span
                  key={i}
                  className={cn(
                    "px-1.5 py-0.2 rounded border font-mono",
                    h?.success
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20"
                      : "bg-muted text-muted-foreground border-border"
                  )}
                >
                  {h?.success ? "✅" : "⚠️"} {h?.detail || h?.action}
                  {h?.at ? ` @ ${h.at}` : ""}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* L3 AI 诊断报告 (如有) */}
        <FailedDiagnosisReport diagnosis={diagnosis} formatTime={formatFullDateTime} />

        {/* 展开/折叠 JD 信息 */}
        {job.jd_text && (
          <div className="pt-0.5">
            <button
              onClick={() => setShowDetail(!showDetail)}
              className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              {showDetail ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {showDetail ? "收起岗位原始 JD" : "▶ 查看岗位原始 JD 信息"}
            </button>

            {showDetail && (
              <div className="mt-1.5 p-2.5 rounded-lg bg-muted/40 border border-border/60 text-xs text-muted-foreground whitespace-pre-wrap max-h-48 overflow-y-auto leading-relaxed">
                {job.jd_text}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 底部操作栏：状态描述与操作按钮 */}
      <div className="flex items-center justify-between pt-3 border-t border-border/50 mt-3 gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 text-[11px] min-w-0">
          <span className="inline-flex items-center gap-1 text-rose-600 dark:text-rose-400 font-semibold truncate">
            <AlertTriangle className="h-3 w-3 shrink-0" />
            {isPersistent ? "持久故障 · 待人工介入" : "投递受阻 · 待重试自愈"}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0 flex-wrap">
          <button
            onClick={handleDiagnose}
            disabled={diagLoading}
            title="AI 诊断官：自动分析后端日志与引擎失败日志，产出死因与修复工单"
            className="flex h-7 items-center gap-1 rounded-md border border-violet-300 dark:border-violet-800 bg-violet-50 dark:bg-violet-950/50 px-2 text-[11px] font-medium text-violet-700 dark:text-violet-300 hover:bg-violet-100 hover:text-violet-900 dark:hover:bg-violet-900/40 transition-all active:scale-95 disabled:opacity-50 cursor-pointer shadow-xs"
          >
            <Stethoscope className={cn("h-3 w-3", diagLoading && "animate-spin")} />
            {diagLoading ? "诊断中…" : diagnosis ? "重新诊断" : "AI 诊断"}
          </button>

          <a
            href={customPanelUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground transition-all active:scale-95 shadow-xs"
            title="新标签页打开定制面板"
          >
            <SlidersHorizontal className="h-3 w-3" />
            定制 ↗
          </a>

          <button
            onClick={handleDismiss}
            disabled={dismissing || retrying}
            className="flex h-7 items-center gap-1 rounded-md border border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-950/30 px-2 text-[11px] font-medium text-rose-700 dark:text-rose-300 hover:bg-rose-100 hover:text-rose-900 transition-all active:scale-95 disabled:opacity-50 cursor-pointer shadow-xs"
            title="放弃该岗位并移出看板（飞书端状态将同步为已放弃）"
          >
            <Trash2 className="h-3 w-3" />
            {dismissing ? "放弃中…" : "放弃"}
          </button>

          <button
            onClick={handleRetry}
            disabled={retrying || !canRetry}
            title={canRetry ? "重新拉起该岗位全链路流转" : "该失败类型暂不支持自动重试"}
            className="flex h-7 items-center gap-1 rounded-md bg-rose-600 hover:bg-rose-500 px-2.5 text-[11px] font-medium text-white shadow-xs transition-all active:scale-95 disabled:opacity-50 cursor-pointer"
          >
            <RotateCcw className={cn("h-3 w-3", retrying && "animate-spin")} />
            {retrying ? "重试中…" : "重试"}
          </button>
        </div>
      </div>
    </div>
  )
})
