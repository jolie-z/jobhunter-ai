"use client"

import { useState, useEffect, useRef } from "react"
import { API_BASE } from "@/lib/api"

/**
 * Skill Agent 异步推演任务的 SSE 实时流订阅 hook。
 *
 * 看板弹窗（多文件技能包的多轮 Agent 推演）与行内状态条（官方剧本/单文件技能的
 * 单轮引擎推演）共用：事件分发、状态机、计时器全部收敛在这一处，两种呈现只是
 * 消费同一份流状态的不同皮肤。
 */

export interface AgentLogItem {
  id: string
  timestamp: string
  type: string
  message: string
  detail?: string
  tool?: string
  file?: string
  size?: number
  /** 引擎类型（init/agent_start 由后端下发，进度坞据此切换轨道） */
  engine?: RewriteEngine
  /** 结果类型：简历 / 通用 markdown / JSON（init/agent_done 下发） */
  resultKind?: ResultKind
  /** 引擎 step_start 的阶段号（官方剧本：1=装载剧本，2=大模型推演） */
  step?: number
  /** worker 结构化阶段标记（prepare / parse / truncate / archive）：进度坞按此点亮步骤，不依赖文案匹配 */
  stage?: string
}

/** 后端执行引擎：官方单轮剧本 / 多文件技能包 Tool-Use 智能体 */
export type RewriteEngine = "official" | "agent"

/** 产物类型：简历 JSON 写回 / 通用 Markdown / JSON 结构化产物 */
export type ResultKind = "resume" | "markdown" | "json"

export interface SavedArtifactChip {
  name: string
  title: string
  size: number
  is_final_resume?: boolean
}

export type SkillAgentStatus = "connecting" | "running" | "completed" | "error"

/** Token 消耗累计（runner 逐轮/单轮路径完成后上抛） */
export interface AgentUsageTotals {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens?: number
}

/** 推演完成时后端上抛的业务载荷（铺画布/写回岗位共用） */
export interface SkillAgentCompletePayload {
  parsed_json: any
  markdown: string
  usage: any
  /** 06 主稿有效但其余产物未跑完：按部分成功写回，前端用警告态而非成功态 */
  partial?: boolean
  artifact_count?: number
  expected_artifact_count?: number
  engine?: RewriteEngine
  result_kind?: ResultKind
  has_resume_output?: boolean
  final_artifact?: string
  archive_error?: string
  /** 权威落库回执（worker 写飞书成功后携带）：前端据此同步岗位跟进状态与脏检测基线 */
  persisted?: { ai_rewrite_json?: boolean; follow_status?: string | null }
}

export interface SkillAgentCompletionMeta {
  partial: boolean
  artifactCount: number
  expectedArtifactCount: number
}

export interface SkillAgentStreamState {
  logs: AgentLogItem[]
  artifacts: SavedArtifactChip[]
  status: SkillAgentStatus
  errorMessage: string
  currentStep: number
  maxTurns: number
  elapsedSeconds: number
  usage: AgentUsageTotals | null
  /** 当前引擎（init/agent_start 最后一次下发为准） */
  engine: RewriteEngine
  /** 当前结果类型（init/agent_done/complete 最后一次下发为准） */
  resultKind: ResultKind
  /** 终局部分成功元数据；null = 未完成或完整成功 */
  completion: SkillAgentCompletionMeta | null
}

export interface UseSkillAgentStreamOptions {
  taskId: string | null
  /** false 时断开并不再重连（看板关闭/行内条卸载即停订，任务在服务端继续执行） */
  active: boolean
  onComplete?: (data: SkillAgentCompletePayload) => void
}

/** 事件里的 engine 只接受白名单值，避免脏数据把进度坞切到未知轨道 */
function asRewriteEngine(value: unknown): RewriteEngine | undefined {
  return value === "agent" || value === "official" ? value : undefined
}

function asResultKind(value: unknown): ResultKind | undefined {
  return value === "resume" || value === "markdown" || value === "json" ? value : undefined
}

