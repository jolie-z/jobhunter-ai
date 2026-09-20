"use client"

import { useCallback, useEffect, useState } from "react"
import { Save, RefreshCw, Check, BookOpen, Lightbulb, Trash2, Undo2, ArrowRight, Key, ServerOff } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { GROUP_META, type Tutorial } from "./system-config-meta"
import { useStrategyStore } from "@/hooks/use-strategy-store"
import { apiFetch } from "@/lib/api"

interface FieldItem {
  key: string
  label: string
  value: string
  sensitive: boolean
}

interface ConfigGroup {
  group: string
  fields: FieldItem[]
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
        setSaved(true)
        setTimeout(() => setSaved(false), 2500)
        fetchConfig()
      }
    } catch {
      // silent
    } finally {
      setSaving(false)
    }
  }

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

  return (
    <div className="mx-auto max-w-6xl px-8 py-8 space-y-8">
      {/* 顶部环境与安全提示卡片 */}
      <div className="flex items-start justify-between gap-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs transition-all">
        <div className="flex items-start gap-3.5">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-slate-900 text-white shadow-xs">
            <Key className="size-5" />
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-sm font-semibold text-slate-900">底层服务凭据与模型路由</h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[10px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200/60">
                <span className="size-1.5 rounded-full bg-emerald-500" />
                本地安全写入
              </span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              API 密钥写入本地独立环境，页面不回显敏感明文；修改保存后即时生效（语音识别等少数项需重启）。如需撤回自定义值，可悬停目标字段点击「清除」回落至 <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-slate-700">.env</code> 默认值。
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-9">
        {groups.map((group) => {
          const meta = GROUP_META[group.group]
          const required = meta?.required ?? false

          return (
            <section key={group.group} className="space-y-3">
              {/* Group header: title + required badge + tutorial button */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                    {group.group}
                  </h3>
                  {required ? (
                    <span className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-0.5 text-[10px] font-medium text-rose-600 ring-1 ring-inset ring-rose-200/60">
                      必填
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 ring-1 ring-inset ring-slate-200/60">
                      选填
                    </span>
                  )}
                </div>
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
              </div>

              {/* Optional note */}
              {meta?.note && (
                <div className="flex items-start gap-2 rounded-xl border border-slate-200/70 bg-white/70 px-3.5 py-2.5 text-xs leading-relaxed text-slate-600 shadow-2xs backdrop-blur-xs">
                  <Lightbulb className="size-3.5 shrink-0 text-amber-500/80 mt-0.5" />
                  <span>{meta.note}</span>
                </div>
              )}

              {/* 飞书集成专属导流卡片 */}
              {group.group === "飞书" && (
                <div className="flex items-center justify-between rounded-xl border border-blue-500/20 bg-blue-50/50 px-4 py-3 text-xs text-blue-800 shadow-2xs">
                  <span className="flex items-center gap-2 font-medium">
                    <span className="flex size-5 items-center justify-center rounded-full bg-blue-500/10 text-blue-600">💡</span>
                    飞书长连接机器人状态、ChatOps 指令集与自动化战报推送已移至独立的「飞书集成中心」管理。
                  </span>
                  <button
                    type="button"
                    onClick={() => setSection("feishu")}
                    className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-700 hover:underline transition-colors"
                  >
                    前往飞书集成中心
                    <ArrowRight className="size-3.5" />
                  </button>
                </div>
              )}

              <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
                {group.fields.map((field) => {
                  const isEditing = field.key in edits
                  const isClearing = !!pendingClears[field.key]
                  // 敏感字段不回显后端遮罩值：输入框留空 = 保持现有配置，只有输入新值才会覆盖
                  const displayValue = isClearing
                    ? ""
                    : isEditing
                    ? edits[field.key]
                    : (field.sensitive ? "" : field.value)

                  const markClear = () => {
                    setPendingClears((prev) => ({ ...prev, [field.key]: true }))
                    setEdits((prev) => ({ ...prev, [field.key]: "" }))
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
                    <div
                      key={field.key}
                      className="group relative flex flex-col justify-between rounded-xl border border-slate-200/80 bg-white p-4 shadow-xs transition-all duration-200 hover:border-slate-300 hover:shadow-md"
                    >
                      <div>
                        <div className="mb-2 flex items-center justify-between">
                          <label className="text-xs font-semibold text-slate-700">
                            {field.label}
                          </label>
                          {field.sensitive && (
                            <span className="text-[10px] font-mono text-slate-400" title="加密密钥字段">
                              SECRET
                            </span>
                          )}
                        </div>

                        <input
                          type={field.sensitive ? "password" : "text"}
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
                              ? (field.value ? "已配置，留空保持不变" : "粘贴密钥...")
                              : "留空保持不变"
                          }
                          className={`w-full rounded-lg border px-3 py-2 text-[13px] transition-all focus:outline-none ${
                            isClearing
                              ? "border-rose-300 bg-rose-50/40 text-slate-400 line-through placeholder:text-rose-300"
                              : isEditing && edits[field.key]?.trim()
                              ? "border-amber-300 bg-amber-50/30 text-slate-900 focus:border-amber-400 focus:ring-2 focus:ring-amber-500/10"
                              : "border-slate-200 bg-slate-50/50 text-slate-800 placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-900/5"
                          } ${field.sensitive ? "font-mono" : ""}`}
                        />
                      </div>

                      <div className="mt-3 flex items-center justify-between pt-1">
                        <span className="font-mono text-[10px] text-slate-400 truncate max-w-[130px]" title={field.key}>
                          {field.key}
                        </span>

                        <div className="flex items-center gap-1.5 shrink-0">
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
                              className="rounded p-1 text-slate-300 opacity-0 transition-all hover:bg-rose-50 hover:text-rose-500 group-hover:opacity-100"
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
                })}
              </div>
            </section>
          )
        })}
      </div>

      {/* Sticky Save Bar */}
      <div className="sticky bottom-6 mt-12 flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving || dirtyCount === 0}
          className={`flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-semibold shadow-lg transition-all duration-200 ${
            dirtyCount > 0
              ? "bg-slate-900 text-white shadow-slate-900/15 hover:bg-slate-800 hover:shadow-xl hover:scale-[1.01] active:scale-[0.98]"
              : "bg-slate-200/80 text-slate-400 shadow-none cursor-not-allowed"
          }`}
        >
          {saving ? (
            <RefreshCw className="size-4 animate-spin text-slate-300" />
          ) : saved ? (
            <Check className="size-4 text-emerald-400" />
          ) : (
            <Save className={`size-4 ${dirtyCount > 0 ? "text-white" : "text-slate-400"}`} />
          )}
          <span>{saving ? "正在写入本地配置..." : saved ? "已成功保存配置" : "保存配置"}</span>
          {dirtyCount > 0 && !saving && (
            <span className="rounded-full bg-white/20 px-2 py-0.5 text-xs font-bold text-white">
              {dirtyCount}
            </span>
          )}
        </button>
      </div>

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
