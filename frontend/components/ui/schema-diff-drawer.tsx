"use client"

import React, { useState } from "react"
import {
  Sparkles,
  PlusCircle,
  MinusCircle,
  Layers,
  CheckCircle2,
  X,
  AlertTriangle,
  RefreshCw,
  ArrowRight,
} from "lucide-react"

export interface SchemaDiffReport {
  platform: string
  has_changes: boolean
  summary: string
  added_fields: Array<{ module: string; field: string; type: string; sample?: any }>
  removed_fields: Array<{ module: string; field: string; last_value?: any }>
  new_modules: Array<{ module: string; type: string; item_count: number }>
  removed_modules: Array<{ module: string }>
  sub_list_changes: Array<{
    module: string
    parent_field: string
    added_keys: string[]
    removed_keys: string[]
  }>
  timestamp?: number
}

export interface SchemaDiffDrawerProps {
  isOpen: boolean
  onClose: () => void
  diff: SchemaDiffReport | null
  platformLabel?: string
  apiBase?: string
  onSyncSuccess?: () => void
}

export function SchemaDiffDrawer({
  isOpen,
  onClose,
  diff,
  platformLabel = "在线招聘平台",
  apiBase = "http://localhost:8000",
  onSyncSuccess,
}: SchemaDiffDrawerProps) {
  const [applying, setApplying] = useState(false)
  const [feedback, setFeedback] = useState<{ message: string; ok: boolean } | null>(null)

  if (!isOpen || !diff) return null

  const handleApplyPatch = async () => {
    setApplying(true)
    setFeedback(null)
    try {
      const res = await fetch(`${apiBase}/api/platforms/${diff.platform}/apply-schema-patch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ diff_result: diff }),
      })
      const result = await res.json()
      if (result.success) {
        setFeedback({ message: `✓ ${result.message || "模版对齐成功！"}`, ok: true })
        if (onSyncSuccess) onSyncSuccess()
        setTimeout(() => {
          onClose()
        }, 1200)
      } else {
        setFeedback({ message: result.message || "对齐失败", ok: false })
      }
    } catch (e: any) {
      setFeedback({ message: `网络异常: ${e.message || e}`, ok: false })
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl shadow-2xl border border-gray-100 max-w-xl w-full overflow-hidden flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-200">
        {/* 头部 */}
        <div className="bg-gradient-to-r from-indigo-600 via-indigo-700 to-purple-700 p-4 text-white flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-white/20 backdrop-blur-md flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-amber-300" />
            </div>
            <div>
              <h3 className="text-base font-semibold leading-tight">
                {platformLabel} · 模版动态自适应体检
              </h3>
              <p className="text-xs text-indigo-100/80 mt-0.5">
                实时探针已前置捕获官网最新 Schema 结构差异
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 主体差分清单 */}
        <div className="p-5 overflow-y-auto space-y-4 flex-1">
          {/* 摘要横幅 */}
          <div className="bg-indigo-50/80 border border-indigo-100 rounded-xl p-3.5 flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-indigo-600 shrink-0 mt-0.5" />
            <div className="text-xs text-indigo-900 leading-relaxed">
              <span className="font-semibold text-indigo-950">变动摘要：</span>
              {diff.summary}
            </div>
          </div>

          {/* 1. 全新模块 */}
          {diff.new_modules && diff.new_modules.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-blue-600" />
                <span>全新模块新增 ({diff.new_modules.length})</span>
              </div>
              <div className="space-y-1.5">
                {diff.new_modules.map((m, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between bg-blue-50/50 border border-blue-100 rounded-lg px-3 py-2 text-xs"
                  >
                    <span className="font-medium text-blue-900">{m.module}</span>
                    <span className="text-[11px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                      {m.type === "array" ? `列表 (${m.item_count} 项)` : "对象结构"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 2. 新增字段 */}
          {diff.added_fields && diff.added_fields.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
                <PlusCircle className="w-3.5 h-3.5 text-emerald-600" />
                <span>新增字段属性 ({diff.added_fields.length})</span>
              </div>
              <div className="grid grid-cols-1 gap-1.5">
                {diff.added_fields.map((f, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between bg-emerald-50/50 border border-emerald-100 rounded-lg px-3 py-2 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 font-mono text-[11px]">{f.module}.</span>
                      <span className="font-semibold text-emerald-900">{f.field}</span>
                    </div>
                    {f.sample !== undefined && f.sample !== null && (
                      <span className="text-[10px] text-emerald-600 truncate max-w-[140px]">
                        示例: {JSON.stringify(f.sample)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 3. 下线废弃字段 */}
          {diff.removed_fields && diff.removed_fields.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
                <MinusCircle className="w-3.5 h-3.5 text-amber-600" />
                <span>官网下线字段 ({diff.removed_fields.length})</span>
              </div>
              <div className="grid grid-cols-1 gap-1.5">
                {diff.removed_fields.map((f, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between bg-amber-50/50 border border-amber-100 rounded-lg px-3 py-2 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-gray-400 font-mono text-[11px]">{f.module}.</span>
                      <span className="font-medium text-amber-900 line-through">{f.field}</span>
                    </div>
                    <span className="text-[10px] text-amber-600 bg-amber-100/60 px-1.5 py-0.5 rounded">
                      将自动软归档备份
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 反馈提示 */}
          {feedback && (
            <div
              className={`p-3 rounded-xl text-xs font-medium flex items-center gap-2 ${
                feedback.ok
                  ? "bg-emerald-50 text-emerald-800 border border-emerald-200"
                  : "bg-red-50 text-red-800 border border-red-200"
              }`}
            >
              {feedback.ok ? <CheckCircle2 className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
              <span>{feedback.message}</span>
            </div>
          )}
        </div>

        {/* 底部操作条 */}
        <div className="p-4 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
          <div className="text-[11px] text-gray-500">
            同步后将自动创建历史快照备份，安全可回滚
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={applying}
              onClick={onClose}
              className="px-3.5 py-1.5 text-xs font-medium text-gray-600 bg-white hover:bg-gray-100 border border-gray-200 rounded-lg transition-colors"
            >
              暂不处理 (忽略)
            </button>
            <button
              type="button"
              disabled={applying}
              onClick={handleApplyPatch}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg shadow-sm transition-all disabled:opacity-50"
            >
              {applying ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>正在对齐模版...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5 text-amber-300" />
                  <span>确认一键同步模版</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
