"use client"

import { useEffect, useState, useCallback, useRef } from "react"
import { useToast } from "@/hooks/use-toast"
import type { JobData } from "@/types/job"
import type { JobProgressInfo } from "@/components/dashboard/job-live-progress-inline"
import type { MacroProgressData } from "@/components/dashboard/filter-bar"
import { API_BASE } from "@/lib/api"

export interface UseGlobalTaskStreamOptions {
  fetchJobs: (silent?: boolean, force?: boolean) => Promise<void>
  setSelectedJob: React.Dispatch<React.SetStateAction<JobData | null>>
  setJobs: React.Dispatch<React.SetStateAction<JobData[]>>
  setTrashBinCount: React.Dispatch<React.SetStateAction<number>>
}

// 🌟 鲁棒的岗位 ID 归一化比对工具（兼容 "BOSS直聘-recXXX" 与纯 "recXXX" 双向模糊/前后缀匹配）
function isMatchJobId(jobId: string, targetId: string): boolean {
  if (!jobId || !targetId) return false
  if (jobId === targetId) return true
  if (jobId.endsWith(`-${targetId}`) || targetId.endsWith(`-${jobId}`)) return true
  const ridA = jobId.includes("-") ? jobId.split("-").pop()! : jobId
  const ridB = targetId.includes("-") ? targetId.split("-").pop()! : targetId
  return !!ridA && !!ridB && ridA === ridB
}

// 🌟 B-1：SSE 断线重连策略（指数退避：2s/4s/8s/16s，共 5 次连接机会）
const MAX_SSE_ATTEMPTS = 5
const RECONNECT_BASE_DELAY_MS = 2000
const RECONNECT_MAX_DELAY_MS = 30000

interface ActiveTaskStream {
  es: EventSource
  jobIds: string[]
}

