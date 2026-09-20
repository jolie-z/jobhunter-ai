"use client"

import { API_BASE } from "@/lib/api"
import { useState } from "react"
import { CheckCircle2, Loader2, AlertCircle, Clock3, Inbox, ThumbsUp, ThumbsDown } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { usePipelineStore, PipelineJob } from "@/store/pipeline-store"
import { toast } from "sonner"


const PLATFORM_LABELS: Record<string, string> = {
  boss: "BOSS直聘",
  liepin: "猎聘",
  "51job": "前程无忧",
  zhilian: "智联招聘",
  xiaohongshu: "小红书",
}

const PLATFORM_BADGE: Record<string, string> = {
  boss: "bg-[#00c8c8]/10 text-[#00a0a0]",
  liepin: "bg-[#ff6b00]/10 text-[#ff6b00]",
  "51job": "bg-[#ffeb00]/20 text-[#c78800]",
  zhilian: "bg-blue-500/10 text-blue-600",
  xiaohongshu: "bg-[#FF2442]/10 text-[#FF2442]",
}

const NODE_LABELS: Record<string, string> = {
  evaluate_node: "AI初评",
  rewrite_node: "简历改写",
  quick_greeting_node: "欢迎语",
  manual_review_node: "待审批",
  delivery_node: "自动投递",
  error: "异常",
}

// ── 单平台进度条 ──
function PlatformBar({ platform, current, total }: { platform: string; current: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (current / total) * 100) : 0
  const done = total > 0 && current >= total
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-slate-600 flex items-center gap-1.5">
          {done ? <CheckCircle2 className="size-3.5 text-emerald-500" /> : <Loader2 className="size-3.5 animate-spin text-indigo-500" />}
          {PLATFORM_LABELS[platform] ?? platform}
        </span>
        <span className="text-slate-400 tabular-nums">{current}/{total || "—"}</span>
      </div>
      <Progress value={pct} className="h-1.5 bg-slate-100" />
    </div>
  )
}

