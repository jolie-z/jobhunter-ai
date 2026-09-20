"use client"

import { useState, useEffect, useCallback, useMemo, useRef } from "react"
import { Save, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { ReviewMaterialGuideCard } from "./review/review-material-guide-card"
import { ReviewPolicyCard } from "./review/review-policy-card"
import { ReviewPendingJobsCard, PendingReviewJob } from "./review/review-pending-jobs-card"
import { usePipelineStore } from "@/store/pipeline-store"
import { API_BASE } from "@/lib/api"

interface ReviewConfigPanelProps {
  onSaved: () => void
}

export function ReviewConfigPanel({ onSaved }: ReviewConfigPanelProps) {
  const storeJobs = usePipelineStore((s) => s.jobs)
  const handleEvent = usePipelineStore((s) => s.handleEvent)

  const [massApplyMaxHeadcount, setMassApplyMaxHeadcount] = useState(1000)
  const [feishuPendingJobs, setFeishuPendingJobs] = useState<PendingReviewJob[]>([])

  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState("")
  // 保存成功提示自动清除定时器（组件卸载时清理，防止 setState 泄漏）
  const saveMsgTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (saveMsgTimer.current) clearTimeout(saveMsgTimer.current)
    }
  }, [])

  // 从后端拉取配置与飞书待审批记录
  const fetchConfig = useCallback(async (isSilent = false) => {
    if (!isSilent) setLoading(true)
    else setRefreshing(true)

    try {
      const res = await fetch(`${API_BASE}/api/pipeline/review-config`)
      const result = await res.json()
      if (result.code === 0 && result.data) {
        const d = result.data
        if (d.mass_apply_max_headcount !== undefined) {
          setMassApplyMaxHeadcount(d.mass_apply_max_headcount)
        }
        if (Array.isArray(d.pending_jobs)) {
          setFeishuPendingJobs(d.pending_jobs)
        }
      }
    } catch {
      toast.error("读取待审批规则配置异常")
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  // 合并 PipelineStore 的实时 waiting 岗位与飞书待审批记录
  const combinedJobs = useMemo(() => {
    const map = new Map<string, PendingReviewJob>()

    // 1. 先加入飞书拉取到的待审批记录
    feishuPendingJobs.forEach((j) => {
      map.set(j.job_id, j)
    })

    // 2. 将 PipelineStore 中当前正在等待的岗位覆盖/合并进去
    Object.values(storeJobs).forEach((j) => {
      if (j.status === "waiting" || j.node === "manual_review_node") {
        const existing = map.get(j.job_id) || ({} as Partial<PendingReviewJob>)
        map.set(j.job_id, {
          job_id: j.job_id,
          job_name: j.job_name || existing.job_name || "未知岗位",
          company_name: j.company_name || existing.company_name || "未知公司",
          company_scale: j.company_scale || existing.company_scale || "",
          platform: j.platform || existing.platform || "boss",
          grade: j.grade || existing.grade || "B",
          salary: j.salary || existing.salary || "",
          city: j.city || existing.city || "",
          job_url: j.job_url || existing.job_url || "",
          has_image: existing.has_image ?? false,
          has_pdf: existing.has_pdf ?? false,
          has_greeting: existing.has_greeting ?? false,
          greeting_text: existing.greeting_text || "",
          is_custom: (j.grade ? ["A", "B"].includes(j.grade.toUpperCase()) : existing.is_custom) ?? true,
          status: "waiting",
        })
      }
    })

    return Array.from(map.values())
  }, [feishuPendingJobs, storeJobs])

  // 单岗位审批
  const handleApprove = async (jobId: string, action: "approve" | "reject") => {
    try {
      const res = await fetch(`${API_BASE}/api/automation/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: jobId, action }),
      })
      const data = await res.json()
      if (res.ok) {
        toast.success(action === "approve" ? "岗位已放行至待投递队列" : "岗位已拒绝投递")
        // 更新本地 store（对齐主看板口径：放行进入 ready_to_deliver，拒绝进入 rejected_manual）
        handleEvent({
          type: "job",
          job_id: jobId,
          status: action === "approve" ? "ready_to_deliver" : "rejected_manual",
        })
        // 移除已处理记录
        setFeishuPendingJobs((prev) => prev.filter((j) => j.job_id !== jobId))
      } else {
        toast.error(data.detail || data.message || "审批操作失败")
      }
    } catch {
      toast.error("无法连接审批接口服务")
    }
  }

  // 批量审批
  const handleBatchApprove = async (
    action: "approve" | "reject",
    targetJobs: PendingReviewJob[]
  ) => {
    const threadIds = targetJobs.map((j) => j.job_id)
    if (threadIds.length === 0) return

    try {
      const res = await fetch(`${API_BASE}/api/automation/resume_batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_ids: threadIds, action }),
      })
      const data = await res.json()
      if (res.ok) {
        toast.success(
          action === "approve"
            ? `已成功批量放行 ${threadIds.length} 个就绪岗位至待投递队列`
            : `已批量拒绝 ${threadIds.length} 个岗位`
        )
        // 更新本地 store（对齐主看板口径）
        threadIds.forEach((id) => {
          handleEvent({
            type: "job",
            job_id: id,
            status: action === "approve" ? "ready_to_deliver" : "rejected_manual",
          })
        })
        // 移除已处理记录
        setFeishuPendingJobs((prev) =>
          prev.filter((j) => !threadIds.includes(j.job_id))
        )
      } else {
        toast.error(data.message || "批量审批失败")
      }
    } catch {
      toast.error("网络异常，无法执行批量审批")
    }
  }

  // 保存策略设置（大公司门槛人数）
  const handleSave = async () => {
    setSaving(true)
    setSaveMsg("")
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/review-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mass_apply_max_headcount: massApplyMaxHeadcount,
        }),
      })
      const result = await res.json()
      if (res.ok && result.code === 0) {
        setSaveMsg("待审批规则已保存生效")
        toast.success("待审批规则已保存生效")
        onSaved()
        if (saveMsgTimer.current) clearTimeout(saveMsgTimer.current)
        saveMsgTimer.current = setTimeout(() => setSaveMsg(""), 3000)
      } else {
        toast.error(result.msg || "保存失败")
      }
    } catch {
      toast.error("网络异常，无法保存待审批规则")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">
        <RefreshCw className="h-4 w-4 animate-spin mr-2 text-violet-500" />
        正在加载待审批岗位与物料安检配置...
      </div>
    )
  }

  return (
    <div className="space-y-3.5 text-xs select-none">
      {/* 1. 第一分区：平台简历物料格式硬核指南 (BOSS长图 vs PDF) */}
      <ReviewMaterialGuideCard />

      {/* 2. 第二分区：待审批触发规则与大公司海投拦截门槛人数 */}
      <ReviewPolicyCard
        massApplyMaxHeadcount={massApplyMaxHeadcount}
        onChangeHeadcount={setMassApplyMaxHeadcount}
      />

      {/* 3. 第三分区：待审批岗位列表与物料安检放行卡片 */}
      <ReviewPendingJobsCard
        jobs={combinedJobs}
        onApprove={handleApprove}
        onBatchApprove={handleBatchApprove}
        onRefresh={() => fetchConfig(true)}
        loading={refreshing}
      />

      {/* 保存操作底栏 */}
      <div className="flex items-center justify-between pt-2 border-t border-border/60">
        <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
          {saveMsg}
        </span>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-700 active:scale-95 transition-all shadow-sm cursor-pointer disabled:opacity-50"
        >
          {saving ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          <span>{saving ? "正在保存..." : "保存待审批规则"}</span>
        </button>
      </div>
    </div>
  )
}
