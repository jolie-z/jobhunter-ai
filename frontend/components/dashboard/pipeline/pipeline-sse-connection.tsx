"use client"

import { API_BASE } from "@/lib/api"
import { useEffect, useRef } from "react"
import { toast } from "sonner"
import { classifyEndFrame, usePipelineStore } from "@/store/pipeline-store"


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
    // 已结束或无任务：不连接（blocked = 链路已收口暂停，等「继续任务」置回 running 再连）
    if (!pipelineTaskId || status === "idle" || status === "done" || status === "error" || status === "blocked") {
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

        // 非正常收口 toast（2026-11-02 审计 P1-9）：复用 store 的 classifyEndFrame
        // 唯一分诊——blocked 不弹（BlockedDetail 横幅已承载）、aborted 走 info、
        // expired/no_resume 走 error，与状态机口径严格一致
        if (data.type === "end") {
          const verdict = classifyEndFrame(data)
          if (verdict.kind === "aborted") {
            toast.info(verdict.message)
          } else if (verdict.kind === "expired" || verdict.kind === "no_resume") {
            toast.error(verdict.message)
          }
        }

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
      if (cur.status === "done" || cur.status === "error" || cur.status === "idle" || cur.status === "blocked") {
        close()
        return
      }
      // 永久死亡自愈（2026-11-02 审计 P2-16）：原生重连收到非 200/非 event-stream 响应时
      // 规范规定不再重建（readyState=CLOSED），此时 status 停在 running 无人知晓。
      // 检测到 CLOSED 且链路仍 running → 显式置错误态并提示（用户可重新触发任务）
      if (es.readyState === EventSource.CLOSED) {
        console.error(`❌ [Pipeline SSE] 连接永久关闭且链路仍在运行 (${pipelineTaskId})，置为错误态`)
        usePipelineStore.setState({
          status: "error",
          logs: [...cur.logs.slice(-199), "❌ 实时事件流已断开且无法自动重连，请刷新页面或重新触发任务"],
        })
        toast.error("实时事件流已断开，请刷新页面恢复")
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
