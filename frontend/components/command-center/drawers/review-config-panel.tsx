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

  // 单岗位审批（2026-11-02 审计 P1-10 同源迁移）：放行改走 /auto-heal-and-approve
  // （补料+放行一体，与主看板同端点——裸 /resume 只改状态不问物料，会放出缺物料岗位）；
  // 拒绝无物料语义，保持裸 /resume。本地口径与主看板对齐：放行写 ready_to_deliver 节点，
  // 拒绝写 manual_rejected 节点 + reject_type（修复此前缺 node 导致最长 12s 仍留待审批计数）
  const handleApprove = async (jobId: string, action: "approve" | "reject") => {
    try {
      if (action === "approve") {
        const res = await fetch(`${API_BASE}/api/automation/auto-heal-and-approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ record_id: jobId }),
        })
        const data = await res.json().catch(() => ({} as any))
        if (res.ok && (data.status === "success" || data.status === "processing")) {
          toast.success(data.message || "岗位已补料放行至待投递队列")
          handleEvent({ type: "job", job_id: jobId, status: "ready_to_deliver", node: "ready_to_deliver" })
          setFeishuPendingJobs((prev) => prev.filter((j) => j.job_id !== jobId))
        } else {
          toast.error("放行中止: " + (data.detail || data.message || "未知错误"))
        }
      } else {
        const res = await fetch(`${API_BASE}/api/automation/resume`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: jobId, action }),
        })
        const data = await res.json().catch(() => ({} as any))
        if (res.ok) {
          toast.success("岗位已拒绝投递")
          handleEvent({ type: "job", job_id: jobId, status: "rejected_manual", node: "manual_rejected", reject_type: "manual" })
          setFeishuPendingJobs((prev) => prev.filter((j) => j.job_id !== jobId))
        } else {
          toast.error(data.detail || data.message || "审批操作失败")
        }
      }
    } catch {
      toast.error("无法连接审批接口服务")
    }
  }

  // 批量审批（2026-11-02 审计 P1-10）：放行逐岗走 /auto-heal-and-approve（同源+逐条
  // 读结果，/resume_batch 恒 200+明细 曾把部分失败报成全部成功、失败岗位被乐观置
  // 「待投递」成幽灵卡）；拒绝保持 /resume_batch 但消费 success/failed/details 明细。
  // 本地状态只对真实成功者乐观更新，失败者留抽屉逐个处理
  const handleBatchApprove = async (
    action: "approve" | "reject",
    targetJobs: PendingReviewJob[]
  ) => {
    const threadIds = targetJobs.map((j) => j.job_id)
    if (threadIds.length === 0) return

    try {
      if (action === "approve") {
        const okIds: string[] = []
        let failCount = 0
        toast.info(`批量放行进行中（0/${threadIds.length}）...`)
        for (const id of threadIds) {
          try {
            const res = await fetch(`${API_BASE}/api/automation/auto-heal-and-approve`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ record_id: id }),
            })
            const data = await res.json().catch(() => ({} as any))
            if (res.ok && (data.status === "success" || data.status === "processing")) {
              okIds.push(id)
              handleEvent({ type: "job", job_id: id, status: "ready_to_deliver", node: "ready_to_deliver" })
            } else {
              failCount += 1
              console.warn(`批量放行中止 ${id}:`, data.detail || data.message)
            }
          } catch {
            failCount += 1
          }
        }
        setFeishuPendingJobs((prev) => prev.filter((j) => !okIds.includes(j.job_id)))
        if (okIds.length > 0 && failCount === 0) toast.success(`🎉 批量放行完成：${okIds.length} 个岗位已补料放行至待投递队列`)
        if (okIds.length > 0 && failCount > 0) toast.warning(`${failCount} 个放行中止（物料缺失/未评估/记录异常），已留在列表，请单独处理`)
        if (okIds.length === 0 && failCount > 0) toast.error(`批量放行全部中止（${failCount} 个），请检查岗位状态`)
      } else {
        const res = await fetch(`${API_BASE}/api/automation/resume_batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_ids: threadIds, action }),
        })
        const data = await res.json().catch(() => ({} as any))
        if (res.ok && data.status !== "error") {
          const ok = Number(data.data?.success ?? threadIds.length)
          const failed = Number(data.data?.failed ?? 0)
          // 失败明细剔除法（CR-B2-R1-P2）：details 若带岗位标识则精确剔除；仅无标识时
          // 才退化为保守口径（成功数==全集时全剔，否则全部留在抽屉人工核对）
          const failIds: string[] = (data.data?.details || [])
            .map((d: any) => d?.thread_id || d?.job_id || d?.record_id || "")
            .filter(Boolean)
          const okIds: string[] = failIds.length > 0
            ? threadIds.filter((id) => !failIds.includes(id))
            : (ok === threadIds.length ? [...threadIds] : [])
          if (okIds.length > 0) {
            okIds.forEach((id) => handleEvent({ type: "job", job_id: id, status: "rejected_manual", node: "manual_rejected", reject_type: "manual" }))
            toast.success(`已批量拒绝 ${okIds.length} 个岗位`)
          }
          if (failed > 0) toast.warning(`${failed} 个拒绝失败：${(data.data?.details || []).slice(0, 3).map((d: any) => d?.error || d?.detail || "").filter(Boolean).join("；")}`)
          setFeishuPendingJobs((prev) => prev.filter((j) => !okIds.includes(j.job_id)))
        } else {
          toast.error(data.message || "批量审批失败")
        }
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
