"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Checkbox } from "@/components/ui/checkbox"
import type { JobData } from "@/types/job"
import { cn } from "@/lib/utils"
import {
  jobDataToJobCard,
  normalizePlatform,
} from "@/lib/job-data"
import { FilterBar, type MacroProgressData } from "@/components/dashboard/filter-bar"
import { type JobProgressInfo } from "@/components/dashboard/job-live-progress-inline"
import { JobCard } from "@/components/dashboard/job-card"
import { FloatActionBar } from "@/components/dashboard/float-action-bar"
import { useJobFilterStore, PAGE_SIZE_OPTIONS } from "@/store/job-filter-store"
import { MissingMaterialsModal } from "@/components/dashboard/missing-materials-modal"
import { GreetingConfigGateModal } from "@/components/dashboard/greeting-config-gate-modal"
import { BatchApproveGateModal } from "@/components/dashboard/batch-approve-gate-modal"
import { AiRerunConfirmModal } from "@/components/dashboard/ai-rerun-confirm-modal"
import { useBatchActions } from "@/hooks/use-batch-actions"

/* 对外 Props 契约 */
interface JobListViewProps {
  jobs: JobData[]
  onEnterDetail: (job: JobData, currentFilteredJobs: JobData[]) => void
  dynamicStatuses: string[]
  onRefreshJobs?: (silent?: boolean, force?: boolean) => Promise<void> | void
  onOpenImport: () => void
  processingJobs?: Record<string, string>
  jobProgressMap?: Record<string, JobProgressInfo>
  jobLiveLogs?: Record<string, string[]>
  onBatchDelete?: (jobIds: string[]) => Promise<void>
  globalTaskStatus?: "idle" | "running" | "completed" | "interrupted"
  macroProgress?: MacroProgressData | null
}

function getPageItems(totalPages: number, current: number): (number | "...")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1)
  }
  const items: (number | "...")[] = [1]
  const start = Math.max(2, current - 1)
  const end = Math.min(totalPages - 1, current + 1)
  if (start > 2) items.push("...")
  for (let i = start; i <= end; i++) items.push(i)
  if (end < totalPages - 1) items.push("...")
  items.push(totalPages)
  return items
}

