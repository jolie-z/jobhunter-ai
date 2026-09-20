"use client"

import { useState, useCallback, useRef } from "react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"
import { usePipelineStore, PipelineJob } from "@/store/pipeline-store"
import { isJobReadyToDeliver, isJobWaitingReview } from "../job-predicates"

// 本地时间串（与后端快照 "YYYY-MM-DD HH:mm:ss" 同格式）：放行后立刻参与看板置顶排序，
// 不用 ISO（UTC）以免与后端本地时间串混排时差 8 小时
function nowLocalString(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const RELEASED_DESC = "老板放行就绪，等待定时发射"

export function useBoardActions(waitingJobs: PipelineJob[], readyToDeliverJobs: PipelineJob[]) {
  const [batchLoading, setBatchLoading] = useState(false)
  const [deliveringBatch, setDeliveringBatch] = useState(false)
  const [approvingJobIds, setApprovingJobIds] = useState<Record<string, boolean>>({})
  const [batchRetryingFailed, setBatchRetryingFailed] = useState(false)
  const [batchDismissingFailed, setBatchDismissingFailed] = useState(false)
  const [cancellingJobIds, setCancellingJobIds] = useState<Record<string, boolean>>({})
  const cancellingJobIdsRef = useRef<Record<string, boolean>>({})

  // 从 store 获取更新方法，确保类型一致性和统一的修改入口
  const updateJob = usePipelineStore((s) => s.updateJob)

  // 单个审批放行（补料+放行一体）：改走 /auto-heal-and-approve，
  // 缺失物料自动渲染挂载（定制岗按 AI改写JSON 渲染定制 PDF），杜绝「放了行却没物料，
  // 到发射时才报缺 PDF 或错投通用简历」——此前裸 /resume 只改状态不问物料
  const handleApprove = useCallback(async (jobId: string, action: "approve" | "reject") => {
    // 🌟 单岗防抖：处理中直接拦截，杜绝重复连击
    if (approvingJobIds[jobId]) return

    setApprovingJobIds((prev) => ({ ...prev, [jobId]: true }))

    // 拒绝无需补料，保持轻量状态流转
    if (action === "reject") {
      try {
        const res = await fetch(`${API_BASE}/api/automation/resume`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: jobId, action }),
        })
        const data = await res.json()
        if (res.ok) {
          const st = usePipelineStore.getState()
          if (updateJob && st.jobs[jobId]) {
            // 与后端快照口径一致：rejected_manual 不属于任何 Tab 集合（淘汰Tab留给机器清洗），仅保留在全部岗位
            updateJob(jobId, {
              status: "rejected_manual",
              node: "manual_rejected",
              reject_type: "manual",
              reject_reason: "老板人工审批拒绝",
            })
          }
          toast.info("已拒绝该岗位")
        } else {
          toast.error("审批操作失败: " + (data.detail || data.message || "未知错误"))
        }
      } catch {
        toast.error("无法连接后端审批服务")
      } finally {
        setApprovingJobIds((prev) => {
          const next = { ...prev }
          delete next[jobId]
          return next
        })
      }
      return
    }

    try {
      const res = await fetch(`${API_BASE}/api/automation/auto-heal-and-approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: jobId }),
      })
      const data = await res.json().catch(() => ({} as any))
      if (res.ok && (data.status === "success" || data.status === "processing")) {
        const st = usePipelineStore.getState()
        if (updateJob && st.jobs[jobId]) {
          updateJob(jobId, {
            status: "ready_to_deliver",
            node: "ready_to_deliver",
            last_action_time: nowLocalString(),
            last_action_desc: RELEASED_DESC,
          })
        }
        toast.success(data.message || "✅ 岗位已补料放行，进入「待投递」队列")
      } else {
        // 失败即拦截在待审批：物料缺失/海投打招呼语未配置等，后端已给明原因
        toast.error("放行中止: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      toast.error("无法连接后端审批服务")
    } finally {
      setApprovingJobIds((prev) => {
        const next = { ...prev }
        delete next[jobId]
        return next
      })
    }
  }, [updateJob, approvingJobIds])

  // 批量一键放行当前待审批列表（补料+放行一体，逐岗串行避免渲染与飞书写入打架）
  const handleBatchApprove = useCallback(async (targetJobs?: PipelineJob[]) => {
    // 直接从 store 获取最新数据，避免闭包捕获旧值
    const st = usePipelineStore.getState()
    const jobsToApprove = targetJobs && targetJobs.length > 0
      ? targetJobs
      : Object.values(st.jobs).filter(isJobWaitingReview)
    const threadIds = jobsToApprove.map((j) => j.job_id)
    if (threadIds.length === 0) return
    setBatchLoading(true)
    let succeededCount = 0
    try {
      for (const id of threadIds) {
        try {
          const res = await fetch(`${API_BASE}/api/automation/auto-heal-and-approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ record_id: id }),
          })
          const data = await res.json().catch(() => ({} as any))
          if (res.ok && data.status === "success") {
            succeededCount += 1
            const cur = usePipelineStore.getState()
            if (cur.jobs[id]) {
              cur.updateJob(id, {
                status: "ready_to_deliver",
                node: "ready_to_deliver",
                last_action_time: nowLocalString(),
                last_action_desc: RELEASED_DESC,
              })
            }
          } else {
            console.warn(`放行中止 ${id}:`, data.detail || data.message)
          }
        } catch {
          // 单岗网络异常不中断整批，留待审批逐个处理
        }
      }
      const failedCount = threadIds.length - succeededCount
      toast.success(`🎉 批量放行完成：${succeededCount} 个岗位已补料放行进入「待投递」队列`)
      if (failedCount > 0) {
        toast.warning(`${failedCount} 个放行中止（物料缺失或记录异常），已留在待审批，请单独处理`)
      }
    } finally {
      setBatchLoading(false)
    }
  }, []) // 移掉 waitingJobs 依赖，直接使用 store

  // 批量立即触发投递
  const handleTriggerDeliverAll = useCallback(async () => {
    // 直接从 store 获取最新数据
    const st = usePipelineStore.getState()
    const jobs = Object.values(st.jobs).filter(isJobReadyToDeliver)
    const threadIds = jobs.map((j) => j.job_id)
    if (threadIds.length === 0) return
    setDeliveringBatch(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/deliver_approved`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_ids: threadIds }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        toast.success(`🚀 投递任务已启动：正在自动投递 ${threadIds.length} 个就绪岗位...`)
        // 使用最新状态更新
        const currentSt = usePipelineStore.getState()
        threadIds.forEach((id) => {
          if (currentSt.jobs[id]) {
            currentSt.updateJob(id, {
              status: "running",
              sub_status: "delivering",
              node: "delivery_node",
              failure_info: undefined,
              last_action_desc: "正在自动投递中…",
            })
          }
        })
      } else {
        toast.error("触发投递失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      toast.error("无法连接后端投递服务")
    } finally {
      setDeliveringBatch(false)
    }
  }, []) // 移掉 readyToDeliverJobs 依赖，直接使用 store

  // 单个立即触发投递
  const handleTriggerDeliverSingle = useCallback(async (jobId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/automation/deliver_approved`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_ids: [jobId] }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        toast.success("🚀 已启动该岗位单独投递")
        const st = usePipelineStore.getState()
        if (st.jobs[jobId]) {
          st.updateJob(jobId, {
            status: "running",
            sub_status: "delivering",
            node: "delivery_node",
            failure_info: undefined,
            last_action_desc: "正在自动投递中…",
          })
        }
      } else {
        toast.error("投递失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      toast.error("无法连接后端投递服务")
    }
  }, [])

  // 失败岗位：重试
  const handleRetryFailedJob = useCallback(async (job: PipelineJob) => {
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
        toast.error("重试失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      toast.error("重试请求异常")
    }
  }, [])

  // 失败岗位：放弃（移出指挥中心看板）
  const handleDismissFailedJob = useCallback(async (job: PipelineJob) => {
    try {
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
        toast.info(`🗑️ 已放弃【${jobTitle}】：已移出指挥中心看板，不会再自动投递`)
        const st = usePipelineStore.getState()
        // 从当前看板 store 中移除
        const nextJobs = { ...st.jobs }
        delete nextJobs[job.job_id]
        usePipelineStore.setState({ jobs: nextJobs })
      } else {
        toast.error("放弃操作失败: " + (data.detail || data.message || "未知错误"))
      }
    } catch {
      toast.error("放弃请求异常")
    }
  }, [])

  // 批量重试执行失败岗位（接入标准编排队列，带乐观更新与回滚）
  const handleBatchRetryFailedJobs = useCallback(async (jobIds: string[]): Promise<boolean> => {
    if (!jobIds || jobIds.length === 0) return false

    // 1. 快照备份：精准备份涉及岗位的原状态，用于异常回滚
    const currentJobs = usePipelineStore.getState().jobs
    const backupMap = new Map<string, PipelineJob>()
    jobIds.forEach((id) => {
      if (currentJobs[id]) {
        backupMap.set(id, { ...currentJobs[id] })
      }
    })

    // 2. 乐观更新：将涉及岗位标记为正在排队重试
    const currentSt = usePipelineStore.getState()
    jobIds.forEach((id) => {
      if (currentSt.jobs[id]) {
        currentSt.updateJob(id, {
          status: "running",
          node: "delivery_node",
          sub_status: "delivering",
          failure_info: undefined,
          last_action_desc: "正在排队批量重试中…",
        })
      }
    })

    setBatchRetryingFailed(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/batch-retry-failed-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: jobIds }),
      })
      const data = await res.json().catch(() => ({} as any))

      if (res.ok && data.status === "success") {
        toast.success(data.message || `🚀 已成功拉起 ${jobIds.length} 个岗位的批量重试编排！`)
        return true
      } else {
        // 409 锁冲突或 400：回滚状态
        const errorMsg = data.detail || data.message || "批量重试启动失败"
        toast.error(`❌ ${errorMsg}，已恢复卡片状态`)
        const st = usePipelineStore.getState()
        backupMap.forEach((oldJob, id) => {
          if (st.jobs[id]) {
            st.updateJob(id, { ...oldJob })
          }
        })
        return false
      }
    } catch (err: any) {
      toast.error("网络异常，无法连接批量重试服务，已恢复卡片状态")
      const st = usePipelineStore.getState()
      backupMap.forEach((oldJob, id) => {
        if (st.jobs[id]) {
          st.updateJob(id, { ...oldJob })
        }
      })
      return false
    } finally {
      setBatchRetryingFailed(false)
    }
  }, [])

  // 批量放弃执行失败岗位（带乐观移除与回滚）
  const handleBatchDismissFailedJobs = useCallback(async (jobIds: string[]): Promise<boolean> => {
    if (!jobIds || jobIds.length === 0) return false

    // 1. 快照备份
    const currentJobs = usePipelineStore.getState().jobs
    const backupMap = new Map<string, PipelineJob>()
    jobIds.forEach((id) => {
      if (currentJobs[id]) {
        backupMap.set(id, { ...currentJobs[id] })
      }
    })

    // 2. 乐观移除
    const nextJobs = { ...currentJobs }
    jobIds.forEach((id) => {
      delete nextJobs[id]
    })
    usePipelineStore.setState({ jobs: nextJobs })

    setBatchDismissingFailed(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/batch-dismiss-failed-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: jobIds }),
      })
      const data = await res.json().catch(() => ({} as any))

      if (res.ok && data.status === "success") {
        toast.info(data.message || `🗑️ 已成功放弃 ${data.dismissed_count || jobIds.length} 个岗位`)
        // 若有正在投递未被放弃的岗位，回滚恢复那些岗位
        if (data.busy_count > 0) {
          const st = usePipelineStore.getState()
          const restoredJobs = { ...st.jobs }
          backupMap.forEach((oldJob, id) => {
            if (!restoredJobs[id]) {
              // 由快照轮询或当前状态恢复
              restoredJobs[id] = oldJob
            }
          })
          usePipelineStore.setState({ jobs: restoredJobs })
        }
        return true
      } else {
        toast.error("批量放弃失败: " + (data.detail || data.message || "未知错误") + "，已恢复卡片")
        const st = usePipelineStore.getState()
        const restoredJobs = { ...st.jobs }
        backupMap.forEach((oldJob, id) => {
          restoredJobs[id] = oldJob
        })
        usePipelineStore.setState({ jobs: restoredJobs })
        return false
      }
    } catch {
      toast.error("网络异常，批量放弃失败，已恢复卡片")
      const st = usePipelineStore.getState()
      const restoredJobs = { ...st.jobs }
      backupMap.forEach((oldJob, id) => {
        restoredJobs[id] = oldJob
      })
      usePipelineStore.setState({ jobs: restoredJobs })
      return false
    } finally {
      setBatchDismissingFailed(false)
    }
  }, [])

  // 单个正在投递岗位的紧急终止
  const handleCancelDelivery = useCallback(async (jobId: string) => {
    if (cancellingJobIdsRef.current[jobId]) return
    cancellingJobIdsRef.current[jobId] = true
    setCancellingJobIds((prev) => ({ ...prev, [jobId]: true }))

    const cleanupCancellingState = () => {
      delete cancellingJobIdsRef.current[jobId]
      setCancellingJobIds((prev) => {
        if (!prev[jobId]) return prev
        const next = { ...prev }
        delete next[jobId]
        return next
      })
    }

    // 10 秒超时清理保护：若网络断开或后端未推流，10秒后重置 loading，避免按钮永久禁用
    const timeoutTimer = setTimeout(() => {
      cleanupCancellingState()
    }, 10000)

    try {
      const res = await fetch(`${API_BASE}/api/automation/cancel-job-delivery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: jobId }),
      })
      const data = await res.json().catch(() => ({} as any))
      if (res.ok && data.status === "success") {
        toast.info(data.message || "🛑 终止指令已下达，正在退出并释放锁…")
        // 不抢跑更新 store，等待后端通过 SSE 或快照将岗位置为失败态
      } else {
        clearTimeout(timeoutTimer)
        toast.error("终止失败: " + (data.detail || data.message || "未知错误"))
        cleanupCancellingState()
      }
    } catch {
      clearTimeout(timeoutTimer)
      toast.error("无法连接后端终止服务")
      cleanupCancellingState()
    }
  }, [])

  return {
    batchLoading,
    deliveringBatch,
    approvingJobIds,
    batchRetryingFailed,
    batchDismissingFailed,
    cancellingJobIds,
    handleCancelDelivery,
    handleApprove,
    handleBatchApprove,
    handleTriggerDeliverAll,
    handleTriggerDeliverSingle,
    handleRetryFailedJob,
    handleDismissFailedJob,
    handleBatchRetryFailedJobs,
    handleBatchDismissFailedJobs,
  }
}

