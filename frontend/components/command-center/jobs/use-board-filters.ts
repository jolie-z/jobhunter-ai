import { useState, useEffect, useMemo } from "react"
import { usePipelineStore, PipelineJob } from "@/store/pipeline-store"
import { TabType } from "../types"
import {
  isJobDelivered,
  isJobEvaluating,
  isJobFailed,
  isJobReadyToDeliver,
  isJobRejected,
  isJobWaitingReview,
} from "../job-predicates"

const VALID_TABS = ["all", "rejected", "review", "ready_to_deliver", "evaluating", "delivered", "failed"]

// 时间字符串统一转毫秒时间戳：兼容 "YYYY-MM-DD HH:mm:ss"（快照/SQLite）与 ISO（前端乐观写入）
function toTimeTs(timeStr?: string | null): number {
  if (!timeStr) return 0
  const normalized = timeStr.includes("T") ? timeStr : timeStr.replace(" ", "T")
  const ts = new Date(normalized).getTime()
  return Number.isNaN(ts) ? 0 : ts
}

// 最新动作永远置顶：待投递按放行时间、已投递按送达时间（均为 last_action_time）倒序
function byLatestActionDesc(a: PipelineJob, b: PipelineJob): number {
  return toTimeTs(b.last_action_time) - toTimeTs(a.last_action_time)
}

export function useBoardFilters() {
  const jobs = usePipelineStore((s) => s.jobs)
  const [filterTab, setFilterTab] = useState<TabType>("all")

  // 支持外部深链定位 tab（首页「自动投递」入队后跳转 /prototype/command-center?tab=ready_to_deliver）
  useEffect(() => {
    const tab = new URLSearchParams(window.location.search).get("tab")
    if (tab && VALID_TABS.includes(tab as TabType)) setFilterTab(tab as TabType)
  }, [])

  // 输入即时回显、过滤 300ms 防抖：岗位池大时避免每次击键全量过滤
  const [searchInput, setSearchInput] = useState("")
  const [searchQuery, setSearchQuery] = useState("")

  useEffect(() => {
    const timer = setTimeout(() => setSearchQuery(searchInput), 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  const jobList: PipelineJob[] = useMemo(() => Object.values(jobs).reverse(), [jobs])

  // 各状态列表（统一走 job-predicates，只保留当次任务纯净数据）
  const rejectedJobs = useMemo(() => jobList.filter(isJobRejected), [jobList])
  const evaluatingJobs = useMemo(() => jobList.filter(isJobEvaluating), [jobList])
  const waitingJobs = useMemo(() => jobList.filter(isJobWaitingReview), [jobList])
  const readyToDeliverJobs = useMemo(() => jobList.filter(isJobReadyToDeliver).sort(byLatestActionDesc), [jobList])
  const deliveredJobs = useMemo(() => jobList.filter(isJobDelivered).sort(byLatestActionDesc), [jobList])
  const failedJobs = useMemo(() => jobList.filter(isJobFailed), [jobList])

  // 过滤后的岗位
  const filteredJobs = useMemo(() => {
    let list = jobList
    if (filterTab === "all") {
      list = jobList
    } else if (filterTab === "rejected") {
      list = rejectedJobs
    } else if (filterTab === "evaluating") {
      list = evaluatingJobs
    } else if (filterTab === "review") {
      list = waitingJobs
    } else if (filterTab === "ready_to_deliver") {
      list = readyToDeliverJobs
    } else if (filterTab === "delivered") {
      list = deliveredJobs
    } else if (filterTab === "failed") {
      list = failedJobs
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      list = list.filter((job) => {
        const matchTitle = (job.job_name || "").toLowerCase().includes(q)
        const matchCompany = (job.company_name || "").toLowerCase().includes(q)
        const matchPlatform = (job.platform || "").toLowerCase().includes(q)
        return matchTitle || matchCompany || matchPlatform
      })
    }
    return list
  }, [
    jobList,
    filterTab,
    searchQuery,
    rejectedJobs,
    evaluatingJobs,
    waitingJobs,
    readyToDeliverJobs,
    deliveredJobs,
    failedJobs,
  ])

  return {
    filterTab,
    setFilterTab,
    searchInput,
    setSearchInput,
    allJobs: jobList,
    rejectedJobs,
    waitingJobs,
    readyToDeliverJobs,
    evaluatingJobs,
    deliveredJobs,
    failedJobs,
    filteredJobs,
  }
}
