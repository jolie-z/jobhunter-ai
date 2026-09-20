"use client"

/**
 * 映射报告共享组件 —— 汇总新（agent-tab）与各平台 tab（liepin-tab）共用
 * 类型定义 + 警告列表 + 待人工补充列表 + 模块变动汇总 + 模块级警告分发
 * （改一处两边同步生效；agent-tab 表格/编辑等复杂交互不在此处，保持组件内私有）
 */

import { useState } from "react"
import { API_BASE } from "@/lib/api"
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react"

export interface MappedField {
  path: string
  value: unknown
  confidence: "high" | "medium" | "low"
  source: string
  note: string
  translation?: string
  type?: string
  options?: string[]
  item_options?: Record<string, string[]>
  item_value_labels?: Record<string, Record<string, string>>
  /** 变更标记：映射值与官网采集原值不同（应用映射后该字段值会变） */
  changed?: boolean
  /** 数组字段：发生变更的条目索引（与排序后的报告顺序一致） */
  changed_items?: number[]
}

export interface UnfilledItem {
  path: string
  label: string
  reason: string
}

export interface PlatformReport {
  success: boolean
  platform: string
  fields: MappedField[]
  unfilled: UnfilledItem[]
  warnings: string[]
  message: string
  restored?: boolean
  generated_at?: string
  /** 「已修改」标识：成功应用映射写入平台本地数据的字段 path 列表（后端持久化，刷新不丢） */
  applied_paths?: string[]
}

export interface ResumeOption {
  record_id: string
  name: string
  status: string
  char_count: number
}

export const PLATFORM_LABELS: Record<string, string> = {
  zhilian: "智联招聘",
  boss: "BOSS直聘",
  liepin: "猎聘",
  "51job": "前程无忧",
}

// 映射报告警告列表（⚠️ 琥珀色卡片，默认折叠仅展示前 6 条，可展开全部）
export function ReportWarnings({ warnings, className = "" }: { warnings: string[]; className?: string }) {
  const [expanded, setExpanded] = useState(false)
  if (!warnings || warnings.length === 0) return null
  const visible = expanded ? warnings : warnings.slice(0, 6)
  return (
    <div className={`rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-xs text-amber-700 space-y-0.5 ${className}`}>
      <div className="flex items-center justify-between">
        <span className="font-medium">⚠️ 映射提示（{warnings.length} 条）</span>
        {warnings.length > 6 && (
          <button
            type="button"
            onClick={() => setExpanded(v => !v)}
            className="inline-flex items-center gap-0.5 text-amber-600 hover:text-amber-800 font-medium"
          >
            {expanded ? <>收起 <ChevronDown className="w-3 h-3" /></> : <>展开全部 <ChevronRight className="w-3 h-3" /></>}
          </button>
        )}
      </div>
      {visible.map((w, i) => (
        <div key={i} className="flex items-start gap-1.5">
          <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
          <span>{w}</span>
        </div>
      ))}
    </div>
  )
}

