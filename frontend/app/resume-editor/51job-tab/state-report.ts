/**
 * Job51 Tab 映射报告 handler 簇（自 state.tsx 机械拆出，行为零变化）。
 */
"use client"

import { API_BASE } from "@/lib/api"
import { fetchPlatformReport } from "../api-client"
import type { Dispatch, SetStateAction } from "react"
import type { PlatformReport } from "../agent-report-shared"

interface Job51ReportDeps {
  report: PlatformReport | null
  setReport: Dispatch<SetStateAction<PlatformReport | null>>
  setReportLoading: Dispatch<SetStateAction<boolean>>
  setApplyConfirmOpen: Dispatch<SetStateAction<boolean>>
  setApplying: Dispatch<SetStateAction<boolean>>
  setApplyFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; time?: string } | null>>
  getNowTime: () => string
  onRefresh: () => void
}

export function useJob51ReportHandlers(deps: Job51ReportDeps) {
  const {
    report,
    setReport,
    setReportLoading,
    setApplyConfirmOpen,
    setApplying,
    setApplyFeedback,
    getNowTime,
    onRefresh,
  } = deps

  const fetchReport = async () => {
    setReportLoading(true)
    try {
      const r = await fetchPlatformReport(API_BASE, "51job")
      if (r.status === "ok") setReport(r.report)
      else if (r.status === "absent") setReport(null)
      // error：后端暂不可用，保留旧报告
    } finally {
      setReportLoading(false)
    }
  }

  const handleApplyReport = async () => {
    if (!report) return
    setApplyConfirmOpen(false)
    setApplying(true)
    setApplyFeedback(null)
    const now = getNowTime()
    try {
      const entries = report.fields.map(f => ({ path: f.path, value: f.value }))
      const res = await fetch(`${API_BASE}/api/agent-map/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "51job", entries }),
      })
      const result = await res.json()
      if (result.success) {
        // 即时合并「已修改」标识（后端已持久化，此处本地先行，无需等下次拉报告）
        const applied: string[] = result.applied || []
        if (applied.length) {
          setReport((prev: any) => prev ? {
            ...prev,
            applied_paths: Array.from(new Set([...(prev.applied_paths || []), ...applied])),
          } : prev)
        }
        setApplyFeedback({ msg: `✓ ${result.message}；点「保存快照」后可回写官网`, ok: true, time: now })
        onRefresh()
      } else {
        setApplyFeedback({ msg: result.message || "写入失败", ok: false, time: now })
      }
    } catch (e) {
      setApplyFeedback({ msg: "写入失败: " + e, ok: false, time: now })
    } finally {
      setApplying(false)
    }
  }

  return {
    fetchReport,
    handleApplyReport,
  }
}
