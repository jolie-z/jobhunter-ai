"use client"

import { API_BASE } from "@/lib/api"
import { useEffect, useState, useMemo, useCallback, useTransition, useRef } from "react"
import { TopNavBar } from "@/components/dashboard/top-nav-bar"
import { JobListView } from "@/components/dashboard/job-list-view"
import { JobDetailWorkspace } from "@/components/dashboard/job-detail-workspace"
import { InterviewCamp } from "@/components/dashboard/interview-camp"
import { Spinner } from "@/components/ui/spinner"
import { QuickImportModal } from "@/components/dashboard/quick-import-modal"
import { TerminalContainer } from "@/components/dashboard/terminal-container"
import { TrashBinWorkspace } from "@/components/dashboard/trash-bin-workspace"
import { useTrashBinStore } from "@/store/trash-bin-store"
import type { JobData } from "@/types/job"
import { mapApiItemToJob, type JobsApiItem } from "@/lib/job-mapper"
import { useJobDetail, getCachedJobDetail } from "@/hooks/use-job-detail"
import { useGlobalTaskStream } from "@/hooks/use-global-task-stream"
import { toast } from "@/hooks/use-toast"
import { clearDeepLinkParams, setDeepLinkParam } from "@/lib/deep-link"

// =========================================================================
// 🛑 AI 助手 CASCADE 请严格注意 (DO NOT MODIFY OR REMOVE) 🛑
// 本项目为 Project Polaris，高度依赖飞书 API 的实时数据流。
// 严禁在此文件中使用任何形式的 `revalidate` (包括 export const revalidate = ... 或 import)。
// 必须且只能使用 force-dynamic！如果你敢加回 revalidate，系统会立即 500 崩溃！
// =========================================================================
export const dynamic = 'force-dynamic';
export type GlobalView = "immersive-list" | "immersive-detail" | "interview-camp"

