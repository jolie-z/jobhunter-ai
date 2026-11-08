"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  CornerDownRight,
  Eye,
  EyeOff,
  Key,
  Lightbulb,
  MapPin,
  MessageSquare,
  Mic,
  Power,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ServerOff,
  Settings2,
  Sparkles,
  Trash2,
  Undo2,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { GROUP_META, type Tutorial } from "./system-config-meta"
import { LlmDiagnoseButton } from "./llm-diagnose"
import { FeishuFullGuideButton } from "./feishu-guide-link"
import { DiagnosticsExportCard } from "./diagnostics-export"
import { useStrategyStore } from "@/hooks/use-strategy-store"
import { apiFetch } from "@/lib/api"

interface FieldItem {
  key: string
  label: string
  value: string
  sensitive: boolean
  /** 字段级「最小启动必填」标注（后端 common.config MINIMAL_REQUIRED_KEYS 同源下发） */
  required?: boolean
}

interface ConfigGroup {
  group: string
  fields: FieldItem[]
}

// 语音识别组的配置 key（重启门控用）：任一发生变化保存后按钮才点亮
const VOIP_RESTART_KEYS = new Set(["VOLC_ASR_APPID", "VOLC_ASR_TOKEN", "VOLC_ASR_RESOURCE_ID"])
// 门控分组名（后端 CONFIG_GROUPS 同源字符串，与 VOIP_RESTART_KEYS 语义强耦合故同置顶层）
const RESTART_GATED_GROUP = "语音识别 (火山引擎)"

// 分组图标与色调：左侧色块承担视觉分区，标题保持中性色，避免整页花哨
const GROUP_ICONS: Record<string, LucideIcon> = {
  "LLM 大模型": Brain,
  "视觉通道 (可选)": Eye,
  "数据清洗 LLM": Sparkles,
  "飞书": MessageSquare,
  "搜索/情报": Search,
  "语音识别 (火山引擎)": Mic,
  "地图 (高德)": MapPin,
}

const GROUP_TONES: Record<string, string> = {
  "LLM 大模型": "bg-indigo-50 text-indigo-600 ring-indigo-100",
  "视觉通道 (可选)": "bg-violet-50 text-violet-600 ring-violet-100",
  "数据清洗 LLM": "bg-cyan-50 text-cyan-600 ring-cyan-100",
  "飞书": "bg-blue-50 text-blue-600 ring-blue-100",
  "搜索/情报": "bg-amber-50 text-amber-600 ring-amber-100",
  "语音识别 (火山引擎)": "bg-rose-50 text-rose-600 ring-rose-100",
  "地图 (高德)": "bg-emerald-50 text-emerald-600 ring-emerald-100",
}

// 左侧导航/移动端 chips 的短标签
const GROUP_SHORT: Record<string, string> = {
  "LLM 大模型": "LLM",
  "视觉通道 (可选)": "视觉",
  "数据清洗 LLM": "清洗",
  "飞书": "飞书",
  "搜索/情报": "搜索",
  "语音识别 (火山引擎)": "语音",
  "地图 (高德)": "地图",
}

// 一级/二级分组关系：视觉与清洗都是 LLM 能力的子配置
const GROUP_PARENT: Record<string, string> = {
  "视觉通道 (可选)": "LLM 大模型",
  "数据清洗 LLM": "LLM 大模型",
}

interface GroupStats {
  total: number
  configured: number
  requiredMissing: number
  dirty: number
}

