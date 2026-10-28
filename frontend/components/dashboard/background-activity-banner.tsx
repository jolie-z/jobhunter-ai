"use client"

import { useEffect, useState } from "react"
import { Loader2, Radar } from "lucide-react"
import { API_BASE } from "@/lib/api"

/**
 * 后台定时任务占用横幅（根因修复：定时批量此前对前端完全不可见）
 *
 * 数据源：GET /api/tasks/status 的 background 聚合字段（15s 轮询）——
 * - activities: 定时投递等后台批量活动登记
 * - pipeline:   全链路自动化运行态（定时侦察/手动全链路共用）
 * - llm_gate:   LLM 闸门实时水位（并发槽/429 冷却窗）
 *
 * 空闲时不渲染任何内容；后端未启动/网络闪断时静默降级，绝不打扰主界面。
 */

interface BackgroundActivity {
  key: string
  label: string
  detail?: string
}

interface GateStats {
  enabled?: boolean
  max_concurrency?: number
  active_slots?: number
  cooldown_remaining?: number
}

interface BackgroundInfo {
  activities: BackgroundActivity[]
  pipeline?: { task_id?: string | null; running?: boolean }
  llm_gate?: GateStats
}

const POLL_INTERVAL_MS = 15000

export function useBackgroundActivity(): BackgroundInfo | null {
  const [info, setInfo] = useState<BackgroundInfo | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/tasks/status`)
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled && data?.background) {
          setInfo(data.background as BackgroundInfo)
        }
      } catch {
        // 后端未启动/网络闪断：静默，下次轮询自愈
      }
    }
    poll()
    const timer = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return info
}

export function BackgroundActivityBanner() {
  const info = useBackgroundActivity()

  const activities = info?.activities ?? []
  const pipelineRunning = info?.pipeline?.running === true
  if (activities.length === 0 && !pipelineRunning) return null

  const labels: string[] = activities.map((a) =>
    a.detail ? `${a.label}（${a.detail}）` : a.label
  )
  if (pipelineRunning) labels.push("全链路自动化")

  const gate = info?.llm_gate
  const gateParts: string[] = []
  if (typeof gate?.active_slots === "number" && gate.max_concurrency) {
    gateParts.push(`AI 并发 ${gate.active_slots}/${gate.max_concurrency}`)
  }
  if (gate?.cooldown_remaining && gate.cooldown_remaining > 0) {
    gateParts.push(`限流冷却 ${Math.ceil(gate.cooldown_remaining)}s`)
  }

  return (
    <div
      className="flex items-center gap-2 border-b border-amber-500/20 bg-amber-500/[0.08] px-4 py-1.5 text-xs text-amber-700 dark:text-amber-300"
      role="status"
      aria-live="polite"
    >
      <Radar className="size-3.5 shrink-0 animate-pulse" />
      <span className="font-semibold shrink-0">后台自动化运行中</span>
      <span className="truncate" title={labels.join("、")}>
        {labels.join("、")}
      </span>
      {gateParts.length > 0 && (
        <span className="shrink-0 text-amber-600/70 dark:text-amber-400/70">
          · {gateParts.join(" · ")}
        </span>
      )}
      <span className="ml-auto hidden shrink-0 items-center gap-1 text-[11px] text-amber-600/80 dark:text-amber-400/80 sm:flex">
        <Loader2 className="size-3 animate-spin" />
        手动 AI 任务走交互优先通道，无需排队等待
      </span>
    </div>
  )
}
