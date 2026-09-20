import { useState, useEffect } from "react"
import type { JobData } from "@/types/job"
import { API_BASE } from "@/lib/api"
import { toast } from "@/hooks/use-toast"

const MAX_SCHEDULE_CACHE = 25

function pruneScheduleMap(map: Record<string, { time: string, location: string }>, maxItems = MAX_SCHEDULE_CACHE) {
  const keys = Object.keys(map)
  if (keys.length <= maxItems) return map
  const pruned: Record<string, { time: string, location: string }> = {}
  for (const k of keys.slice(-maxItems)) {
    pruned[k] = map[k]
  }
  return pruned
}

export function useInterviewSchedule(activeJob: JobData | undefined) {
  // 🌟 引入 LocalStorage 持久化引擎，锁死面试日程
  const [scheduleCacheMap, setScheduleCacheMap] = useState<Record<string, { time: string, location: string }>>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("interview_schedule_cache")
      try { return saved ? pruneScheduleMap(JSON.parse(saved)) : {} } 
      catch (e) { return {} }
    }
    return {}
  })

  // 监听字典更新，写入本地磁盘，限制最大条目并捕获写入异常
  useEffect(() => {
    if (typeof window === "undefined") return
    try {
      const pruned = pruneScheduleMap(scheduleCacheMap, MAX_SCHEDULE_CACHE)
      localStorage.setItem("interview_schedule_cache", JSON.stringify(pruned))
    } catch (e) {
      console.warn("⚠️ [useInterviewSchedule] 日程缓存写入失败:", e)
    }
  }, [scheduleCacheMap])

  // 🌟 【权威对齐】：服务端数据为唯一事实源（Single Source of Truth），
  // 优先读取 activeJob 的时间与地点；本地 localStorage 仅作为弱网或离线时的降级回显
  const serverTime = activeJob ? (activeJob.interviewTime || (activeJob as any)?.interview_time || "") : ""
  const serverLocation = activeJob ? (activeJob.interviewLocation || (activeJob as any)?.interview_location || "") : ""

  const displayTime = activeJob ? (serverTime || scheduleCacheMap[activeJob.id]?.time || "") : ""
  const displayLocation = activeJob ? (serverLocation || scheduleCacheMap[activeJob.id]?.location || "") : ""

  // 🌟 当服务端最新数据抵达或多端更新时，自动校准本地缓存
  useEffect(() => {
    if (!activeJob) return
    const sTime = activeJob.interviewTime || (activeJob as any)?.interview_time || ""
    const sLoc = activeJob.interviewLocation || (activeJob as any)?.interview_location || ""
    if (sTime || sLoc) {
      setScheduleCacheMap(prev => {
        const existing = prev[activeJob.id]
        if (existing?.time === sTime && existing?.location === sLoc) return prev
        return {
          ...prev,
          [activeJob.id]: {
            time: sTime || existing?.time || "",
            location: sLoc || existing?.location || ""
          }
        }
      })
    }
  }, [activeJob?.id, activeJob?.interviewTime, (activeJob as any)?.interview_time, activeJob?.interviewLocation, (activeJob as any)?.interview_location])

  // 🌟 与后端 update_interview_schedule 中保持一致的线上特征词，命中即认为是线上面试，不展示高德导航按钮
  const ONLINE_LOCATION_KEYWORDS = ["腾讯会议", "飞书", "钉钉", "zoom", "线上", "视频", "电话", "http", "会议号", "在线"]
  const isOnlineLocation = (loc: string): boolean => {
    if (!loc) return false
    const lower = loc.toLowerCase()
    return ONLINE_LOCATION_KEYWORDS.some(k => lower.includes(k.toLowerCase()))
  }
  const shouldShowAmapNav = !!displayLocation && !isOnlineLocation(displayLocation)

  // 🌟 日程表单状态（新增 status 轮次状态）
  const [scheduleForm, setScheduleForm] = useState({ time: "", location: "", status: "一面" })
  const [isSavingSchedule, setIsSavingSchedule] = useState(false)
  const [modalType, setModalType] = useState<"resume" | "jd" | "report" | "schedule" | null>(null)

  const openScheduleModal = () => {
    setScheduleForm({
      time: displayTime,
      location: displayLocation,
      status: (activeJob as any)?.followStatus || "一面"
    })
    setModalType('schedule')
  }

  const handleSaveSchedule = async () => {
    if (!activeJob) return
    setIsSavingSchedule(true)
    try {
      // 🌟 【极致提速】：去掉了 await，让请求发出去就不管了，让后端自己默默干活
      fetch(`${API_BASE}/api/generate_handbook_pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: activeJob.id })
      }).catch(e => console.error("PDF打包指令发送失败", e))

      // 🌟 瞬间更新飞书时间与状态，立刻触发飞书机器人！
      const res = await fetch(`${API_BASE}/api/update_interview_schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: activeJob.id,
          interview_time: scheduleForm.time,
          interview_location: scheduleForm.location,
          follow_status: scheduleForm.status // 🌟 传入自主选择的轮次
        })
      })
      const data = await res.json()
      if (data.status === "success") {
        // 🌟 保存成功后，立即更新本地缓存并永久固化
        setScheduleCacheMap(prev => ({
          ...prev,
          [activeJob.id]: {
            time: scheduleForm.time,
            location: scheduleForm.location
          }
        }))
        
        ;(activeJob as any).interviewTime = scheduleForm.time
        ;(activeJob as any).interview_time = scheduleForm.time
        ;(activeJob as any).interviewLocation = scheduleForm.location
        ;(activeJob as any).interview_location = scheduleForm.location
        ;(activeJob as any).followStatus = scheduleForm.status // 🌟 状态实时联动
        setModalType(null)
        toast({
          title: "✅ 日程已同步",
          description: "面试日程及跟进状态已成功同步至飞书！",
        })
      } else {
        toast({
          title: "❌ 同步失败",
          description: data?.detail ? `同步飞书失败: ${data.detail}` : "同步飞书失败",
          variant: "destructive",
        })
      }
    } catch (e: any) {
      toast({
        title: "❌ 请求异常",
        description: e?.message || "网络请求异常，未能更新日程",
        variant: "destructive",
      })
    } finally {
      setIsSavingSchedule(false)
    }
  }

  return {
    displayTime,
    displayLocation,
    isOnlineLocation,
    shouldShowAmapNav,
    scheduleForm,
    setScheduleForm,
    isSavingSchedule,
    modalType,
    setModalType,
    openScheduleModal,
    handleSaveSchedule
  }
}