// 待人工补充列表
export function ReportUnfilled({ unfilled }: { unfilled: UnfilledItem[] }) {
  if (!unfilled || unfilled.length === 0) return null
  return (
    <div>
      <div className="text-xs font-medium text-gray-500 mb-1.5">待人工补充（{unfilled.length}）</div>
      <div className="space-y-1">
        {unfilled.map((u, i) => (
          <div key={i} className="flex items-start gap-2 text-xs text-gray-400">
            <span className="shrink-0 px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-mono">{u.path}</span>
            <span>{u.reason || "主简历无对应信息"}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// 「已变更」徽章：该字段/条目因执行映射其值发生了改变（对比官网采集原值）
export function ChangedBadge({ className = "" }: { className?: string }) {
  return (
    <span
      title="该字段的值因执行主简历映射而改变（对比官网原值）"
      className={`inline-flex items-center shrink-0 px-1 py-px rounded bg-orange-100 text-orange-600 border border-orange-200 text-[10px] leading-tight font-medium ${className}`}
    >
      已变更
    </span>
  )
}

// ============================================================
// 模块变动汇总 + 模块级警告分发（四个平台 Tab 共用）
// ============================================================

/** 从报告中聚合"发生变动"的模块 key 集合：changed 字段 + applied_paths（刷新不丢） */
export function computeChangedModuleKeys(report: PlatformReport | null): Set<string> {
  const keys = new Set<string>()
  for (const f of report?.fields || []) {
    if (f.changed) {
      keys.add(String(f.path).includes(".") ? String(f.path).split(".")[0] : String(f.path))
    }
  }
  for (const p of report?.applied_paths || []) {
    keys.add(String(p).includes(".") ? String(p).split(".")[0] : String(p))
  }
  return keys
}

/**
 * 「本次映射有以下模块发生变动」汇总块（蓝框，参考智联样式）
 * moduleLabelMap: 平台模块 key → 中文名（各 Tab 自带，如 works→工作经历）
 */
export function ModuleChangeSummary({
  report,
  moduleLabelMap,
  className = "",
}: {
  report: PlatformReport | null
  moduleLabelMap: Record<string, string>
  className?: string
}) {
  if (!report?.fields) return null
  const changedModules = new Set<string>()
  for (const f of report.fields) {
    if (f.changed) {
      const root = String(f.path).includes(".") ? String(f.path).split(".")[0] : String(f.path)
      changedModules.add(moduleLabelMap[root] || root)
    }
  }
  if (changedModules.size === 0) return null
  return (
    <div className={`mt-3 px-4 py-3 rounded-lg bg-blue-50/80 border border-blue-200 text-sm text-blue-900 ${className}`}>
      <div className="font-medium mb-1">本次映射有以下模块发生变动：</div>
      <ul className="ml-4 list-disc space-y-0.5 text-blue-800">
        {[...changedModules].map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
    </div>
  )
}

/**
 * 模块级警告分发条（琥珀色黄框，渲染在各模块卡片顶部）：
 * 从报告 warnings 里筛选与该模块相关的条目**完整展示**（用户要求模块内看到全部相关内容）。
 * matchKeywords：命中任一关键词即归入该模块（如工作经历：["work_experience", "工作经历", "职位类目"]）
 */
export function ModuleReportNotice({
  warnings,
  matchKeywords,
  title,
  className = "",
}: {
  warnings?: string[]
  matchKeywords: string[]
  title: string
  className?: string
}) {
  const related = (warnings || []).filter((w) => matchKeywords.some((k) => w.includes(k)))
  if (related.length === 0) return null
  return (
    <div className={`mb-3 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-xs text-amber-700 ${className}`}>
      <div className="font-medium mb-1">{title}（{related.length} 条）</div>
      <ul className="ml-3 list-disc space-y-0.5">
        {related.map((w, i) => (
          <li key={i}>{w.replace(/⚠/g, "").replace(/^△\s*/, "")}</li>
        ))}
      </ul>
    </div>
  )
}

/**
 * 报告字段值就地编辑（Q-M5-3 接页面：POST /api/agent-map/save-edits 闲置端点接 UI）。
 * 在映射报告卡内展开字段清单，修改值后「保存编辑」落盘到报告文件（未写入平台数据），
 * 后续「应用映射」以编辑后的值为准。
 */
export function ReportFieldEdits({ platform, report, onSaved }: {
  platform: string
  report: PlatformReport
  onSaved?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // 仅标量字段可编辑；数组/对象字段展示只读摘要（save-edits 契约为 path→value 覆写）
  const isScalar = (v: unknown) => ["string", "number", "boolean"].includes(typeof v)
  const editableFields = report.fields.filter((f) => isScalar(f.value))
  const readOnlyFields = report.fields.filter((f) => !isScalar(f.value))
  const isDirty = (f: MappedField) => drafts[f.path] !== undefined && drafts[f.path] !== String(f.value ?? "")
  const changed = editableFields.filter(isDirty)
  // 非法草稿阻止保存：数值空串/非数（Number("")===0 的空串陷阱）、布尔仅接受 "true"/"false"
  const invalidFields = editableFields.filter((f) => {
    if (!isDirty(f)) return false
    const draft = drafts[f.path]
    if (typeof f.value === "number") return draft.trim() === "" || !Number.isFinite(Number(draft))
    if (typeof f.value === "boolean") return draft !== "true" && draft !== "false"
    return false
  })

  const coerce = (orig: unknown, draft: string) => {
    if (typeof orig === "number") return Number(draft)
    if (typeof orig === "boolean") return draft === "true"
    return draft
  }

  const handleSave = async () => {
    if (changed.length === 0 || invalidFields.length > 0) return
    setSaving(true)
    setMsg(null)
    try {
      const res = await fetch(`${API_BASE}/api/agent-map/save-edits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform,
          entries: changed
            .filter((f) => !invalidFields.some((inv) => inv.path === f.path))
            .map((f) => ({ path: f.path, value: coerce(f.value, drafts[f.path]) })),
        }),
      })
      const result = await res.json()
      if (result.success) {
        setMsg({ ok: true, text: result.message || `已保存 ${result.saved} 项编辑` })
        setDrafts({})
        onSaved?.()
      } else {
        setMsg({ ok: false, text: result.message || "保存失败" })
      }
    } catch (e) {
      setMsg({ ok: false, text: "保存失败: " + e })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs cursor-pointer text-gray-500 hover:text-gray-800 underline decoration-dotted"
      >
        {open ? "收起字段编辑" : `编辑字段值（${editableFields.length} 个可编辑）`}
      </button>
      {open && (
        <div className="mt-2 border border-gray-100 rounded-lg p-2 space-y-2 max-h-64 overflow-y-auto bg-gray-50/60">
          {editableFields.map((f) => {
            const draft = drafts[f.path]
            const val = draft ?? String(f.value ?? "")
            const isDirty = draft !== undefined && draft !== String(f.value ?? "")
            return (
              <div key={f.path} className="flex items-center gap-2">
                <span className="w-[38%] shrink-0 truncate text-[11px] text-gray-500" title={f.path}>
                  {f.translation || f.note || f.path}
                </span>
                <input
                  className={`flex-1 h-7 px-2 text-xs border rounded-md focus:outline-none ${isDirty ? "border-amber-400 bg-amber-50/60" : "border-gray-200 bg-white"}`}
                  value={val}
                  placeholder={typeof f.value === "number" ? "数字" : typeof f.value === "boolean" ? "true / false" : ""}
                  onChange={(e) => setDrafts((prev) => ({ ...prev, [f.path]: e.target.value }))}
                />
              </div>
            )
          })}
          {readOnlyFields.length > 0 && (
            <div className="text-[11px] text-gray-400 pt-1 border-t border-gray-100">
              另有 {readOnlyFields.length} 个结构化字段（数组/对象）不支持就地编辑
            </div>
          )}
          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || changed.length === 0 || invalidFields.length > 0}
              className="h-7 px-3 text-xs rounded-md bg-gray-800 text-white hover:bg-gray-700 disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              {saving ? "保存中..." : `保存编辑（${changed.length}）`}
            </button>
            {invalidFields.length > 0 && (
              <span className="text-[11px] text-rose-600">
                {invalidFields.length} 项草稿非法（数值不可为空/非数，布尔仅接受 true/false），已阻止保存
              </span>
            )}
            {msg && (
              <span className={`text-[11px] ${msg.ok ? "text-emerald-600" : "text-rose-600"}`}>{msg.text}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
