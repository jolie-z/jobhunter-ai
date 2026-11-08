/**
 * 阻塞任务的两个全局出口（继续 / 终止）——blocked-banner 与 command-header
 * 共用唯一实现。
 *
 * 抽取背景（外审 R4-P1-1/P1-2）：此前两处各自复制了一份，顶栏副本漏掉了
 * clear-blocked 后端清理与 pipelineTaskId 补建，导致顶栏终止后横幅在轮询/
 * 刷新后凭空复活、刷新恢复后点「继续任务」不建 SSE 连接并被轮询清场。
 */
import { toast } from "sonner"
import { usePipelineStore } from "@/store/pipeline-store"
import { API_BASE } from "@/lib/api"

/**
 * 继续阻塞任务：重跑遗留「待AI初筛」岗位的 AI 排雷。
 * 刷新后恢复的任务 pipelineTaskId 为 null → SSE effect 不建连，resume 实时事件
 * 全部丢失、横幅 12s 后被轮询 startPipeline 清场闪没（审计 P2-17）。响应带回
 * task_id 时同步补建链路标识：已有同 id 则仅切 running（保留现场），否则
 * startPipeline 重建连接。返回 true 表示受理成功。
 */
export async function resumeBlockedTask(): Promise<boolean> {
  const taskId = usePipelineStore.getState().blockedDetail?.task_id || ""
  try {
    const res = await fetch(`${API_BASE}/api/automation/resume-cleaning`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    })
    const data = await res.json()
    if (res.ok && data?.task_id) {
      const st = usePipelineStore.getState()
      if (st.pipelineTaskId === data.task_id) {
        st.resumePipeline()
      } else {
        st.startPipeline(data.task_id)
      }
      toast.success("继续任务已启动，正在重洗遗留岗位…")
      return true
    }
    toast.error("继续任务失败: " + (data?.detail || data?.message || "未知错误"))
    return false
  } catch {
    toast.error("继续任务失败：无法连接后端服务")
    return false
  }
}

/**
 * 终止阻塞任务：链路已收尾（无运行中协程），这是放弃继续这条链路的显式出口。
 * 先同步清后端阻塞登记：只清前端 store 的话，刷新后 dashboard-sync 快照会把横幅
 * 凭空种回来（2026-11-03 事故伴生缺陷）。fire-and-forget，失败不阻断本地收口。
 */
export function terminateBlockedTask(): void {
  const taskId = usePipelineStore.getState().blockedDetail?.task_id
  if (taskId) {
    fetch(`${API_BASE}/api/automation/clear-blocked`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId }),
    }).catch(() => {})
  }
  usePipelineStore.getState().reset()
  toast.success("已终止并关闭阻塞任务")
}
