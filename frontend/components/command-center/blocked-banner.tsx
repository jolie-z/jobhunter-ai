"use client"

/**
 * 全局 LLM 阻塞横幅
 * =========================================================================
 * LLM 网关异常导致链路暂停时显著告知：出了什么错（类别 + 模型 + 上游提示）、
 * 该怎么修（按类别给出可操作建议），并提供「检测恢复 / 继续任务 / 终止任务」。
 *
 * 数据来源三路合一（store 内 blockedDetail）：
 * - SSE stage(status=blocked) / end(summary.outcome=blocked) 实时事件
 * - dashboard-sync 12 秒轮询的 stage_snapshot.blocked（页面刷新恢复）
 */

import { useState } from "react"
import { PauseCircle, Stethoscope, Play, Square, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { usePipelineStore } from "@/store/pipeline-store"
import { resumeBlockedTask, terminateBlockedTask } from "@/store/blocked-task-actions"
import { API_BASE } from "@/lib/api"

// 错误类别 → 人话标签 + 可操作修复建议（与后端 llm_errors 分类同源）
const KIND_META: Record<string, { label: string; advice: string }> = {
  rate_limited: {
    label: "上游频控（429）",
    advice: "上游频控：更换模型或等待额度重置后点「检测恢复」",
  },
  quota: {
    label: "额度不足",
    advice: "模型账户余额不足：充值或更换模型后点「检测恢复」",
  },
  auth: {
    label: "鉴权失败",
    advice: "API Key 无效：检查 LLM 配置页的 API Key 后点「检测恢复」",
  },
  timeout: {
    label: "连接超时",
    advice: "LLM 网关连接超时：检查网络与 OPENAI_BASE_URL 后点「检测恢复」",
  },
  connection: {
    label: "网络不可达",
    advice: "无法连接 LLM 网关：确认网关进程存活与 OPENAI_BASE_URL 配置",
  },
  server: {
    label: "LLM 网关异常（5xx）",
    advice: "上游服务异常（5xx）：请检查模型服务商状态、网关账号/余额或切换模型后点「检测恢复」",
  },
  bad_request: {
    label: "请求被上游拒绝",
    advice: "请求被上游拒绝：检查模型名是否有效或更换模型",
  },
  unknown: {
    label: "模型输出异常",
    advice: "模型返回内容异常：更换模型或稍后点「检测恢复」",
  },
}

function kindMeta(kind?: string) {
  return KIND_META[kind || "unknown"] || KIND_META.unknown
}

export function BlockedBanner() {
  const status = usePipelineStore((s) => s.status)
  const blockedDetail = usePipelineStore((s) => s.blockedDetail)

  const [probing, setProbing] = useState(false)
  const [healthOk, setHealthOk] = useState<boolean | null>(null)
  const [resuming, setResuming] = useState(false)
  // 探测结论只对「本次阻塞」有效：组件常驻挂载（仅条件渲染隐藏），新一轮阻塞/
  // 继续任务/终止都必须重置，否则旧「✅ 检测通过」会与新故障同屏误报（外审 R2-P1）。
  // 用 render 期调整状态模式（React 推荐）而非 effect，避免级联渲染
  const [lastDetail, setLastDetail] = useState(blockedDetail)
  if (blockedDetail !== lastDetail) {
    setLastDetail(blockedDetail)
    setHealthOk(null)
  }

  if (!blockedDetail) return null

  const meta = kindMeta(blockedDetail.kind)
  // 阻塞已收口（status=blocked）展示完整横幅；继续任务进行中（status=running）转进行时态
  const resumingNow = status === "running"

  // 检测恢复：调后端 LLM 体检端点，探测通过后引导一键继续
  const handleProbe = async () => {
    if (probing) return
    setProbing(true)
    try {
      const res = await fetch(`${API_BASE}/api/automation/llm-health`)
      const data = await res.json()
      const health = data?.data
      if (res.ok && health?.ok) {
        setHealthOk(true)
        toast.success(`LLM 网关已恢复（${health.latency_ms ?? "?"}ms），可点击「继续任务」重洗遗留岗位`)
      } else {
        setHealthOk(false)
        const h = health || {}
        toast.error(`LLM 仍不可用（${kindMeta(h.error_kind).label}）：${h.message || "未知错误"}`)
      }
    } catch {
      setHealthOk(false)
      toast.error("检测失败：无法连接后端服务")
    } finally {
      setProbing(false)
    }
  }

  // 继续任务：重跑遗留待AI初筛岗位的 AI 排雷，链路继续向下走
  // （与顶栏入口共用同一实现 blocked-task-actions——含刷新恢复场景的 pipelineTaskId 补建）
  const handleResume = async () => {
    if (resuming) return
    setResuming(true)
    setHealthOk(null)
    try {
      await resumeBlockedTask()
    } finally {
      setResuming(false)
    }
  }

  // 终止任务：阻塞任务已收尾（无运行中协程），此处为放弃继续这条链路的显式出口
  const handleTerminate = () => {
    if (!window.confirm(
      "确定终止并关闭该阻塞任务？\n剩余「待AI初筛」岗位将保留在清洗池，可稍后在清洗面板手动重跑 AI 排雷。"
    )) return
    // 与顶栏入口共用同一实现（blocked-task-actions）：先清后端阻塞登记（只清前端
    // store 的话，刷新后 dashboard-sync 快照会把横幅凭空种回来，2026-11-03 事故
    // 伴生缺陷），再复位本地 store
    terminateBlockedTask()
    setHealthOk(null)
  }

  if (resumingNow) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.07] px-4 py-2.5 text-xs animate-in slide-in-from-top-1 duration-200">
        <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300">
          <RefreshCw className="h-4 w-4 shrink-0 animate-spin" />
          <span>
            <strong>继续任务进行中</strong> — 正在重洗遗留「待AI初筛」岗位并续推飞书链路，结束后自动汇报结果。
          </span>
        </div>
        <span className="shrink-0 text-[11px] text-muted-foreground">
          如需放弃可点右上角「终止任务」
        </span>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-amber-500/40 bg-amber-500/[0.06] p-4 text-xs animate-in slide-in-from-top-1 duration-200">
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-2.5">
          <PauseCircle className="h-5 w-5 shrink-0 text-amber-500 mt-0.5" />
          <div className="flex-1 min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-amber-700 dark:text-amber-300 text-sm">
                链路已暂停 · LLM 异常
              </span>
              <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-300">
                {meta.label}
              </span>
              {blockedDetail.model && (
                <span className="rounded-md bg-muted/60 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  模型: {blockedDetail.model}
                </span>
              )}
              {typeof blockedDetail.failed_count === "number" && blockedDetail.failed_count > 0 && (
                <span className="text-[10px] text-muted-foreground">
                  累计失败 {blockedDetail.failed_count} 次{blockedDetail.first_seen ? ` · 自 ${blockedDetail.first_seen}` : ""}
                </span>
              )}
            </div>
            {blockedDetail.message && (
              <p className="text-foreground/80 leading-relaxed">{blockedDetail.message}</p>
            )}
            {blockedDetail.gateway_hint && (
              <p className="truncate text-muted-foreground font-mono text-[10px]" title={blockedDetail.gateway_hint}>
                上游提示: {blockedDetail.gateway_hint}
              </p>
            )}
            <p className="text-amber-700 dark:text-amber-300 leading-relaxed">
              修复建议：{meta.advice}
            </p>
            {healthOk === true && (
              <p className="text-emerald-600 dark:text-emerald-400 font-medium">
                ✅ 检测通过：LLM 网关已恢复，点「继续任务」继续本条链路
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pl-7.5">
          <button
            onClick={handleResume}
            disabled={resuming}
            className="flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm transition-all hover:bg-amber-500 active:scale-95 disabled:opacity-50"
            title="重新评估遗留的待AI初筛岗位，并继续飞书推送等后续链路"
          >
            <Play className="h-3 w-3 fill-current" />
            {resuming ? "启动中…" : "继续任务"}
          </button>
          <button
            onClick={handleProbe}
            disabled={probing}
            className="flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[11px] font-medium text-amber-700 transition-all hover:bg-amber-500/20 active:scale-95 disabled:opacity-50 dark:text-amber-300"
            title="用当前 LLM 配置向网关发一次最小请求，检测是否已恢复"
          >
            <Stethoscope className="h-3 w-3" />
            {probing ? "检测中…" : "检测恢复"}
          </button>
          <button
            onClick={handleTerminate}
            className="flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-[11px] font-medium text-red-600 transition-all hover:bg-red-500/20 active:scale-95"
            title="放弃继续这条链路（遗留岗位保留在清洗池）"
          >
            <Square className="h-3 w-3 fill-current" />
            终止任务
          </button>
        </div>
      </div>
    </div>
  )
}
