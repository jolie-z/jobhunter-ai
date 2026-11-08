"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"
import { usePipelineStore, PipelineJob } from "@/store/pipeline-store"
import { isJobDelivering, isJobReadyToDeliver, isJobWaitingReview } from "../job-predicates"
import { nowLocalString } from "@/lib/local-time"

const RELEASED_DESC = "老板放行就绪，等待定时发射"

// 后端 422 校验错误的 detail 是 Pydantic 数组（审计 P2-25）：直接 toast 会显示 [object Object]
function safeDetail(data: any, fallback: string): string {
  const d = data?.detail
  if (Array.isArray(d)) return String(d[0]?.msg || (typeof d[0] === "object" ? JSON.stringify(d[0]) : d[0]) || fallback)
  if (d && typeof d === "object") return JSON.stringify(d)
  return String(d || data?.message || fallback)
}

export function useBoardActions(waitingJobs: PipelineJob[], readyToDeliverJobs: PipelineJob[]) {
  const [batchLoading, setBatchLoading] = useState(false)
  const [deliveringBatch, setDeliveringBatch] = useState(false)
  const [approvingJobIds, setApprovingJobIds] = useState<Record<string, boolean>>({})
  // 单岗「重试/立即投递」防抖（2026-11-02 审计 P1-11）：failed-job-card 的 onRetry
  // 分支先于本地 setRetrying 返回、按钮禁用永不生效，双击会 spawn 并发后台任务。
  // 照抄 cancellingJobIdsRef 模式：ref 立即占位（同步拦连击），state 驱动按钮禁用
  const [deliveringJobIds, setDeliveringJobIds] = useState<Record<string, boolean>>({})
  const deliveringJobIdsRef = useRef<Record<string, boolean>>({})
  const [batchRetryingFailed, setBatchRetryingFailed] = useState(false)
  const [batchDismissingFailed, setBatchDismissingFailed] = useState(false)
  const [cancellingJobIds, setCancellingJobIds] = useState<Record<string, boolean>>({})
  const cancellingJobIdsRef = useRef<Record<string, boolean>>({})
  // 终止兜底定时器句柄：store 复位时提前 clear，避免迟到回调在组件卸载后仍持有闭包
  const cancelTimersRef = useRef<
    Record<string, { buffered?: ReturnType<typeof setTimeout>; longTail?: ReturnType<typeof setTimeout> }>
  >({})

  const clearCancelTimers = useCallback((jobId: string) => {
    const timers = cancelTimersRef.current[jobId]
    if (!timers) return
    if (timers.buffered) clearTimeout(timers.buffered)
    if (timers.longTail) clearTimeout(timers.longTail)
    delete cancelTimersRef.current[jobId]
  }, [])

  // 从 store 获取更新方法，确保类型一致性和统一的修改入口
  const updateJob = usePipelineStore((s) => s.updateJob)

  // 「终止中」状态跟随真实投递状态：岗位一旦离开 delivering（终止生效/投递结束/失败落账），
  // 立即复位按钮。此前只靠 10 秒定时器盲复位——后端仍在等待预检窗口时按钮会提前恢复可点，
  // 用户重复点击只会得到「已处于终止处理流程中」。
  useEffect(() => {
    const sync = (jobs: Record<string, PipelineJob>) => {
      setCancellingJobIds((prev) => {
        const stale = Object.keys(prev).filter((id) => !isJobDelivering(jobs[id]))
        if (stale.length === 0) return prev
        const next = { ...prev }
        for (const id of stale) {
          delete next[id]
          delete cancellingJobIdsRef.current[id]
          clearCancelTimers(id)
        }
        return next
      })
    }
    sync(usePipelineStore.getState().jobs)
    return usePipelineStore.subscribe((state) => sync(state.jobs))
  }, [clearCancelTimers])

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
          toast.error("审批操作失败: " + safeDetail(data, "未知错误"))
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
        toast.error("放行中止: " + safeDetail(data, "未知错误"))
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
    // 与单岗防抖互斥（审计 P1-11）：任一单岗投递在途时批量暂缓
    if (Object.keys(deliveringJobIdsRef.current).length > 0) {
      toast.warning("有岗位正在单岗投递中，请稍候再批量触发")
      return
    }
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
        toast.error("触发投递失败: " + safeDetail(data, "未知错误"))
      }
    } catch {
      toast.error("无法连接后端投递服务")
    } finally {
      setDeliveringBatch(false)
    }
  }, []) // 移掉 readyToDeliverJobs 依赖，直接使用 store

  // 单个立即触发投递
  const handleTriggerDeliverSingle = useCallback(async (jobId: string) => {
    if (deliveringJobIdsRef.current[jobId]) return  // 在途拦截：双击不再产生并发后台任务
    deliveringJobIdsRef.current[jobId] = true
    setDeliveringJobIds((prev) => ({ ...prev, [jobId]: true }))
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
        toast.error("投递失败: " + safeDetail(data, "未知错误"))
      }
    } catch {
      toast.error("无法连接后端投递服务")
    } finally {
      delete deliveringJobIdsRef.current[jobId]
      setDeliveringJobIds((prev) => {
        const next = { ...prev }
        delete next[jobId]
        return next
      })
    }
  }, [])

  // 失败岗位：重试
  const handleRetryFailedJob = useCallback(async (job: PipelineJob) => {
    if (deliveringJobIdsRef.current[job.job_id]) return  // 在途拦截（同上）
    deliveringJobIdsRef.current[job.job_id] = true
    setDeliveringJobIds((prev) => ({ ...prev, [job.job_id]: true }))
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
        toast.error("重试失败: " + safeDetail(data, "未知错误"))
      }
    } catch {
      toast.error("重试请求异常")
    } finally {
      delete deliveringJobIdsRef.current[job.job_id]
      setDeliveringJobIds((prev) => {
        const next = { ...prev }
        delete next[job.job_id]
        return next
      })
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
        toast.error("放弃操作失败: " + safeDetail(data, "未知错误"))
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
        const busyIds: string[] = Array.isArray(data.busy_ids) ? data.busy_ids : []
        // 墓碑登记（审计 P2-19；CR-B3-R1 修正）：仅放弃成功者 removeJob（busy 岗位不登记，
        // 否则稍后恢复的卡片会被快照合并直接丢弃）
        jobIds.forEach((id) => {
          if (busyIds.includes(id)) return
          usePipelineStore.getState().removeJob(id)
        })
        // 恢复在途（busy）岗位（CR-B3-R1 修正）：重新 getState（原版复用 removeJob 前的
        // 陈旧快照把删除覆盖回去）；仅恢复 busy 且看板中已消失者，不再遍历全量 backupMap
        if (data.busy_count > 0) {
          const restoredJobs = { ...usePipelineStore.getState().jobs }
          backupMap.forEach((oldJob, id) => {
            if (busyIds.includes(id) && !restoredJobs[id]) {
              restoredJobs[id] = oldJob
            }
          })
          usePipelineStore.setState({ jobs: restoredJobs })
        }
        return true
      } else {
        toast.error("批量放弃失败: " + safeDetail(data, "未知错误") + "，已恢复卡片")
        const cur = usePipelineStore.getState()
        const restoredJobs = { ...cur.jobs }
        backupMap.forEach((oldJob, id) => {
          // 回滚不覆盖最新快照（审计 P2-19）：请求在途期间 12s 轮询/SSE 可能已推进
          // 该岗位状态，仅恢复「看板中已消失（未被新快照接管）」的岗位
          if (!restoredJobs[id]) {
            restoredJobs[id] = oldJob
          }
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
      clearCancelTimers(jobId)
      delete cancellingJobIdsRef.current[jobId]
      setCancellingJobIds((prev) => {
        if (!prev[jobId]) return prev
        const next = { ...prev }
        delete next[jobId]
        return next
      })
    }

    // 网络层兜底：仅防「请求本身挂起」导致按钮永久禁用。请求一旦返回，终止中状态交给
    // 真实的投递状态驱动（见上方 store 订阅），不再 10 秒盲复位。
    const requestTimeout = setTimeout(() => {
      cleanupCancellingState()
    }, 10000)

    try {
      const res = await fetch(`${API_BASE}/api/automation/cancel-job-delivery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: jobId }),
      })
      clearTimeout(requestTimeout)
      const data = await res.json().catch(() => ({} as any))
      if (res.ok && data.status === "success") {
        toast.info(data.message || "🛑 终止指令已下达，正在退出并释放锁…")
        // 不抢跑更新 store，等后端快照把岗位移出投递中；按钮复位由 store 订阅自动完成。
        // interrupted=true 表示浏览器已破门打断，给状态推流留 3s 缓冲后兜底复位；
        // 兜底前复判一次 delivering——后端收尾超过 3s 时不能提前复活按钮。
        if (data.interrupted === true) {
          cancelTimersRef.current[jobId] = {
            ...(cancelTimersRef.current[jobId] || {}),
            buffered: setTimeout(() => {
              if (!isJobDelivering(usePipelineStore.getState().jobs[jobId])) {
                cleanupCancellingState()
              }
            }, 3000),
          }
        }
        // 长尾兜底（2026-10-30 CR R2-P1）：终态推送丢失/断流时「终止中」不能永久禁用按钮。
        // 120s 后无条件复位；此时重复点击由后端 already_cancelled 幂等兜住，只多一条提示。
        // interrupted=false（预检等待被终止）同样受此保护——它本就没有 3s 分支。
        cancelTimersRef.current[jobId] = {
          ...(cancelTimersRef.current[jobId] || {}),
          longTail: setTimeout(() => cleanupCancellingState(), 120000),
        }
      } else {
        toast.error("终止失败: " + safeDetail(data, "未知错误"))
        cleanupCancellingState()
      }
    } catch {
      clearTimeout(requestTimeout)
      toast.error("无法连接后端终止服务")
      cleanupCancellingState()
    }
  }, [clearCancelTimers])

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
    deliveringJobIds,
    handleDismissFailedJob,
    handleBatchRetryFailedJobs,
    handleBatchDismissFailedJobs,
  }
}

