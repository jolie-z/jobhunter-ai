"use client"

import React from "react"
import {
  MapPin,
  GraduationCap,
  Briefcase,
  ArrowRight,
  Clock,
  Loader2,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { JobData } from "@/types/job"
import { cn } from "@/lib/utils"
import {
  PLATFORM_CONFIG,
  normalizeStatus,
  type JobCardData,
} from "@/lib/job-data"
import { AiScore } from "@/components/dashboard/ai-score"
import { PlatformBadge } from "@/components/dashboard/platform-badge"
import {
  JobLiveProgressInline,
  type JobProgressInfo,
} from "@/components/dashboard/job-live-progress-inline"

export interface JobCardProps {
  job: JobData
  card: JobCardData
  isSelected: boolean
  onSelect: (checked: boolean) => void
  onEnterDetail: (job: JobData) => void
  processingJob?: string
  progressInfo?: JobProgressInfo
  liveLogs?: string[]
  onApprove?: () => void
  /** B12：批量批准请求进行中，横幅按钮禁用防重复点击（后端幂等，重复请求徒增飞书写入） */
  approveBusy?: boolean
  onRetry?: () => void
}

// 任务类型 → 中文标签
const TASK_LABEL: Record<string, string> = {
  evaluate: "初步评估",
  deep_evaluate: "深度评估",
  rewrite: "简历改写",
  deliver: "自动投递",
}

// 跟进状态 → 浅色徽标样式（中文动态值兜底为灰色）
function getStatusStyle(status: JobCardData["status"], rawText: string) {
  // 疑似重复：停牌待人工复核的岗位，用琥珀色醒目区分（点开详情看母本信息再判断）
  if (rawText === "疑似重复") return "bg-amber-50 border-amber-200 text-amber-700"
  const map: Record<JobCardData["status"], string> = {
    new: "bg-blue-50 border-blue-200 text-blue-700",
    evaluated: "bg-purple-50 border-purple-200 text-purple-700",
    applied: "bg-green-50 border-green-200 text-green-700",
    interview: "bg-amber-50 border-amber-200 text-amber-700",
  }
  return map[status] ?? "bg-slate-100 border-slate-200 text-slate-600"
}

export function JobCard({
  job,
  card,
  isSelected,
  onSelect,
  onEnterDetail,
  processingJob,
  progressInfo,
  liveLogs,
  onApprove,
  approveBusy,
  onRetry,
}: JobCardProps) {
  // 状态文案优先用真实中文 followStatus，未命中映射才用枚举兜底
  const statusEnum = normalizeStatus(job.followStatus)
  const statusText = job.followStatus || (statusEnum ? "新线索" : "—")
  const platformName = PLATFORM_CONFIG[card.platform].name

  return (
    <article
      className={cn(
        "group relative bg-white rounded-2xl border transition-all duration-200",
        "hover:shadow-[0_4px_20px_-4px_rgba(0,0,0,0.1)] hover:-translate-y-px",
        isSelected
          ? "border-blue-300 bg-blue-50/40 shadow-[0_0_0_2px_rgba(59,130,246,0.12)]"
          : processingJob && processingJob !== "interrupted"
          ? "border-blue-300/80 ring-1 ring-blue-200/70 bg-blue-50/10 shadow-sm"
          : "border-slate-200 shadow-sm"
      )}
    >
      <div className="flex items-center gap-4 px-5 py-3">
        {/* 复选框 */}
        <div className="shrink-0" onClick={(e) => e.stopPropagation()}>
          <Checkbox
            checked={isSelected}
            onCheckedChange={onSelect}
            className="size-4 rounded-md border-slate-300 data-[state=checked]:bg-blue-600 data-[state=checked]:border-blue-600"
            aria-label={`选择职位 ${job.jobTitle}`}
          />
        </div>

        {/* 平台 Logo + 名称 */}
        <div className="flex flex-col items-center gap-1 shrink-0 w-11">
          <PlatformBadge platform={card.platform} size="md" />
          <span className="text-[10px] font-medium text-slate-400 truncate max-w-full">
            {platformName}
          </span>
        </div>

        {/* 竖分隔线 */}
        <div className="w-px h-14 bg-slate-100 shrink-0" />

        {/* 公司信息 */}
        <div className="flex flex-col gap-1 w-32 shrink-0">
          <p className="text-xs font-semibold text-slate-800 truncate leading-tight">
            {card.company}
          </p>
          <p className="text-[10px] text-slate-400 truncate">{card.companySize}</p>
          <p className="text-[10px] text-slate-400 truncate">{card.industry}</p>
          {/* 跟进状态徽标 */}
          <div
            className={cn(
              "mt-0.5 inline-flex items-center px-1.5 py-0.5 rounded-md border text-[10px] font-medium w-fit",
              getStatusStyle(card.status, statusText)
            )}
          >
            {statusText}
          </div>
        </div>

        {/* 竖分隔线 */}
        <div className="w-px h-14 bg-slate-100 shrink-0" />

        {/* 职位核心信息 */}
        <div className={cn("min-w-0 flex flex-col gap-1", processingJob && processingJob !== "interrupted" ? "w-60 shrink-0" : "flex-1")}>
          <h2 className="text-sm font-bold text-slate-900 truncate group-hover:text-blue-600 transition-colors">
            {card.title}
          </h2>
          <p className="text-sm font-bold text-blue-600">{card.salary}</p>
          <div className="flex items-center gap-3 text-[11px] text-slate-400 flex-wrap">
            <span className="flex items-center gap-1">
              <MapPin className="size-3 shrink-0" />
              {card.location}
            </span>
            <span className="flex items-center gap-1">
              <GraduationCap className="size-3 shrink-0" />
              {card.education}
            </span>
            <span className="flex items-center gap-1">
              <Briefcase className="size-3 shrink-0" />
              {card.experience}
            </span>
          </div>
          {card.tags.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              {card.tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 text-[10px] font-medium"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
          
          {/* 🌟 待审批横幅：精投（简历人工复核）/ 海投（海投人工复核）两轨共用，单按钮极简审批 */}
          {(statusText === "简历人工复核" || statusText === "海投人工复核") && !processingJob && (
            <div className="mt-2 flex items-center gap-3 px-3 py-2 bg-orange-50 border border-orange-200 rounded-lg max-w-fit animate-in fade-in slide-in-from-top-1">
              <div className="flex items-center gap-1.5">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-orange-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-orange-500"></span>
                </span>
                <span className="text-xs font-bold text-orange-700">
                  {statusText === "海投人工复核" ? "岗位已进入海投复核，等待您的批准：" : "定制简历已生成，等待您的批阅："}
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={(e) => { e.stopPropagation(); onApprove?.(); }}
                  disabled={approveBusy}
                  className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold bg-orange-500 text-white rounded shadow-sm hover:bg-orange-600 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  title="批准即放行：跟进状态将改为「待投递」，岗位自动进入定时投递队列，由每日发射波次统一投出；不想投递可去飞书把跟进状态改为「不合适」"
                >
                  <CheckCircle2 className="size-3.5" />
                  {approveBusy ? "批准中…" : "批准"}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* 🌟 中轴：如果该岗位正在执行任务，内嵌 4 阶段进度节点与微观动态日志（红框位置） */}
        {processingJob && processingJob !== "interrupted" && (
          <>
            <div className="w-px h-12 bg-blue-100/80 shrink-0" />
            <div className="flex-1 min-w-[240px] max-w-[460px] mx-1">
              <JobLiveProgressInline
                taskType={processingJob}
                progressInfo={progressInfo}
                latestLog={liveLogs?.[liveLogs.length - 1]}
              />
            </div>
          </>
        )}

        {/* 竖分隔线 */}
        <div className="w-px h-12 bg-slate-100 shrink-0" />

        {/* AI 评分（独立列，hover 显示评估详情 Tooltip） */}
        <div className="shrink-0">
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <AiScore score={card.score} maxScore={card.maxScore} grade={card.scoreGrade} />
                </div>
              </TooltipTrigger>
              {job.aiEvaluationDetail && (
                <TooltipContent
                  side="left"
                  className="max-w-[300px] p-3 bg-white border border-violet-200 shadow-lg"
                >
                  <div className="text-[11px] leading-relaxed text-gray-800 whitespace-pre-line">
                    {job.aiEvaluationDetail.split("\n\n").slice(0, 3).join("\n\n")}
                  </div>
                </TooltipContent>
              )}
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* 右侧：发布时间 + 进入面板/任务栏 */}
        <div className="flex flex-col items-center gap-1 shrink-0 w-24">
          <span className="flex items-center gap-1 text-[10px] text-slate-400">
            <Clock className="size-3" />
            {card.postedAt}
          </span>

          {/* 进入面板 或 实时任务栏 */}
          {processingJob === "interrupted" ? (
            <button
              onClick={() => (onRetry ? onRetry() : null)}
              className="self-end flex items-center gap-1.5 px-2.5 py-1 bg-amber-50 hover:bg-amber-100 border border-amber-300 rounded-lg text-amber-800 text-[10px] font-medium shadow-sm transition-all duration-150 active:scale-95 animate-in fade-in"
              title="后端曾发生重启或连接中断，点击针对该岗位重新发起评估"
            >
              <AlertTriangle className="size-3.5 text-amber-600 shrink-0" />
              <span>中断·点击重试</span>
            </button>
          ) : processingJob ? (
            <div
              className="flex items-center justify-center gap-1.5 w-full py-1 px-2 bg-blue-50/90 border border-blue-200 rounded-lg text-blue-600 text-[11px] font-medium shadow-2xs cursor-wait select-none"
              title={liveLogs?.[liveLogs.length - 1] || "后台任务处理中..."}
            >
              <Loader2 className="size-3 text-blue-500 animate-spin shrink-0" />
              <span className="truncate">
                {TASK_LABEL[processingJob] ? `${TASK_LABEL[processingJob]}中` : "处理中"}
              </span>
            </div>
          ) : (
            <button
              onClick={() => onEnterDetail(job)}
              className={cn(
                "flex items-center gap-1 text-xs font-medium px-3 py-1 rounded-lg border",
                "text-slate-500 border-slate-200 bg-white",
                "hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50",
                "transition-all duration-150"
              )}
              aria-label="定制面板"
            >
              定制面板
              <ArrowRight className="size-3" />
            </button>
          )}
        </div>
      </div>
    </article>
  )
}
