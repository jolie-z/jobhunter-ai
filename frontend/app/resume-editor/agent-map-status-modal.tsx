"use client"

import { useEffect, useState } from "react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle, Ban, CheckCircle2, Circle, Loader2, Timer, XCircle } from "lucide-react"
import type { AgentMapPlatformState, AgentMapStreamState } from "./use-agent-map-stream"

/**
 * Agent 映射进度弹窗（Phase 4）：平台进度 chips、退避倒计时、取消按钮、失败平台红色态卡片。
 * 纯展示组件：所有状态来自 useAgentMapStream，自身只维护倒计时 tick。
 */

interface AgentMapStatusModalProps {
  open: boolean
  onClose: () => void
  onCancel: () => void
  state: AgentMapStreamState
  platformOrder: string[]
  platformNames: Record<string, string>
  platformColors: Record<string, string>
}

function retryRemaining(p: AgentMapPlatformState, now: number): number {
  if (p.status !== "retry_wait" || !p.retrySeconds || !p.retryStartedAt) return 0
  return Math.max(0, Math.ceil(p.retrySeconds - (now - p.retryStartedAt) / 1000))
}

function StatusIcon({ p, now }: { p: AgentMapPlatformState; now: number }) {
  switch (p.status) {
    case "running":
      return <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-600" />
    case "retry_wait":
      return <Timer className="w-3.5 h-3.5 text-amber-600" />
    case "done":
      return p.degraded
        ? <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
        : <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
    case "failed":
      return <XCircle className="w-3.5 h-3.5 text-red-600" />
    default:
      return <Circle className="w-3.5 h-3.5 text-gray-300" />
  }
}

function statusLabel(p: AgentMapPlatformState, now: number): string {
  switch (p.status) {
    case "running": return "AI 映射中"
    case "retry_wait": return `限流退避 ${retryRemaining(p, now)}s`
    case "done": return p.degraded ? "已降级规则映射" : "完成"
    case "failed": return "失败"
    default: return "排队中"
  }
}

export function AgentMapStatusModal({
  open, onClose, onCancel, state, platformOrder, platformNames, platformColors,
}: AgentMapStatusModalProps) {
  const [now, setNow] = useState(() => Date.now())
  const [cancelRequested, setCancelRequested] = useState(false)
  const hasRetryWait = Object.values(state.platforms).some(p => p.status === "retry_wait")

  // 仅在有平台处于退避等待时每秒 tick，驱动倒计时；
  // 进入退避时先同步一次 now：useState 的初值是组件挂载时刻，若首次退避发生在挂载很久之后，
  // 首个 interval 触发前的那一秒会用过期的 now 算出「3 + 挂载至今秒数」的离谱倒计时
  useEffect(() => {
    if (!open || !hasRetryWait) return
    setNow(Date.now())
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [open, hasRetryWait])

  useEffect(() => {
    if (state.phase === "connecting") setCancelRequested(false)
  }, [state.phase])

  const terminal = state.phase === "complete" || state.phase === "cancelled" || state.phase === "error"
  const platforms = [
    ...platformOrder.filter(p => state.platforms[p]),
    ...Object.keys(state.platforms).filter(p => !platformOrder.includes(p)),
  ]
  const doneCount = platforms.filter(p => state.platforms[p].status === "done").length
  const failed = platforms.filter(p => state.platforms[p].status === "failed")

  const title = state.phase === "cancelled"
    ? "映射任务已取消"
    : state.phase === "error"
      ? "映射任务异常终止"
      : terminal
        ? "映射报告生成完成"
        : "AI 智能映射进行中"

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && terminal) onClose() }}>
      <DialogContent className="sm:max-w-[560px]" showCloseButton={terminal}>
        <DialogHeader>
          <DialogTitle className="text-sm font-semibold text-gray-900">{title}</DialogTitle>
          <DialogDescription className="text-xs text-gray-500">
            {terminal
              ? `${doneCount}/${platforms.length} 个平台生成成功${failed.length ? `，${failed.length} 个失败` : ""}${state.phase === "cancelled" ? "（已完成平台的报告已保留）" : ""}`
              : "按平台顺序执行；遇到限流会自动退避重试，可随时取消（当前请求收尾后在平台边界停止）"}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap gap-2">
          {platforms.map(p => {
            const ps = state.platforms[p]
            return (
              <div
                key={p}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs ${
                  ps.status === "failed" ? "border-red-200 bg-red-50/60"
                    : ps.status === "done" && ps.degraded ? "border-amber-200 bg-amber-50/60"
                      : ps.status === "done" ? "border-emerald-200 bg-emerald-50/60"
                        : "border-gray-200 bg-gray-50/70"
                }`}
              >
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: platformColors[p] }} />
                <span className="font-medium text-gray-800">{platformNames[p] || p}</span>
                <StatusIcon p={ps} now={now} />
                <span className="text-[11px] text-gray-600">{statusLabel(ps, now)}</span>
              </div>
            )
          })}
        </div>

        {failed.length > 0 && (
          <div className="space-y-1.5">
            {failed.map(p => (
              <div key={p} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs">
                <div className="font-medium text-red-700">{platformNames[p] || p} 映射失败</div>
                <div className="text-red-600/90 mt-0.5 break-all">{state.platforms[p].message || "未知错误"}</div>
              </div>
            ))}
          </div>
        )}

        {platforms.some(p => state.platforms[p].degraded) && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            部分平台因 AI 模型不可用已降级为确定性规则映射，仅覆盖文本/日期字段，请在对应 Tab 重点核对。
          </div>
        )}

        {state.errorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 break-all">
            {state.errorMessage}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-1">
          {!terminal ? (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs text-red-600 border-red-200 hover:bg-red-50"
              disabled={cancelRequested}
              onClick={() => { setCancelRequested(true); onCancel() }}
            >
              <Ban className="w-3 h-3 mr-1" />
              {cancelRequested ? "取消中（等待当前请求收尾）..." : "取消映射"}
            </Button>
          ) : (
            <>
              {state.phase === "complete" && failed.length === 0 && (
                <Badge variant="outline" className="text-[11px] bg-emerald-50 text-emerald-700 border-emerald-200 font-normal">
                  请到对应平台 Tab 查阅并确认
                </Badge>
              )}
              <Button size="sm" className="h-7 text-xs" onClick={onClose}>关闭</Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
