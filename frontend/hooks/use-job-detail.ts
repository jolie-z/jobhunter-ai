import { useEffect, useState } from "react"
import type { JobData } from "@/types/job"
import { mapApiItemToJob, type JobsApiItem } from "@/lib/job-mapper"
import { API_BASE } from "@/lib/api"

// 模块级详情缓存（record_id -> 后端原始详情对象）：
// 列表接口已瘦身不含大文本字段，已打开过的岗位在此留底，列表刷新后可立即补回
const jobDetailCache = new Map<string, JobsApiItem>()

export function getCachedJobDetail(recordId: string): JobsApiItem | undefined {
  return jobDetailCache.get(recordId)
}

export function findRecordIdInJobId(jobId: string): string {
  // JobData.id 形如 "boss直聘-recXXXX"，取最后一段即纯 record_id
  return jobId.split("-").slice(-1)[0] ?? ""
}

/**
 * 打开岗位时按需拉取大文本详情（岗位详情/AI改写JSON/面试记录等）。
 * 返回补齐详情后的完整 JobData；同一岗位只请求一次，之后走缓存。
 */
export function useJobDetail(jobId: string | undefined, enabled: boolean): JobData | null {
  const [detail, setDetail] = useState<JobData | null>(null)

  useEffect(() => {
    setDetail(null) // 切换岗位先清空，避免上一个岗位的详情串台
    if (!jobId || !enabled) return

    const recordId = findRecordIdInJobId(jobId)
    if (!recordId || recordId.startsWith("temp-")) return

    // 缓存仅作秒开预览，不提前 return：AI改写JSON/评估报告等大字段是评估后才写入的动态数据，
    // 若评估前打开过（缓存留底空详情）且永不刷新，改写内容将永远无法在面板渲染
    const cached = jobDetailCache.get(recordId)
    if (cached) {
      setDetail(mapApiItemToJob(cached, 0))
    }

    let cancelled = false
    fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/detail`, { cache: "no-store" })
      .then(res => (res.ok ? res.json() : null))
      .then(payload => {
        const item: JobsApiItem | undefined = payload?.data
        if (cancelled || !item?.record_id) return
        jobDetailCache.set(String(item.record_id), item)
        setDetail(mapApiItemToJob(item, 0))
      })
      .catch(err => console.error("Failed to fetch job detail:", err))
    return () => {
      cancelled = true
    }
  }, [jobId, enabled])

  return detail
}
