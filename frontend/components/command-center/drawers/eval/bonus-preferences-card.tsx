"use client"

import { useState } from "react"
import { Heart, Plus, Trash2, Info, Edit3, Check, X, ChevronDown, ChevronUp } from "lucide-react"
import { cn } from "@/lib/utils"
import { Switch } from "@/components/ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface PreferenceItem {
  record_id?: string
  type: string
  rule: string
  status: string
}

interface BonusPreferencesCardProps {
  preferences: PreferenceItem[]
  onAddPreference: (type: string, rule: string) => Promise<void>
  onUpdatePreference: (item: PreferenceItem) => Promise<void>
  onToggleStatus: (item: PreferenceItem) => Promise<void>
  onDeletePreference: (recordId: string) => Promise<void>
}

export function BonusPreferencesCard({
  preferences,
  onAddPreference,
  onUpdatePreference,
  onToggleStatus,
  onDeletePreference,
}: BonusPreferencesCardProps) {
  const [newType, setNewType] = useState("核心加分")
  const [newRule, setNewRule] = useState("")
  const [adding, setAdding] = useState(false)

  // 编辑态状态管理
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState("")
  const [editingType, setEditingType] = useState("核心加分")

  // 展开查看更多状态
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const handleAdd = async () => {
    if (!newRule.trim() || adding) return
    setAdding(true)
    try {
      await onAddPreference(newType, newRule.trim())
      setNewRule("")
    } finally {
      setAdding(false)
    }
  }

  const startEdit = (item: PreferenceItem) => {
    setEditingId(item.record_id || null)
    setEditingText(item.rule)
    setEditingType(item.type)
  }

  const saveEdit = async (item: PreferenceItem) => {
    if (!editingText.trim()) return
    await onUpdatePreference({
      ...item,
      type: editingType,
      rule: editingText.trim(),
    })
    setEditingId(null)
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card p-4.5 space-y-3.5 shadow-xs">
      {/* 顶栏 */}
      <div className="flex items-center justify-between border-b border-border/50 pb-2.5">
        <div className="flex items-center gap-2">
          <Heart className="h-4 w-4 text-rose-500 fill-rose-500/20" />
          <span className="font-semibold text-foreground text-xs">
            求职偏好与核心加分项
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button type="button" className="text-muted-foreground/60 hover:text-foreground transition-colors">
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs p-2.5 bg-zinc-900 text-zinc-100 dark:bg-zinc-800 dark:text-zinc-100 border border-zinc-700 shadow-xl rounded-xl leading-relaxed">
              此处设置的偏好规则会在初评时直接注入大模型 Prompt，作为匹配度加分与意向过滤的关键依据。
            </TooltipContent>
          </Tooltip>
        </div>

        <span className="text-[10px] text-muted-foreground font-mono">
          已生效 {preferences.filter((p) => p.status === "启用").length} / {preferences.length} 条
        </span>
      </div>

      {/* 规则条目列表 */}
      <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
        {preferences.length === 0 ? (
          <div className="py-4 text-center text-xs text-muted-foreground bg-muted/10 rounded-xl border border-dashed border-border/60">
            暂无加分偏好规则，可在下方输入添加（如：具备大模型实战经验 / 理想薪资15k+）
          </div>
        ) : (
          preferences.map((item, idx) => {
            const isEnabled = item.status === "启用"
            const isEditing = editingId === item.record_id
            const isExpanded = expandedId === item.record_id

            if (isEditing) {
              return (
                <div
                  key={item.record_id || idx}
                  className="p-3 rounded-xl border border-violet-500/40 bg-violet-500/5 space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <select
                      value={editingType}
                      onChange={(e) => setEditingType(e.target.value)}
                      className="h-7 rounded-lg border border-border bg-background px-2 text-[11px] font-medium"
                    >
                      <option value="核心加分">📈 核心加分</option>
                      <option value="职业愿景">🎯 职业愿景</option>
                    </select>

                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => saveEdit(item)}
                        className="inline-flex items-center gap-1 rounded-lg bg-foreground text-background px-2.5 py-1 text-[11px] font-medium hover:opacity-90 active:scale-95 transition-all"
                      >
                        <Check className="h-3 w-3" />
                        <span>保存</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        className="rounded-lg border border-border bg-background p-1 text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  </div>

                  <textarea
                    value={editingText}
                    onChange={(e) => setEditingText(e.target.value)}
                    rows={3}
                    className="w-full rounded-lg border border-border bg-background p-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-violet-500 resize-y"
                  />
                </div>
              )
            }

            return (
              <div
                key={item.record_id || idx}
                className={cn(
                  "p-3 rounded-xl border transition-all space-y-1.5",
                  isEnabled
                    ? "bg-muted/20 border-border/60 hover:border-border"
                    : "bg-muted/5 border-border/30 opacity-60"
                )}
              >
                {/* 顶栏：标签 + 开关 + 动作 */}
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-bold shrink-0 border",
                      item.type === "职业愿景"
                        ? "bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/20"
                        : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20"
                    )}
                  >
                    {item.type}
                  </span>

                  <div className="flex items-center gap-2 shrink-0">
                    <Switch
                      checked={isEnabled}
                      onCheckedChange={() => onToggleStatus(item)}
                    />
                    <button
                      type="button"
                      onClick={() => startEdit(item)}
                      className="text-muted-foreground/60 hover:text-violet-600 p-1 rounded transition-colors"
                      title="编辑完整内容"
                    >
                      <Edit3 className="h-3 w-3" />
                    </button>
                    {item.record_id && (
                      <button
                        type="button"
                        onClick={() => onDeletePreference(item.record_id!)}
                        className="text-muted-foreground/50 hover:text-rose-500 p-1 rounded transition-colors"
                        title="移除此项"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>

                {/* 正文：支持完整展示与点击展开全部 */}
                <div
                  onClick={() => setExpandedId(isExpanded ? null : item.record_id || null)}
                  className="cursor-pointer group"
                >
                  <p
                    className={cn(
                      "text-xs text-foreground/90 font-normal leading-relaxed transition-all",
                      isExpanded ? "" : "line-clamp-2"
                    )}
                  >
                    {item.rule}
                  </p>
                  {item.rule.length > 50 && (
                    <span className="text-[10px] text-violet-600 dark:text-violet-400 mt-0.5 inline-flex items-center gap-0.5 font-medium hover:underline">
                      {isExpanded ? (
                        <>
                          <span>收起完整内容</span>
                          <ChevronUp className="h-2.5 w-2.5" />
                        </>
                      ) : (
                        <>
                          <span>查看完整内容</span>
                          <ChevronDown className="h-2.5 w-2.5" />
                        </>
                      )}
                    </span>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* 快捷录入栏 */}
      <div className="pt-2 flex items-center gap-2 border-t border-border/50">
        <select
          value={newType}
          onChange={(e) => setNewType(e.target.value)}
          className="h-8 rounded-xl border border-border bg-background px-2 text-[11px] font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-violet-500 shrink-0"
        >
          <option value="核心加分">📈 核心加分</option>
          <option value="职业愿景">🎯 职业愿景</option>
        </select>

        <input
          type="text"
          placeholder="输入新加分要点，如：精通 LangGraph 架构 / 偏好远程办公"
          value={newRule}
          onChange={(e) => setNewRule(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleAdd()
          }}
          className="flex-1 h-8 rounded-xl border border-border bg-background px-3 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-violet-500"
        />

        <button
          type="button"
          onClick={handleAdd}
          disabled={!newRule.trim() || adding}
          className="h-8 inline-flex items-center gap-1 rounded-xl bg-violet-600/10 text-violet-700 dark:text-violet-300 hover:bg-violet-600/20 px-3 text-xs font-medium active:scale-95 transition-all disabled:opacity-40 shrink-0"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>添加</span>
        </button>
      </div>
    </div>
  )
}
