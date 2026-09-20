"use client"

import { useState, useRef } from "react"
import { Sparkles, Plus, Trash2, Loader2, Bot, ShieldCheck, ShieldAlert, Info } from "lucide-react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { API_BASE } from "@/lib/api"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface AIScoutRule {
  keyword: string
  condition: "must" | "never"
  desc: string
}

interface AIScoutRulesTableProps {
  rules: AIScoutRule[]
  onChange: (rules: AIScoutRule[]) => void
}

export function AIScoutRulesTable({ rules, onChange }: AIScoutRulesTableProps) {
  const [predictingIdx, setPredictingIdx] = useState<number | null>(null)

  // 稳定 key 池：与 rules 下标一一对应，删除行时同步 splice，保证删除中间行后其余行 key 不变（避免用 idx 作 key 导致错位）
  const ruleKeysRef = useRef<string[]>([])
  const ruleKeyIdRef = useRef(0)
  while (ruleKeysRef.current.length < rules.length) {
    ruleKeysRef.current.push(`ai-scout-rule-${ruleKeyIdRef.current++}`)
  }

  // 辅助 AI 自动生成提示词判定语
  const handlePredictDesc = async (idx: number) => {
    const rule = rules[idx]
    if (!rule.keyword.trim()) {
      toast.error("请先输入规则关键词")
      return
    }

    setPredictingIdx(idx)
    try {
      const res = await fetch(`${API_BASE}/api/strategy/predict_desc`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword: rule.keyword.trim() }),
      })
      const data = await res.json()
      if (res.ok && data.status === "success" && data.data) {
        // 不可变更新：仅浅拷贝被修改的规则项，避免原地修改 state 对象
        const newRules = rules.map((r, i) => (i === idx ? { ...r, desc: data.data } : r))
        onChange(newRules)
        toast.success(`已为「${rule.keyword}」自动生成 AI 判定标准`)
      } else {
        toast.error(data.message || "生成失败，请重试")
      }
    } catch {
      toast.error("AI 辅助服务网络请求异常")
    } finally {
      setPredictingIdx(null)
    }
  }

  const handleAddRule = () => {
    onChange([...rules, { keyword: "", condition: "never", desc: "" }])
  }

  const handleDeleteRule = (idx: number) => {
    // 与 rules 同步 splice key 池，保证删除后其余行 key 稳定
    ruleKeysRef.current.splice(idx, 1)
    onChange(rules.filter((_, i) => i !== idx))
  }

  const handleUpdateRule = (idx: number, patch: Partial<AIScoutRule>) => {
    const newRules = [...rules]
    newRules[idx] = { ...newRules[idx], ...patch }
    onChange(newRules)
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-card/60 p-4 shadow-xs backdrop-blur-xs space-y-3.5">
      {/* 极简顶栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-purple-500/10 text-purple-600 dark:text-purple-400 font-bold text-[11px]">
            T2
          </div>
          <span className="text-xs font-semibold text-foreground tracking-tight">
            Tier 2 大模型初筛规则表 (AI 侦察兵 · {rules.length} 条)
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors cursor-help p-0.5 rounded-full hover:bg-muted"
              >
                <Info className="h-3.5 w-3.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed p-2.5">
              应对正则难以穷举的复杂语义红线（如：外包、单休、销售、培训生等）。大模型将根据设定的“判定标准与伪表述排除”执行深度语义审查。
            </TooltipContent>
          </Tooltip>
        </div>

        <button
          type="button"
          onClick={handleAddRule}
          className="flex items-center gap-1 rounded-lg bg-purple-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-purple-500 transition-all active:scale-95 shadow-xs shrink-0 cursor-pointer"
        >
          <Plus className="h-3 w-3" />
          <span>添加规则</span>
        </button>
      </div>

      {/* 规则卡片列表 */}
      <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
        {rules.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-6 rounded-xl border border-dashed border-border/70 bg-muted/20 text-center">
            <Bot className="h-6 w-6 text-muted-foreground/50 mb-1.5" />
            <p className="text-xs font-medium text-foreground">暂无 AI 侦察兵规则</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              点击右上角添加规则，定义如“外包、单休、销售”等复杂语义红线。
            </p>
          </div>
        ) : (
          rules.map((rule, idx) => {
            const isMust = rule.condition === "must"
            const isPredicting = predictingIdx === idx

            return (
              <div
                key={ruleKeysRef.current[idx] ?? `ai-scout-rule-fallback-${idx}`}
                className={cn(
                  "rounded-xl border p-3 bg-background/80 transition-all space-y-2",
                  isMust
                    ? "border-emerald-500/30 hover:border-emerald-500/60"
                    : "border-rose-500/30 hover:border-rose-500/60"
                )}
              >
                {/* 顶部：关键词 + 条件切换 + AI 辅助生成 + 删除 */}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[10px] font-mono font-bold text-muted-foreground shrink-0">
                      {idx + 1}
                    </span>

                    {/* 规则词输入 */}
                    <div className="flex items-center gap-1">
                      <span className="text-xs text-muted-foreground whitespace-nowrap">规则词:</span>
                      <input
                        type="text"
                        placeholder="如: 单休 / 外包"
                        value={rule.keyword}
                        onChange={(e) => handleUpdateRule(idx, { keyword: e.target.value })}
                        className="h-7 w-28 sm:w-36 rounded-lg border border-border bg-background px-2 text-xs font-semibold focus:border-purple-500 focus:outline-none"
                      />
                    </div>

                    {/* 条件切换 */}
                    <div className="inline-flex items-center rounded-lg border border-border/80 bg-muted/30 p-0.5 text-xs shrink-0">
                      <button
                        type="button"
                        onClick={() => handleUpdateRule(idx, { condition: "must" })}
                        className={cn(
                          "flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition-all cursor-pointer",
                          isMust
                            ? "bg-emerald-600 text-white shadow-xs font-semibold"
                            : "text-muted-foreground hover:text-foreground"
                        )}
                      >
                        <ShieldCheck className="h-3 w-3" />
                        <span>必须包含</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleUpdateRule(idx, { condition: "never" })}
                        className={cn(
                          "flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition-all cursor-pointer",
                          !isMust
                            ? "bg-rose-600 text-white shadow-xs font-semibold"
                            : "text-muted-foreground hover:text-foreground"
                        )}
                      >
                        <ShieldAlert className="h-3 w-3" />
                        <span>绝不包含 (一票淘汰)</span>
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      type="button"
                      onClick={() => handlePredictDesc(idx)}
                      disabled={isPredicting}
                      className="flex items-center gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-500/20 transition-all disabled:opacity-50 cursor-pointer"
                      title="AI 辅助自动生成判定标准"
                    >
                      {isPredicting ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="h-3 w-3 text-amber-500" />
                      )}
                      <span>{isPredicting ? "生成中…" : "AI 生成标准"}</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleDeleteRule(idx)}
                      className="rounded-lg p-1 text-muted-foreground hover:bg-rose-500/10 hover:text-rose-500 transition-colors cursor-pointer"
                      title="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                {/* 判定标准输入 */}
                <div>
                  <input
                    type="text"
                    placeholder="判定标准与伪表述排除（如：大小周、单双休均属于单休；公司介绍提及不属于）"
                    value={rule.desc}
                    onChange={(e) => handleUpdateRule(idx, { desc: e.target.value })}
                    className="h-8 w-full rounded-lg border border-border bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground/60 focus:border-purple-500 focus:outline-none"
                  />
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
