"use client"

import { useCallback, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import type { JobData } from "@/types/job"
import { normalizePlatform } from "@/lib/job-data"
import { API_BASE } from "@/lib/api"

// 🌟 前端岗位 id 形如 "BOSS直聘-recXXX"（平台中文前缀 + 飞书记录 id），提取纯 record_id。
// B-8：与后端 extract_record_id 同口径——优先取 rec 开头的段，避免平台名含「-」时切错。
function toRecordId(jobId: string): string {
  const parts = jobId.split("-")
  for (let i = parts.length - 1; i >= 0; i--) {
    if (parts[i].startsWith("rec")) return parts[i]
  }
  return parts.length > 1 ? parts.slice(1).join("-") : jobId
}

const platformOf = (j: JobData) => normalizePlatform(j.platform)
const statusOf = (j: JobData) => (j.followStatus || "").trim()
const SUPPORTED_PLATFORMS = ["boss", "liepin", "job51", "zhilian"]

// 🌟 B-7：这些状态下的岗位不该被海投静默覆盖物料（负向终态/进行中流程），命中时需二次确认
const RISKY_MASS_APPLY_STATUSES = ["已拒绝", "不合适", "已下架", "疑似重复"]
const isRiskyMassApplyStatus = (status: string) =>
  RISKY_MASS_APPLY_STATUSES.includes(status) ||
  status.includes("面试") ||
  status.toLowerCase().includes("offer")

export interface UseBatchActionsOptions {
  jobs: JobData[]
  selectedJobIds: string[]
  setSelectedJobIds: React.Dispatch<React.SetStateAction<string[]>>
  onRefreshJobs?: (silent?: boolean, force?: boolean) => Promise<void> | void
  onBatchDelete?: (jobIds: string[]) => Promise<void>
  processingJobs?: Record<string, string>
}

export function useBatchActions({
  jobs,
  selectedJobIds,
  setSelectedJobIds,
  onRefreshJobs,
  onBatchDelete,
  processingJobs = {},
}: UseBatchActionsOptions) {
  const router = useRouter()

  const [isProcessing, setIsProcessing] = useState(false)
  // 🌟 B-10：同步 ref 守卫。state 异步刷新靠不住，双击/并发入口用 ref 同步判重
  const isProcessingRef = useRef(false)
  const setProcessing = useCallback((v: boolean) => {
    isProcessingRef.current = v
    setIsProcessing(v)
  }, [])

  const [isRefreshing, setIsRefreshing] = useState(false)
  const [refreshed, setRefreshed] = useState(false)

  // 🌟 物料检测状态
  const [missingModalOpen, setMissingModalOpen] = useState(false)
  const [missingModalJob, setMissingModalJob] = useState<JobData | null>(null)
  const [materialStatus, setMaterialStatus] = useState<{
    has_pdf?: boolean
    has_image?: boolean
    has_greeting?: boolean
    has_url?: boolean
    has_custom_json?: boolean
    platform?: string
  } | null>(null)

  // 🌟 打招呼语门禁弹窗状态
  const [greetingGateOpen, setGreetingGateOpen] = useState(false)
  const [greetingGateJobs, setGreetingGateJobs] = useState<JobData[]>([])

  // 🌟 批量批准投递物料预检弹窗状态
  const [approveModalOpen, setApproveModalOpen] = useState(false)
  const [approveModalReadyJobs, setApproveModalReadyJobs] = useState<JobData[]>([])
  const [approveModalNotReadyJobs, setApproveModalNotReadyJobs] = useState<
    Array<{ job: JobData; missing: string[] }>
  >([])

  // 🚀 只检查【当前选中的岗位】是否在运行（排除已中断状态），避免误锁死
  const isAnySelectedRunning = selectedJobIds.some(
    (id) => processingJobs[id] && processingJobs[id] !== "interrupted"
  )

  // 🌟 刷新列表：手动刷新走硬刷新（force=true 绕过后端缓存直连飞书）
  const handleRefresh = async () => {
    if (isRefreshing) return
    setIsRefreshing(true)
    setRefreshed(false)
    try {
      await onRefreshJobs?.(false, true)
    } finally {
      setIsRefreshing(false)
      setRefreshed(true)
      setTimeout(() => setRefreshed(false), 2000)
    }
  }

  // 🌟 B-6：剔除幽灵选中 id（列表刷新/删除后 selectedJobIds 里可能残留已不存在的岗位）
  const sanitizeJobIds = useCallback(
    (ids: string[]) => {
      const validSet = new Set(jobs.map((j) => j.id))
      return ids.filter((id) => validSet.has(id))
    },
    [jobs]
  )

  // 🌟 统一的批量任务派发核心（无入口守卫，供内部流程复用）：
  // POST batch-process → 抛出 START_GLOBAL_TASK 事件
  const runBatchDispatch = useCallback(
    async (
      taskType: "evaluate" | "deep_evaluate" | "rewrite" | "deliver" | "mass_apply" | "approve",
      title: string,
      extraBody: Record<string, unknown> = {},
      overrideJobIds?: string[]
    ) => {
      const targetJobIds = sanitizeJobIds(overrideJobIds ?? selectedJobIds)
      if (targetJobIds.length === 0) return

      // B4/B6 门禁：深度评估与简历改写必须先跑过初步评估（有 A-F 评级）
      if (taskType === "deep_evaluate" || taskType === "rewrite") {
        const selectedJobs = jobs.filter((j) => targetJobIds.includes(j.id))
        const notEvaluated = selectedJobs.filter((j) => !j.grade)
        if (notEvaluated.length > 0) {
          const listPreview = notEvaluated.slice(0, 5).map((j) => `· ${j.companyName} - ${j.jobTitle}`).join("\n")
          const moreHint = notEvaluated.length > 5 ? `\n· …等共 ${notEvaluated.length} 个` : ""
          const proceed = window.confirm(
            `⚠️ ${title}要求岗位先完成初步评估（有 A-F 评级）：\n${listPreview}${moreHint}\n\n` +
              `【确定】仅对已初评的 ${selectedJobs.length - notEvaluated.length} 个岗位继续${taskType === "rewrite" ? "改写" : "深评"}；\n` +
              `【取消】终止本次操作，可先对这些岗位执行「初步评估」。`
          )
          if (!proceed) return
          if (selectedJobs.length - notEvaluated.length === 0) {
            alert("❌ 所选岗位均未完成初步评估，已取消本次任务。请先执行「初步评估」再回来深评/改写。")
            return
          }
        }
      }

      if (
        targetJobIds.length > 50 &&
        !window.confirm(
          `⚠️ 已选 ${targetJobIds.length} 个岗位：批量任务是逐个串行执行的（每岗位约 1-2 分钟），数量过多会耗时很久。\n建议分批处理（每次不超过 50 个）。仍要继续吗？`
        )
      )
        return

      setProcessing(true)
      try {
        const eligibleIds =
          taskType === "deep_evaluate" || taskType === "rewrite"
            ? jobs.filter((j) => targetJobIds.includes(j.id) && j.grade).map((j) => j.id)
            : targetJobIds
        const response = await fetch(`${API_BASE}/api/tasks/batch-process`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_type: taskType, job_ids: eligibleIds, ...extraBody }),
        })
        const data = await response.json()
        if (response.ok) {
          console.log(`🚀 ${title} 已启动:`, data.task_id)
          window.dispatchEvent(
            new CustomEvent("START_GLOBAL_TASK", {
              detail: { taskId: data.task_id, title: `${title} (${eligibleIds.length}个岗位)`, jobIds: eligibleIds, taskType },
            })
          )
          setProcessing(false)
          setSelectedJobIds([])
        } else {
          alert("❌ 启动任务失败: " + (data.detail || "未知错误"))
          setProcessing(false)
        }
      } catch (error) {
        console.error(`❌ ${title} 错误:`, error)
        alert("❌ 网络错误，请检查后端是否运行")
        setProcessing(false)
      }
    },
    [jobs, sanitizeJobIds, selectedJobIds, setProcessing, setSelectedJobIds]
  )

  // 🌟 B-10：对外入口带同步守卫，防止确认弹窗期间/渲染间隙双击重复派发
  const dispatchBatchTask = useCallback(
    async (
      taskType: "evaluate" | "deep_evaluate" | "rewrite" | "deliver" | "mass_apply" | "approve",
      title: string,
      extraBody: Record<string, unknown> = {},
      overrideJobIds?: string[]
    ) => {
      if (isProcessingRef.current) return
      return runBatchDispatch(taskType, title, extraBody, overrideJobIds)
    },
    [runBatchDispatch]
  )

  const handleBatchEvaluate = () => dispatchBatchTask("evaluate", "批量 AI 评估任务")
  const handleBatchDeepEvaluate = () => dispatchBatchTask("deep_evaluate", "批量 AI 深度评估任务")
  const handleBatchRewrite = () => dispatchBatchTask("rewrite", "批量简历改写任务")

  // 🌟 批量一键海投（一步到位：0ms即时反馈 + 专属定制门禁弹窗 + 派发全局 SSE 批量任务流）
  const handleBatchMassApply = async () => {
    if (selectedJobIds.length === 0 || isProcessingRef.current) return
    setProcessing(true)

    const selectedJobs = jobs.filter((j) => selectedJobIds.includes(j.id))
    const supported = selectedJobs.filter((j) => SUPPORTED_PLATFORMS.includes(platformOf(j)))
    if (supported.length === 0) {
      setProcessing(false)
      alert("❌ 所选岗位均不支持海投（仅支持 BOSS直聘/猎聘/51job/智联招聘）")
      return
    }

    const unsupported = selectedJobs.filter((j) => !SUPPORTED_PLATFORMS.includes(platformOf(j)))
    const delivered = supported.filter((j) => statusOf(j) === "已投递")
    const readyToDeliver = supported.filter((j) => statusOf(j) === "待投递")
    const targets = supported.filter((j) => statusOf(j) !== "已投递" && statusOf(j) !== "待投递")

    if (targets.length === 0) {
      setProcessing(false)
      alert("❌ 所选岗位均已投递或已在待投递队列中，无需重复海投")
      return
    }

    // 🌟 B-7：负向终态/进行中岗位守卫——海投会用通用物料覆盖其定制简历与打招呼语，必须二次确认
    const risky = targets.filter((j) => isRiskyMassApplyStatus(statusOf(j)))
    if (risky.length > 0) {
      const listPreview = risky.slice(0, 5).map((j) => `· 【${statusOf(j)}】${j.companyName} - ${j.jobTitle}`).join("\n")
      const moreHint = risky.length > 5 ? `\n· …等共 ${risky.length} 个` : ""
      const proceed = window.confirm(
        `⚠️ 所选岗位中有 ${risky.length} 个处于非新线索状态（已拒绝/不合适/已下架/面试/Offer/疑似重复）：\n${listPreview}${moreHint}\n\n` +
          `一键海投会用通用简历物料覆盖这些岗位已有的定制简历与打招呼语。\n\n` +
          `【确定】包含这 ${risky.length} 个岗位继续海投；\n【取消】终止本次操作。`
      )
      if (!proceed) {
        setProcessing(false)
        return
      }
    }

    // 1. 直聊平台强门禁预检：仅针对需要打招呼语的平台（BOSS直聘/猎聘/智联等），纯51job投递无需阻断
    const requiresGreeting = targets.some((j) => platformOf(j) !== "job51")
    if (requiresGreeting) {
      try {
        const cfgRes = await fetch(`${API_BASE}/api/automation/config`)
        const cfgData = await cfgRes.json()
        const greeting = (cfgData?.data?.mass_apply_greeting || "").trim()
        if (!greeting) {
          setProcessing(false)
          setGreetingGateJobs(targets)
          setGreetingGateOpen(true)
          return
        }
      } catch (e) {
        // 🌟 B-11：配置预检失败改 fail-closed——后端虽有权威门禁兜底，但整批会在启动后才失败，
        // 与其浪费一次派发，不如就地终止并提示
        console.error("检测海投配置失败:", e)
        setProcessing(false)
        alert("❌ 无法确认「海投通用打招呼语」配置（后端连接失败），已终止本次海投。请检查后端运行状态后重试。")
        return
      }
    }

    // 2. 派发全局批处理任务（具备实时 SSE 进度流、卡片与雷达动效、中断与日志白盒化）
    await runBatchDispatch(
      "mass_apply",
      "批量一键海投任务",
      {},
      targets.map((j) => j.id)
    )
  }

  // 🌟 单岗位放行（物料预检 ➔ 齐全则放行，不齐则弹窗）
  const handleApproveSingleJob = async (targetJob: JobData) => {
    try {
      const res = await fetch(`${API_BASE}/api/automation/check-job-materials`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: targetJob.id }),
      })
      const data = await res.json()
      if (res.ok && data?.data) {
        if (data.data.is_ready) {
          await dispatchResumeTask("approve", [targetJob.id])
        } else {
          setMaterialStatus(data.data)
          setMissingModalJob(targetJob)
          setMissingModalOpen(true)
        }
        return
      }
      alert(
        `❌ 物料预检失败，已中止放行【${targetJob.companyName} - ${targetJob.jobTitle}】。\n` +
          "请稍后重试，或前往定制面板确认物料后手动批准。"
      )
    } catch (e) {
      console.error("物料检测请求失败:", e)
      alert(
        `❌ 无法连接物料预检服务，已中止放行【${targetJob.companyName} - ${targetJob.jobTitle}】。\n请检查后端是否运行后重试。`
      )
    }
  }

  // 🌟 批量批准投递（质检一体化：前置物料三要素预检 + 专属弹窗确认 + 派发全局 SSE 批量任务流）
  const handleBatchApprove = async () => {
    if (selectedJobIds.length === 0 || isProcessingRef.current) return
    setProcessing(true)

    const selectedJobs = jobs.filter((j) => selectedJobIds.includes(j.id))
    const ENQUEUE_STATUSES = ["简历人工复核", "海投人工复核"]

    const supportedJobs = selectedJobs.filter((j) => SUPPORTED_PLATFORMS.includes(platformOf(j)))
    const eligible = supportedJobs.filter((j) => ENQUEUE_STATUSES.includes(statusOf(j)))
    if (eligible.length === 0) {
      setProcessing(false)
      alert(
        "❌ 所选岗位均无法批准投递：需为「简历人工复核 / 海投人工复核」状态，且平台支持（BOSS直聘/猎聘/51job/智联招聘）"
      )
      return
    }

    try {
      // 1. 物料三要素严格并发预检
      const checkResults = await Promise.all(
        eligible.map(async (job) => {
          try {
            const res = await fetch(`${API_BASE}/api/automation/check-job-materials`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ record_id: job.id }),
            })
            const data = res.ok ? await res.json() : null
            const d = data?.data
            const missing: string[] = []
            if (!d) {
              missing.push("检测异常")
            } else {
              if (!d.has_url) missing.push("岗位链接")
              if (!d.has_pdf && !d.has_image) missing.push("简历附件(PDF/长图)")
              if (!d.has_greeting && platformOf(job) !== "job51") missing.push("打招呼语")
            }
            return { job, ready: !!d?.is_ready, missing }
          } catch {
            return { job, ready: false, missing: ["检测异常"] }
          }
        })
      )

      const ready = checkResults.filter((r) => r.ready).map((r) => r.job)
      const notReady = checkResults
        .filter((r) => !r.ready)
        .map((r) => ({ job: r.job, missing: r.missing }))

      setApproveModalReadyJobs(ready)
      setApproveModalNotReadyJobs(notReady)
      setApproveModalOpen(true)
    } catch (error) {
      console.error("❌ 批量批准物料预检失败:", error)
      alert("❌ 无法连接物料预检服务，请稍后重试")
    } finally {
      setProcessing(false)
    }
  }

  // 🌟 确认执行批量批准投递（派发全局 SSE 批量任务流）
  const confirmBatchApproveStream = async () => {
    const targetJobs = [
      ...approveModalReadyJobs,
      ...approveModalNotReadyJobs.map((item) => item.job),
    ]
    const targetJobIds = targetJobs.map((j) => j.id)
    if (targetJobIds.length === 0) return

    // 🌟 1. 立即清空选中项，收起浮动操作条和复选框选中态
    setSelectedJobIds([])
    // 🌟 2. 立即关闭门禁预检弹窗
    setApproveModalOpen(false)

    // 🌟 3. 启动批量任务流（卡片留在当前列表展示 4 阶段物料挂载流水线胶囊，待执行完毕再流转入待投递）
    await runBatchDispatch(
      "approve",
      "批量批准投递任务",
      {},
      targetJobIds
    )
  }

  // 🌟 审批 A 级挂起任务（单岗位批准横幅入口）
  const dispatchResumeTask = async (action: "approve" | "reject", jobIds?: string[]) => {
    const idsToProcess = sanitizeJobIds(jobIds || selectedJobIds)
    if (idsToProcess.length === 0) return
    if (isProcessingRef.current) return
    setProcessing(true)
    try {
      const threadIds = idsToProcess.map((id) => toRecordId(id))
      // 🌟 派发单项乐观更新事件，避免网络往返等待导致横幅闪烁。
      // 与批量路径（confirmBatchApproveStream）刻意不同：本路径为普通 fetch、无 SSE 流水线胶囊，
      // 不存在"卡片提前离开当前 Tab 隐藏流水线动画"的问题，因此保留 0ms 乐观更新。
      window.dispatchEvent(
        new CustomEvent("OPTIMISTIC_JOB_UPDATE", {
          detail: {
            jobIds: idsToProcess,
            followStatus: action === "approve" ? "待投递" : "已拒绝",
          },
        })
      )
      setSelectedJobIds([])
      const response = await fetch(`${API_BASE}/api/automation/resume_batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_ids: threadIds, action }),
      })
      const data = await response.json()
      if (response.ok) {
        console.log(`🚀 审批任务已发送:`, data)
        setProcessing(false)
        setSelectedJobIds([])
        await handleRefresh()
      } else {
        // 🌟 B-4：乐观更新失败必须回滚——静默硬刷新从后端拉回真实状态，防止界面停在假状态
        alert("❌ 审批失败: " + (data.detail || "未知错误"))
        setProcessing(false)
        await onRefreshJobs?.(true, true)
      }
    } catch (error) {
      console.error(`❌ 审批错误:`, error)
      // 🌟 B-4：网络异常同样回滚乐观更新
      alert("❌ 网络错误，请检查后端是否运行")
      setProcessing(false)
      await onRefreshJobs?.(true, true)
    }
  }

  // 🌟 批量删除
  const handleBatchDelete = () => {
    const validIds = sanitizeJobIds(selectedJobIds)
    if (validIds.length === 0) return
    if (isProcessingRef.current) return
    if (
      window.confirm(
        `⚠️ 危险操作：确定要从系统和飞书中永久删除选中的 ${validIds.length} 个岗位吗？此操作不可恢复！`
      )
    ) {
      setProcessing(true)
      Promise.resolve(onBatchDelete?.(validIds))
        .catch((e) => console.error("批量删除回调异常:", e))
        .finally(() => {
          setProcessing(false)
          setSelectedJobIds([])
        })
    }
  }

  // 🌟 浮动操作栏按钮索引 → 对应 handler
  const handleFloatAction = (index: number) => {
    switch (index) {
      case 0:
        return handleBatchEvaluate()
      case 1:
        return handleBatchDeepEvaluate()
      case 2:
        return handleBatchRewrite()
      case 3:
        return handleBatchMassApply()
      case 4:
        return handleBatchApprove()
      case 5:
        return handleBatchDelete()
    }
  }

  const floatDisabled = isProcessing || isAnySelectedRunning

  return {
    isProcessing,
    isRefreshing,
    refreshed,
    isAnySelectedRunning,
    floatDisabled,
    missingModalOpen,
    setMissingModalOpen,
    missingModalJob,
    materialStatus,
    greetingGateOpen,
    setGreetingGateOpen,
    greetingGateJobs,
    handleRefresh,
    dispatchBatchTask,
    handleBatchEvaluate,
    handleBatchDeepEvaluate,
    handleBatchRewrite,
    handleBatchMassApply,
    handleApproveSingleJob,
    handleBatchApprove,
    approveModalOpen,
    setApproveModalOpen,
    approveModalReadyJobs,
    approveModalNotReadyJobs,
    confirmBatchApproveStream,
    dispatchResumeTask,
    handleBatchDelete,
    handleFloatAction,
  }
}