export function SystemConfig() {
  const { setSection } = useStrategyStore()
  const [groups, setGroups] = useState<ConfigGroup[]>([])
  const [edits, setEdits] = useState<Record<string, string>>({})
  // 待清除的配置键（两步确认：先标记、保存时生效；清除后回落 .env / 未配置）
  const [pendingClears, setPendingClears] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [activeTutorial, setActiveTutorial] = useState<Tutorial | null>(null)

  // 折叠状态：未显式操作过的分组取 GROUP_META.defaultCollapsed（视觉/清洗/语音/地图默认收起）
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  // 飞书「更多选填配置」二级折叠
  const [showOptional, setShowOptional] = useState<Record<string, boolean>>({})
  // 左侧导航高亮（当前视口内最靠上的分组）
  const [activeIndex, setActiveIndex] = useState(0)
  // 敏感字段明文/掩码切换。列表接口只下发遮罩值；点击眼睛时才按需向后端读取完整明文，
  // 避免整页初始加载就把全部密钥下发到浏览器。保存/清除/隐藏后立即从内存清除明文。
  const [revealed, setRevealed] = useState<Record<string, boolean>>({})
  const [revealedValues, setRevealedValues] = useState<Record<string, string>>({})
  const [revealing, setRevealing] = useState<Record<string, boolean>>({})
  const [revealError, setRevealError] = useState<Record<string, string>>({})

  const isCollapsed = (group: string) => collapsed[group] ?? GROUP_META[group]?.defaultCollapsed ?? false
  const toggleCollapsed = (group: string) => {
    // 基于 prev 计算，连续点击不会因闭包读到旧值而卡在同一个状态
    setCollapsed((prev) => {
      const current = prev[group] ?? GROUP_META[group]?.defaultCollapsed ?? false
      return { ...prev, [group]: !current }
    })
  }

  // ── 一键重启后端（语音识别等少数配置需重启生效）────────────────────────
  // 门控语义：按钮默认灰色禁用；仅当本页保存过「语音识别 (火山引擎)」分组的配置
  // （发生 App ID/Token/Resource ID 变更，保存后内存标记 restartPendingVoip=true）
  // 时才点亮。点按三段式：检验环境 → 重启中 → 已生效（进度文案直接落在按钮上）。
  type RestartPhase = "idle" | "checking" | "restarting" | "done"
  const [restartPhase, setRestartPhase] = useState<RestartPhase>("idle")
  // 待重启标记：handleSave 检测到语音组 key 变更时置位（成功重启后复位）
  const [restartPendingVoip, setRestartPendingVoip] = useState(false)
  const [restartBlockers, setRestartBlockers] = useState<string[]>([])
  const [restartError, setRestartError] = useState("")
  // 组件卸载中断标志：探活轮询跨后端重启周期，卸载后必须停止，防僵尸轮询与无效 setState
  const restartAbortRef = useRef(false)
  const restartDoneTimerRef = useRef<number | null>(null)
  useEffect(() => {
    restartAbortRef.current = false
    return () => {
      restartAbortRef.current = true
      if (restartDoneTimerRef.current !== null) window.clearTimeout(restartDoneTimerRef.current)
    }
  }, [])

  const pollBackendAlive = async (): Promise<boolean> => {
    try {
      // apiFetch 携带后端基地址与统一错误处理：裸 fetch 相对路径在前后端分端口部署时会打到前端自身
      const res = await apiFetch(`/api/settings/readiness`, { cache: "no-store" } as RequestInit)
      return res.ok
    } catch {
      return false
    }
  }

  const handleRestart = async () => {
    if (!restartPendingVoip || restartPhase !== "idle") return
    setRestartError("")
    setRestartBlockers([])
    // 阶段一：检验环境（占用检测；404 = 后端还是旧进程没有此接口，提示先升级重启一次）
    setRestartPhase("checking")
    let preflightOk = false
    let backendStale = false
    try {
      const res = await apiFetch(`/api/settings/restart/preflight`)
      if (res.status === 404) {
        backendStale = true
      } else if (!res.ok) {
        // 服务端异常（500/502/403/422...）不是"任务占用"，误报会误导排障方向；
        // detail 可能是字符串也可能是 FastAPI 校验错误对象数组，防御性取串
        const err = await res.json().catch(() => ({}))
        const detail = typeof err?.detail === "string" ? err.detail : "后端内部错误"
        setRestartError(`环境检验失败（HTTP ${res.status}）：${detail}`)
        setRestartPhase("idle")
        return
      } else {
        const data = await res.json()
        preflightOk = !!data.ok
        if (!data.ok) setRestartBlockers(data.blockers || ["有任务正在执行"])
      }
    } catch {
      setRestartError("无法连接后端，无法检验环境")
      setRestartPhase("idle")
      return
    }
    if (backendStale) {
      setRestartError("当前后端是旧版本（无重启接口），本次请手动重启一次后端（此后即可一键重启）")
      setRestartPhase("idle")
      return
    }
    if (!preflightOk) {
      setRestartPhase("idle")
      return
    }
    // 阶段二：重启中（优雅退出由 PM2 自动拉起）
    setRestartPhase("restarting")
    try {
      const res = await apiFetch(`/api/settings/restart`, { method: "POST" })
      if (res.status === 409) {
        const data = await res.json().catch(() => ({}))
        setRestartBlockers(data.detail?.blockers || ["有任务正在执行"])
        setRestartPhase("idle")
        return
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setRestartError(data.detail?.message || data.detail || "重启指令发送失败")
        setRestartPhase("idle")
        return
      }
    } catch {
      // 请求可能因后端退出而中断，属于预期：进入探活
    }
    // 等待端口下线 → 轮询探活（PM2 restart_delay 500ms + uvicorn 启动数秒）
    await new Promise((r) => setTimeout(r, 4000))
    const deadline = Date.now() + 90_000
    while (Date.now() < deadline) {
      if (restartAbortRef.current) return // 组件已卸载，停止轮询与状态更新
      if (await pollBackendAlive()) {
        // 阶段三：已生效（按钮保持点亮 4 秒展示文字，随后随标记复位一同回灰）
        setRestartPhase("done")
        restartDoneTimerRef.current = window.setTimeout(() => {
          setRestartPendingVoip(false)
          setRestartPhase("idle")
        }, 4000)
        fetchConfig()
        return
      }
      await new Promise((r) => setTimeout(r, 2500))
    }
    if (restartAbortRef.current) return
    setRestartError("等待超时：后端尚未恢复，请检查 PM2 进程状态（pm2 ls）后手动启动，或稍后刷新页面重试")
    setRestartPhase("idle")
  }

  const fetchConfig = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/settings`)
      if (res.ok) {
        const data = await res.json()
        setGroups(data.groups || [])
        setLoadError(false)
      } else {
        setLoadError(true)
      }
    } catch {
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  // 锚点高亮：以视口内最靠上的分组为准（滚动容器即页面自身）
  useEffect(() => {
    if (groups.length === 0) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible.length === 0) return
        const idx = Number((visible[0].target as HTMLElement).dataset.index)
        if (!Number.isNaN(idx)) setActiveIndex(idx)
      },
      { rootMargin: "-72px 0px -60% 0px" },
    )
    groups.forEach((_, i) => {
      const el = document.getElementById(`cfg-group-${i}`)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [groups])

  const scrollToGroup = (index: number) => {
    document.getElementById(`cfg-group-${index}`)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  const clearCount = Object.keys(pendingClears).length
  const dirtyCount = Object.values(edits).filter((v) => v.trim()).length + clearCount

  const handleSave = async () => {
    const payload: Record<string, string> = {}
    for (const [k, v] of Object.entries(edits)) {
      if (v.trim()) payload[k] = v.trim()
    }
    const deleteKeys = Object.keys(pendingClears)
    const hasSettings = Object.keys(payload).length > 0
    if (!hasSettings && deleteKeys.length === 0) return

    // 保存前先记下本次是否动了语音识别组（这些 key 需重启才生效）
    const touchedVoipKeys = Object.keys(payload).some((k) => VOIP_RESTART_KEYS.has(k))
      || deleteKeys.some((k) => VOIP_RESTART_KEYS.has(k))

    setSaving(true)
    setSaved(false)
    try {
      const res = await apiFetch(`/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(deleteKeys.length > 0 ? { __delete__: deleteKeys, ...payload } : payload),
      })
      if (res.ok) {
        setEdits({})
        setPendingClears({})
        setRevealed({})
        setRevealedValues({})
        setRevealError({})
        setSaved(true)
        setTimeout(() => setSaved(false), 2500)
        if (touchedVoipKeys) setRestartPendingVoip(true) // 语音组值已变更：点亮重启按钮
        fetchConfig()
      }
    } catch {
      // silent
    } finally {
      setSaving(false)
    }
  }

  const resetEdits = () => {
    setEdits({})
    setPendingClears({})
  }

  const fieldConfigured = (field: FieldItem) => {
    if (pendingClears[field.key]) return false
    if ((edits[field.key] ?? "").trim()) return true
    return !!field.value
  }

  const groupStats = (group: ConfigGroup): GroupStats => {
    const requiredFields = group.fields.filter((f) => f.required)
    return {
      total: group.fields.length,
      configured: group.fields.filter(fieldConfigured).length,
      requiredMissing: requiredFields.filter((f) => !fieldConfigured(f)).length,
      dirty: group.fields.filter((f) => (edits[f.key] ?? "").trim() || pendingClears[f.key]).length,
    }
  }

  const allFields = groups.flatMap((g) => g.fields)
  const requiredFields = allFields.filter((f) => f.required)
  const optionalFields = allFields.filter((f) => !f.required)
  const requiredDone = requiredFields.filter(fieldConfigured).length
  const optionalDone = optionalFields.filter(fieldConfigured).length
  const requiredRatio = requiredFields.length > 0 ? Math.round((requiredDone / requiredFields.length) * 100) : 100
  // 缺失项带分组前缀，避免多个「API Key」同名难以定位
  const missingRequiredLabels = groups.flatMap((g) =>
    g.fields
      .filter((f) => f.required && !fieldConfigured(f))
      .map((f) => `${GROUP_SHORT[g.group] ?? g.group} · ${f.label}`),
  )

  if (loading) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw className="size-6 animate-spin text-slate-400" />
          <span className="text-xs font-medium text-slate-400">正在加载底层系统配置...</span>
        </div>
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="flex h-full min-h-[400px] items-center justify-center px-8">
        <div className="flex w-full max-w-md flex-col items-center gap-4 rounded-2xl border border-amber-200 bg-amber-50/60 p-8 text-center">
          <div className="flex size-11 items-center justify-center rounded-full bg-amber-100">
            <ServerOff className="size-5 text-amber-600" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-semibold text-slate-900">无法连接后端服务</p>
            <p className="text-xs leading-relaxed text-slate-500">
              系统配置需要后端接口支持。请确认后端已启动（uvicorn app.main:app）后重试。
            </p>
          </div>
          <button
            type="button"
            onClick={() => { setLoadError(false); setLoading(true); fetchConfig() }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-slate-700"
          >
            <RefreshCw className="size-3.5" />
            重新加载
          </button>
        </div>
      </div>
    )
  }

  // 眼睛按钮：已保存密钥按需读取完整明文；刚输入的值直接用 edits 里的内容
  const toggleReveal = async (field: FieldItem) => {
    const key = field.key
    if (revealed[key]) {
      setRevealed((prev) => ({ ...prev, [key]: false }))
      setRevealedValues((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      return
    }

    // 用户刚输入/修改的值已经在内存里，直接切换显示即可
    if ((edits[key] ?? "").trim()) {
      setRevealed((prev) => ({ ...prev, [key]: true }))
      return
    }

    // 已保存的密钥：按需向后端读取完整明文（列表接口只给遮罩值）
    setRevealing((prev) => ({ ...prev, [key]: true }))
    setRevealError((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    try {
      const res = await apiFetch(`/api/settings/reveal?key=${encodeURIComponent(key)}`)
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.code !== 0) {
        setRevealError((prev) => ({
          ...prev,
          [key]: typeof data.detail === "string" ? data.detail : "读取密钥失败，请稍后重试",
        }))
        return
      }
      setRevealedValues((prev) => ({ ...prev, [key]: String(data.data?.value ?? "") }))
      setRevealed((prev) => ({ ...prev, [key]: true }))
    } catch {
      setRevealError((prev) => ({ ...prev, [key]: "网络请求失败，请稍后重试" }))
    } finally {
      setRevealing((prev) => ({ ...prev, [key]: false }))
    }
  }

  // ── 单个字段（标签 + 输入框 + key/状态行；不再各自套卡片，降低视觉噪声）──
  const renderField = (field: FieldItem) => {
    const isEditing = field.key in edits
    const isClearing = !!pendingClears[field.key]
    const isRevealed = !!revealed[field.key]
    const hasTypedValue = (edits[field.key] ?? "").trim().length > 0
    const canReveal = field.sensitive && !isClearing && (!!field.value || hasTypedValue)
    // 敏感字段默认留空（占位提示「已配置」）；点击眼睛后显示完整明文或刚输入的值
    const displayValue = isClearing
      ? ""
      : isEditing
        ? edits[field.key]
        : field.sensitive
          ? (isRevealed ? (revealedValues[field.key] ?? "") : "")
          : field.value

    const markClear = () => {
      setPendingClears((prev) => ({ ...prev, [field.key]: true }))
      setEdits((prev) => ({ ...prev, [field.key]: "" }))
      setRevealed((prev) => ({ ...prev, [field.key]: false }))
      setRevealedValues((prev) => {
        const next = { ...prev }
        delete next[field.key]
        return next
      })
    }
    const undoClear = () => {
      setPendingClears((prev) => {
        const next = { ...prev }
        delete next[field.key]
        return next
      })
      setEdits((prev) => {
        const next = { ...prev }
        delete next[field.key]
        return next
      })
    }

    return (
      <div key={field.key} className="group/field min-w-0">
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <label
            htmlFor={`cfg-input-${field.key}`}
            className="truncate text-xs font-semibold text-slate-700"
            title={field.label}
          >
            {field.label}
            {field.required && (
              <span className="ml-0.5 text-rose-500" title="最小启动必填字段：缺任一项项目无法完整启动">
                *
              </span>
            )}
          </label>
          {field.sensitive && (
            <span className="shrink-0 rounded bg-slate-100 px-1 py-0.5 font-mono text-[9px] text-slate-400" title="加密密钥字段">
              SECRET
            </span>
          )}
        </div>

        <div className="relative">
          <input
            id={`cfg-input-${field.key}`}
            type={field.sensitive && !isRevealed ? "password" : "text"}
            value={displayValue}
            onChange={(e) => {
              const v = e.target.value
              setEdits((prev) => ({ ...prev, [field.key]: v }))
              if (v.trim()) {
                // 输入了新值 = 覆盖而非清除，自动撤销待清除标记
                setPendingClears((prev) => {
                  if (!(field.key in prev)) return prev
                  const next = { ...prev }
                  delete next[field.key]
                  return next
                })
              }
            }}
            placeholder={
              isClearing
                ? "保存后清除，回落 .env..."
                : field.sensitive
                  ? (field.value ? "已配置，点击右侧眼睛查看完整密钥" : "粘贴密钥...")
                  : "留空保持不变"
            }
            className={cn(
              "h-9 w-full rounded-lg border px-3 text-[13px] transition-all focus:outline-none",
              field.sensitive && "pr-9",
              isClearing
                ? "border-rose-300 bg-rose-50/40 text-slate-400 line-through placeholder:text-rose-300"
                : isEditing && edits[field.key]?.trim()
                  ? "border-amber-300 bg-amber-50/30 text-slate-900 focus:border-amber-400 focus:ring-2 focus:ring-amber-500/10"
                  : "border-slate-200 bg-slate-50/60 text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-900/5",
              field.sensitive && "font-mono",
            )}
          />
          {canReveal && (
            <button
              type="button"
              onClick={() => toggleReveal(field)}
              disabled={!!revealing[field.key]}
              aria-label={
                revealing[field.key] ? "正在读取密钥" : isRevealed ? "隐藏密钥" : "显示密钥"
              }
              title={isRevealed ? "隐藏完整密钥" : "显示完整密钥，便于二次核对"}
              className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-r-lg text-slate-400 transition-colors hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-900/20 disabled:cursor-wait disabled:opacity-60"
            >
              {revealing[field.key] ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : isRevealed ? (
                <EyeOff className="size-4" />
              ) : (
                <Eye className="size-4" />
              )}
            </button>
          )}
        </div>

        {revealError[field.key] && (
          <p className="mt-1 text-[10px] leading-relaxed text-rose-600" role="alert">
            {revealError[field.key]}
          </p>
        )}

        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span className="truncate font-mono text-[10px] text-slate-400" title={field.key}>
            {field.key}
          </span>

          <div className="flex shrink-0 items-center gap-1">
            {isClearing ? (
              <button
                type="button"
                onClick={undoClear}
                className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium text-amber-600 transition-colors hover:bg-amber-50"
                title="撤销清除标记"
              >
                <Undo2 className="size-3" />
                撤销
              </button>
            ) : (
              <button
                type="button"
                onClick={markClear}
                className="rounded p-1 text-slate-300 opacity-0 transition-all hover:bg-rose-50 hover:text-rose-500 group-hover/field:opacity-100 focus:opacity-100"
                title="标记清除此配置（保存后生效，回落至 .env 默认值或未配置）"
              >
                <Trash2 className="size-3" />
              </button>
            )}

            {isClearing ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-600 ring-1 ring-inset ring-rose-200/70">
                <span className="size-1.5 rounded-full bg-rose-500" />
                待清除
              </span>
            ) : isEditing && edits[field.key]?.trim() ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-inset ring-amber-200/70">
                <span className="size-1.5 rounded-full bg-amber-500" />
                已修改
              </span>
            ) : field.value ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200/60">
                <span className="size-1.5 rounded-full bg-emerald-500" />
                已配置
              </span>
            ) : (
              <span className="inline-flex items-center rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-400 ring-1 ring-inset ring-slate-200/50">
                未配置
              </span>
            )}
          </div>
        </div>
      </div>
    )
  }

  // 左侧导航单项：一级与二级（视觉/清洗）共用，二级缩进并缩小字号
  const renderNavItem = (group: ConfigGroup, index: number, isChild = false) => {
    const stats = groupStats(group)
    const active = activeIndex === index
    const allDone = stats.total > 0 && stats.configured === stats.total
    const someDone = stats.configured > 0
    const required = GROUP_META[group.group]?.required ?? false
    return (
      <button
        key={group.group}
        type="button"
        onClick={() => scrollToGroup(index)}
        title={isChild ? `${GROUP_PARENT[group.group]} → ${group.group}` : group.group}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg text-left transition-colors",
          isChild ? "px-2 py-1.5 text-[10.5px]" : "px-2.5 py-2 text-[11px]",
          active ? "bg-slate-900 text-white shadow-sm" : "text-slate-600 hover:bg-white hover:text-slate-900",
        )}
      >
        <span
          className={cn(
            "shrink-0 rounded-full",
            isChild ? "size-1" : "size-1.5",
            allDone ? "bg-emerald-500" : someDone ? "bg-amber-400" : "bg-slate-300",
          )}
        />
        <span className="min-w-0 flex-1 truncate">
          {GROUP_SHORT[group.group] ?? group.group}
          {required && (
            <span className={cn("ml-0.5", active ? "text-rose-400" : "text-rose-500")} title="必填分组">
              *
            </span>
          )}
        </span>
        <span className={cn("shrink-0 font-mono text-[10px]", active ? "text-white/60" : "text-slate-400")}>
          {stats.configured}/{stats.total}
        </span>
        {stats.dirty > 0 && <span className="size-1.5 shrink-0 rounded-full bg-amber-400" />}
      </button>
    )
  }

  return (
    <div className="mx-auto max-w-7xl px-4 pb-24 pt-6 sm:px-6 lg:px-8">
      {/* 顶部总览：一眼看到必填完成度与还缺什么 */}
      <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs">
        <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3.5">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-slate-900 text-white shadow-sm">
              <Key className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <h2 className="text-[15px] font-semibold text-slate-900">底层服务凭据与模型路由</h2>
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200/60">
                  <span className="size-1.5 rounded-full bg-emerald-500" />
                  本地安全写入
                </span>
              </div>
              <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-500">
                标 <span className="font-bold text-rose-500">*</span> 为最小启动必填项，配齐即可启动；其余按需选配。
                密钥写入本地独立环境且页面不回显明文，保存后即时生效（语音识别等少数项需重启）。
              </p>
              {missingRequiredLabels.length > 0 ? (
                <p className="mt-1.5 text-[11px] leading-relaxed text-rose-600">
                  还缺必填：
                  {missingRequiredLabels.slice(0, 4).join("、")}
                  {missingRequiredLabels.length > 4 ? ` 等 ${missingRequiredLabels.length} 项` : ""}
                </p>
              ) : (
                <p className="mt-1.5 text-[11px] leading-relaxed text-emerald-600">
                  最小启动必填项已配齐，可以正常启动。
                </p>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-5 rounded-xl bg-slate-50/80 px-4 py-3 ring-1 ring-inset ring-slate-100">
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-slate-400">必填</div>
              <div className={cn("mt-0.5 text-sm font-semibold", requiredDone === requiredFields.length ? "text-emerald-600" : "text-rose-600")}>
                {requiredDone}
                <span className="text-slate-400">/{requiredFields.length}</span>
              </div>
            </div>
            <div className="h-8 w-px bg-slate-200" />
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-slate-400">选填</div>
              <div className="mt-0.5 text-sm font-semibold text-slate-700">
                {optionalDone}
                <span className="text-slate-400">/{optionalFields.length}</span>
              </div>
            </div>
            {dirtyCount > 0 && (
              <>
                <div className="h-8 w-px bg-slate-200" />
                <div>
                  <div className="text-[10px] font-medium uppercase tracking-wider text-amber-500">未保存</div>
                  <div className="mt-0.5 text-sm font-semibold text-amber-600">{dirtyCount}</div>
                </div>
              </>
            )}
          </div>
        </div>
        <div className="h-1 w-full bg-slate-100">
          <div
            className={cn("h-full transition-all duration-500", requiredRatio === 100 ? "bg-emerald-500" : "bg-amber-400")}
            style={{ width: `${requiredRatio}%` }}
          />
        </div>
      </div>

      <div className="mt-5 lg:grid lg:grid-cols-[210px_minmax(0,1fr)] lg:gap-6">
        {/* 桌面端左侧锚点导航 */}
        <aside className="hidden lg:block">
          <div className="sticky top-4 space-y-1">
            <p className="px-2.5 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">配置分组</p>
            {groups.map((group, index) => {
              // 二级分组由父级统一渲染，避免在同一层重复出现
              if (GROUP_PARENT[group.group]) return null
              const children = groups
                .map((child, childIndex) => ({ child, childIndex }))
                .filter(({ child }) => GROUP_PARENT[child.group] === group.group)
              return (
                <div key={group.group}>
                  {renderNavItem(group, index)}
                  {children.length > 0 && (
                    <div className="ml-3 mt-0.5 space-y-0.5 border-l border-slate-200 pl-1.5">
                      {children.map(({ child, childIndex }) => renderNavItem(child, childIndex, true))}
                    </div>
                  )}
                </div>
              )
            })}

            <div className="mt-3 rounded-xl border border-slate-200/70 bg-white p-3 shadow-2xs">
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>必填完成度</span>
                <span className="font-mono">{requiredDone}/{requiredFields.length}</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div
                  className={cn("h-full rounded-full transition-all duration-500", requiredRatio === 100 ? "bg-emerald-500" : "bg-amber-400")}
                  style={{ width: `${requiredRatio}%` }}
                />
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-slate-400">
                修改先暂存，点击右下角保存后写入本地。
              </p>
            </div>
          </div>
        </aside>

        <div className="min-w-0">
          {/* 移动端横向 chips */}
          <div className="mb-3 flex gap-1.5 overflow-x-auto pb-1 lg:hidden">
            {groups.map((group, index) => {
              const stats = groupStats(group)
              return (
                <button
                  key={group.group}
                  type="button"
                  onClick={() => scrollToGroup(index)}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                    activeIndex === index
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-slate-200 bg-white text-slate-600",
                  )}
                >
                  {GROUP_PARENT[group.group] && (
                    <span className={cn(activeIndex === index ? "text-white/50" : "text-slate-300")}>↳</span>
                  )}
                  {GROUP_SHORT[group.group] ?? group.group}
                  {GROUP_META[group.group]?.required && (
                    <span className={cn(activeIndex === index ? "text-rose-400" : "text-rose-500")}>*</span>
                  )}
                  <span className={cn("font-mono text-[10px]", activeIndex === index ? "text-white/60" : "text-slate-400")}>
                    {stats.configured}/{stats.total}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="space-y-4">
            {groups.map((group, index) => {
              const meta = GROUP_META[group.group]
              const required = meta?.required ?? false
              const stats = groupStats(group)
              const groupCollapsed = isCollapsed(group.group)
              const Icon = GROUP_ICONS[group.group] ?? Settings2
              const tone = GROUP_TONES[group.group] ?? "bg-slate-100 text-slate-600 ring-slate-200"
              const splitOptional = meta?.splitOptionalFields ?? false
              const mainFields = splitOptional ? group.fields.filter((f) => f.required) : group.fields
              const extraFields = splitOptional ? group.fields.filter((f) => !f.required) : []
              const extraConfigured = extraFields.filter(fieldConfigured).length
              const optionalOpen = !!showOptional[group.group]

              return (
                <section
                  key={group.group}
                  id={`cfg-group-${index}`}
                  data-index={index}
                  className="scroll-mt-4 overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs transition-shadow hover:shadow-sm"
                >
                  {/* 分组头：整块可点击折叠；窄屏时标题与操作按钮分两行，避免标题被挤成竖排 */}
                  <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 px-4 py-3.5 sm:flex-nowrap sm:px-5">
                    <button
                      type="button"
                      onClick={() => toggleCollapsed(group.group)}
                      aria-expanded={!groupCollapsed}
                      className="flex w-full min-w-0 items-center gap-3 text-left sm:w-auto sm:flex-1"
                    >
                      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset", tone)}>
                        <Icon className="size-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">{group.group}</span>
                          {required ? (
                            <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-[10px] font-medium text-rose-600 ring-1 ring-inset ring-rose-200/60">
                              必填
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 ring-1 ring-inset ring-slate-200/60">
                              选填
                            </span>
                          )}
                          {GROUP_PARENT[group.group] && (
                            <span className="inline-flex items-center gap-0.5 rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 ring-1 ring-inset ring-slate-200/60">
                              <CornerDownRight className="size-2.5" />
                              {GROUP_SHORT[GROUP_PARENT[group.group]] ?? GROUP_PARENT[group.group]} 子配置
                            </span>
                          )}
                          {stats.requiredMissing > 0 ? (
                            <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-inset ring-amber-200/70">
                              缺 {stats.requiredMissing} 项必填
                            </span>
                          ) : stats.configured === stats.total && stats.total > 0 ? (
                            <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200/60">
                              <Check className="size-2.5" />
                              已配齐
                            </span>
                          ) : null}
                          {stats.dirty > 0 && (
                            <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-inset ring-amber-200/70">
                              <span className="size-1.5 rounded-full bg-amber-500" />
                              {stats.dirty} 项未保存
                            </span>
                          )}
                        </span>
                        <span className="mt-0.5 block truncate text-[11px] text-slate-400">
                          {stats.configured}/{stats.total} 项已配置
                          {groupCollapsed ? " · 已折叠，点击展开" : ""}
                        </span>
                      </span>
                    </button>

                    <div className="flex w-full shrink-0 items-center justify-end gap-1.5 sm:w-auto sm:justify-start">
                      {/* 仅 LLM 分组挂 LLM 诊断按钮；diagnose 标志为分组级通用位（飞书组的诊断在飞书集成中心），不可单独作渲染条件 */}
                      {group.group === "LLM 大模型" && meta?.diagnose && (
                        <LlmDiagnoseButton hasDirtyEdits={dirtyCount > 0} />
                      )}
                      {meta?.tutorial && (
                        <button
                          type="button"
                          onClick={() => setActiveTutorial(meta.tutorial!)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 shadow-xs transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 hover:shadow-sm active:scale-[0.98]"
                        >
                          <BookOpen className="size-3 text-slate-400" />
                          配置教程
                        </button>
                      )}
                      {/* 语音识别组：一键重启按钮（门控）——仅在保存过该组配置（值变更）后点亮，
                          其余时候灰色禁用；点击后按钮内直接走三段式进度文案 */}
                      {group.group === RESTART_GATED_GROUP && (
                        <button
                          type="button"
                          onClick={handleRestart}
                          disabled={!restartPendingVoip || (restartPhase !== "idle" && restartPhase !== "done")}
                          className={cn(
                            "inline-flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-medium shadow-xs transition-all active:scale-[0.98] disabled:active:scale-100",
                            restartPendingVoip
                              ? "border-amber-200 bg-amber-50 text-amber-700 hover:border-amber-300 hover:bg-amber-100 disabled:opacity-50"
                              : "cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400",
                          )}
                          title={
                            restartPendingVoip
                              ? "语音识别配置已变更，点击重启后端使其生效（自动检查任务占用）"
                              : "语音识别配置未变更，无需重启。修改 App ID / Token 等字段并保存后，此按钮才会点亮"
                          }
                        >
                          <Power className={cn("size-3", (restartPhase === "checking" || restartPhase === "restarting") && "animate-pulse")} />
                          {restartPhase === "checking" && "检验环境..."}
                          {restartPhase === "restarting" && "重启中..."}
                          {restartPhase === "done" && "已生效"}
                          {restartPhase === "idle" && (restartPendingVoip ? "重启后端生效" : "重启后端")}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => toggleCollapsed(group.group)}
                        aria-label={groupCollapsed ? "展开分组" : "折叠分组"}
                        aria-expanded={!groupCollapsed}
                        className="flex size-7 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                      >
                        <ChevronDown className={cn("size-4 transition-transform duration-200", !groupCollapsed && "rotate-180")} />
                      </button>
                    </div>
                  </div>

                  {!groupCollapsed && (
                    <div className="border-t border-slate-100 px-4 pb-5 pt-4 sm:px-5">
                      {meta?.note && (
                        <div className="flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-500">
                          <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-amber-500/80" />
                          <span>{meta.note}</span>
                        </div>
                      )}

                      {/* 飞书集成专属导流卡片 */}
                      {group.group === "飞书" && (
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-blue-500/20 bg-blue-50/50 px-3.5 py-2.5 text-[11px] text-blue-800">
                          <span className="flex items-center gap-2 font-medium">
                            <span className="flex size-4 items-center justify-center rounded-full bg-blue-500/10 text-[10px] text-blue-600">💡</span>
                            飞书长连接机器人状态、ChatOps 指令集与自动化战报推送已移至独立的「飞书集成中心」管理。
                          </span>
                          <button
                            type="button"
                            onClick={() => setSection("feishu")}
                            className="inline-flex items-center gap-1 font-semibold text-blue-600 transition-colors hover:text-blue-700 hover:underline"
                          >
                            前往飞书集成中心
                            <ArrowRight className="size-3.5" />
                          </button>
                        </div>
                      )}

                      <div className={cn("grid gap-x-5 gap-y-5 sm:grid-cols-2 xl:grid-cols-3", meta?.note || group.group === "飞书" ? "mt-4" : "mt-1")}>
                        {mainFields.map(renderField)}
                      </div>

                      {/* 飞书：必填 5 项优先展示，其余选填收进二级折叠 */}
                      {splitOptional && extraFields.length > 0 && (
                        <div className="mt-5">
                          <button
                            type="button"
                            onClick={() => setShowOptional((prev) => ({ ...prev, [group.group]: !prev[group.group] }))}
                            aria-expanded={optionalOpen}
                            className="flex w-full items-center justify-between gap-3 rounded-lg border border-dashed border-slate-200 bg-slate-50/50 px-3.5 py-2.5 text-left transition-colors hover:border-slate-300 hover:bg-slate-50"
                          >
                            <span className="flex items-center gap-2 text-[11px] font-medium text-slate-600">
                              <ChevronDown className={cn("size-3.5 text-slate-400 transition-transform duration-200", optionalOpen && "rotate-180")} />
                              更多选填配置
                              <span className="rounded bg-slate-200/70 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
                                {extraFields.length} 项
                              </span>
                            </span>
                            <span className="shrink-0 text-[10px] text-slate-400">
                              已配置 {extraConfigured}/{extraFields.length}
                            </span>
                          </button>

                          {optionalOpen && (
                            <div className="mt-4 grid gap-x-5 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
                              {extraFields.map(renderField)}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </section>
              )
            })}

          </div>
        </div>
      </div>

      {/* 内测期诊断通道：恢复为页面底部通栏卡片（桌面壳内可见；web 模式无 IPC 桥时组件自隐藏） */}
      <div className="mt-5">
        <DiagnosticsExportCard />
      </div>

      {/* Sticky Save Bar */}
      <div className="pointer-events-none sticky bottom-4 z-20 mt-6 flex justify-end">
        <div className="pointer-events-auto flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-white/95 px-3 py-2 shadow-lg backdrop-blur-sm">
          {dirtyCount > 0 && (
            <>
              <span className="hidden text-[11px] text-slate-500 sm:inline">
                有 <span className="font-semibold text-amber-600">{dirtyCount}</span> 项修改未保存
              </span>
              <button
                type="button"
                onClick={resetEdits}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                <RotateCcw className="size-3" />
                撤销
              </button>
            </>
          )}
          <button
            onClick={handleSave}
            disabled={saving || dirtyCount === 0}
            className={cn(
              "flex items-center gap-2 rounded-xl px-5 py-2 text-[13px] font-semibold transition-all duration-200",
              dirtyCount > 0
                ? "bg-slate-900 text-white shadow-md shadow-slate-900/15 hover:bg-slate-800 hover:shadow-lg active:scale-[0.98]"
                : "cursor-not-allowed bg-slate-200/80 text-slate-400 shadow-none",
            )}
          >
            {saving ? (
              <RefreshCw className="size-4 animate-spin text-slate-300" />
            ) : saved ? (
              <Check className="size-4 text-emerald-400" />
            ) : (
              <Save className={cn("size-4", dirtyCount > 0 ? "text-white" : "text-slate-400")} />
            )}
            <span>{saving ? "正在写入本地配置..." : saved ? "已成功保存配置" : "保存配置"}</span>
            {dirtyCount > 0 && !saving && (
              <span className="rounded-full bg-white/20 px-2 py-0.5 text-[11px] font-bold text-white">
                {dirtyCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Restart Blockers/Error Dialog：有任务在跑，或重启流程出错（含后端旧版无接口），拦截并明示 */}
      <Dialog open={(restartBlockers.length > 0 || !!restartError) && restartPhase === "idle"} onOpenChange={(open) => { if (!open) { setRestartBlockers([]); setRestartError("") } }}>
        <DialogContent className="sm:max-w-md border-slate-200 bg-white">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base font-bold text-slate-900">
              <AlertTriangle className="size-4 text-rose-500" />
              {restartError ? "重启未完成" : "暂不能重启：有任务正在执行"}
            </DialogTitle>
            {restartError ? (
              <DialogDescription className="mt-1 text-[13px] leading-relaxed text-slate-600">
                {restartError}
              </DialogDescription>
            ) : (
              <DialogDescription className="mt-1 text-[13px] leading-relaxed text-slate-600">
                为避免任务中断丢失进度，请等以下任务全部结束后，再回到这里点击「重启后端生效」：
              </DialogDescription>
            )}
          </DialogHeader>
          {!restartError && (
            <ul className="mt-2 space-y-1.5">
              {restartBlockers.map((b, i) => (
                <li key={i} className="flex items-start gap-2 rounded-lg bg-rose-50/60 px-3 py-2 text-xs text-rose-700">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-rose-400" />
                  {b}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={() => { setRestartBlockers([]); setRestartError("") }}
              className="rounded-lg border border-slate-200 px-4 py-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50"
            >
              我知道了
            </button>
          </div>
        </DialogContent>
      </Dialog>

      {/* （重启进度直接展示在按钮文字上：检验环境 → 重启中 → 已生效，无独立弹窗） */}

      {/* Tutorial Dialog */}
      <Dialog open={!!activeTutorial} onOpenChange={(open) => !open && setActiveTutorial(null)}>
        <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto border-slate-200 bg-white">
          {activeTutorial && (
            <>
              <DialogHeader>
                <DialogTitle className="text-lg font-bold text-slate-900">{activeTutorial.title}</DialogTitle>
                <DialogDescription className="mt-1 text-[13px] leading-relaxed text-slate-500">
                  {activeTutorial.intro}
                </DialogDescription>
              </DialogHeader>

              {activeTutorial.fullGuide && <FeishuFullGuideButton />}

              <ol className="mt-4 space-y-4">
                {activeTutorial.steps.map((step, i) => (
                  <li key={i} className="flex gap-3.5">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white shadow-2xs">
                      {i + 1}
                    </span>
                    <div className="pt-0.5">
                      <p className="text-sm font-semibold text-slate-900">{step.title}</p>
                      <p className="mt-0.5 text-[13px] leading-relaxed text-slate-600 whitespace-pre-line">{step.desc}</p>
                    </div>
                  </li>
                ))}
              </ol>

              {activeTutorial.tip && (
                <div className="mt-4 flex gap-2.5 rounded-xl border border-amber-200/80 bg-amber-50/80 px-4 py-3">
                  <Lightbulb className="size-4 shrink-0 text-amber-600 mt-0.5" />
                  <p className="text-xs leading-relaxed text-amber-800">{activeTutorial.tip}</p>
                </div>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>

    </div>
  )
}
