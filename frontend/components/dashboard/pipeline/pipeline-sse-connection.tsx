"use client"

import { API_BASE } from "@/lib/api"
import { useEffect, useRef } from "react"
import { usePipelineStore } from "@/store/pipeline-store"


/**
 * 无头组件：负责为当前全链路（pipelineTaskId）建立并维护 SSE 长连接，
 * 把后端事件灌入 usePipelineStore。设计参照 live-task-terminal 的 TaskSseConnection。
 *
 * - 仅在链路处于 running 时连接；end/error 后主动断开。
 * - 依赖 pipelineTaskId 变化重建连接（切换/新启动链路时）。
 */
export function PipelineSseConnection() {
  const pipelineTaskId = usePipelineStore(s => s.pipelineTaskId)
  const status = usePipelineStore(s => s.status)
  const eventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    // 已结束或无任务：不连接
    if (!pipelineTaskId || status === "idle" || status === "done" || status === "error") {
      return
    }

    // 避免重复连接
    if (eventSourceRef.current) {
      return
    }

    const es = new EventSource(`${API_BASE}/api/tasks/logs?task_id=${pipelineTaskId}`)
    eventSourceRef.current = es

    const close = () => {
      es.close()
      if (eventSourceRef.current === es) {
        eventSourceRef.current = null
      }
    }

    es.onopen = () => {
      console.log(`📡 [Pipeline SSE] 连接已建立: ${pipelineTaskId}`)
    }

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        usePipelineStore.getState().handleEvent(data)

        // 终态事件：主动断开
        if (data.type === "end" || data.type === "error") {
          close()
        }
      } catch (err) {
        console.error("❌ [Pipeline SSE] 解析消息失败:", err)
      }
    }

    es.onerror = () => {
      const cur = usePipelineStore.getState()
      // 已结束则直接关闭；否则交给浏览器原生 EventSource 自动重连
      if (cur.status === "done" || cur.status === "error" || cur.status === "idle") {
        close()
        return
      }
      console.warn(`⚠️ [Pipeline SSE] 连接暂时异常，等待自动重连 (${pipelineTaskId})`)
    }

    return () => {
      if (eventSourceRef.current && eventSourceRef.current.readyState !== EventSource.CLOSED) {
        eventSourceRef.current.close()
      }
      eventSourceRef.current = null
    }
  }, [pipelineTaskId, status])

  return null
}
