"use client"

import React, { useState } from "react"
import {
  ExternalLink,
  Building2,
  MapPin,
  GraduationCap,
  Briefcase,
  Clock,
  CheckCircle2,
  Sparkles,
  Send,
  SlidersHorizontal,
  AlertCircle,
  Truck,
  RotateCcw,
  Loader2,
  Square
} from "lucide-react"
import { PipelineJob } from "@/store/pipeline-store"
import { GRADE_COLOR_MAP, getPlatformTheme, formatFullDateTime } from "../types"
import { cn } from "@/lib/utils"
import { isJobDelivered, isJobReadyToDeliver, isJobRejected, isJobWaitingReview } from "../job-predicates"
import { JobMaterialPreviewModal } from "./job-material-preview-modal"
import { useResendGreeting } from "./use-resend-greeting"
import { JobCardMaterials } from "./job-card-materials"
import { isGreetingSupportedPlatform } from "@/lib/platform-utils"

interface JobCardProps {
  job: PipelineJob
  isApproving?: boolean
  isCancelling?: boolean
  onApprove?: (jobId: string, action: "approve" | "reject") => void
  onDeliverSingle?: (jobId: string) => void
  onCancelDelivery?: (jobId: string) => void
}

// memo：岗位池大时，单个岗位的 SSE 更新不应让全部卡片重渲染
// （依赖 live-jobs-board 的 handleApprove 已 useCallback 保持引用稳定）
export const JobCard = React.memo(function JobCard({
  job,
  isApproving,
  isCancelling,
  onApprove,
  onDeliverSingle,
  onCancelDelivery,
}: JobCardProps) {

  const [previewModalOpen, setPreviewModalOpen] = useState(false)
  const [previewTab, setPreviewTab] = useState<"resume" | "greeting">("resume")
  const { resending: resendingGreeting, resendGreeting } = useResendGreeting(job)

  // Q14：收敛到 job-predicates 单一判源（与内联判定在互斥状态下语义等价）
  const isWaiting = isJobWaitingReview(job)
  const isReadyToDeliver = isJobReadyToDeliver(job)
  const isDelivered = isJobDelivered(job)
  const isRejected = isJobRejected(job)
  const isRunning =
    (job.status === "running" ||
      job.node === "evaluate_node" ||
      job.node === "rewrite_node" ||
      job.node === "deep_eval_node" ||
      job.node === "greeting_node" ||
      job.node === "quick_greeting_node") &&
    job.status !== "done" &&
    job.status !== "waiting" &&
    job.status !== "delivered" &&
    !isRejected &&
    job.sub_status !== "eval_done"
  const isDelivering = isRunning && (job.sub_status === "delivering" || job.node === "delivery_node")
  const normalizedGrade = job.grade ? job.grade.toUpperCase() : ""
  const gradeStyle = normalizedGrade ? GRADE_COLOR_MAP[normalizedGrade] : null


  // 规范化获取平台专属视觉主题（橙色猎聘、蓝色智联、绿色BOSS、金橙51job）
  const platTheme = getPlatformTheme(job.platform)
  const platDisplayName = platTheme.name
  const isZhilian =
    job.platform === "zhilian" || job.platform === "智联招聘" || job.platform === "智联" ||
    (typeof job.job_url === "string" && job.job_url.includes("zhaopin.com"))
  // 长图简历为 BOSS 直聘微聊专属物料，其余平台（含猎聘）一律不展示
  const isBoss =
    job.platform === "boss" || job.platform === "BOSS直聘" ||
    (typeof job.job_url === "string" && job.job_url.includes("zhipin.com"))
  // 平台是否具备微聊打招呼外发能力
  const supportsGreeting = isGreetingSupportedPlatform(job.platform)

  // 链接定制面板（沉浸工作台根路径）
  const customPanelUrl = `/?job_id=${encodeURIComponent(job.job_id)}`

  // 子阶段文案
  const getRunningStageText = () => {
    if (job.sub_status === "ai_eval_queued") return "AI初步评估排队中"
    if (job.sub_status === "deep_eval" || job.node === "deep_eval_node") return "AI深度画像评估中"
    if (job.sub_status === "rewriting" || job.node === "rewrite_node") return "定制简历改写中"
    if (job.sub_status === "greeting" || job.node === "greeting_node" || job.node === "quick_greeting_node") return "生成打招呼语中"
    if (job.sub_status === "delivering" || job.node === "delivery_node") return "正在自动投递中"
    return "AI初步评估打分中"
  }

  // 🌟 精投/海投标签只信后端 review_type（is_custom_record 口径），评级 A/B 仅作旧数据兜底。
  // 严禁拿 C 级私自反推海投：待投递的 C 级定制改写岗（AI改写JSON 在）实际按精投投递，
  // 此前按评级硬算曾把这类岗误标成「通用海投简历」
  const isCustomJob = job.review_type === "custom_tailored" || normalizedGrade === "A" || normalizedGrade === "B"
  const isCustomWaiting = isWaiting && isCustomJob

  return (
    <div
      className={cn(
        "group relative flex flex-col justify-between rounded-xl border p-4 transition-all duration-200 hover:shadow-md bg-card",
        isCustomWaiting
          ? "border-amber-500/50 bg-gradient-to-br from-amber-500/[0.04] via-background to-background ring-1 ring-amber-500/30 shadow-amber-500/10"
          : isWaiting
          ? "border-blue-400/40 bg-blue-500/[0.02] ring-1 ring-blue-500/20 shadow-blue-500/5"
          : isReadyToDeliver
          ? "border-blue-500/40 bg-blue-500/[0.02] ring-1 ring-blue-500/20 shadow-blue-500/5"
          : isDelivered
          ? "border-emerald-500/30 bg-emerald-500/[0.02]"
          : "border-border/80 hover:border-violet-500/30"
      )}
    >
      {/* 头部：公司 & 平台 Logo + 岗位标题 + 薪资 */}
      <div>
        <div className="flex items-start justify-between gap-3">
          {/* 左侧主体 */}
          <div className="flex items-start gap-2.5 min-w-0 flex-1">
            {/* 平台微图标 */}
            <div
              className={cn(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-white font-bold text-[11px] shadow-sm",
                platTheme.badgeBg
              )}
            >
              {platDisplayName.slice(0, 2)}
            </div>

            {/* 公司与岗位标题 */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[12px] font-semibold text-foreground/90 flex items-center gap-1 truncate max-w-[170px]">
                  <Building2 className="h-3 w-3 text-muted-foreground shrink-0" />
                  {job.company_name || "未知公司"}
                </span>
                <span className={cn("rounded-full px-1.5 py-0.2 text-[9px] font-medium border", platTheme.bg, platTheme.text, platTheme.border)}>
                  {platDisplayName}
                </span>
              </div>

              {/* 岗位标题与外链 */}
              <div className="flex items-center gap-1 mt-1">
                <h3 className="text-xs sm:text-sm font-bold text-foreground truncate group-hover:text-violet-600 transition-colors" title={job.job_name}>
                  {job.job_name}
                </h3>
                {job.job_url && (
                  <a
                    href={job.job_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-muted-foreground hover:text-foreground transition-colors p-0.5"
                    title="新窗口查看原始职位详情"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            </div>
          </div>

          {/* 右侧：等级徽章 & 薪资 */}
          <div className="flex flex-col items-end shrink-0 gap-1">
            {gradeStyle && (
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full text-xs font-black shadow-xs border transition-transform group-hover:scale-105",
                    gradeStyle.bg,
                    gradeStyle.text,
                    gradeStyle.border
                  )}
                >
                  {normalizedGrade}
                </div>
                {job.score !== undefined && job.score !== null && (
                  <span className="text-[9px] font-bold text-muted-foreground mt-0.5">
                    {job.score}分
                  </span>
                )}
              </div>
            )}
            {job.salary && (
              <span className="text-xs font-bold text-amber-600 dark:text-amber-400 font-mono">
                {job.salary}
              </span>
            )}
          </div>
        </div>

        {/* 标签栏：地点、经验、学历、规模、抓取时间 */}
        <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
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
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px]",
                isWaiting && !isCustomWaiting && (job.company_scale.includes("1000") || job.company_scale.includes("10000") || job.company_scale.includes("万人"))
                  ? "bg-rose-500/10 text-rose-700 dark:text-rose-300 border border-rose-500/25 font-semibold"
                  : "bg-muted/60 text-muted-foreground"
              )}
              title={
                isWaiting && !isCustomWaiting && (job.company_scale.includes("1000") || job.company_scale.includes("10000") || job.company_scale.includes("万人"))
                  ? "因公司规模 ≥ 1000人，已触发海投大厂防盲投拦截，进入审批池"
                  : "公司规模"
              }
            >
              <Building2 className="h-2.5 w-2.5" />
              {job.company_scale}
              {isWaiting && !isCustomWaiting && (job.company_scale.includes("1000") || job.company_scale.includes("10000") || job.company_scale.includes("万人")) && (
                <span className="text-[9px] text-rose-600 dark:text-rose-400 font-bold ml-0.5">
                  (大厂拦截)
                </span>
              )}
            </span>
          )}
          {job.crawl_time && (
            <span
              className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground font-mono"
              title={`岗位入库抓取时间: ${job.crawl_time}`}
            >
              <Clock className="h-2.5 w-2.5 text-muted-foreground/70" />
              抓取: {formatFullDateTime(job.crawl_time)}
            </span>
          )}
          {job.last_action_time && job.last_action_time !== job.crawl_time && !isDelivered && (
            <span
              className="inline-flex items-center gap-1 rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground font-mono"
              title={`最后执行时间: ${job.last_action_time} (${job.last_action_desc || "状态更新"})`}
            >
              <Sparkles className="h-2.5 w-2.5 text-violet-500/70" />
              动作: {formatFullDateTime(job.last_action_time)}
            </span>
          )}

          {/* 审批类型专属 Tag */}
          {isWaiting && (
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                isCustomWaiting
                  ? "bg-amber-500/15 text-amber-800 dark:text-amber-300 border border-amber-500/30 flex items-center gap-1"
                  : "bg-blue-500/10 text-blue-700 dark:text-blue-300 border border-blue-500/20"
              )}
            >
              {isCustomWaiting ? "🎯 精投改写审批 · 需细审" : "⚡ 海投规则审批 · 快速过目"}
            </span>
          )}

          {/* 待投递就绪 Tag */}
          {isReadyToDeliver && (
            <span className="rounded bg-blue-500/10 text-blue-700 dark:text-blue-300 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-semibold flex items-center gap-1">
              <Truck className="h-2.5 w-2.5" /> 待投递（已放行）
            </span>
          )}
        </div>

        {/* 精投 / 海投物料 & 已送达物料回检与快捷补发 */}
        <JobCardMaterials
          job={job}
          isWaiting={isWaiting}
          isReadyToDeliver={isReadyToDeliver}
          isDelivered={isDelivered}
          isCustomJob={isCustomJob}
          isZhilian={isZhilian}
          isBoss={isBoss}
          supportsGreeting={supportsGreeting}
          resendingGreeting={resendingGreeting}
          onPreview={(tab) => {
            setPreviewTab(tab)
            setPreviewModalOpen(true)
          }}
          onResendGreeting={resendGreeting}
        />
      </div>

      {/* 底部：状态指示与操作栏 */}
      <div className="flex items-center justify-between pt-3 border-t border-border/50 mt-3 gap-2">
        {/* 左侧状态展示 */}
        <div className="flex items-center gap-1.5 text-[11px] min-w-0">
          {isApproving ? (
            <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold truncate animate-pulse" title="正在自动生成物料并同步飞书，请稍候...">
              <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
              正在补齐物料并同步飞书...
            </span>
          ) : isRejected ? (
            <span className="inline-flex items-center gap-1 text-rose-600 dark:text-rose-400 font-semibold truncate" title={job.reject_reason || "触发清洗淘汰规则"}>
              <AlertCircle className="h-3 w-3 shrink-0" />
              {job.reject_type === "ai" ? "AI排雷淘汰" : "清洗淘汰"}
            </span>
          ) : isWaiting ? (
            <span
              className={cn(
                "inline-flex items-center gap-1 font-semibold truncate",
                isCustomWaiting
                  ? "text-amber-700 dark:text-amber-300"
                  : "text-blue-700 dark:text-blue-300"
              )}
              title={`评估就绪时间: ${job.last_action_time || job.crawl_time || ""}`}
            >
              <Clock className="h-3 w-3 shrink-0" />
              {isCustomWaiting ? "🎯 待精细改写审批" : "⚡ 待海投规则审批"}
              {job.last_action_time ? ` · ${formatFullDateTime(job.last_action_time)}` : ""}
            </span>
          ) : isReadyToDeliver ? (
            <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 font-semibold truncate" title={`就绪时间: ${job.last_action_time || job.crawl_time || ""}`}>
              <Truck className="h-3 w-3 shrink-0" />
              待投递 · 就绪
            </span>
          ) : isDelivered ? (
            <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold truncate" title={`送达时间: ${job.last_action_time || ""}`}>
              <CheckCircle2 className="h-3 w-3 shrink-0" />
              已完成投递
            </span>
          ) : isRunning ? (
            <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 font-semibold truncate">
              <Sparkles className="h-3 w-3 shrink-0 animate-spin" />
              {getRunningStageText()}
            </span>
          ) : job.node === "feishu_sync" ? (
            <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 font-semibold truncate">
              ☁️ 正在推送飞书多维表格
            </span>
          ) : job.job_id.startsWith("raw_") || job.status === "scraped" ? (
            <span className="inline-flex items-center gap-1 text-muted-foreground truncate" title="爬虫已抓取存入本地 SQLite 数据库，待规则清洗与飞书推送">
              📥 本地SQLite库已存 · 待清洗
            </span>
          ) : job.grade ? (
            <span className="inline-flex items-center gap-1 text-muted-foreground truncate" title="已完成 AI 评估">
              🎯 AI初评完成 · {normalizedGrade}级
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-muted-foreground truncate" title="已通过规则清洗并同步到飞书多维表格">
              ☁️ 飞书多维表格已存 · 待评估
            </span>
          )}
        </div>

        {/* 右侧：定制面板链接 & 审批/投递按钮 */}
        <div className="flex items-center gap-1.5 shrink-0">
          {/* 定制面板新标签页打开 */}
          <a
            href={customPanelUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "flex h-6.5 items-center gap-1 rounded-md border px-2 text-[10px] transition-all active:scale-95 shadow-xs",
              isCustomWaiting
                ? "border-amber-500/40 bg-amber-500/15 text-amber-900 dark:text-amber-200 font-semibold hover:bg-amber-500/25 hover:border-amber-500/60"
                : "border-border/80 bg-background text-muted-foreground hover:bg-accent hover:text-foreground"
            )}
            title="新标签页打开定制面板"
          >
            <SlidersHorizontal className="h-2.5 w-2.5" />
            定制面板 ↗
          </a>

          {/* 🌟 已投递但打招呼语未送达时，显式提供高感知度的快捷补发按钮 */}
          {isDelivered && Boolean(job.delivery_materials?.greeting_failed) && (
            <button
              type="button"
              disabled={resendingGreeting}
              onClick={resendGreeting}
              className={cn(
                "flex h-6.5 items-center gap-1 rounded-md border px-2.5 text-[10px] font-semibold transition-all active:scale-95 cursor-pointer shadow-xs",
                "border-amber-500/50 bg-amber-500/15 text-amber-900 dark:text-amber-200 hover:bg-amber-500/25 hover:border-amber-500/70 disabled:opacity-50"
              )}
              title="单独唤起岗位微聊，重新发送打招呼语"
            >
              {resendingGreeting ? (
                <Loader2 className="h-2.5 w-2.5 animate-spin" />
              ) : (
                <RotateCcw className="h-2.5 w-2.5" />
              )}
              {resendingGreeting ? "补发中..." : "补发打招呼"}
            </button>
          )}

          {/* 待审批操作 */}
          {isWaiting && onApprove && (
            <>
              <button
                type="button"
                disabled={isApproving}
                onClick={() => onApprove(job.job_id, "reject")}
                className="flex h-6.5 items-center justify-center rounded-md border border-border bg-background px-2 text-[10px] text-muted-foreground hover:bg-rose-50 hover:text-rose-600 hover:border-rose-200 transition-all active:scale-95 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                拒绝
              </button>
              <button
                type="button"
                disabled={isApproving}
                onClick={() => onApprove(job.job_id, "approve")}
                className="flex h-6.5 items-center gap-1 rounded-md bg-emerald-600 hover:bg-emerald-500 px-2.5 text-[10px] font-medium text-white shadow-xs transition-all active:scale-95 cursor-pointer disabled:opacity-80 disabled:cursor-not-allowed"
              >
                {isApproving ? (
                  <>
                    <Loader2 className="h-2.5 w-2.5 animate-spin" />
                    放行中...
                  </>
                ) : (
                  <>
                    <Send className="h-2.5 w-2.5" />
                    放行
                  </>
                )}
              </button>
            </>
          )}

          {/* 待投递单岗发射 */}
          {isReadyToDeliver && onDeliverSingle && (
            <button
              onClick={() => onDeliverSingle(job.job_id)}
              className="flex h-6.5 items-center gap-1 rounded-md bg-blue-600 hover:bg-blue-500 px-2.5 text-[10px] font-medium text-white shadow-xs transition-all active:scale-95 cursor-pointer"
              title="立即执行此岗位的自动投递"
            >
              <Send className="h-2.5 w-2.5" />
              立即投递
            </button>
          )}

          {/* 自动投递中紧急终止按钮 */}
          {isDelivering && onCancelDelivery && (
            <button
              type="button"
              disabled={isCancelling}
              onClick={() => onCancelDelivery(job.job_id)}
              className={cn(
                "flex h-6.5 items-center gap-1 rounded-md border px-2 text-[10px] font-medium transition-all active:scale-95 cursor-pointer shadow-xs",
                "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-400 hover:bg-rose-500/20 hover:border-rose-500/60 disabled:opacity-60 disabled:cursor-not-allowed"
              )}
              title="终止当前岗位的自动投递，流转至执行失败"
            >
              {isCancelling ? (
                <>
                  <Loader2 className="h-2.5 w-2.5 animate-spin" />
                  终止中...
                </>
              ) : (
                <>
                  <Square className="h-2.5 w-2.5 fill-current" />
                  终止投递
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* 投递物料 Double Check 浮层 */}
      <JobMaterialPreviewModal
        job={job}
        open={previewModalOpen}
        onOpenChange={setPreviewModalOpen}
        initialTab={previewTab}
      />
    </div>
  )
})