export function useSkillAgentStream({ taskId, active, onComplete }: UseSkillAgentStreamOptions): SkillAgentStreamState {
  const [logs, setLogs] = useState<AgentLogItem[]>([])
  const [artifacts, setArtifacts] = useState<SavedArtifactChip[]>([])
  const [status, setStatus] = useState<SkillAgentStatus>("connecting")
  const [errorMessage, setErrorMessage] = useState<string>("")
  const [currentStep, setCurrentStep] = useState<number>(1)
  const [maxTurns, setMaxTurns] = useState<number>(8)
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0)
  const [usage, setUsage] = useState<AgentUsageTotals | null>(null)
  const [engine, setEngine] = useState<RewriteEngine>("official")
  const [resultKind, setResultKind] = useState<ResultKind>("resume")
  const [completion, setCompletion] = useState<SkillAgentCompletionMeta | null>(null)

  const eventSourceRef = useRef<EventSource | null>(null)
  const timerRef = useRef<NodeJS.Timeout | null>(null)
  // onCompleteRef 承接回调（2026-10-11 真机排查实锤的 stale closure）：SSE effect 依赖
  // 只有 [active, taskId]，effect 内闭包捕获的是建连首帧的 onComplete——后续渲染传入的
  // 新回调（携带最新 job/onUpdateJob）永远不进 complete 分支，落库同步链路整体失效。
  const onCompleteRef = useRef(onComplete)
  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])
  // onerror 闭包陷阱：effect 只在 active/taskId 变化时重建，直接读 status 恒为建连时的
  // 旧值（"connecting"）——完成后再断流会被误判成异常。终局事件在 onmessage 内同步置位，
  // 不等 React 重渲染，杜绝断流竞态。
  const statusRef = useRef<SkillAgentStatus>("connecting")

  // 1. 计时器：仅在任务存在且未到终局时走秒；清零只在 SSE effect（任务启动）里做一次，
  //    connecting→running 的状态迁移不重置（否则建连阶段耗时刻被抹掉）
  useEffect(() => {
    if (active && (status === "connecting" || status === "running")) {
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
  }, [active, status])

  // 2. 建立 SSE 连接
  useEffect(() => {
    if (!active || !taskId) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      return
    }

    setLogs([])
    setArtifacts([])
    statusRef.current = "connecting"
    setStatus("connecting")
    setErrorMessage("")
    setCurrentStep(1)
    setElapsedSeconds(0)
    setUsage(null)
    setEngine("official")
    setResultKind("resume")
    setCompletion(null)

    const sseUrl = `${API_BASE}/api/strategy/skill_agent_logs?task_id=${taskId}`
    console.log("📡 [SSE] 连接 Skill Agent 日志流:", sseUrl)
    const es = new EventSource(sseUrl)
    eventSourceRef.current = es

    const addLog = (
      type: string,
      message: string,
      detail?: string,
      extra?: Pick<AgentLogItem, "tool" | "step" | "stage" | "engine" | "file" | "resultKind">,
    ) => {
      const now = new Date()
      const timeStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`
      setLogs((prev) => [
        ...prev,
        {
          id: Math.random().toString(36).substring(7),
          timestamp: timeStr,
          type,
          message,
          detail,
          ...extra,
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

        if (data.type === "init") {
          const eventEngine = asRewriteEngine(data.engine)
          if (eventEngine) setEngine(eventEngine)
          const eventResultKind = asResultKind(data.result_kind)
          if (eventResultKind) setResultKind(eventResultKind)
          addLog(
            "system",
            data.message || "🚀 任务已创建，正在初始化推演环境…",
            undefined,
            { engine: eventEngine, resultKind: eventResultKind },
          )
        } else if (data.type === "agent_start") {
          setStatus("running")
          const eventEngine = asRewriteEngine(data.engine)
          if (eventEngine) setEngine(eventEngine)
          addLog(
            "agent_start",
            data.message || "智能体启动",
            undefined,
            eventEngine ? { engine: eventEngine } : undefined,
          )
        } else if (data.type === "step_start") {
          setCurrentStep(data.step || 1)
          if (data.max_turns) setMaxTurns(data.max_turns)
          const eventEngine = asRewriteEngine(data.engine)
          if (eventEngine) setEngine(eventEngine)
          const eventResultKind = asResultKind(data.result_kind)
          if (eventResultKind) setResultKind(eventResultKind)
          addLog(
            "step_start",
            data.message || `正在执行第 ${data.step} 阶段推演`,
            undefined,
            {
              step: Number(data.step) || undefined,
              engine: eventEngine,
              resultKind: eventResultKind,
            },
          )
        } else if (data.type === "thinking") {
          addLog("thinking", data.message || "🧠 深度思考中...", undefined, { stage: data.stage || undefined })
        } else if (data.type === "tool_call") {
          addLog("tool_call", data.message || `调用工具: ${data.tool}`, undefined, { tool: data.tool || undefined })
        } else if (data.type === "artifact_saved") {
          const eventResultKind = asResultKind(data.result_kind)
          if (eventResultKind) setResultKind(eventResultKind)
          addLog(
            "artifact_saved",
            data.message || `产物已落盘: ${data.filename}`,
            undefined,
            { stage: data.stage, file: data.filename, resultKind: eventResultKind },
          )
          // 逐文件事件（runner 路径带 filename）才进托盘；worker 的归档汇总事件无 filename，只记日志
          if (data.filename) {
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
          }
        } else if (data.type === "usage") {
          setUsage({
            prompt_tokens: Number(data.prompt_tokens) || 0,
            completion_tokens: Number(data.completion_tokens) || 0,
            total_tokens: Number(data.total_tokens) || 0,
            cached_tokens: Number(data.cached_tokens) || 0,
          })
        } else if (data.type === "agent_error") {
          // runner 内部单步异常（可能回退续跑）：只记日志不改全局状态，终局以 complete/error 为准
          addLog("error", `⚠️ ${data.message || data.error || "智能体内部出现可恢复异常"}`)
        } else if (data.type === "agent_done") {
          const eventResultKind = asResultKind(data.result_kind)
          if (eventResultKind) setResultKind(eventResultKind)
          addLog(
            "agent_done",
            data.message || "🎉 智能体推演定稿完毕！",
            undefined,
            { resultKind: eventResultKind },
          )
        } else if (data.type === "complete") {
          // ref 同步先行：服务器发 complete 后立即关流时，onerror 可能在 React 重渲染前触发
          statusRef.current = "completed"
          setStatus("completed")
          const payload = data.data || {}
          const completeEngine = asRewriteEngine(payload.engine) || asRewriteEngine(data.engine)
          if (completeEngine) setEngine(completeEngine)
          const completeResultKind = asResultKind(payload.result_kind) || asResultKind(data.result_kind)
          if (completeResultKind) setResultKind(completeResultKind)
          setCompletion({
            partial: Boolean(payload.partial),
            artifactCount: Number(payload.artifact_count) || 0,
            expectedArtifactCount: Number(payload.expected_artifact_count) || 0,
          })
          // 个别引擎逐轮 usage 事件缺失时，用 complete 终值兜底
          if (data.usage && Number(data.usage.total_tokens)) {
            setUsage({
              prompt_tokens: Number(data.usage.prompt_tokens) || 0,
              completion_tokens: Number(data.usage.completion_tokens) || 0,
              total_tokens: Number(data.usage.total_tokens) || 0,
              cached_tokens: Number(data.usage.cached_tokens) || 0,
            })
          }
          addLog("complete", data.message || "✅ 全套改写数据与飞书字段落盘完成！")
          if (data.data && onCompleteRef.current) {
            onCompleteRef.current(data.data)
          }
        } else if (data.type === "error") {
          statusRef.current = "error"
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
      // completed/error 均为终局：静默关流。error 态若被断流文案覆盖，
      // 后端真实报错会被「任务仍在后台执行」的假死提示顶掉
      if (statusRef.current === "completed" || statusRef.current === "error") {
        es.close()
        eventSourceRef.current = null
        return
      }
      es.close()
      eventSourceRef.current = null
      statusRef.current = "error"
      setStatus("error")
      setErrorMessage("实时推演流连接中断，任务仍在后台执行，可关闭看板稍后查看产物")
      addLog("error", "❌ 实时推演流连接中断（任务仍在后台执行）")
    }

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [active, taskId])

  return {
    logs,
    artifacts,
    status,
    errorMessage,
    currentStep,
    maxTurns,
    elapsedSeconds,
    usage,
    engine,
    resultKind,
    completion,
  }
}

/** 秒 → mm:ss（看板计时与行内条共用） */
export function formatAgentElapsed(s: number): string {
  const mins = Math.floor(s / 60)
  const secs = s % 60
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
}