export function JobListView({
  jobs,
  onEnterDetail,
  dynamicStatuses,
  onRefreshJobs,
  onOpenImport,
  processingJobs = {},
  jobProgressMap = {},
  jobLiveLogs = {},
  onBatchDelete,
  globalTaskStatus = "idle",
  macroProgress,
}: JobListViewProps) {
  // 🌟 筛选状态（值沿用原中文枚举，筛选逻辑零改动，提升到全局 store）
  const searchQuery = useJobFilterStore((s) => s.searchQuery)
  const setSearchQuery = useJobFilterStore((s) => s.setSearchQuery)
  const sortMode = useJobFilterStore((s) => s.sortMode)
  const setSortMode = useJobFilterStore((s) => s.setSortMode)
  const statusFilter = useJobFilterStore((s) => s.statusFilter)
  const setStatusFilter = useJobFilterStore((s) => s.setStatusFilter)
  const scoreFilter = useJobFilterStore((s) => s.scoreFilter)
  const setScoreFilter = useJobFilterStore((s) => s.setScoreFilter)
  const eduFilter = useJobFilterStore((s) => s.eduFilter)
  const setEduFilter = useJobFilterStore((s) => s.setEduFilter)
  const expFilter = useJobFilterStore((s) => s.expFilter)
  const setExpFilter = useJobFilterStore((s) => s.setExpFilter)
  const scaleFilter = useJobFilterStore((s) => s.scaleFilter)
  const setScaleFilter = useJobFilterStore((s) => s.setScaleFilter)
  const platformFilter = useJobFilterStore((s) => s.platformFilter)
  const setPlatformFilter = useJobFilterStore((s) => s.setPlatformFilter)
  const pageSize = useJobFilterStore((s) => s.pageSize)
  const setPageSize = useJobFilterStore((s) => s.setPageSize)
  const currentPage = useJobFilterStore((s) => s.currentPage)
  const setCurrentPage = useJobFilterStore((s) => s.setCurrentPage)

  const listScrollRef = useRef<HTMLDivElement>(null)
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([])

  // 🌟 B-6：列表数据变化（刷新/删除/任务流转）后修剪选中集里已不存在的幽灵 id，
  // 防止批量任务把失效 id 派发给后端按 failed 计数、浮条计数虚高
  useEffect(() => {
    setSelectedJobIds((prev) => {
      if (prev.length === 0) return prev
      const validIds = new Set(jobs.map((j) => j.id))
      const next = prev.filter((id) => validIds.has(id))
      return next.length === prev.length ? prev : next
    })
  }, [jobs])

  // 🌟 核心抽离：批量派发与自动化流程
  const {
    isProcessing,
    isRefreshing,
    refreshed,
    floatDisabled,
    missingModalOpen,
    setMissingModalOpen,
    missingModalJob,
    materialStatus,
    greetingGateOpen,
    setGreetingGateOpen,
    greetingGateJobs,
    approveModalOpen,
    setApproveModalOpen,
    approveModalReadyJobs,
    approveModalNotReadyJobs,
    confirmBatchApproveStream,
    rerunGateOpen,
    rerunGateKind,
    rerunGateJobs,
    rerunGateTotal,
    confirmRerunDispatch,
    cancelRerunDispatch,
    handleRefresh,
    dispatchBatchTask,
    handleApproveSingleJob,
    handleFloatAction,
  } = useBatchActions({
    jobs,
    selectedJobIds,
    setSelectedJobIds,
    onRefreshJobs,
    onBatchDelete,
    processingJobs,
  })

  const filteredJobs = useMemo(() => {
    return jobs.filter((job) => {
      const matchesSearch =
        (job.companyName || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
        (job.jobTitle || "").toLowerCase().includes(searchQuery.toLowerCase())
      const matchesStatus = statusFilter === "全部" || job.followStatus === statusFilter
      const matchesEdu = eduFilter === "全部" || job.education === eduFilter
      const matchesExp = expFilter === "全部" || job.experience === expFilter
      const matchesScale = scaleFilter === "全部" || job.companyScale === scaleFilter
      const matchesPlatform =
        platformFilter === "全部" ||
        normalizePlatform(job.platform) === normalizePlatform(platformFilter)

      let matchesScore = true
      const grade = job.grade ?? ""
      if (scoreFilter === "A") matchesScore = grade === "A"
      else if (scoreFilter === "B") matchesScore = grade === "B"
      else if (scoreFilter === "C") matchesScore = grade === "C"
      else if (scoreFilter === "D-F") matchesScore = grade === "D" || grade === "F"
      else if (scoreFilter === "未评估") matchesScore = !grade

      return (
        matchesSearch &&
        matchesStatus &&
        matchesScore &&
        matchesEdu &&
        matchesExp &&
        matchesScale &&
        matchesPlatform
      )
    })
  }, [
    jobs,
    searchQuery,
    statusFilter,
    eduFilter,
    expFilter,
    scaleFilter,
    platformFilter,
    scoreFilter,
  ])

  // 🌟 排序逻辑：支持按时间（默认后端抓取时间）或按评级（有评级的优先）
  const sortedJobs = useMemo(() => {
    const list = [...filteredJobs]
    if (sortMode === "按评级") {
      const getGradeScore = (grade?: string | null) => {
        if (!grade) return 0
        const g = grade.toUpperCase()
        if (g === "A") return 5
        if (g === "B") return 4
        if (g === "C") return 3
        if (g === "D") return 2
        if (g === "F") return 1
        return 0
      }
      list.sort((a, b) => {
        const scoreA = getGradeScore(a.grade)
        const scoreB = getGradeScore(b.grade)
        return scoreB - scoreA // 降序排（A在最前，未评估在最后）
      })
    }
    return list
  }, [filteredJobs, sortMode])

  /* ------------------------------ 分页逻辑 ------------------------------ */

  const totalJobs = sortedJobs.length
  const totalPages = Math.max(1, Math.ceil(totalJobs / pageSize))
  const safePage = Math.min(currentPage, totalPages)
  useEffect(() => {
    if (safePage !== currentPage) setCurrentPage(safePage)
  }, [safePage, currentPage, setCurrentPage])

  const pagedJobs = useMemo(
    () => sortedJobs.slice((safePage - 1) * pageSize, safePage * pageSize),
    [sortedJobs, safePage, pageSize]
  )

  const isFirstScroll = useRef(true)
  useEffect(() => {
    if (isFirstScroll.current) {
      isFirstScroll.current = false
      return
    }
    listScrollRef.current?.scrollTo({ top: 0 })
  }, [safePage, pageSize])

  /* ------------------------------ 状态计数卡 ------------------------------ */

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const job of jobs) {
      const s = (job.followStatus || "").trim()
      if (s && s !== "-" && s !== "未标注") counts[s] = (counts[s] ?? 0) + 1
    }
    return counts
  }, [jobs])

  const orderedStatuses = useMemo(() => {
    const order = [
      "新线索", "简历人工复核", "已完成初步评估", "已完成深度评估", "疑似重复",
      "待投递", "已投递", "已拒绝", "面试中", "Offer", "不合适", "已下架",
    ]
    const known = order.filter((s) => statusCounts[s])
    const extra = Object.keys(statusCounts).filter((s) => !order.includes(s))
    return [...known, ...extra]
  }, [statusCounts])

  // 🌟 本页岗位 ID 清单与全选感知
  const pagedJobIds = useMemo(() => pagedJobs.map((job) => job.id), [pagedJobs])
  const isAllPagedSelected =
    pagedJobIds.length > 0 && pagedJobIds.every((id) => selectedJobIds.includes(id))
  const isSomePagedSelected =
    pagedJobIds.some((id) => selectedJobIds.includes(id)) && !isAllPagedSelected

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedJobIds((prev) => Array.from(new Set([...prev, ...pagedJobIds])))
    } else {
      const pagedSet = new Set(pagedJobIds)
      setSelectedJobIds((prev) => prev.filter((id) => !pagedSet.has(id)))
    }
  }

  const handleSelectJob = (jobId: string, checked: boolean) => {
    if (checked) {
      setSelectedJobIds((prev) => [...prev, jobId])
    } else {
      setSelectedJobIds((prev) => prev.filter((id) => id !== jobId))
    }
  }

  return (
    <div className="h-full flex flex-col bg-slate-50">
      {/* 状态计数卡 */}
      <div className="border-b border-slate-100 bg-white px-6 py-2.5 flex items-center gap-2 overflow-x-auto custom-scrollbar shrink-0">
        <button
          onClick={() => setStatusFilter("全部")}
          className={cn(
            "shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition-colors",
            statusFilter === "全部"
              ? "bg-slate-800 border-slate-800 text-white shadow-sm"
              : "bg-white border-slate-200 text-slate-600 hover:border-slate-400"
          )}
        >
          全部
          <span className={cn("font-bold", statusFilter === "全部" ? "text-white" : "text-slate-800")}>
            {jobs.length}
          </span>
        </button>
        {orderedStatuses.map((status) => {
          const active = statusFilter === status
          return (
            <button
              key={status}
              onClick={() => setStatusFilter(active ? "全部" : status)}
              className={cn(
                "shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition-colors",
                active
                  ? "bg-blue-600 border-blue-600 text-white shadow-sm"
                  : "bg-white border-slate-200 text-slate-600 hover:border-blue-300 hover:text-blue-600"
              )}
            >
              {status}
              <span className={cn("font-bold", active ? "text-white" : "text-blue-600")}>
                {statusCounts[status]}
              </span>
            </button>
          )
        })}
      </div>

      {/* 筛选条 */}
      <FilterBar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        scoreFilter={scoreFilter}
        onScoreFilterChange={setScoreFilter}
        eduFilter={eduFilter}
        onEduFilterChange={setEduFilter}
        expFilter={expFilter}
        onExpFilterChange={setExpFilter}
        scaleFilter={scaleFilter}
        onScaleFilterChange={setScaleFilter}
        platformFilter={platformFilter}
        onPlatformFilterChange={setPlatformFilter}
        dynamicStatuses={dynamicStatuses}
        filteredCount={sortedJobs.length}
        globalTaskStatus={globalTaskStatus}
        macroProgress={macroProgress}
        isRefreshing={isRefreshing}
        refreshed={refreshed}
        onRefresh={handleRefresh}
        onOpenImport={onOpenImport}
        sortMode={sortMode}
        onSortModeChange={setSortMode}
      />

      {/* 岗位列表 */}
      <div ref={listScrollRef} className="flex-1 overflow-y-auto">
        <div className="max-w-screen-xl mx-auto px-6 py-6">
          {/* 全选本页（左侧） */}
          {pagedJobs.length > 0 && (
            <div
              className="inline-flex items-center gap-2 text-xs text-slate-600 cursor-pointer select-none mb-4 hover:text-slate-900 transition-colors"
              onClick={(e) => {
                if ((e.target as HTMLElement).tagName !== "BUTTON" && (e.target as HTMLElement).getAttribute("role") !== "checkbox") {
                  handleSelectAll(!isAllPagedSelected)
                }
              }}
            >
              <Checkbox
                checked={
                  isAllPagedSelected
                    ? true
                    : isSomePagedSelected
                    ? "indeterminate"
                    : false
                }
                onCheckedChange={(checked) => handleSelectAll(checked === true)}
              />
              <span>全选本页（共 {pagedJobs.length} 个）</span>
              {selectedJobIds.length > 0 && (
                <span className="text-slate-400">
                  · 已累计勾选 <span className="font-semibold text-blue-600">{selectedJobIds.length}</span> 个
                </span>
              )}
            </div>
          )}

          {sortedJobs.length > 0 ? (
            <div className="flex flex-col gap-2">
              {pagedJobs.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  card={jobDataToJobCard(job)}
                  isSelected={selectedJobIds.includes(job.id)}
                  onSelect={(checked) => handleSelectJob(job.id, checked)}
                  onEnterDetail={(selectedJob) => onEnterDetail(selectedJob, sortedJobs)}
                  processingJob={processingJobs[job.id]}
                  progressInfo={jobProgressMap[job.id]}
                  liveLogs={jobLiveLogs[job.id]}
                  onApprove={() => handleApproveSingleJob(job)}
                  approveBusy={isProcessing}
                  onRetry={() => dispatchBatchTask("evaluate", "重试评估", {}, [job.id])}
                />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-28 text-center">
              <div className="size-14 rounded-2xl bg-slate-100 flex items-center justify-center mb-4">
                <svg className="size-7 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M21 21l-4.35-4.35M17 11A6 6 0 105 11a6 6 0 0012 0z"
                  />
                </svg>
              </div>
              <p className="text-sm font-semibold text-slate-700">没有找到匹配的职位</p>
              <p className="text-xs text-slate-400 mt-1">尝试调整搜索词或筛选条件</p>
            </div>
          )}

          {/* 底部留白，避免浮动栏遮挡 */}
          {selectedJobIds.length > 0 && <div className="h-24" />}
        </div>
      </div>

      {/* 分页条 */}
      {totalJobs > 0 && (
        <div className="border-t border-slate-100 bg-white px-6 py-2.5 flex items-center gap-4 text-xs shrink-0">
          <div className="text-slate-400 shrink-0">
            共 <span className="font-semibold text-slate-700">{totalJobs}</span> 个职位 · 第{" "}
            <span className="font-semibold text-slate-700">{safePage}</span> / {totalPages} 页
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage(safePage - 1)}
              disabled={safePage <= 1}
              className="inline-flex items-center gap-0.5 h-7 px-2 rounded-md border border-slate-200 bg-white text-slate-600 transition-colors hover:border-blue-300 hover:text-blue-600 disabled:opacity-40 disabled:pointer-events-none"
            >
              <ChevronLeft className="size-3.5" />
              上一页
            </button>
            {getPageItems(totalPages, safePage).map((item, idx) =>
              item === "..." ? (
                <span key={`ellipsis-${idx}`} className="px-1 text-slate-300">
                  …
                </span>
              ) : (
                <button
                  key={item}
                  onClick={() => setCurrentPage(item)}
                  className={cn(
                    "min-w-7 h-7 px-1 rounded-md border text-xs transition-colors",
                    item === safePage
                      ? "bg-blue-600 border-blue-600 text-white font-semibold"
                      : "bg-white border-slate-200 text-slate-600 hover:border-blue-300 hover:text-blue-600"
                  )}
                >
                  {item}
                </button>
              )
            )}
            <button
              onClick={() => setCurrentPage(safePage + 1)}
              disabled={safePage >= totalPages}
              className="inline-flex items-center gap-0.5 h-7 px-2 rounded-md border border-slate-200 bg-white text-slate-600 transition-colors hover:border-blue-300 hover:text-blue-600 disabled:opacity-40 disabled:pointer-events-none"
            >
              下一页
              <ChevronRight className="size-3.5" />
            </button>
          </div>
          <div className="ml-auto flex items-center gap-2 text-slate-400 shrink-0">
            <span>每页显示</span>
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="h-7 px-2 text-xs rounded-md border border-slate-200 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 cursor-pointer"
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n} 个
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* 浮动批量操作栏 */}
      <FloatActionBar
        selectedCount={selectedJobIds.length}
        disabled={floatDisabled}
        onAction={handleFloatAction}
        onClear={() => setSelectedJobIds([])}
      />

      {/* 缺失投递物料弹窗 */}
      <MissingMaterialsModal
        open={missingModalOpen}
        onOpenChange={setMissingModalOpen}
        job={missingModalJob}
        materialStatus={materialStatus}
        onEnterCustomDetail={(j) => onEnterDetail(j, sortedJobs)}
        onAutoHealSuccess={handleRefresh}
      />

      {/* 海投打招呼语门禁弹窗 */}
      <GreetingConfigGateModal
        open={greetingGateOpen}
        onOpenChange={setGreetingGateOpen}
        selectedJobs={greetingGateJobs}
      />

      {/* 批量批准投递物料预检弹窗 */}
      <BatchApproveGateModal
        open={approveModalOpen}
        onOpenChange={setApproveModalOpen}
        readyJobs={approveModalReadyJobs}
        notReadyJobs={approveModalNotReadyJobs}
        onConfirmApprove={confirmBatchApproveStream}
      />

      {/* 重复发起 AI 任务（初评/深评/改写）二次确认弹窗 */}
      <AiRerunConfirmModal
        open={rerunGateOpen}
        kind={rerunGateKind}
        existingJobs={rerunGateJobs}
        totalCount={rerunGateTotal}
        onConfirm={confirmRerunDispatch}
        onCancel={cancelRerunDispatch}
      />
    </div>
  )
}
