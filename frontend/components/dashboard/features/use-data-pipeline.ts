import { useState, useEffect, useRef } from "react"
import { toast } from "sonner"
import { useCrawlerTaskStore } from "@/store/crawler-task-store"
import { getMainApiBase } from "@/lib/platform-auth"
import { fetchMissingKeys } from "@/lib/readiness"

export interface PipelineStats {
  raw_pending: number
  ai_pending: number
  global_pending: number
  global_breakdown: Record<string, number>
  ready_to_sync: number
  synced_count: number
  rejected_count: number
  rejected_rule_count: number
  rejected_ai_count: number
  xhs_pending: number
}

interface UseDataPipelineProps {
  onTaskStarted: () => void
}

export function useDataPipeline({ onTaskStarted }: UseDataPipelineProps) {
  const [stats, setStats] = useState<PipelineStats>({
    raw_pending: 0,
    ai_pending: 0,
    global_pending: 0,
    global_breakdown: {},
    ready_to_sync: 0,
    synced_count: 0,
    rejected_count: 0,
    rejected_rule_count: 0,
    rejected_ai_count: 0,
    xhs_pending: 0,
  })
  const [loading, setLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [runningTask, setRunningTask] = useState<string | null>(null)
  // 小红书清洗的视觉模型闸门：非 null 时展示配置引导弹窗（缺失字段列表）
  const [xhsGate, setXhsGate] = useState<string[] | null>(null)
  const [cleanLimit, setCleanLimit] = useState<string>("10")

  const addTask = useCrawlerTaskStore((state) => state.addTask)
  const tasks = useCrawlerTaskStore((state) => state.tasks)
  const activeCleaningTask = Object.values(tasks).find((t) =>
    ['pending', 'running', 'cleaning'].includes(t.status) &&
    (t.platform === 'global' || t.id.startsWith('clean_') || t.id.startsWith('sync_feishu_') || t.id.startsWith('skip_ai_'))
  )
  const isProcessing = runningTask !== null || Boolean(activeCleaningTask)
  const abortControllerRef = useRef<AbortController | null>(null)
  const isFetchingRef = useRef<boolean>(false)

  const fetchStats = async (isManual = false) => {
    if (isFetchingRef.current && !isManual) {
      return
    }

    if (isManual) {
      abortControllerRef.current?.abort()
    }

    const controller = new AbortController()
    abortControllerRef.current = controller
    isFetchingRef.current = true
    const startTime = Date.now()

    if (isManual) {
      setIsRefreshing(true)
    }

    try {
      const apiBase = getMainApiBase()
      const res = await fetch(`${apiBase}/v1/processor/stats`, {
        signal: controller.signal,
      })
      if (res.ok) {
        const data = await res.json()
        setStats({
          raw_pending: Number(data.raw_pending ?? data.global_pending) || 0,
          ai_pending: Number(data.ai_pending) || 0,
          global_pending: Number(data.global_pending) || 0,
          global_breakdown: data.global_breakdown && typeof data.global_breakdown === "object" ? data.global_breakdown : {},
          ready_to_sync: Number(data.ready_to_sync) || 0,
          synced_count: Number(data.synced_count) || 0,
          rejected_count: Number(data.rejected_count) || 0,
          rejected_rule_count: Number(data.rejected_rule_count) || 0,
          rejected_ai_count: Number(data.rejected_ai_count) || 0,
          xhs_pending: Number(data.xhs_pending) || 0,
        })
      }
    } catch (e: unknown) {
      if (controller.signal.aborted) return
      if (e instanceof Error && e.name === "AbortError") return
      console.warn("[DataExplorer] 轮询获取流水线指标重试中:", e)
      if (isManual) {
        toast.error("刷新流水线数据失败，请确认后端服务运行中")
      }
    } finally {
      if (abortControllerRef.current === controller) {
        isFetchingRef.current = false
        if (isManual) {
          const elapsed = Date.now() - startTime
          if (elapsed < 500) {
            await new Promise((resolve) => setTimeout(resolve, 500 - elapsed))
          }
          setIsRefreshing(false)
          toast.success("流水线水位已刷新", { duration: 1500 })
        } else {
          setIsRefreshing(false)
        }
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    const initialTimer = setTimeout(() => {
      void fetchStats()
    }, 0)
    const intervalTimer = setInterval(() => {
      void fetchStats()
    }, 5000)
    return () => {
      clearTimeout(initialTimer)
      clearInterval(intervalTimer)
      abortControllerRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    const handleStatsRefresh = (e: Event) => {
      const customEvent = e as CustomEvent<{ action?: string }>
      if (customEvent.detail?.action === "unreject") {
        // 🌟 乐观更新：收到放行事件时，毫秒级自增已同步数、扣减拦截数
        setStats((prev) => ({
          ...prev,
          synced_count: prev.synced_count + 1,
          rejected_count: Math.max(0, prev.rejected_count - 1),
        }))
      } else if (customEvent.detail?.action === "confirm-reject") {
        setStats((prev) => ({
          ...prev,
          rejected_count: Math.max(0, prev.rejected_count - 1),
        }))
      } else if (customEvent.detail?.action === "empty-trash") {
        setStats((prev) => ({
          ...prev,
          rejected_count: 0,
        }))
      }
      void fetchStats(false)
    }

    window.addEventListener("pipeline-stats-refresh", handleStatsRefresh)
    return () => {
      window.removeEventListener("pipeline-stats-refresh", handleStatsRefresh)
    }
  }, [])

  const handleRunGlobal = async () => {
    if (isProcessing || stats.raw_pending === 0) return
    setRunningTask("global")
    try {
      const parsedLimit = cleanLimit.trim() === "" ? 0 : parseInt(cleanLimit, 10)
      const actualLimit = isNaN(parsedLimit) ? 10 : Math.max(0, parsedLimit)
      const res = await fetch(`${getMainApiBase()}/v1/processor/run-global`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: actualLimit }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.task_id) {
          const targetJobsCount = actualLimit > 0 ? Math.min(actualLimit, stats.raw_pending) : stats.raw_pending
          addTask({
            id: data.task_id,
            platform: "global",
            keyword: actualLimit > 0 ? `全平台清洗 (限${actualLimit}条)` : "全平台清洗 (全量)",
            city: "全国",
            salary: "自动",
            targetJobs: targetJobsCount,
          })
        }
        toast.success("全平台漏斗清洗管道已启动！")
        onTaskStarted()
      } else {
        const err = await res.json().catch(() => ({}))
        toast.error(`全平台清洗启动失败: ${err.detail || err.message || "服务繁忙"}`)
      }
    } catch (e) {
      console.warn("[DataExplorer] 启动清洗异常:", e)
      toast.error("网络异常，无法连接到清洗服务")
    } finally {
      setRunningTask(null)
      void fetchStats(true)
    }
  }

  const handleSyncFeishu = async () => {
    if (isProcessing || stats.ready_to_sync === 0) return
    setRunningTask("sync_feishu")
    try {
      const parsedLimit = cleanLimit.trim() === "" ? 0 : parseInt(cleanLimit, 10)
      const actualLimit = isNaN(parsedLimit) ? 50 : Math.max(0, parsedLimit)
      const targetJobsCount = actualLimit > 0 ? Math.min(actualLimit, stats.ready_to_sync) : stats.ready_to_sync
      const res = await fetch(`${getMainApiBase()}/v1/processor/sync-feishu`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: actualLimit }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.task_id) {
          addTask({
            id: data.task_id,
            platform: "global",
            keyword: actualLimit > 0 ? `存量补推飞书 (限${actualLimit}条)` : "存量补推飞书 (全量)",
            city: "全国",
            salary: "自动",
            targetJobs: targetJobsCount,
          })
        }
        toast.success("已启动存量岗位推送到飞书！")
        onTaskStarted()
      } else {
        const err = await res.json().catch(() => ({}))
        toast.error(`推送启动失败: ${err.detail || err.message || "服务繁忙"}`)
      }
    } catch (e) {
      console.warn("[DataExplorer] 启动推送异常:", e)
      toast.error("网络异常，无法连接到推送服务")
    } finally {
      setRunningTask(null)
      void fetchStats(true)
    }
  }

  const handleRunXhs = async () => {
    if (isProcessing || stats.xhs_pending === 0) return
    setRunningTask("xhs")
    try {
      // 视觉闸门：多模态清洗依赖视觉模型，未配置时弹配置引导而非裸报错（预检失败由后端 400 兜底）
      const visionMissing = await fetchMissingKeys("vision")
      if (visionMissing && visionMissing.length > 0) {
        setXhsGate(visionMissing)
        return
      }
      const res = await fetch(`${getMainApiBase()}/v1/processor/run-xhs`, { method: "POST" })
      if (res.ok) {
        const data = await res.json()
        if (data.task_id) {
          const targetJobsCount = Math.min(20, stats.xhs_pending)
          addTask({
            id: data.task_id,
            platform: "xiaohongshu",
            keyword: "多模态智能清洗",
            city: "全国",
            salary: "自动",
            targetJobs: targetJobsCount,
          })
        }
        toast.success("小红书多模态清洗已启动！")
        onTaskStarted()
      } else {
        const err = await res.json().catch(() => ({}))
        if (err.detail?.code === "vision_not_configured") {
          setXhsGate(err.detail.missing || ["VISION_MODEL"])
          return
        }
        const detailMsg = typeof err.detail === "string"
          ? err.detail
          : err.detail?.message || err.detail?.code
        toast.error(`小红书清洗启动失败: ${detailMsg || err.message || "服务繁忙"}`)
      }
    } catch (e) {
      console.warn("[DataExplorer] 启动小红书清洗异常:", e)
      toast.error("网络异常，无法连接到清洗服务")
    } finally {
      setRunningTask(null)
      void fetchStats(true)
    }
  }

  const handleRunHardFilter = async () => {
    if (isProcessing || stats.raw_pending === 0) return
    setRunningTask("hard_filter")
    try {
      const parsedLimit = cleanLimit.trim() === "" ? 0 : parseInt(cleanLimit, 10)
      const actualLimit = isNaN(parsedLimit) ? 10 : Math.max(0, parsedLimit)
      const res = await fetch(`${getMainApiBase()}/v1/processor/run-hard-filter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: actualLimit }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.task_id) {
          const targetJobsCount = actualLimit > 0 ? Math.min(actualLimit, stats.raw_pending) : stats.raw_pending
          addTask({
            id: data.task_id,
            platform: "global",
            keyword: actualLimit > 0 ? `纯硬规则初筛 (限${actualLimit}条)` : "纯硬规则初筛 (全量)",
            city: "全国",
            salary: "自动",
            targetJobs: targetJobsCount,
          })
        }
        toast.success("Tier 1 硬规则初筛已启动！(0 Token)")
        onTaskStarted()
      } else {
        const err = await res.json().catch(() => ({}))
        toast.error(`硬规则初筛启动失败: ${err.detail || err.message || "服务繁忙"}`)
      }
    } catch (e) {
      console.warn("[DataExplorer] 启动硬规则初筛异常:", e)
      toast.error("网络异常，无法连接到清洗服务")
    } finally {
      setRunningTask(null)
      void fetchStats(true)
    }
  }

  const handleRunAiScout = async () => {
    if (isProcessing || stats.ai_pending === 0) return
    setRunningTask("ai_scout")
    try {
      const parsedLimit = cleanLimit.trim() === "" ? 0 : parseInt(cleanLimit, 10)
      const actualLimit = isNaN(parsedLimit) ? 10 : Math.max(0, parsedLimit)
      const res = await fetch(`${getMainApiBase()}/v1/processor/run-ai-scout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: actualLimit }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.task_id) {
          const targetJobsCount = actualLimit > 0 ? Math.min(actualLimit, stats.ai_pending) : stats.ai_pending
          addTask({
            id: data.task_id,
            platform: "global",
            keyword: actualLimit > 0 ? `AI深度排雷 (限${actualLimit}条)` : "AI深度排雷 (全量)",
            city: "全国",
            salary: "自动",
            targetJobs: targetJobsCount,
          })
        }
        toast.success("Tier 2 AI 深度排雷已启动！")
        onTaskStarted()
      } else {
        const err = await res.json().catch(() => ({}))
        toast.error(`AI排雷启动失败: ${err.detail || err.message || "服务繁忙"}`)
      }
    } catch (e) {
      console.warn("[DataExplorer] 启动AI排雷异常:", e)
      toast.error("网络异常，无法连接到排雷服务")
    } finally {
      setRunningTask(null)
      void fetchStats(true)
    }
  }

  const handleSkipAiSync = async () => {
    if (isProcessing || (stats.raw_pending === 0 && stats.ai_pending === 0)) return
    setRunningTask("skip_ai")
    try {
      const parsedLimit = cleanLimit.trim() === "" ? 0 : parseInt(cleanLimit, 10)
      const actualLimit = isNaN(parsedLimit) ? 50 : Math.max(0, parsedLimit)
      const res = await fetch(`${getMainApiBase()}/v1/processor/skip-ai-sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: actualLimit }),
      })
      if (res.ok) {
        const data = await res.json()
        if (data.task_id) {
          const count = stats.ai_pending > 0 ? stats.ai_pending : stats.raw_pending
          const targetJobsCount = actualLimit > 0 ? Math.min(actualLimit, count) : count
          addTask({
            id: data.task_id,
            platform: "global",
            keyword: actualLimit > 0 ? `免AI直推飞书 (限${actualLimit}条)` : "免AI直推飞书 (全量)",
            city: "全国",
            salary: "自动",
            targetJobs: targetJobsCount,
          })
        }
        toast.success("已启动免 AI 直通飞书！")
        onTaskStarted()
      } else {
        const err = await res.json().catch(() => ({}))
        toast.error(`直通飞书启动失败: ${err.detail || err.message || "服务繁忙"}`)
      }
    } catch (e) {
      console.warn("[DataExplorer] 启动免AI直推异常:", e)
      toast.error("网络异常，无法连接到推送服务")
    } finally {
      setRunningTask(null)
      void fetchStats(true)
    }
  }

  return {
    stats,
    loading,
    isRefreshing,
    runningTask,
    isProcessing,
    xhsGate,
    clearXhsGate: () => setXhsGate(null),
    activeCleaningTask,
    cleanLimit,
    setCleanLimit,
    fetchStats,
    handleRunGlobal,
    handleSyncFeishu,
    handleRunXhs,
    handleRunHardFilter,
    handleRunAiScout,
    handleSkipAiSync,
  }
}
