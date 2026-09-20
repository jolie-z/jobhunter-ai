/**
 * Zhilian Tab 映射报告 handler 簇（自 state.tsx 机械拆出，行为零变化）。
 */
"use client"

import { API_BASE } from "@/lib/api"
import { fetchPlatformReport } from "../api-client"
import type { Dispatch, SetStateAction } from "react"
import type { PlatformReport } from "../agent-report-shared"

interface ZhilianReportDeps {
  report: PlatformReport | null
  setReport: Dispatch<SetStateAction<PlatformReport | null>>
  setReportLoading: Dispatch<SetStateAction<boolean>>
  setApplyConfirmOpen: Dispatch<SetStateAction<boolean>>
  setApplying: Dispatch<SetStateAction<boolean>>
  setApplyFeedback: Dispatch<SetStateAction<{ msg: string; ok: boolean; time?: string } | null>>
  getNowTime: () => string
  onRefresh: () => void
}

export function useZhilianReportHandlers(deps: ZhilianReportDeps) {
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
      const r = await fetchPlatformReport(API_BASE, "zhilian")
      if (r.status === "ok") setReport(r.report)
      else if (r.status === "absent") setReport(null)
      // error：后端暂不可用，保留旧报告
    } finally {
      setReportLoading(false)
    }
  }

  // 应用映射：报告字段覆盖写入智联本地数据（两步确认；写入后刷新展示）
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
        body: JSON.stringify({ platform: "zhilian", entries }),
      })
      const result = await res.json()
      if (result.success) {
        // 即时合并「已修改」标识（后端已持久化 applied_paths，本地先行，无需等下次拉报告）
        setReport(prev => prev ? {
          ...prev,
          applied_paths: [...new Set([...(prev.applied_paths || []), ...entries.map(e => e.path)])],
        } : prev)
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