export function useGlobalTaskStream({
  fetchJobs,
  setSelectedJob,
  setJobs,
  setTrashBinCount,
}: UseGlobalTaskStreamOptions) {
  const { toast } = useToast()

  const [processingJobs, setProcessingJobs] = useState<Record<string, string>>({})
  const [jobProgressMap, setJobProgressMap] = useState<Record<string, JobProgressInfo>>({})
  const [macroProgress, setMacroProgress] = useState<MacroProgressData | null>(null)
  const [jobLiveLogs, setJobLiveLogs] = useState<Record<string, string[]>>({})
  const [globalTaskStatus, setGlobalTaskStatus] = useState<
    "idle" | "running" | "completed" | "interrupted"
  >("idle")

  // 🌟 B-2：多批量任务并存。按 taskId 管理 EventSource，派发新任务不再掐断旧任务的进度流
  const activeStreamsRef = useRef<Map<string, ActiveTaskStream>>(new Map())
  // 🌟 B-1：断线重连的定时器登记（卸载时统一清理）
  const reconnectTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const processingJobsRef = useRef<Record<string, string>>({})
  // 🌟 Q23：任务流消息批量缓冲。后端重连会整段回放任务事件日志，若逐条 handleSseMessage，
  // 每条消息都触发一次大卡量看板重渲染（130+ 卡时主线程秒级~分钟级冻结）。
  // 缓冲 200ms 统一 flush：同一同步块内的多次 setState 被 React 18 自动合并为一次渲染。
  const pendingSseMsgsRef = useRef<any[]>([])
  const sseFlushTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const handleSseMessageRef = useRef<(data: any) => void>(() => {})
  const flushPendingSseMsgs = () => {
    const buf = pendingSseMsgsRef.current
    if (!buf.length) return
    pendingSseMsgsRef.current = []
    for (const msg of buf) {
      try {
        handleSseMessageRef.current(msg)
      } catch (err) {
        // 单条异常只丢该条，不中断同批其余合法消息
        console.warn("⚠️ [SSE] 单条任务消息处理异常(已跳过):", err)
      }
    }
    // 队列已清空且无活跃流时停表，避免空转轮询
    if (!pendingSseMsgsRef.current.length && activeStreamsRef.current.size === 0 && sseFlushTimerRef.current) {
      clearInterval(sseFlushTimerRef.current)
      sseFlushTimerRef.current = null
    }
  }

  useEffect(() => {
    processingJobsRef.current = processingJobs
  }, [processingJobs])

  // 🌟 清除指定岗位的处理中/微进度状态（scoped：只动本批岗位，不误伤其它在跑任务）
  const clearJobsProcessing = useCallback((jobIds: string[]) => {
    const idSet = new Set(jobIds)
    setProcessingJobs((prev) => {
      if (!jobIds.some((id) => id in prev)) return prev
      const next = { ...prev }
      for (const id of idSet) delete next[id]
      return next
    })
    setJobProgressMap((prev) => {
      if (!jobIds.some((id) => id in prev)) return prev
      const next = { ...prev }
      for (const id of idSet) delete next[id]
      return next
    })
  }, [])

  // 🌟 单个批量任务流终态收尾（scoped）：清本批岗位转圈 → 刷数据；
  // 仅当没有其它活跃批量流时才把全局状态置为 completed
  const finalizeTaskStream = useCallback(
    (_taskId: string, jobIds: string[]) => {
      clearJobsProcessing(jobIds)
      fetchJobs(true, false)
      if (activeStreamsRef.current.size > 0) return

      setGlobalTaskStatus("completed")
      setMacroProgress((prev) =>
        prev
          ? {
              ...prev,
              isWaveDone: true,
              statusText: `批量任务完结 (共 ${prev.totalJobs || 0} 岗全部就绪) ✓`,
            }
          : {
              isWaveDone: true,
              statusText: "批量任务完结 ✓",
            }
      )
      setTimeout(() => {
        setGlobalTaskStatus("idle")
        setMacroProgress(null)
        setJobLiveLogs({})
      }, 10000)
    },
    [clearJobsProcessing, fetchJobs]
  )

  // 🌟 判定批量任务连接中断：岗位切换为可一键重试状态
  const markTaskInterrupted = useCallback(
    (jobIds: string[]) => {
      setProcessingJobs((prev) => {
        const next = { ...prev }
        for (const id of jobIds) {
          if (next[id] && next[id] !== "completed") {
            next[id] = "interrupted"
          }
        }
        return next
      })
      setGlobalTaskStatus("interrupted")
      toast({
        title: "⚠️ 批量任务连接中断",
        description: "检测到后端连接断开或服务重载，任务已中断。岗位已切换为可一键重试状态。",
        variant: "destructive",
      })
    },
    [toast]
  )

  const handleSseMessage = useCallback(
    (data: any) => {
      if (!data) return
      const rawId = data.job_id || data.record_id
      let targetKey = rawId

      if (rawId) {
        const activeKeys = Object.keys(processingJobsRef.current)
        const matchedKey = activeKeys.find(
          (key) => key === rawId || key.endsWith(`-${rawId}`) || key.includes(rawId) || rawId.includes(key)
        )
        if (matchedKey) targetKey = matchedKey
      }

      if (targetKey && data.message) {
        setJobLiveLogs((prev) => ({
          ...prev,
          [targetKey]: [...(prev[targetKey] ?? []), data.message].slice(-3),
        }))
      }

      // 🌟 监听微观子阶段进度 (用于岗位卡片内嵌 SSE 节点)
      if ((data.type === "progress" || data.type === "stage_progress") && targetKey) {
        setJobProgressMap((prev) => ({
          ...prev,
          [targetKey]: {
            subStage: data.sub_stage,
            totalStages: data.total_stages,
            stageTitle: data.stage_title,
            message: data.message,
            updatedAt: Date.now(),
          },
        }))
      }

      // 🌟 监听宏观波次进度 (用于左上角 FilterBar 宏观波次雷达)
      if (data.type === "wave_status") {
        setMacroProgress((prev) => ({
          ...prev,
          totalJobs: data.total_jobs ?? prev?.totalJobs,
          currentWave: data.wave,
          totalWaves: data.total_waves,
          waveName: data.wave_name,
          waveCurrent: data.wave_current,
          waveTotal: data.wave_total,
          statusText: data.status_text || data.message,
          isWaveDone: !!data.is_wave_done,
        }))
      }

      // 🌟 监听清洗报告事件
      if (data.type === "cleaning_report" && data.data) {
        const { hard_rejected, ai_rejected } = data.data
        setTrashBinCount((prev) => prev + (hard_rejected + ai_rejected))
      }

      // 🌟 任务开始
      if (data.type === "start") {
        setGlobalTaskStatus("running")
        if (data.total_jobs) {
          setMacroProgress((prev) => ({
            ...prev,
            totalJobs: data.total_jobs,
            statusText: data.message || "批量任务已启动...",
          }))
        }
      }

      // 🌟 标准生命周期状态码
      const isFinished =
        data.type === "done" ||
        data.type === "error" ||
        data.type === "close" ||
        data.type === "success"

      if (isFinished && targetKey) {
        // 1. 立即解除该岗位的转圈状态
        setProcessingJobs((prev) => {
          const next = { ...prev }
          delete next[targetKey]
          return next
        })

        // 2. 清除该岗位的微观进度缓存
        setJobProgressMap((prev) => {
          const next = { ...prev }
          delete next[targetKey]
          return next
        })

        // 3. 如果后端传了具体的更新数据，执行局部热更新
        if (data.job_updates) {
          const updates = { ...data.job_updates }
          if (updates.follow_status && !updates.followStatus) {
            updates.followStatus = updates.follow_status
          }
          setJobs((prev) =>
            prev.map((job) => (isMatchJobId(job.id, targetKey) ? { ...job, ...updates } : job))
          )
          setSelectedJob((prev) => {
            if (!prev) return null
            return isMatchJobId(prev.id, targetKey) ? { ...prev, ...updates } : prev
          })
        } else {
          fetchJobs(true, false)
        }
      }

      // 🌟 终态收尾：批量任务流（attachTaskSse 管理）的 end/complete 在流包装层做 scoped 收尾，
      // 不会走到这里；此处只处理爬虫/清洗等外部终端流的全局收尾。
      // 若仍有活跃批量流，跳过全局清理（防止误清在跑任务的转圈），仅静默刷数据。
      if (data.type === "end" || data.type === "complete") {
        if (activeStreamsRef.current.size > 0) {
          fetchJobs(true, false)
          return
        }
        console.log("🎉 [SSE] 收到任务完成信号:", data)
        setGlobalTaskStatus("completed")
        setMacroProgress((prev) =>
          prev
            ? {
                ...prev,
                isWaveDone: true,
                statusText: `批量任务完结 (共 ${prev.totalJobs || 0} 岗全部就绪) ✓`,
              }
            : {
                isWaveDone: true,
                statusText: "批量任务完结 ✓",
              }
        )
        setProcessingJobs({})
        setJobProgressMap({})
        // 🌟 任务完结时执行静默刷新（读取后端已原地打了热补丁的最新 JobCache），
        // 杜绝因飞书 Bitable 索引写入异步延迟（2~10s）导致旧状态倒灌覆盖
        fetchJobs(true, false)
        setTimeout(() => {
          setGlobalTaskStatus("idle")
          setMacroProgress(null)
          setJobLiveLogs({})
        }, 10000)
      }
    },
    [fetchJobs, setJobs, setSelectedJob, setTrashBinCount]
  )

  // Q23：flush 经 ref 调用最新版 handler，避免闭包过期
  handleSseMessageRef.current = handleSseMessage

  // 🌟 复用的 SSE 任务长连接管理器（B-2：多流并存；B-1：断线探活 + 指数退避重连）
  const attachTaskSse = useCallback(
    (taskId: string, jobIds: string[], attempt = 1) => {
      // 同一任务已有旧连接或重连排程 → 先清理（重连场景）
      const prevStream = activeStreamsRef.current.get(taskId)
      if (prevStream) {
        prevStream.es.close()
        activeStreamsRef.current.delete(taskId)
      }
      const pendingTimer = reconnectTimersRef.current.get(taskId)
      if (pendingTimer) {
        clearTimeout(pendingTimer)
        reconnectTimersRef.current.delete(taskId)
      }

      const sseUrl = `${API_BASE}/api/tasks/logs?task_id=${taskId}`
      console.log(`🔌 [SSE 连接] 正在接入任务流: ${taskId} (第 ${attempt} 次)`)
      const eventSource = new EventSource(sseUrl)
      activeStreamsRef.current.set(taskId, { es: eventSource, jobIds })
      let isStreamEndedNormally = false
      // 🌟 P3 加固：退避计数用可变变量承载——连接一旦成功建立即重置，
      // 长批次任务期间多次偶发断线不会被累计成「连续 5 次」而误判中断
      let currentAttempt = attempt

      const finishStream = () => {
        isStreamEndedNormally = true
        eventSource.close()
        if (activeStreamsRef.current.get(taskId)?.es === eventSource) {
          activeStreamsRef.current.delete(taskId)
        }
      }

      const scheduleReconnect = () => {
        if (currentAttempt >= MAX_SSE_ATTEMPTS) {
          console.error(`🛑 [SSE] 任务 ${taskId} 连续 ${currentAttempt} 次连接失败，判定中断`)
          markTaskInterrupted(jobIds)
          return
        }
        const delay = Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_BASE_DELAY_MS * 2 ** (currentAttempt - 1))
        console.warn(`🔁 [SSE] 将在 ${delay / 1000}s 后重连任务流 ${taskId} (第 ${currentAttempt + 1} 次)`)
        const timer = setTimeout(() => attachTaskSse(taskId, jobIds, currentAttempt + 1), delay)
        reconnectTimersRef.current.set(taskId, timer)
      }

      eventSource.onopen = () => {
        if (currentAttempt !== 1) {
          console.log(`✅ [SSE] 任务流 ${taskId} 重连成功，退避计数已重置`)
        }
        currentAttempt = 1
      }

      eventSource.onmessage = (event) => {
        try {
          const parsedData = JSON.parse(event.data)
          if (
            parsedData.type === "end" ||
            parsedData.type === "complete" ||
            parsedData.type === "terminated"
          ) {
            flushPendingSseMsgs()
            finishStream()
            finalizeTaskStream(taskId, jobIds)
            return
          }
          pendingSseMsgsRef.current.push(parsedData)
          if (!sseFlushTimerRef.current) {
            sseFlushTimerRef.current = setInterval(flushPendingSseMsgs, 200)
          }
        } catch (err) {
          console.error("SSE 解析错误:", err)
        }
      }

      eventSource.addEventListener("end", () => {
        finishStream()
        finalizeTaskStream(taskId, jobIds)
      })

      eventSource.onerror = async () => {
        if (isStreamEndedNormally) {
          return
        }
        console.warn("⚠️ SSE 连接断开或异常，正在探活后端任务状态...", taskId)
        finishStream()

        try {
          const res = await fetch(`${API_BASE}/api/tasks/status?task_id=${taskId}`)
          if (res.ok) {
            const statusData = await res.json()
            if (statusData.task && statusData.task.status === "completed") {
              console.log("✅ 经探活确认，后台任务已顺利完成，刷新列表数据")
              clearJobsProcessing(jobIds)
              if (activeStreamsRef.current.size === 0) {
                setGlobalTaskStatus("completed")
                setTimeout(() => setGlobalTaskStatus("idle"), 5000)
              }
              fetchJobs(true)
              return
            }

            // 🌟 B-1 修复：后端仍在运行（或任务排队中）→ 指数退避重连，而不是放弃导致 UI 永久卡「运行中」
            if (
              statusData.is_processing ||
              statusData.task?.status === "running" ||
              statusData.task?.status === "pending"
            ) {
              scheduleReconnect()
              return
            }

            // 后端无活跃任务且未完成 → 批量任务已中断
            markTaskInterrupted(jobIds)
            return
          }
          // 探活接口本身异常 → 走重连兜底
          scheduleReconnect()
        } catch {
          // 🌟 后端暂时不可达（网络抖动/重启中）→ 同样给重连机会，超限才判离线
          console.error("后端探活请求失败:", taskId)
          if (currentAttempt >= MAX_SSE_ATTEMPTS) {
            setProcessingJobs((prev) => {
              const next = { ...prev }
              for (const id of jobIds) {
                if (next[id]) next[id] = "interrupted"
              }
              return next
            })
            setGlobalTaskStatus("interrupted")
            toast({
              title: "❌ 后端服务离线",
              description: "无法连接到后端任务接口，请检查服务状态。",
              variant: "destructive",
            })
            return
          }
          scheduleReconnect()
        }
      }
    },
    [handleSseMessage, finalizeTaskStream, clearJobsProcessing, markTaskInterrupted, toast]
  )

  // 🌟 监听 START_GLOBAL_TASK 事件（B-2：不再关闭其它任务的流）
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (Array.isArray(detail?.jobIds) && detail?.taskType) {
        const type = detail.taskType as string
        setProcessingJobs((prev) => ({
          ...prev,
          ...Object.fromEntries(detail.jobIds.map((id: string) => [id, type])),
        }))
        setMacroProgress({
          totalJobs: detail.jobIds.length,
          taskType: type,
          statusText: `批量任务启动 (共 ${detail.jobIds.length} 岗)...`,
        })
        setGlobalTaskStatus("running")

        if (detail.taskId) {
          attachTaskSse(detail.taskId, detail.jobIds)
        }
      }
    }
    window.addEventListener("START_GLOBAL_TASK", handler)
    return () => window.removeEventListener("START_GLOBAL_TASK", handler)
  }, [attachTaskSse])

  // 🌟 核心增强：监听单项乐观更新事件
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (Array.isArray(detail?.jobIds) && detail?.followStatus) {
        const targetIds: string[] = detail.jobIds
        const newStatus = detail.followStatus
        setJobs((prev) =>
          prev.map((job) => {
            const hit = targetIds.some((id) => isMatchJobId(job.id, id))
            return hit ? { ...job, followStatus: newStatus } : job
          })
        )
        setSelectedJob((prev) => {
          if (!prev) return null
          const hit = targetIds.some((id) => isMatchJobId(prev.id, id))
          return hit ? { ...prev, followStatus: newStatus } : prev
        })
      }
    }
    window.addEventListener("OPTIMISTIC_JOB_UPDATE", handler)
    return () => window.removeEventListener("OPTIMISTIC_JOB_UPDATE", handler)
  }, [setJobs, setSelectedJob])

  // 🌟 核心增强：页面挂载（包括从数据大盘切回主页）时，探活后台任务状态并自动续连
  useEffect(() => {
    let isMounted = true

    const checkAndReattachTask = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/tasks/status`)
        if (!res.ok || !isMounted) return
        const data = await res.json()

        if (data.is_processing && (data.current_task_id || data.task_id)) {
          const activeTid = data.current_task_id || data.task_id
          console.log(`🔄 [主页断点探活] 发现后台正在执行批量任务: ${activeTid}`)
          const taskInfo = data.task || {}
          const jobIds: string[] = taskInfo.job_ids || []
          const taskType: string = taskInfo.task_type || "evaluate"

          if (jobIds.length > 0) {
            setProcessingJobs(Object.fromEntries(jobIds.map((id: string) => [id, taskType])))
            setMacroProgress({
              totalJobs: jobIds.length,
              taskType,
              statusText: "已续连后台批量流水线...",
            })
          }
          setGlobalTaskStatus("running")
          attachTaskSse(activeTid, jobIds)
        } else if (data.task && data.task.status === "completed") {
          console.log("ℹ️ [主页断点探活] 后台任务已完结，执行静默数据同步")
          fetchJobs(true)
        }
      } catch (err) {
        console.warn("⚠️ [主页断点探活] 探活异常:", err)
      }
    }

    checkAndReattachTask()

    return () => {
      isMounted = false
      // 🌟 B-2：卸载时关闭所有批量任务流与重连排程
      for (const [, stream] of activeStreamsRef.current) {
        stream.es.close()
      }
      activeStreamsRef.current.clear()
      for (const [, timer] of reconnectTimersRef.current) {
        clearTimeout(timer)
      }
      reconnectTimersRef.current.clear()
      // Q23：flush 定时器随流管理 effect 生命周期启停
      if (sseFlushTimerRef.current) {
        clearInterval(sseFlushTimerRef.current)
        sseFlushTimerRef.current = null
      }
      flushPendingSseMsgs()
    }
  }, [attachTaskSse, fetchJobs])

  // 🌟 监听 Skill 执行任务
  useEffect(() => {
    const handleSkillTask = async (e: Event) => {
      const { skillId, taskId } = (e as CustomEvent).detail

      console.log(`🎯 [Skill] 收到执行请求：skill=${skillId}, taskId=${taskId}`)
      if (!taskId) {
        alert(`❌ Skill 执行失败：未返回 task_id`)
        return
      }

      const sseUrl = `${API_BASE}/api/tasks/logs?task_id=${taskId}`
      const eventSource = new EventSource(sseUrl)

      setProcessingJobs((prev) => ({
        ...prev,
        [`${skillId}-${taskId}`]: `skill:${skillId}`,
      }))
      setGlobalTaskStatus("running")

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === "progress") {
            console.log(`🔄 [${skillId}] 进度：${data.message || "处理中..."}`)
          }

          if (data.type === "write_back" && data.job_updates) {
            console.log(`✅ [${skillId}] 写入飞书成功`)
            setSelectedJob((prev) => (prev ? { ...prev, ...data.job_updates } : prev))
          }

          if (data.type === "done" || data.type === "success") {
            console.log(` [${skillId}] 任务完成`)
            fetchJobs(true)
            setTimeout(() => {
              alert(`✅ Skill "${skillId}" 改写完成！\n\n结果已自动保存到简历画布。`)
            }, 500)
            eventSource.close()
          }
        } catch (err) {
          console.error("SSE 解析错误:", err)
        }
      }

      eventSource.addEventListener("end", () => {
        console.log(`🔚 [${skillId}] SSE 连接关闭`)
        eventSource.close()
      })

      eventSource.onerror = (err) => {
        console.error(`❌ [${skillId}] SSE 连接错误:`, err)
        alert(`❌ Skill 执行异常：${err}`)
        eventSource.close()
      }
    }

    window.addEventListener("START_SKILL_TASK", handleSkillTask)
    return () => window.removeEventListener("START_SKILL_TASK", handleSkillTask)
  }, [fetchJobs, setSelectedJob])

  // 🌟 智能全局解锁机制：侦测所有并发任务是否全部完结
  useEffect(() => {
    const activeRunningCount = Object.values(processingJobs).filter(
      (s) => s !== "interrupted"
    ).length
    if (globalTaskStatus === "running" && activeRunningCount === 0) {
      console.log("✅ 所有独立岗位任务均已结束，全局状态完结")
      setGlobalTaskStatus("completed")
      fetchJobs(true)
    }
  }, [processingJobs, globalTaskStatus, fetchJobs])

  // 🌟 自动淡出控制
  useEffect(() => {
    if (globalTaskStatus === "completed") {
      const timer = setTimeout(() => {
        setGlobalTaskStatus("idle")
        setJobLiveLogs({})
      }, 4000)
      return () => clearTimeout(timer)
    }
  }, [globalTaskStatus])

  return {
    processingJobs,
    setProcessingJobs,
    jobProgressMap,
    macroProgress,
    jobLiveLogs,
    globalTaskStatus,
    setGlobalTaskStatus,
    handleSseMessage,
    attachTaskSse,
  }
}
