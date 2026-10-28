"use client"

import { useEffect, useRef } from "react"
import { Loader2, CheckCircle2, AlertCircle, X } from "lucide-react"
import { useSkillAgentStream, formatAgentElapsed, type SkillAgentCompletePayload } from "@/hooks/use-skill-agent-stream"

/**
 * 官方剧本/单文件技能改写的轻量行内状态条。
 *
 * 这类技能走单轮标准引擎（一次大模型调用，事件稀疏），不配「作战推演看板」那套
 * 终端 UI；但改写耗时 1-3 分钟，异步启动秒级返回后按钮转圈即停——本条承接同一份
 * SSE 流，给用户阶段文本 + 计时的最低限度反馈。终局（完成/失败）由父级清理任务态
 * 卸载本条：完成=铺画布+toast，失败=onError 上报真实报错，状态条不留常驻横幅。
 */

export interface SkillRewriteInlineStatusProps {
  taskId: string
  skillLabel?: string
  /** 改写完成：业务落点（铺画布/开产物库）由父级处理 */
  onComplete: (data: SkillAgentCompletePayload) => void
  /** 改写失败：上报真实报错（仅触发一次），父级负责 toast 与清理 */
  onError: (message: string) => void
  /** 用户手动收起状态条（仅运行中可见）：SSE 停订，任务仍在服务端继续执行 */
  onDismiss: () => void
}

export function SkillRewriteInlineStatus({
  taskId,
  skillLabel,
  onComplete,
  onError,
  onDismiss
}: SkillRewriteInlineStatusProps) {
  const { logs, status, errorMessage, elapsedSeconds } = useSkillAgentStream({
    taskId,
    active: true,
    onComplete
  })

  // 失败终局上报（仅一次；完成侧走 onComplete 链路，不经此回调）
  const reportedRef = useRef(false)
  useEffect(() => {
    if (status === "error" && !reportedRef.current) {
      reportedRef.current = true
      onError(errorMessage || "改写推演出错，请重试")
    }
  }, [status, errorMessage, onError])

  // 最新一条日志作为阶段文本
  const latestMessage = logs.length > 0 ? logs[logs.length - 1].message : "正在建立实时通道…"
  const isTerminal = status === "completed" || status === "error"

  return (
    <div className="shrink-0 mx-4 mt-2 flex items-center gap-2.5 rounded-xl border border-amber-300/70 bg-gradient-to-r from-amber-50/95 via-orange-50/85 to-amber-50/95 px-3.5 py-2 shadow-xs ring-1 ring-amber-400/25 animate-in slide-in-from-top-2 duration-300">
      {status === "error" ? (
        <AlertCircle className="size-4 shrink-0 text-rose-500" />
      ) : status === "completed" ? (
        <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
      ) : (
        <Loader2 className="size-4 shrink-0 animate-spin text-amber-500" />
      )}

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-700 shrink-0">
            {skillLabel || "官方标准剧本"} · 简历改写中
          </span>
          <span className="text-[10px] font-mono text-amber-700 bg-white/70 border border-amber-200 px-1.5 rounded shrink-0">
            {formatAgentElapsed(elapsedSeconds)}
          </span>
          {status === "error" && (
            <span className="text-[10px] font-medium text-rose-600 bg-rose-50 border border-rose-200 px-1.5 rounded shrink-0">
              失败
            </span>
          )}
          {/* 完成态 UI 系防御性双保险：父级正常调度下 onComplete 后立即卸载本条（瞬时即逝），
             独立单测/解耦场景下仍能正确呈现终态 */}
          {status === "completed" && (
            <span className="text-[10px] font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 rounded shrink-0">
              完成
            </span>
          )}
        </div>
        <p className={`text-xs truncate mt-0.5 ${status === "error" ? "text-rose-600" : "text-slate-500"}`}>
          {status === "error" ? errorMessage : latestMessage}
        </p>
      </div>

      {/* 终局后状态条由父级卸载；收起仅对运行中有意义，避免「完成后收起被误报后台执行」 */}
      {!isTerminal && (
        <button
          onClick={onDismiss}
          title="收起（任务仍在后台执行，完成后产物写入飞书）"
          className="shrink-0 rounded-md p-1 text-slate-400 hover:text-slate-600 hover:bg-black/5 transition-colors"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  )
}
