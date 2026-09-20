"use client"

import { useState, useEffect, useCallback } from "react"
import { API_BASE } from "@/lib/api"
import type { OverviewStats, FunnelStage, PlatformStat, TrendPoint, GoalData } from "../types"

export function useAnalyticsData() {
  const [ov, setOv] = useState<OverviewStats | null>(null)
  const [funnel, setFunnel] = useState<FunnelStage[]>([])
  const [funnelCrawled, setFunnelCrawled] = useState(0)
  const [platforms, setPlatforms] = useState<PlatformStat[]>([])
  const [initialTrend, setInitialTrend] = useState<TrendPoint[]>([])
  const [goals, setGoals] = useState<GoalData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastSyncTime, setLastSyncTime] = useState<string>("")

  const load = useCallback(async (isSilent = false) => {
    if (!isSilent) setLoading(true)
    try {
      const [a, b, c, d, e] = await Promise.all([
        fetch(`${API_BASE}/api/v2/analytics/overview`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v2/analytics/funnel`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v2/analytics/platform`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v2/analytics/trend?range=daily`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v2/goals/current`).then((r) => r.json()).catch(() => null),
      ])

      if (a?.code === 0 && a.data) setOv(a.data)
      if (b?.code === 0 && b.data) {
        setFunnel(b.data.funnel || [])
        setFunnelCrawled(b.data.total_crawled || 0)
      }
      if (c?.code === 0 && c.data) setPlatforms(c.data.platforms || [])
      if (d?.code === 0 && d.data) setInitialTrend(d.data.trend || [])
      if (e?.code === 0 && e.data) setGoals(e.data)

      const now = new Date()
      setLastSyncTime(
        `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`
      )
    } catch (err) {
      console.error("[useAnalyticsData] Load failed:", err)
    } finally {
      if (!isSilent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const refreshAll = async () => {
    setRefreshing(true)
    try {
      await fetch(`${API_BASE}/api/v2/analytics/cache/clear`, { method: "POST" }).catch(() => {})
      await load(true)
    } finally {
      setTimeout(() => setRefreshing(false), 800)
    }
  }

  return {
    ov,
    funnel,
    funnelCrawled,
    platforms,
    initialTrend,
    goals,
    loading,
    refreshing,
    lastSyncTime,
    reload: () => load(false),
    refreshAll,
  }
}