// ── 岗位卡片 ──
function JobCard({ job }: { job: PipelineJob }) {
  const handleEvent = usePipelineStore(s => s.handleEvent)
  const [busy, setBusy] = useState<null | "approve" | "reject">(null)

  const isWaiting = job.status === "waiting" || job.node === "manual_review_node" && job.status !== "delivered"

  const doResume = async (action: "approve" | "reject") => {
    setBusy(action)
    try {
      const res = await fetch(`${API_BASE}/api/automation/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: job.job_id, action }),
      })
      const data = await res.json()
      if (res.ok) {
        if (action === "approve") {
          toast.success(`已放行：${job.job_name}`)
          handleEvent({ type: "job", job_id: job.job_id, job_name: job.job_name, node: "delivery_node", status: "delivered", platform: job.platform, grade: job.grade })
        } else {
          toast.info(`已拒绝：${job.job_name}`)
          handleEvent({ type: "job", job_id: job.job_id, job_name: job.job_name, node: "manual_review_node", status: "rejected", platform: job.platform, grade: job.grade })
        }
      } else {
        toast.error(data.detail || "操作失败")
      }
    } catch (e) {
      toast.error("网络异常，无法连接到自动化引擎")
    } finally {
      setBusy(null)
    }
  }

  // 状态徽章
  const renderStatus = () => {
    switch (job.status) {
      case "delivered":
        return <span className="flex items-center text-[11px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-full"><CheckCircle2 className="size-3 mr-1" /> 已投递</span>
      case "rejected":
        return <span className="flex items-center text-[11px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full"><ThumbsDown className="size-3 mr-1" /> 已拒绝</span>
      case "error":
        return <span className="flex items-center text-[11px] font-medium text-rose-600 bg-rose-50 border border-rose-100 px-2 py-0.5 rounded-full"><AlertCircle className="size-3 mr-1" /> 异常</span>
      case "waiting":
        return <span className="flex items-center text-[11px] font-medium text-amber-600 bg-amber-50 border border-amber-100 px-2 py-0.5 rounded-full"><Clock3 className="size-3 mr-1" /> 待审批</span>
      default:
        return <span className="flex items-center text-[11px] font-medium text-indigo-600 bg-indigo-50 border border-indigo-100 px-2 py-0.5 rounded-full"><Loader2 className="size-3 mr-1 animate-spin" /> {NODE_LABELS[job.node] ?? "流转中"}</span>
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200/70 shadow-sm p-3 space-y-2.5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-800 truncate">{job.job_name}</p>
          <div className="flex items-center gap-1.5 mt-1">
            {job.platform && (
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${PLATFORM_BADGE[job.platform] ?? "bg-slate-100 text-slate-500"}`}>
                {PLATFORM_LABELS[job.platform] ?? job.platform}
              </span>
            )}
            {job.grade && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-violet-50 text-violet-600">{job.grade} 级</span>
            )}
          </div>
        </div>
        <div className="shrink-0">{renderStatus()}</div>
      </div>

      {isWaiting && job.status !== "delivered" && job.status !== "rejected" && (
        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            onClick={() => doResume("approve")}
            disabled={busy !== null}
            className="flex-1 h-7 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
          >
            {busy === "approve" ? <Loader2 className="size-3.5 animate-spin mr-1" /> : <ThumbsUp className="size-3.5 mr-1" />}
            放行投递
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => doResume("reject")}
            disabled={busy !== null}
            className="flex-1 h-7 text-xs text-slate-600 border-slate-200 hover:bg-slate-50"
          >
            {busy === "reject" ? <Loader2 className="size-3.5 animate-spin mr-1" /> : <ThumbsDown className="size-3.5 mr-1" />}
            拒绝
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * 全链路实时看板：
 * - 上部：当前阶段详情（抓取→各平台并发进度；清洗→硬规则/AI初筛；其余→提示）
 * - 下部：岗位流水线卡片（含待审批岗位的放行/拒绝操作）
 */
export function PipelineBoard() {
  const currentStage = usePipelineStore(s => s.currentStage)
  const status = usePipelineStore(s => s.status)
  const scrapeProgress = usePipelineStore(s => s.scrapeProgress)
  const hardCleanProgress = usePipelineStore(s => s.hardCleanProgress)
  const aiScoutProgress = usePipelineStore(s => s.aiScoutProgress)
  const jobs = usePipelineStore(s => s.jobs)
  const logs = usePipelineStore(s => s.logs)
  const handleEvent = usePipelineStore(s => s.handleEvent)

  const jobList = Object.values(jobs).sort((a, b) => a.job_name.localeCompare(b.job_name))
  const waitingJobs = jobList.filter(j => j.status === "waiting")
  const waitingCount = waitingJobs.length

  const [batchBusy, setBatchBusy] = useState(false)

  const handleBatchApprove = async () => {
    const threadIds = waitingJobs.map(j => j.job_id)
    if (threadIds.length === 0) return
    setBatchBusy(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/resume_batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_ids: threadIds, action: "approve" }),
      })
      const data = await res.json()
      if (res.ok) {
        const detail = data?.data ?? {}
        const successCount = detail.success ?? threadIds.length
        waitingJobs.forEach(j =>
          handleEvent({ type: "job", job_id: j.job_id, job_name: j.job_name, node: "delivery_node", status: "delivered", platform: j.platform, grade: j.grade })
        )
        toast.success(`已批量放行 ${successCount} 个岗位，投递引擎启动中…`)
      } else {
        toast.error(data?.detail || "批量放行失败")
      }
    } catch (e) {
      toast.error("网络异常，无法连接到自动化引擎")
    } finally {
      setBatchBusy(false)
    }
  }

  // ── 阶段详情区 ──
  const renderStageDetail = () => {
    if (status === "idle") {
      return (
        <div className="flex flex-col items-center justify-center py-8 text-slate-400 gap-2">
          <Inbox className="size-8 text-slate-300" />
          <p className="text-xs">链路尚未启动。前往「链路配置」点击立即执行，或等待定时调度。</p>
        </div>
      )
    }

    if (currentStage === "scraping") {
      const entries = Object.entries(scrapeProgress)
      if (entries.length === 0) {
        return <p className="text-xs text-slate-500 py-4 text-center">正在唤醒各平台爬虫…</p>
      }
      return (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 py-1">
          {entries.map(([platform, p]) => (
            <PlatformBar key={platform} platform={platform} current={p.current} total={p.total} />
          ))}
        </div>
      )
    }

    if (currentStage === "cleaning") {
      return (
        <div className="space-y-3 py-1">
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-slate-600 flex items-center gap-1.5">
                {hardCleanProgress && hardCleanProgress.current >= hardCleanProgress.total && hardCleanProgress.total > 0
                  ? <CheckCircle2 className="size-3.5 text-emerald-500" />
                  : <Loader2 className="size-3.5 animate-spin text-indigo-500" />}
                硬性规则拦截
              </span>
              <span className="text-slate-400 tabular-nums">{hardCleanProgress ? `${hardCleanProgress.current}/${hardCleanProgress.total}` : "等待中…"}</span>
            </div>
            <Progress value={hardCleanProgress && hardCleanProgress.total > 0 ? (hardCleanProgress.current / hardCleanProgress.total) * 100 : 0} className="h-1.5 bg-slate-100" />
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-slate-600 flex items-center gap-1.5">
                {aiScoutProgress && aiScoutProgress.current >= aiScoutProgress.total && aiScoutProgress.total > 0
                  ? <CheckCircle2 className="size-3.5 text-emerald-500" />
                  : <Loader2 className="size-3.5 animate-spin text-indigo-500" />}
                AI初筛侦察
              </span>
              <span className="text-slate-400 tabular-nums">{aiScoutProgress ? `${aiScoutProgress.current}/${aiScoutProgress.total}` : "等待中…"}</span>
            </div>
            <Progress value={aiScoutProgress && aiScoutProgress.total > 0 ? (aiScoutProgress.current / aiScoutProgress.total) * 100 : 0} className="h-1.5 bg-slate-100" />
          </div>
        </div>
      )
    }

    if (currentStage === "feishu_sync") {
      return <p className="text-xs text-slate-500 py-4 text-center">正在将通过清洗的岗位同步至飞书多维表格…</p>
    }

    // evaluating / deep_eval / rewriting / greeting / review / delivering / done
    return (
      <p className="text-xs text-slate-500 py-4 text-center">
        岗位正在 AI 流水线中流转（初评 → 改写 → 欢迎语 → 审批 → 投递），请在下方查看每个岗位的实时状态。
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {/* 当前阶段详情 */}
      <div className="bg-slate-50/60 rounded-xl border border-slate-100 px-4 py-3">
        <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-2">当前阶段详情</h4>
        {renderStageDetail()}
      </div>

      {/* 岗位流水线 */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-bold text-slate-500 uppercase tracking-wide">岗位流水线</h4>
          <div className="flex items-center gap-2 text-[11px]">
            <span className="text-slate-400">共 {jobList.length} 个</span>
            {waitingCount > 0 && (
              <>
                <span className="text-amber-600 font-semibold bg-amber-50 px-1.5 py-0.5 rounded">{waitingCount} 个待审批</span>
                <Button
                  size="sm"
                  onClick={handleBatchApprove}
                  disabled={batchBusy}
                  className="h-6 px-2.5 text-[11px] bg-emerald-600 hover:bg-emerald-700 text-white"
                >
                  {batchBusy ? <Loader2 className="size-3 animate-spin mr-1" /> : <ThumbsUp className="size-3 mr-1" />}
                  批量放行
                </Button>
              </>
            )}
          </div>
        </div>

        {jobList.length === 0 ? (
          <div className="text-center py-6 text-xs text-slate-400 border border-dashed border-slate-200 rounded-xl">
            暂无岗位进入流水线
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2.5 max-h-[240px] overflow-y-auto custom-scrollbar pr-1">
            {jobList.map(job => (
              <JobCard key={job.job_id} job={job} />
            ))}
          </div>
        )}
      </div>

      {/* 实时日志（折叠展示最近几条） */}
      {logs.length > 0 && (
        <div className="bg-slate-900 rounded-xl p-3 max-h-[120px] overflow-y-auto custom-scrollbar">
          {logs.slice(-30).map((line, i) => (
            <p key={i} className="text-[11px] font-mono text-slate-300 leading-relaxed break-all">{line}</p>
          ))}
        </div>
      )}
    </div>
  )
}
