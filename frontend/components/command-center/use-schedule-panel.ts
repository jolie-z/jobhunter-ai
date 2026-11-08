"use client"

import { useCallback, useRef, useState, useEffect } from "react"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"

// chinese-calendar 数据覆盖状态（后端 /holiday-data-status）
export interface HolidayDataStatus {
  installed: boolean
  covered_year: number | null
  current_year: number
  next_year: number
  stale_soon: boolean
  stale_critical: boolean
  version: string
}

/**
 * 每日定时调度面板状态与动作（从 CommandHeader 抽离，Q10 拆分批次 1）。
 *
 * 覆盖：执行模式（手动/定时，localStorage 持久化）、定时窗口五项配置、
 * 保存热更新 APScheduler、节假日数据状态与一键更新。
 */
export function useSchedulePanel() {
  const [mode, setModeState] = useState<"immediate" | "scheduled">("immediate")
  const [dailyTime, setDailyTime] = useState("09:00")
  // 默认 null（未知/加载中）：不预设开或关，避免存量已开启用户首帧闪「关」再跳「开」；
  // 拉取 /api/automation/config 成功后以服务端为准；为 null 时开关与保存按钮置灰
  const [scheduledEnabled, setScheduledEnabled] = useState<boolean | null>(null)
  // 读取失败态：config 拉取失败/坏载荷时置真，面板显示「读取失败 + 重试」而非永久「读取配置中…」
  const [scheduleLoadFailed, setScheduleLoadFailed] = useState(false)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [skipNonWorkdays, setSkipNonWorkdays] = useState(true)
  const [savingSchedule, setSavingSchedule] = useState(false)
  const [scheduleMsg, setScheduleMsg] = useState<string | null>(null)
  const [holidayStatus, setHolidayStatus] = useState<HolidayDataStatus | null>(null)
  const [updatingHoliday, setUpdatingHoliday] = useState(false)

  // config 拉取请求序号：重试/卸载后晚到的旧响应按过期丢弃，防止旧数据覆盖新状态
  const loadSeqRef = useRef(0)

  const loadScheduleConfig = useCallback(() => {
    setScheduleLoadFailed(false)
    setScheduledEnabled(null) // 重载期间回到「读取配置中…」，避免旧值与结果间的不一致窗口
    const seq = ++loadSeqRef.current
    // 定时配置 + 节假日数据并发拉取（相互独立）：各自 10s 超时竞速（Promise.race 与
    // AbortController 双保险）——即便 fetch 实现无视 signal（测试 stub / 网络栈挂死），
    // race 的 reject 分支也保证 10s 必有落定，面板绝不永久卡「读取配置中…」。
    // 两条链独立落定：config 决定开关/失败态，holiday 只影响节假日横幅——
    // holiday 慢不拖慢 config 的 UI 更新。
    const timedJson = (url: string): Promise<any> => {
      const abort = new AbortController()
      const abortTimer = setTimeout(() => abort.abort(), 10_000)
      let raceTimer: ReturnType<typeof setTimeout> | undefined
      const race = Promise.race([
        fetch(url, { signal: abort.signal }).then(r => r.json()),
        new Promise<any>((_, reject) => {
          raceTimer = setTimeout(() => reject(new Error("request timeout (10s)")), 10_000)
        }),
      ])
      return race.finally(() => {
        clearTimeout(abortTimer)
        clearTimeout(raceTimer)
        abort.abort() // 落定后无论谁赢都掐断底层连接（已 settle 的 abort 无副作用）
      })
    }
    const isStale = () => seq !== loadSeqRef.current
    // config 链独立落定开关/失败态（不被 holiday 的慢响应拖住）
    timedJson(`${API_BASE}/api/automation/config`).then(configRes => {
      if (isStale()) return
      const d = configRes?.data
      if (typeof d?.is_enabled !== "boolean") {
        setScheduleLoadFailed(true)
        return
      }
      setScheduledEnabled(d.is_enabled)
      if (d?.cron_time) setDailyTime(d.cron_time)
      if (typeof d?.schedule_start_date === "string") setStartDate(d.schedule_start_date || "")
      if (typeof d?.schedule_end_date === "string") setEndDate(d.schedule_end_date || "")
      if (typeof d?.skip_non_workdays === "boolean") setSkipNonWorkdays(d.skip_non_workdays)
    }).catch(() => {
      if (!isStale()) setScheduleLoadFailed(true)
    })
    // holiday 链独立落定节假日横幅（任何失败折算空对象，绝不影响开关状态）
    timedJson(`${API_BASE}/api/automation/holiday-data-status`)
      .then(holidayRes => {
        if (isStale()) return
        if (holidayRes?.data) setHolidayStatus(holidayRes.data)
      })
      .catch(() => {}) // holiday 任何失败（网络/超时/坏载荷）都静默降级，不阻塞配置面板
  }, [])

  useEffect(() => {
    // 恢复上次选择的执行模式（与顶部其他配置「刷新不丢」的行为对齐）
    const saved = window.localStorage.getItem("command-center:mode")
    if (saved === "immediate" || saved === "scheduled") setModeState(saved)
    loadScheduleConfig()
  }, [loadScheduleConfig])

  // 一键更新节假日数据：后端 pip 升级 + 热加载（可能耗时数十秒）
  const handleUpdateHolidayData = async () => {
    if (updatingHoliday) return
    setUpdatingHoliday(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/holiday-data-update`, { method: "POST" })
      const data = await res.json()
      if (data?.data) {
        setHolidayStatus(data.data)
        const msg = data.data.message || "节假日数据已检查"
        if (data.status === "success") toast.success(msg)
        else toast.info(msg)
      } else {
        toast.error("节假日数据更新失败: " + (data.detail || "未知错误"))
      }
    } catch {
      toast.error("节假日数据更新失败：无法连接后端")
    } finally {
      setUpdatingHoliday(false)
    }
  }

  // 透出规则：数据连当年都覆盖不了（断供降级）随时提醒；下一年安排未收录则 12 月才透出
  const showHolidayUpdate =
    !!holidayStatus && (holidayStatus.stale_critical || (holidayStatus.stale_soon && new Date().getMonth() + 1 === 12))

  // 切换执行模式并本地持久化（SSR 安全：localStorage 只在客户端事件里访问）
  const setMode = (next: "immediate" | "scheduled") => {
    setModeState(next)
    try {
      window.localStorage.setItem("command-center:mode", next)
    } catch {}
  }

  // 保存每日定时调度：后端持久化并热更新 APScheduler
  const handleSaveSchedule = async () => {
    if (savingSchedule) return
    if (scheduledEnabled === null) return // 配置未读取完成（按钮应已置灰，此处兜底防误发 null）
    setSavingSchedule(true)
    setScheduleMsg(null)
    try {
      const res = await fetch(`${API_BASE}/api/automation/schedule-config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cron_time: dailyTime,
          is_enabled: scheduledEnabled,
          schedule_start_date: startDate,
          schedule_end_date: endDate,
          skip_non_workdays: skipNonWorkdays,
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success") {
        setScheduleMsg(data.message || "定时调度已保存生效")
        toast.success(data.message || "定时调度已保存生效")
      } else {
        setScheduleMsg("保存失败: " + (data.detail || data.message || "未知错误"))
        toast.error("定时调度保存失败")
      }
    } catch {
      setScheduleMsg("保存失败：无法连接后端服务")
      toast.error("定时调度保存失败：无法连接后端")
    } finally {
      setSavingSchedule(false)
    }
  }

  return {
    mode,
    setMode,
    dailyTime,
    setDailyTime,
    scheduledEnabled,
    setScheduledEnabled,
    scheduleLoadFailed,
    retryLoadSchedule: loadScheduleConfig,
    startDate,
    setStartDate,
    endDate,
    setEndDate,
    skipNonWorkdays,
    setSkipNonWorkdays,
    savingSchedule,
    scheduleMsg,
    holidayStatus,
    updatingHoliday,
    showHolidayUpdate,
    handleUpdateHolidayData,
    handleSaveSchedule,
  }
}
