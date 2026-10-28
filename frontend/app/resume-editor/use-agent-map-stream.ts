"use client"

import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Agent 映射异步任务 SSE 订阅 hook（Phase 4：进度 / 取消 / 失败态闭环）。
 *
 * 事件契约（与后端 agent_map_tasks.py 一一对应）：
 * - started        → 初始化各平台 pending
 * - platform_start → 平台 running
 * - retry_wait     → 平台进入退避等待（携带秒数，供倒计时展示）
 * - platform_done  → 平台 done/failed（携带 success/message/warnings/degraded 失败载荷）
 * - cancel_requested / heartbeat → 状态提示与保活，不驱动状态机
 * - complete       → 终态（携带全量 reports 与 cancelled），断线由 EventSource 自动重连 + 历史回放兜底
 *
 * 回滚兼容：AGENT_MAP_ASYNC_ENABLED=false 时 /generate 直接返回同步结果，
 * start() 以 syncResult 形式上抛，由调用方沿用旧同步处理路径。
 */

export type AgentMapPlatformStatus = "pending" | "running" | "retry_wait" | "done" | "failed"

export interface AgentMapPlatformState {
  status: AgentMapPlatformStatus
  success?: boolean
  message?: string
  warnings?: string[]
  degraded?: boolean
  retrySeconds?: number
  retryStartedAt?: number
}

export type AgentMapPhase = "idle" | "connecting" | "running" | "complete" | "cancelled" | "error"

export interface AgentMapStreamState {
  phase: AgentMapPhase
  platforms: Record<string, AgentMapPlatformState>
  reports?: Record<string, any>
  errorMessage?: string
}

export interface AgentMapTerminalResult {
  ok: boolean
  cancelled: boolean
  reports: Record<string, any>
  /** 本次尝试的平台清单（同步回退且响应未携带 reports 时用于文案与统计） */
  platforms?: string[]
  /** 后端整体级错误文案（如主简历加载失败），无平台级报告时直接展示 */
  message?: string
}

export interface AgentMapStartOutcome {
  started: boolean
  syncResult?: { success: boolean; reports?: Record<string, any>; message?: string }
  error?: string
}

export interface AgentMapStartPayload {
  platforms: string[]
  record_id: string | null
  selected_modules: string[]
}

const INITIAL_STATE: AgentMapStreamState = { phase: "idle", platforms: {} }

export function useAgentMapStream(
  apiBase: string,
  onTerminal: (result: AgentMapTerminalResult) => void,
) {
  const [state, setState] = useState<AgentMapStreamState>(INITIAL_STATE)
  const esRef = useRef<EventSource | null>(null)
  const taskIdRef = useRef<string | null>(null)
  const terminalFiredRef = useRef(false)
  const onTerminalRef = useRef(onTerminal)
  onTerminalRef.current = onTerminal

  const closeStream = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
  }, [])

  useEffect(() => closeStream, [closeStream])

  const fireTerminal = useCallback((result: AgentMapTerminalResult, phase: AgentMapPhase, errorMessage?: string) => {
    closeStream()
    setState(prev => ({ ...prev, phase, errorMessage }))
    if (!terminalFiredRef.current) {
      terminalFiredRef.current = true
      onTerminalRef.current(result)
    }
  }, [closeStream])

  const start = useCallback(async (payload: AgentMapStartPayload): Promise<AgentMapStartOutcome> => {
    closeStream()
    terminalFiredRef.current = false
    taskIdRef.current = null
    const platforms: Record<string, AgentMapPlatformState> = {}
    for (const p of payload.platforms) platforms[p] = { status: "pending" }
    setState({ phase: "connecting", platforms })

    try {
      const res = await fetch(`${apiBase}/api/agent-map/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // 不显式指定 mode：异步/同步由后端 AGENT_MAP_ASYNC_ENABLED 熔断开关决定（settings.json 热控回滚必须 100% 生效）
        body: JSON.stringify({
          platforms: payload.platforms,
          record_id: payload.record_id,
          selected_modules: payload.selected_modules,
        }),
      })
      const result = await res.json()
      if (!result.task_id) {
        // 回滚态（或旧版后端）：同步返回完整结果，流状态机不启用
        setState(INITIAL_STATE)
        return { started: false, syncResult: result }
      }
      taskIdRef.current = result.task_id
      const taskId = result.task_id
      const es = new EventSource(`${apiBase}/api/agent-map/generate/stream/${taskId}`)
      esRef.current = es

      es.onmessage = (event) => {
        let data: any
        try {
          data = JSON.parse(event.data)
        } catch {
          return
        }
        switch (data.type) {
          case "started":
            setState(prev => ({ ...prev, phase: "running" }))
            break
          case "platform_start":
            setState(prev => ({
              ...prev,
              phase: "running",
              platforms: { ...prev.platforms, [data.platform]: { status: "running" } },
            }))
            break
          case "retry_wait":
            setState(prev => ({
              ...prev,
              platforms: {
                ...prev.platforms,
                [data.platform]: {
                  ...(prev.platforms[data.platform] || {}),
                  status: "retry_wait",
                  retrySeconds: Number(data.seconds) || 0,
                  retryStartedAt: Date.now(),
                },
              },
            }))
            break
          case "platform_done": {
            const success = data.success === true
            setState(prev => ({
              ...prev,
              platforms: {
                ...prev.platforms,
                [data.platform]: {
                  ...(prev.platforms[data.platform] || {}),
                  status: success ? "done" : "failed",
                  success,
                  message: data.message,
                  warnings: data.warnings || [],
                  degraded: data.degraded === true,
                  retrySeconds: undefined,
                  retryStartedAt: undefined,
                },
              },
            }))
            break
          }
          case "complete": {
            const cancelled = data.cancelled === true
            fireTerminal(
              { ok: data.success === true, cancelled, reports: data.reports || {}, message: data.error },
              cancelled ? "cancelled" : data.error ? "error" : "complete",
              data.error,
            )
            break
          }
          case "error":
            fireTerminal({ ok: false, cancelled: false, reports: {} }, "error", data.message)
            break
          default:
            break // heartbeat / cancel_requested 等不驱动状态机
        }
      }

      es.onerror = () => {
        // 瞬断：浏览器自动重连（readyState=CONNECTING）+ 后端历史回放，无需干预；
        // 仅当连接被永久关闭（readyState=CLOSED=2，如任务台账已过期 404）才判定失败，避免 UI 永久卡「进行中」
        if (es.readyState === 2) {
          fireTerminal(
            { ok: false, cancelled: false, reports: {}, message: "进度流连接已断开（任务可能已过期），请点击「刷新数据」查看已生成的报告" },
            "error",
            "进度流连接已断开",
          )
        }
      }
      return { started: true }
    } catch (e: any) {
      setState(prev => ({ ...prev, phase: "error", errorMessage: String(e?.message || e) }))
      return { started: false, error: "映射请求网络异常: " + (e?.message || e) }
    }
  }, [apiBase, closeStream, fireTerminal])

  const cancel = useCallback(async () => {
    const taskId = taskIdRef.current
    if (!taskId) return
    try {
      await fetch(`${apiBase}/api/agent-map/generate/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId }),
      })
    } catch {
      // 取消请求失败不打断前端：任务侧仍会按自身节奏收尾
    }
  }, [apiBase])

  const isRunning = state.phase === "connecting" || state.phase === "running"

  return { state, start, cancel, isRunning }
}
