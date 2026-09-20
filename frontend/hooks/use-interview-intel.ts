import { useState, useEffect } from "react"
import type { JobData } from "@/types/job"
import { API_BASE } from "@/lib/api"
import { toast } from "@/hooks/use-toast"

const MAX_INTEL_CACHE = 10

function pruneIntelMap(map: Record<string, any>, maxItems = MAX_INTEL_CACHE): Record<string, any> {
  const keys = Object.keys(map)
  if (keys.length <= maxItems) return map
  // 按 _cached_at 升序排列，最早访问/获取的岗位排在前面被淘汰
  const sorted = keys.map(k => ({ key: k, ts: map[k]?._cached_at || 0 })).sort((a, b) => a.ts - b.ts)
  const keysToRemove = sorted.slice(0, keys.length - maxItems).map(item => item.key)
  const pruned = { ...map }
  for (const k of keysToRemove) {
    delete pruned[k]
  }
  return pruned
}

export function useInterviewIntel(activeJobId: string, activeJob: JobData | undefined) {
  // 🌟 将全局加载状态精细化为模块化加载状态
  const [loadingStates, setLoadingStates] = useState({
    all: false,
    company: false,
    summary: false,
    qa: false
  })

  // 🌟 核心修改 1：初始化时优先从本地磁盘 (localStorage) 读取已有的岗位资料缓存
  const [intelDataMap, setIntelDataMap] = useState<Record<string, any>>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("interview_intel_persistent_cache")
      try {
        return saved ? pruneIntelMap(JSON.parse(saved), MAX_INTEL_CACHE) : {}
      } catch (e) {
        console.error("读取本地缓存失败", e)
        return {}
      }
    }
    return {}
  })

  // 🌟 核心修改 2：加入 LRU 淘汰（最多保留 10 份全网情报全文）与 QuotaExceededError 熔断自愈机制
  useEffect(() => {
    if (typeof window === "undefined") return
    try {
      const pruned = pruneIntelMap(intelDataMap, MAX_INTEL_CACHE)
      localStorage.setItem("interview_intel_persistent_cache", JSON.stringify(pruned))
    } catch (e) {
      console.warn("⚠️ [useInterviewIntel] 本地缓存超限，触发熔断驱逐保护:", e)
      try {
        // 发生配额溢出时，紧急保留当前激活岗位的单份数据，其余清空
        const emergency = activeJobId && intelDataMap[activeJobId] ? { [activeJobId]: intelDataMap[activeJobId] } : {}
        localStorage.setItem("interview_intel_persistent_cache", JSON.stringify(emergency))
      } catch {
        try { localStorage.removeItem("interview_intel_persistent_cache") } catch {}
      }
    }
  }, [intelDataMap, activeJobId])
  
  // 🌟 动态获取当前激活岗位的资料
  const intelData = intelDataMap[activeJobId] || null

  // 🌟 靶向控制获取函数
  const fetchFullIntel = async (target: 'all' | 'company' | 'summary' | 'qa' = 'all') => {
    if (!activeJob) return
    setLoadingStates(prev => ({ ...prev, [target]: true }))

    try {
      const res = await fetch(`${API_BASE}/api/v1/init_interviewer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: activeJob.id,
          company: activeJob.companyName,
          job_group: activeJob.jobTitle || "未知岗位", 
          business_track: activeJob.industry && activeJob.industry !== "-" ? activeJob.industry : null,
          jd_text: activeJob.jdText || activeJob.jobDescription || "",
          // 确保拿到的永远是最新的缓存
          cached_intel: intelDataMap[activeJob.id]?.company_intel || (activeJob as any)?.companyIntel,
          cached_qa: intelDataMap[activeJob.id]?.predicted_qa || (activeJob as any)?.predictedQa,
          cached_rq: intelDataMap[activeJob.id]?.reverse_questions || (activeJob as any)?.反问环节建议 || "",
          force_refresh: target === 'all', 
          refresh_target: target,
          resume_text: (activeJob as any)?.manualRefinedResume || (activeJob as any)?.latestResumeText || "",
          evaluation_report: [
            (activeJob as any)?.dreamPicture ? `【理想画像】\n${(activeJob as any).dreamPicture}` : '',
            (activeJob as any)?.strongFitAssessment ? `【高杠杆匹配点】\n${(activeJob as any).strongFitAssessment}` : '',
            (activeJob as any)?.riskRedFlags ? `【致命硬伤】\n${(activeJob as any).riskRedFlags}` : '',
            (activeJob as any)?.deepActionPlan ? `【破局计划】\n${(activeJob as any).deepActionPlan}` : ''
          ].filter(Boolean).join('\n\n')
        })
      })
      const data = await res.json().catch(() => null)
      // 🌟 Q-M8-3：成功形态=含 system_prompt 的七字段对象；失败必须显式反馈，杜绝静默无变化
      if (res.ok && data && typeof data === "object" && "system_prompt" in data) {
        // 使用 prev 确保合并数据时不丢失其他模块已加载的数据，并打上访问时间戳，自动按 LRU 限制上限
        setIntelDataMap(prev => {
          const updated = {
            ...prev,
            [activeJob.id]: {
               ...(prev[activeJob.id] || {}),
               ...data,
               _cached_at: Date.now()
            }
          }
          return pruneIntelMap(updated, MAX_INTEL_CACHE)
        })
      } else {
        throw new Error(data?.detail || `情报获取失败 (HTTP ${res.status})`)
      }
    } catch (e: any) {
      console.error("拉取面试资料失败:", e)
      toast({
        title: "❌ 面试资料获取失败",
        description: e?.message || "请检查网络或后端状态后重试。",
        variant: "destructive",
      })
    } finally {
      setLoadingStates(prev => ({ ...prev, [target]: false }))
    }
  }

  return {
    intelData,
    loadingStates,
    fetchFullIntel
  }
}
