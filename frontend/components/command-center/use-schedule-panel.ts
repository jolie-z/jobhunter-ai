"use client"

import { useState, useEffect } from "react"
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
  const [scheduledEnabled, setScheduledEnabled] = useState(true)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [skipNonWorkdays, setSkipNonWorkdays] = useState(true)
  const [savingSchedule, setSavingSchedule] = useState(false)
  const [scheduleMsg, setScheduleMsg] = useState<string | null>(null)
  const [holidayStatus, setHolidayStatus] = useState<HolidayDataStatus | null>(null)
  const [updatingHoliday, setUpdatingHoliday] = useState(false)

  useEffect(() => {
    // 恢复上次选择的执行模式（与顶部其他配置「刷新不丢」的行为对齐）
    const saved = window.localStorage.getItem("command-center:mode")
    if (saved === "immediate" || saved === "scheduled") setModeState(saved)

    // 定时配置 + 节假日数据并发拉取（与 Token 统计请求相互独立）
    Promise.all([
      fetch(`${API_BASE}/api/automation/config`).then(r => r.json()).catch(() => ({})),
      fetch(`${API_BASE}/api/automation/holiday-data-status`).then(r => r.json()).catch(() => ({})),
    ]).then(([configRes, holidayRes]) => {
      const d = configRes?.data
      if (d?.cron_time) setDailyTime(d.cron_time)
      if (typeof d?.is_enabled === "boolean") setScheduledEnabled(d.is_enabled)
      if (typeof d?.schedule_start_date === "string") setStartDate(d.schedule_start_date || "")
      if (typeof d?.schedule_end_date === "string") setEndDate(d.schedule_end_date || "")
      if (typeof d?.skip_non_workdays === "boolean") setSkipNonWorkdays(d.skip_non_workdays)
      if (holidayRes?.data) setHolidayStatus(holidayRes.data)
    }).catch(() => {})
  }, [])

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
