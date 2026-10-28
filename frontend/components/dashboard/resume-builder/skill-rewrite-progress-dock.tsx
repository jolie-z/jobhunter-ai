"use client"

import { useEffect, useMemo, useRef } from "react"
import { AlertTriangle, CheckCircle2, Circle, Loader2, Sparkles, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { useOptionalStrategyStore } from "@/hooks/use-strategy-store"
import {
  useSkillAgentStream,
  type AgentLogItem,
  type ResultKind,
  type RewriteEngine,
  type SkillAgentCompletePayload,
} from "@/hooks/use-skill-agent-stream"

/**
 * 简历改写进度坞（右下角浮动、非阻塞）
 *
 * 两种引擎两套轨道：
 * - official：官方单文件剧本（7 步，含 Truth Boundary 安全阀）；
 * - agent：多文件技能包 Tool-Use 智能体（6 步，产物逐份落盘）。
 *
 * 引擎以 init/agent_start 事件下发的 engine 为准（最后一次为准），不再用
 * `isSkillPack(skillId)` 在前端猜——单文件自定义技能和 runner 异常都走官方引擎。
 *
 * 轨道点亮只认结构化字段（type / step / tool / stage / engine），不做文案匹配；
 * 每个阶段只由自己的事件点亮，禁止「后续阶段出现即默认前面全过」的推断。
 *
 * 挂载契约：父级必须以 `key={taskId}` 挂载，使每次任务全新实例化——SSE 流状态与
 * 「错误只上报一次」的 ref 守卫都随任务重置；常驻复用会把上一次任务的终态带进下一次。
 */

export interface RewriteStage {
  key: string
  label: string
}

export const OFFICIAL_STAGES: readonly RewriteStage[] = [
  { key: "prepare", label: "读取底稿与岗位画像" },
  { key: "load_skill", label: "装载官方剧本" },
  { key: "rewrite", label: "大模型定制改写" },
  { key: "extract", label: "萃取定稿 · 安全阀校验" },
  { key: "parse", label: "解析为结构化简历" },
  { key: "archive", label: "归档改写产物" },
  { key: "write_back", label: "写回简历库" },
] as const

export const AGENT_STAGES: readonly RewriteStage[] = [
  { key: "prepare", label: "读取底稿与岗位画像" },
  { key: "load_skill", label: "装载技能包" },
  { key: "agent_turn", label: "智能体多轮推演" },
  { key: "parse", label: "解析为结构化简历" },
  { key: "archive", label: "归档改写产物" },
  { key: "write_back", label: "写回简历库" },
] as const

/** 非简历通用 skill：没有简历解析/写回阶段，产物归档即交付 */
export const GENERIC_AGENT_STAGES: readonly RewriteStage[] = [
  { key: "prepare", label: "读取底稿与岗位信息" },
  { key: "load_skill", label: "装载技能包" },
  { key: "agent_turn", label: "智能体多轮推演" },
  { key: "archive", label: "归档交付产物" },
] as const

/** 兼容旧导入：默认官方轨道 */
export const REWRITE_STAGES = OFFICIAL_STAGES

export function stagesForEngine(
  engine: RewriteEngine,
  resultKind: ResultKind = "resume",
): readonly RewriteStage[] {
  if (engine !== "agent") return OFFICIAL_STAGES
  return resultKind === "resume" ? AGENT_STAGES : GENERIC_AGENT_STAGES
}

/** 最后一条带 engine 的日志（init/agent_start）——以日志为准，避免 React 状态晚一拍 */
export function latestEngineFromLogs(logs: AgentLogItem[]): RewriteEngine | undefined {
  for (let i = logs.length - 1; i >= 0; i--) {
    const value = logs[i].engine
    if (value === "agent" || value === "official") return value
  }
  return undefined
}

/** 最后一条带 resultKind 的日志（init/agent_done） */
export function latestResultKindFromLogs(logs: AgentLogItem[]): ResultKind | undefined {
  for (let i = logs.length - 1; i >= 0; i--) {
    const value = logs[i].resultKind
    if (value === "resume" || value === "markdown" || value === "json") return value
  }
  return undefined
}

/** 官方轨道单条日志能推进到的下标；-1 = 不推进 */
export function stageIndexOfLog(log: AgentLogItem): number {
  switch (log.type) {
    case "init":
    case "system":
    case "agent_start":
      return 0
    case "thinking":
      if (log.stage === "prepare") return 0
      if (log.stage === "parse") return 4
      return -1
    case "step_start":
      if (log.step === 1) return 1
      if (typeof log.step === "number" && log.step >= 2) return 2
      return -1
    case "tool_call":
      if (log.tool === "truth_boundary_check") return 3
      if (log.tool === "feishu_write") return 6
      return -1
    case "artifact_saved":
      // 逐文件产物（agent_artifact）不越级点亮归档；只认归档汇总
      if (log.stage === "agent_artifact") return -1
      if (log.stage === "archive" || !log.file) return 5
      return -1
    case "complete":
      return OFFICIAL_STAGES.length
    default:
      return -1
  }
}

/** 官方轨道：只前进不后退取最大下标（保留旧导出，供既有测试/行内条使用） */
export function deriveRewriteStage(logs: AgentLogItem[]): number {
  let idx = 0
  for (const log of logs) idx = Math.max(idx, stageIndexOfLog(log))
  return idx
}

export interface RewriteProgress {
  stage: number
  completed: Set<number>
}

/**
 * 按引擎推导「当前阶段 + 已完成集合」。
 *
 * 关键差异：
 * - agent 的 agent_start 表示底稿与技能包已经装载完成 → 前两步直接完成；
 * - 逐文件 artifact_saved 只更新计数，不推进轨道；
 * - 只有 router 的归档汇总（stage=archive）才点亮归档；
 * - 每个阶段只由自己的事件点亮，不用 max 下标把中间阶段默认标绿。
 */
export function deriveRewriteProgress(
  logs: AgentLogItem[],
  engine: RewriteEngine,
  resultKind: ResultKind = "resume",
): RewriteProgress {
  const stages = stagesForEngine(engine, resultKind)
  const stageCount = stages.length
  let stage = 0
  let archiveDone = false
  const completed = new Set<number>()

  for (const log of logs) {
    if (engine === "agent" && resultKind !== "resume") {
      // 通用 skill：prepare → load → agent_turn → archive
      if ((log.type === "init" || log.type === "agent_start") && (log.engine ?? "agent") !== "official") {
        completed.add(0)
        completed.add(1)
        stage = Math.max(stage, 2)
      } else if (log.type === "step_start") {
        stage = Math.max(stage, 2)
      } else if (log.type === "artifact_saved" && log.stage === "archive") {
        completed.add(0)
        completed.add(1)
        completed.add(2)
        stage = 3
      } else if (log.type === "complete") {
        for (let i = 0; i < stageCount; i++) completed.add(i)
        stage = stageCount
      }
    } else if (engine === "agent") {
      if ((log.type === "init" || log.type === "agent_start") && (log.engine ?? "agent") !== "official") {
        // agent_start 发出时 facade 已装载底稿与技能包
        completed.add(0)
        completed.add(1)
        stage = Math.max(stage, 2)
      } else if (log.type === "step_start") {
        stage = Math.max(stage, 2)
      } else if (log.type === "thinking" && log.stage === "parse") {
        completed.add(0)
        completed.add(1)
        completed.add(2)
        stage = 3
      } else if (log.type === "artifact_saved" && log.stage === "archive") {
        archiveDone = true
        completed.add(0)
        completed.add(1)
        completed.add(2)
        completed.add(3)
        stage = 4
      } else if (log.type === "tool_call" && log.tool === "feishu_write") {
        // 归档阶段只由 artifact_saved(stage=archive) 点亮：归档失败时不得显示绿勾
        if (archiveDone) completed.add(4)
        stage = 5
      } else if (log.type === "complete") {
        for (let i = 0; i < stageCount; i++) completed.add(i)
        stage = stageCount
      }
    } else {
      switch (log.type) {
        case "init":
        case "system":
        case "agent_start":
          stage = Math.max(stage, 0)
          break
        case "thinking":
          if (log.stage === "prepare") stage = Math.max(stage, 0)
          if (log.stage === "parse") {
            completed.add(0)
            completed.add(1)
            completed.add(2)
            completed.add(3)
            stage = 4
          }
          break
        case "step_start":
          if (log.step === 1) {
            completed.add(0)
            stage = Math.max(stage, 1)
          } else if (typeof log.step === "number" && log.step >= 2) {
            completed.add(0)
            completed.add(1)
            stage = Math.max(stage, 2)
          }
          break
        case "tool_call":
          if (log.tool === "truth_boundary_check") {
            completed.add(0)
            completed.add(1)
            completed.add(2)
            stage = 3
          } else if (log.tool === "feishu_write") {
            // 归档阶段只由 artifact_saved(stage=archive) 点亮
            if (archiveDone) completed.add(5)
            stage = 6
          }
          break
        case "artifact_saved":
          if (log.stage === "agent_artifact") break
          if (log.stage === "archive" || !log.file) {
            archiveDone = true
            completed.add(0)
            completed.add(1)
            completed.add(2)
            completed.add(3)
            completed.add(4)
            stage = 5
          }
          break
        case "complete":
          for (let i = 0; i < stageCount; i++) completed.add(i)
          stage = stageCount
          break
      }
    }
  }

  return { stage: Math.min(stage, stageCount), completed }
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

const AUTO_DISMISS_MS = 4000

interface SkillRewriteProgressDockProps {
  taskId: string | null
  /** 非官方剧本（多文件技能包）时显示技能名，提示用户产物在作战产物库 */
  skillLabel?: string
  onComplete: (data: SkillAgentCompletePayload) => void
  onError: (message: string) => void
  onDismiss: () => void
}

export function SkillRewriteProgressDock({ taskId, skillLabel, onComplete, onError, onDismiss }: SkillRewriteProgressDockProps) {
  const { logs, artifacts, status, errorMessage, elapsedSeconds, engine, resultKind, completion } = useSkillAgentStream({
    taskId,
    active: Boolean(taskId),
    onComplete,
  })
  // 与同页「简历解析进度卡」共用右下角槽位：解析卡在场（上传解析中/解析失败未关）时上移让位，
  // 两张 fixed 卡片不得重叠遮挡。Optional 取 store：Provider 外挂载（如单测）不抛错
  const strategy = useOptionalStrategyStore()
  const parseCardVisible = Boolean(strategy?.isParsing || strategy?.parseError)

  const effectiveEngine = useMemo(
    () => latestEngineFromLogs(logs) || engine,
    [logs, engine],
  )
  const effectiveResultKind = useMemo(
    () => latestResultKindFromLogs(logs) || resultKind,
    [logs, resultKind],
  )
  const stages = useMemo(
    () => stagesForEngine(effectiveEngine, effectiveResultKind),
    [effectiveEngine, effectiveResultKind],
  )
  const { stage: stageIdx, completed } = useMemo(
    () => deriveRewriteProgress(logs, effectiveEngine, effectiveResultKind),
    [logs, effectiveEngine, effectiveResultKind],
  )
  const latestMessage = useMemo(() => {
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].type !== "system") return logs[i].message
    }
    return "正在建立实时推演通道…"
  }, [logs])

  // 错误只向上报一次（status 不会从 error 回退，ref 防重复 toast）
  const errorReportedRef = useRef(false)
  useEffect(() => {
    if (status === "error" && !errorReportedRef.current) {
      errorReportedRef.current = true
      onError(errorMessage || "改写过程中出现异常")
    }
  }, [status, errorMessage, onError])

  // 完成态短暂停留后自动收起；失败态留给用户阅读原因，手动关闭
  useEffect(() => {
    if (status !== "completed") return
    const timer = setTimeout(onDismiss, AUTO_DISMISS_MS)
    return () => clearTimeout(timer)
  }, [status, onDismiss])

  if (!taskId) return null

  const isRunning = status === "connecting" || status === "running"
  const isDone = status === "completed"
  const isError = status === "error"
  const isPartial = isDone && Boolean(completion?.partial)
  const artifactCount = completion?.artifactCount ?? artifacts.length
  const expectedCount = completion?.expectedArtifactCount ?? 0
  const partialCountLabel = expectedCount > 0
    ? `${artifactCount}/${expectedCount}`
    : `${artifactCount} 份`

  const title = isDone
    ? isPartial
      ? (effectiveResultKind === "resume"
        ? `改写完成 · 部分产物 ${partialCountLabel}`
        : `技能部分完成 · ${partialCountLabel}`)
      : effectiveResultKind !== "resume"
        ? "技能执行完成，产物已归档"
        : effectiveEngine === "agent"
          ? "改写完成，已写回简历库"
          : "改写完成，已写回底稿"
    : isError
      ? (effectiveResultKind === "resume" ? "改写未完成" : "技能执行未完成")
      : effectiveResultKind !== "resume"
        ? "技能执行进行中"
        : effectiveEngine === "agent"
          ? "技能包改写进行中"
          : "官方剧本改写进行中"

  const titleClass = isError
    ? "text-rose-700 dark:text-rose-300"
    : isPartial
      ? "text-amber-700 dark:text-amber-300"
      : isDone
        ? "text-emerald-700 dark:text-emerald-300"
        : "text-slate-900 dark:text-zinc-100"

  return (
    <div
      className={cn(
        "fixed right-6 z-50 w-[360px] rounded-2xl border bg-white p-4 shadow-xl",
        parseCardVisible ? "bottom-[17rem]" : "bottom-6",
        "dark:bg-zinc-900 animate-in fade-in slide-in-from-bottom-4",
        isError
          ? "border-rose-200 dark:border-rose-900/60"
          : isPartial
            ? "border-amber-200 dark:border-amber-900/60"
            : isDone
              ? "border-emerald-200 dark:border-emerald-900/60"
              : "border-slate-200 dark:border-zinc-800",
      )}
    >
      {/* 头部：状态 + 计时 + 关闭（仅终态可关，运行中关闭会丢完成回调）。
          aria-live 收窄到标题节点：计时器每秒跳字、日志区随 SSE 高频变化，
          若纳入 live region 读屏器会被反复播报 */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isRunning && <Loader2 className="size-4 shrink-0 animate-spin text-indigo-500" />}
          {isPartial && <AlertTriangle className="size-4 shrink-0 text-amber-500" />}
          {isDone && !isPartial && <CheckCircle2 className="size-4 shrink-0 text-emerald-500" />}
          {isError && <AlertTriangle className="size-4 shrink-0 text-rose-500" />}
          <div className="min-w-0">
            <div
              role="status"
              aria-live="polite"
              className={cn("text-sm font-semibold leading-tight", titleClass)}
            >
              {title}
            </div>
            {skillLabel && (
              <div className="text-[11px] text-slate-500 dark:text-zinc-400 truncate">{skillLabel}</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-mono text-[11px] text-slate-500 dark:text-zinc-400">{formatElapsed(elapsedSeconds)}</span>
          {!isRunning && (
            <button
              onClick={onDismiss}
              className="rounded p-0.5 text-slate-400 hover:text-slate-700 dark:hover:text-zinc-200"
              aria-label="关闭进度面板"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* 阶段轨道 */}
      <ol className="mt-3 space-y-1.5">
        {stages.map((stage, i) => {
          const done = isDone || completed.has(i)
          const current = !isDone && !isError && !done && i === stageIdx
          const frozen = isError && !done && i === stageIdx
          return (
            <li key={stage.key} className="flex items-center gap-2 text-xs">
              {done ? (
                <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" />
              ) : current ? (
                <Loader2 className="size-3.5 shrink-0 animate-spin text-indigo-500" />
              ) : frozen ? (
                <AlertTriangle className="size-3.5 shrink-0 text-rose-500" />
              ) : (
                <Circle className="size-3.5 shrink-0 text-slate-300 dark:text-zinc-600" />
              )}
              <span
                className={cn(
                  done && "text-slate-500 dark:text-zinc-400",
                  current && "font-medium text-slate-900 dark:text-zinc-100",
                  frozen && "font-medium text-rose-700 dark:text-rose-300",
                  !done && !current && !frozen && "text-slate-400 dark:text-zinc-500",
                )}
              >
                {stage.label}
                {effectiveEngine === "agent" && stage.key === "agent_turn" && artifactCount > 0 && (
                  <span className="ml-1 text-[10px] text-indigo-500">已归档 {artifactCount} 份</span>
                )}
              </span>
            </li>
          )
        })}
      </ol>

      {/* 尾部：最新一条推演日志 / 失败原因（含写回保底闸的拦截说明） */}
      <div
        className={cn(
          "mt-3 rounded-lg px-2.5 py-2 text-[11px] leading-relaxed",
          isError
            ? "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
            : isPartial
              ? "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
              : "bg-slate-50 text-slate-600 dark:bg-zinc-800/60 dark:text-zinc-300",
        )}
      >
        {isError ? (
          <span className="break-words">{errorMessage || "改写过程中出现异常"}</span>
        ) : (
          <span className="flex items-start gap-1.5">
            <Sparkles className="mt-0.5 size-3 shrink-0 text-indigo-400" />
            <span className="line-clamp-2 break-words">{latestMessage}</span>
          </span>
        )}
      </div>
    </div>
  )
}