export default function Dashboard() {
  const [currentView, setCurrentView] = useState<GlobalView>("immersive-list")
  const [jobs, setJobs] = useState<JobData[]>([])
  const [currentNavJobs, setCurrentNavJobs] = useState<JobData[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isPending, startTransition] = useTransition()
  const [selectedJob, setSelectedJob] = useState<JobData | null>(null)

  // 🌟 拦截回收站全局状态
  const isTrashBinOpen = useTrashBinStore((state) => state.isOpen)
  const closeTrashBin = useTrashBinStore((state) => state.closeTrashBin)
  const toggleTrashBin = useTrashBinStore((state) => state.toggleTrashBin)
  const [trashBinCount, setTrashBinCount] = useState(0)

  // 🌟 极速录入状态
  const [isImportModalOpen, setIsImportModalOpen] = useState(false)

  // 🌟 URL 直达参数只消费一次：详情成功打开（或 fallback 请求已发出）后不再重复处理。
  // 防止后续任何 setJobs（SSE 任务流/统计刷新/详情合并等）重新触发 effect，把用户从列表或面试营地拽回详情页。
  const deepLinkRef = useRef({ consumed: false, fetchStarted: false })
  const resetDeepLinkRef = () => {
    deepLinkRef.current = { consumed: false, fetchStarted: false }
  }

  // 🌟 统一退出详情视图逻辑：清理 URL 参数并重置 DeepLinkRef
  const exitDetailView = () => {
    clearDeepLinkParams()
    resetDeepLinkRef()
  }

  // 🌟 声明式保活同步：当处于定制面板且选中岗位变化时，统一将 job_id 写入地址栏，避免分散调用的坏味道
  useEffect(() => {
    if (currentView === "immersive-detail" && selectedJob?.id) {
      setDeepLinkParam(selectedJob.id)
    }
  }, [currentView, selectedJob?.id])

  // 🌟 打开的岗位按需拉取大文本详情（列表已瘦身），并合并进 jobs/selectedJob
  const selectedJobDetail = useJobDetail(selectedJob?.id, currentView !== "immersive-list")

  // 🌟 增加 silent 参数，默认为 false（即默认显示加载中）
  // 🌟 force=true 时走 ?force=1 硬刷新：绕过后端缓存直连飞书，保证读到最新数据
  const fetchJobs = useCallback(async (silent = false, force = false, retryCount = 0) => {
    try {
      if (!silent) setIsLoading(true)
      const response = await fetch(`${API_BASE}/api/jobs${force ? "?force=1" : ""}`, {
        cache: 'no-store',
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'Pragma': 'no-cache',
        },
      })
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`)
      }
      const data = await response.json()
      const items: JobsApiItem[] = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
      const normalizedJobs: JobData[] = items.map((item: JobsApiItem, index: number): JobData => {
        const cachedDetail = getCachedJobDetail(String(item.record_id ?? ""))
        const mergedItem: JobsApiItem = cachedDetail ? { ...cachedDetail, ...item } : item
        return mapApiItemToJob(mergedItem, index)
      })

      setJobs(normalizedJobs)
      setSelectedJob((prev) =>
        prev ? normalizedJobs.find((job: JobData) => job.id === prev.id) ?? prev : null
      )
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error)
      console.warn("Failed to fetch jobs (backend may be starting up):", errMsg)

      // 如果是初次冷启动或瞬态连接拒绝，2.5秒后自动静默重试一次
      if (retryCount === 0 && (errMsg.includes("fetch") || errMsg.includes("NetworkError") || errMsg.includes("Failed"))) {
        setTimeout(() => {
          fetchJobs(silent, force, 1)
        }, 2500)
        return
      }

      toast({
        title: "⚠️ 数据获取受阻",
        description: `未能连接到后端服务 (${API_BASE})，请确认后端已正常启动。`,
        variant: "destructive",
      })
    } finally {
      setIsLoading(false)
    }
  }, [])

  // 🌟 核心抽离：全站批量任务流与 SSE 引擎
  const {
    processingJobs,
    jobProgressMap,
    macroProgress,
    jobLiveLogs,
    globalTaskStatus,
    handleSseMessage,
  } = useGlobalTaskStream({
    fetchJobs,
    setSelectedJob,
    setJobs,
    setTrashBinCount,
  })

  // 🌟 详情到位后合并进当前选中岗位（含岗位详情/AI改写JSON等大文本）
  useEffect(() => {
    if (!selectedJob || !selectedJobDetail || selectedJobDetail.id !== selectedJob.id) return
    setSelectedJob((prev) => (prev && prev.id === selectedJobDetail.id ? { ...prev, ...selectedJobDetail } : prev))
    setJobs((prev) => prev.map((j) => (j.id === selectedJobDetail.id ? { ...j, ...selectedJobDetail } : j)))
  }, [selectedJobDetail, selectedJob?.id])

  const handleBatchDelete = async (jobIds: string[]) => {
    try {
      const response = await fetch(`${API_BASE}/api/jobs/batch-delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: jobIds }),
      })

      const data = await response.json()
      if (response.ok && data.status === "success") {
        const deletedIds: string[] = data.data?.deleted_ids ?? jobIds
        setJobs((prevJobs) => prevJobs.filter((job) => !deletedIds.includes(job.id)))
        alert(`✅ ${data.message}`)
      } else {
        alert("❌ 删除失败：" + (data.detail || data.message || "未知错误"))
      }
    } catch (error) {
      console.error("批量删除请求失败:", error)
      alert("❌ 网络错误，批量删除失败")
    }
  }

  // 2.5 拦截站数量获取
  const fetchTrashBinCount = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/processor/trash-bin-count`)
      if (res.ok) {
        const json = await res.json()
        if (json.status === "success") {
          setTrashBinCount(json.count)
        }
      }
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    fetchTrashBinCount()
  }, [fetchTrashBinCount])

  useEffect(() => {
    if (!isTrashBinOpen) {
      fetchTrashBinCount()
    }
  }, [isTrashBinOpen, fetchTrashBinCount])

  useEffect(() => {
    const handleStatsRefresh = (e: Event) => {
      const customEvent = e as CustomEvent<{ action?: string }>
      if (customEvent.detail?.action === "unreject" || customEvent.detail?.action === "confirm-reject") {
        setTrashBinCount((prev) => Math.max(0, prev - 1))
      } else if (customEvent.detail?.action === "empty-trash") {
        setTrashBinCount(0)
      }
      fetchTrashBinCount()
      fetchJobs(false)
    }

    window.addEventListener("pipeline-stats-refresh", handleStatsRefresh)
    return () => {
      window.removeEventListener("pipeline-stats-refresh", handleStatsRefresh)
    }
  }, [fetchTrashBinCount, fetchJobs])

  useEffect(() => {
    fetchJobs()
  }, [fetchJobs])

  // 🌟 支持通过 URL Query (?job_id=xxx 或 ?record_id=xxx) 直接唤起对应岗位的定制面板
  useEffect(() => {
    if (typeof window === "undefined") return
    const link = deepLinkRef.current
    if (link.consumed) return
    const params = new URLSearchParams(window.location.search)
    const targetId = (params.get("job_id") || params.get("record_id") || "").trim()
    if (!targetId) return

    if (jobs.length > 0) {
      const cleanId = targetId.startsWith("raw_") ? targetId : targetId.split("-").pop() || targetId
      const matched = jobs.find(
        (j) => j.id === targetId || j.id.endsWith(cleanId) || (cleanId && j.id.includes(cleanId)) || j.jobTitle.includes(targetId)
      )
      if (matched) {
        link.consumed = true
        setSelectedJob(matched)
        setCurrentView("immersive-detail")
        setIsLoading(false)
        return
      }
    }

    // fallback 直连详情接口；只发起一次，避免 jobs 每次变化都重复请求
    if (link.fetchStarted) return
    link.fetchStarted = true
    fetch(`${API_BASE}/api/jobs/${encodeURIComponent(targetId)}/detail`)
      .then((r) => r.json())
      .then((res) => {
        if (res?.data) {
          link.consumed = true
          const mapped = mapApiItemToJob(res.data, 0)
          setSelectedJob(mapped)
          setCurrentView("immersive-detail")
          setIsLoading(false)
        }
      })
      .catch((err) => console.warn("无法直接加载指定 job_id 详情:", err))
  }, [jobs])

  // 状态统计与动态可用状态
  const statusCounts = useMemo(() => {
    return jobs.reduce<Record<string, number>>((acc, job) => {
      const status = job.followStatus?.trim()
      if (status && status !== "-" && status !== "未标注") {
        acc[status] = (acc[status] ?? 0) + 1
      }
      return acc
    }, {})
  }, [jobs])

  const PRESET_STATUSES = [
    "新线索",
    "不合适",
    "已完成初步评估",
    "已完成深度评估",
    "简历人工复核",
    "疑似重复",
    "待投递",
    "已投递",
    "面试中",
    "Offer",
    "已下架",
  ]

  const dynamicStatuses = useMemo(() => {
    const fetchedStatuses = Object.keys(statusCounts)
    return Array.from(new Set([...PRESET_STATUSES, ...fetchedStatuses]))
  }, [statusCounts])

  const handleEnterDetail = (job: JobData, filteredList?: JobData[]) => {
    setSelectedJob(job)
    setCurrentView("immersive-detail")
    if (filteredList) {
      setCurrentNavJobs(filteredList)
    }
  }

  const handleUpdateSelectedJob = (nextJob: JobData | null, action?: "remove") => {
    if (action === "remove" && selectedJob) {
      const filteredJobs = jobs.filter((j) => j.id !== selectedJob.id)
      setJobs(filteredJobs)
      const filteredNavJobs = currentNavJobs.filter((j) => j.id !== selectedJob.id)
      setCurrentNavJobs(filteredNavJobs)

      const currentIndex = currentNavJobs.findIndex((job) => job.id === selectedJob.id)
      if (currentIndex < filteredNavJobs.length) {
        setSelectedJob(filteredNavJobs[currentIndex])
      } else if (filteredNavJobs.length > 0) {
        setSelectedJob(filteredNavJobs[filteredNavJobs.length - 1])
      } else {
        handleBackToList()
      }
    } else if (nextJob) {
      setSelectedJob(nextJob)
      setJobs((prev) => prev.map((job) => (job.id === nextJob.id ? nextJob : job)))
      setCurrentNavJobs((prev) => prev.map((job) => (job.id === nextJob.id ? nextJob : job)))
    }
  }

  const handleBackToList = () => {
    exitDetailView()
    startTransition(() => {
      setCurrentView("immersive-list")
      setSelectedJob(null)
    })
  }

  const handleMainTabChange = (tab: "immersive" | "interview") => {
    exitDetailView()
    if (tab === "interview") {
      setCurrentView("interview-camp")
    } else {
      setCurrentView("immersive-list")
    }
    setSelectedJob(null)
  }

  const navigationList = currentNavJobs.length > 0 ? currentNavJobs : jobs
  const currentJobIndex = selectedJob ? navigationList.findIndex((job) => job.id === selectedJob.id) : -1
  const hasPrevious = currentJobIndex > 0
  const hasNext = currentJobIndex >= 0 && currentJobIndex < navigationList.length - 1

  const handlePrevious = () => {
    if (hasPrevious && currentJobIndex > 0) {
      setSelectedJob(navigationList[currentJobIndex - 1])
    }
  }

  const handleNext = () => {
    if (hasNext && currentJobIndex < navigationList.length - 1) {
      setSelectedJob(navigationList[currentJobIndex + 1])
    }
  }

  return (
    <div className="flex flex-col h-screen bg-muted/30">
      {currentView !== "immersive-detail" && (
        <TopNavBar
          currentView={currentView}
          onMainTabChange={handleMainTabChange}
          statusCounts={statusCounts}
          isTrashBinOpen={isTrashBinOpen}
          trashBinCount={trashBinCount}
          onToggleTrashBin={toggleTrashBin}
          globalTaskStatus={globalTaskStatus}
        />
      )}
      <main className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-hidden min-w-0 relative">
          {isLoading && (
            <div className="h-full flex items-center justify-center">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner className="size-5" />
                正在加载岗位数据...
              </div>
            </div>
          )}
          {!isLoading && currentView === "immersive-list" && (
            <JobListView
              jobs={jobs}
              onEnterDetail={handleEnterDetail}
              dynamicStatuses={dynamicStatuses}
              onRefreshJobs={fetchJobs}
              onOpenImport={() => setIsImportModalOpen(true)}
              processingJobs={processingJobs}
              jobProgressMap={jobProgressMap}
              macroProgress={macroProgress}
              jobLiveLogs={jobLiveLogs}
              onBatchDelete={handleBatchDelete}
              globalTaskStatus={globalTaskStatus}
            />
          )}
          {!isLoading && currentView === "immersive-detail" && selectedJob && (
            <JobDetailWorkspace
              job={selectedJob}
              onUpdateJob={handleUpdateSelectedJob}
              onBack={handleBackToList}
              hasPrevious={hasPrevious}
              hasNext={hasNext}
              onPrevious={handlePrevious}
              onNext={handleNext}
              dynamicStatuses={dynamicStatuses}
              onRefreshJobs={fetchJobs}
              processingJobs={processingJobs}
              jobLiveLogs={jobLiveLogs}
              globalTaskStatus={globalTaskStatus}
            />
          )}
          {!isLoading && currentView === "interview-camp" && <InterviewCamp jobs={jobs} />}

          {isImportModalOpen && (
            <QuickImportModal
              onClose={() => setIsImportModalOpen(false)}
              onSuccess={() => fetchJobs(true, true)}
            />
          )}

          {isTrashBinOpen && (
            <TrashBinWorkspace onClose={closeTrashBin} />
          )}
        </div>

        {currentView === "immersive-list" && (
          <TerminalContainer onComplete={fetchJobs} onSseMessage={handleSseMessage} />
        )}
      </main>
    </div>
  )
}
