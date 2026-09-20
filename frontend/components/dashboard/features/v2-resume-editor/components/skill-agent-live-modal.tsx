"use client"

import React, { useState, useEffect, useRef } from "react"
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { API_BASE } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { 
  Sparkles, 
  Loader2, 
  Layers, 
  CheckCircle2, 
  AlertCircle, 
  Terminal, 
  FileText, 
  FolderArchive,
  ArrowRight,
  Clock,
  ExternalLink,
  ShieldCheck,
  Cpu
} from "lucide-react"

export interface AgentLogItem {
  id: string
  timestamp: string
  type: string
  message: string
  detail?: string
  tool?: string
  file?: string
  size?: number
}

export interface SavedArtifactChip {
  name: string
  title: string
  size: number
  is_final_resume?: boolean
}

export interface SkillAgentLiveModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  taskId: string | null
  jobTitle?: string
  skillId?: string
  onComplete: (data: { parsed_json: any; markdown: string; usage: any }) => void
  onOpenStudio: () => void
}


export function SkillAgentLiveModal({
  open,
  onOpenChange,
  taskId,
  jobTitle,
  skillId,
  onComplete,
  onOpenStudio
}: SkillAgentLiveModalProps) {
  const [logs, setLogs] = useState<AgentLogItem[]>([])
  const [artifacts, setArtifacts] = useState<SavedArtifactChip[]>([])
  const [status, setStatus] = useState<"connecting" | "running" | "completed" | "error">("connecting")
  const [errorMessage, setErrorMessage] = useState<string>("")
  const [currentStep, setCurrentStep] = useState<number>(1)
  const [maxTurns, setMaxTurns] = useState<number>(8)
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0)
  
  const terminalEndRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const timerRef = useRef<NodeJS.Timeout | null>(null)

  // 1. 计时器
  useEffect(() => {
    if (open && (status === "connecting" || status === "running")) {
      setElapsedSeconds(0)
      timerRef.current = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1)
      }, 1000)
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [open, status])

  // 2. 建立 SSE 连接
  useEffect(() => {
    if (!open || !taskId) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      return
    }

    setLogs([])
    setArtifacts([])
    setStatus("connecting")
    setErrorMessage("")
    setCurrentStep(1)

    const sseUrl = `${API_BASE}/api/strategy/skill_agent_logs?task_id=${taskId}`
    console.log("📡 [SSE] 连接 Skill Agent 日志流:", sseUrl)
    const es = new EventSource(sseUrl)
    eventSourceRef.current = es

    const addLog = (type: string, message: string, detail?: string) => {
      const now = new Date()
      const timeStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`
      setLogs((prev) => [
        ...prev,
        {
          id: Math.random().toString(36).substring(7),
          timestamp: timeStr,
          type,
          message,
          detail
        }
      ])
    }

    es.onopen = () => {
      setStatus("running")
      addLog("system", "📡 成功建立 Agent 实时推演长连接通道")
    }

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === "close") {
          es.close()
          eventSourceRef.current = null
          return
        }

        if (data.type === "agent_start") {
          setStatus("running")
          addLog("agent_start", data.message || "智能体启动")
        } else if (data.type === "step_start") {
          setCurrentStep(data.step || 1)
          if (data.max_turns) setMaxTurns(data.max_turns)
          addLog("step_start", data.message || `正在执行第 ${data.step} 阶段推演`)
        } else if (data.type === "thinking") {
          addLog("thinking", data.message || "🧠 深度思考中...")
        } else if (data.type === "tool_call") {
          addLog("tool_call", data.message || `调用工具: ${data.tool}`)
        } else if (data.type === "artifact_saved") {
          addLog("artifact_saved", data.message || `产物已落盘: ${data.filename}`)
          setArtifacts((prev) => {
            if (prev.some((a) => a.name === data.filename)) return prev
            return [
              ...prev,
              {
                name: data.filename,
                title: data.title || data.filename,
                size: data.size || 0,
                is_final_resume: Boolean(data.is_final_resume)
              }
            ]
          })
        } else if (data.type === "agent_done") {
          addLog("agent_done", data.message || "🎉 智能体推演定稿完毕！")
        } else if (data.type === "complete") {
          setStatus("completed")
          addLog("complete", "✅ 全套改写数据与飞书字段落盘完成！")
          if (data.data) {
            onComplete(data.data)
          }
        } else if (data.type === "error") {
          setStatus("error")
          setErrorMessage(data.detail || data.message || "推演过程中出现异常")
          addLog("error", `❌ 错误: ${data.detail || data.message}`)
        }
      } catch (err) {
        console.error("SSE parse error:", err)
      }
    }

    es.onerror = (err) => {
      console.warn("SSE connection error or closed:", err)
      // 如果已经处于 completed 状态，直接关闭即可
      if (status !== "completed") {
        es.close()
        eventSourceRef.current = null
      }
    }

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [open, taskId])

  // 3. 自动滚动终端到底部
  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [logs])

  const formatSeconds = (s: number) => {
    const mins = Math.floor(s / 60)
    const secs = s % 60
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
  }

  const progressPercent = Math.min(
    100,
    status === "completed"
      ? 100
      : Math.round((currentStep / Math.max(maxTurns, 8)) * 85) + (artifacts.length * 2)
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!max-w-[860px] w-[92vw] h-[82vh] flex flex-col p-0 gap-0 overflow-hidden rounded-2xl border-slate-800 shadow-2xl bg-slate-950 text-slate-100 focus:outline-none sm:!max-w-[860px]">
        {/* 顶部 Header：极具极客质感的大模型推演控制台 */}
        <div className="px-6 py-4 border-b border-slate-800/80 bg-slate-900/90 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="size-9 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center text-amber-400 shadow-inner">
              <Cpu className="size-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <DialogTitle className="text-base font-bold text-slate-100 tracking-tight flex items-center gap-2">
                  Skill Agent 实时作战推演看板
                  {status === "running" && (
                    <span className="flex items-center gap-1.5 text-xs font-normal text-amber-400 bg-amber-950/60 border border-amber-500/30 px-2 py-0.5 rounded-full">
                      <span className="size-2 rounded-full bg-amber-400 animate-ping" />
                      推演中...
                    </span>
                  )}
                  {status === "completed" && (
                    <span className="flex items-center gap-1 text-xs font-normal text-emerald-400 bg-emerald-950/60 border border-emerald-500/30 px-2 py-0.5 rounded-full">
                      <CheckCircle2 className="size-3.5" />
                      推演定稿完成
                    </span>
                  )}
                </DialogTitle>
              </div>
              <DialogDescription className="text-xs text-slate-400 mt-0.5 flex items-center gap-2">
                <span>{jobTitle || "目标岗位"}</span>
                <span className="text-slate-600">•</span>
                <span className="text-amber-400/90 font-mono">{skillId || "自定义技能剧本"}</span>
              </DialogDescription>
            </div>
          </div>

          <div className="flex items-center gap-3 pr-6">
            <div className="flex items-center gap-1.5 text-xs font-mono text-slate-400 bg-slate-800/60 border border-slate-700/60 px-2.5 py-1 rounded-lg">
              <Clock className="size-3.5 text-amber-400" />
              <span>{formatSeconds(elapsedSeconds)}</span>
            </div>
          </div>
        </div>

        {/* 阶段进度条与核心状态概览 */}
        <div className="px-6 py-3 bg-slate-900/40 border-b border-slate-800/60 flex flex-col gap-2 shrink-0">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-200">推演阶段：</span>
              <span className="text-amber-300 font-mono">
                {status === "completed" ? "全部阶段已就绪 (100%)" : `Step ${currentStep} / ~${maxTurns}`}
              </span>
            </div>
            <div className="flex items-center gap-2 font-mono">
              <span>已生成产物: <b className="text-amber-400">{artifacts.length}</b> 篇</span>
              <span className="text-slate-600">|</span>
              <span>进度: <b className="text-emerald-400">{progressPercent}%</b></span>
            </div>
          </div>

          <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-amber-500 via-amber-400 to-emerald-400 transition-all duration-500 rounded-full shadow-sm"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {/* 实时终端日志区 (极客黑底代码流) */}
        <div className="flex-1 flex flex-col min-h-0 bg-slate-950 p-4 px-6 overflow-hidden">
          <div className="flex items-center justify-between pb-2 border-b border-slate-800/60 text-[11px] text-slate-500 font-mono shrink-0">
            <div className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full bg-rose-500/80 inline-block" />
              <span className="size-2.5 rounded-full bg-amber-500/80 inline-block" />
              <span className="size-2.5 rounded-full bg-emerald-500/80 inline-block" />
              <span className="ml-2 text-slate-400">skill-agent-runner ~ progressive-tool-calling</span>
            </div>
            <span>SSE Live Trace</span>
          </div>

          <div className="flex-1 overflow-y-auto font-mono text-xs leading-relaxed py-3 space-y-2 select-text">
            {logs.length === 0 ? (
              <div className="flex items-center gap-2 text-slate-500 py-4">
                <Loader2 className="size-4 animate-spin text-amber-500" />
                <span>正在建立与后台 Agent 执行引擎的流式通道...</span>
              </div>
            ) : (
              logs.map((log) => {
                let badgeClass = "text-slate-400"
                let prefix = "❯"
                if (log.type === "tool_call") {
                  badgeClass = "text-amber-400"
                  prefix = "🔧"
                } else if (log.type === "artifact_saved") {
                  badgeClass = "text-emerald-400 font-semibold"
                  prefix = "💾"
                } else if (log.type === "thinking") {
                  badgeClass = "text-indigo-300 italic"
                  prefix = "🧠"
                } else if (log.type === "step_start") {
                  badgeClass = "text-sky-400 font-semibold"
                  prefix = "🔄"
                } else if (log.type === "complete" || log.type === "agent_done") {
                  badgeClass = "text-emerald-300 font-bold"
                  prefix = "🎉"
                } else if (log.type === "error") {
                  badgeClass = "text-rose-400 font-bold"
                  prefix = "❌"
                }

                return (
                  <div key={log.id} className="flex items-start gap-2.5 hover:bg-slate-900/40 p-1 rounded transition-colors">
                    <span className="text-slate-600 shrink-0 select-none text-[11px] font-mono">[{log.timestamp}]</span>
                    <span className="shrink-0 select-none">{prefix}</span>
                    <span className={`${badgeClass} break-all leading-relaxed`}>{log.message}</span>
                  </div>
                )
              })
            )}
            {status === "running" && (
              <div className="flex items-center gap-2 pt-1">
                <span className="inline-block w-2 h-4 bg-amber-400 animate-pulse rounded-xs" />
                <span className="text-xs text-slate-500 font-mono">智能体深度推演中...</span>
              </div>
            )}
            <div ref={terminalEndRef} />
          </div>
        </div>

        {/* 实时落盘产物托盘 (Live Artifacts Tray) */}
        {artifacts.length > 0 && (
          <div className="px-6 py-3 bg-slate-900/70 border-t border-slate-800/80 flex items-center gap-2 overflow-x-auto shrink-0">
            <span className="text-xs text-slate-400 flex items-center gap-1 shrink-0 font-medium">
              <Layers className="size-3.5 text-amber-400" />
              已落盘 ({artifacts.length}):
            </span>
            <div className="flex items-center gap-1.5 overflow-x-auto">
              {artifacts.map((art) => (
                <Badge
                  key={art.name}
                  variant="outline"
                  className={`text-[11px] font-mono px-2 py-0.5 shrink-0 border ${
                    art.is_final_resume
                      ? "bg-amber-950/60 text-amber-300 border-amber-500/40 font-semibold"
                      : "bg-slate-800/80 text-slate-300 border-slate-700/60"
                  }`}
                >
                  <FileText className="size-3 mr-1 inline opacity-70" />
                  {art.name}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* 底部控制操作栏 */}
        <div className="px-6 py-3.5 bg-slate-900 border-t border-slate-800 flex items-center justify-between shrink-0">
          <div className="text-xs text-slate-400">
            {status === "running" ? (
              <span className="flex items-center gap-1.5">
                <Loader2 className="size-3.5 animate-spin text-amber-400" />
                推演进行中，关闭本窗口智能体仍将在后台持续执行
              </span>
            ) : status === "completed" ? (
              <span className="text-emerald-400 flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="size-4" />
                改写成功！全套作战产物与飞书 AI改写JSON 已全部落盘
              </span>
            ) : status === "error" ? (
              <span className="text-rose-400 flex items-center gap-1.5">
                <AlertCircle className="size-4" />
                {errorMessage || "改写推演出错，请重试"}
              </span>
            ) : (
              <span>准备就绪</span>
            )}
          </div>

          <div className="flex items-center gap-2.5">
            {status === "completed" ? (
              <Button
                size="sm"
                className="h-8 px-4 text-xs font-semibold bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 text-slate-950 shadow-md transition-all active:scale-[0.98]"
                onClick={() => {
                  onOpenChange(false)
                  onOpenStudio()
                }}
              >
                <FolderArchive className="size-3.5 mr-1.5" />
                进入 Artifacts Studio 浏览全套产物
                <ArrowRight className="size-3.5 ml-1" />
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs text-slate-300 border-slate-700 hover:bg-slate-800 hover:text-white bg-slate-850"
                onClick={() => onOpenChange(false)}
              >
                后台运行并关闭看板
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
