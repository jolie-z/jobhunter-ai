"use client"

import React, { useState, useEffect, useMemo } from "react"
import { Loader2, Flame, CheckCircle, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"

export interface GrillSuggestion {
  section_title: string
  signal: string
  direction: string
  priority: "high" | "medium"
}

export interface GrillSuggestionPanelProps {
  /** AI 原始建议（来自 /grill_suggestion 接口） */
  suggestions: GrillSuggestion[]
  /** 当前画布所有二级经历（用于把建议匹配到 sectionId） */
  sections: { id: string; title: string; isArchived?: boolean }[]
  /** 是否正在加载 */
  isLoading: boolean
  /** 用户点击「开始深度拷问」时，回传勾选的 sectionId 列表 */
  onStartGrill: (sectionIds: string[]) => void
  /** 用户点击「跳过此步」 */
  onSkip: () => void
}

/**
 * Step 3 入口面板：渲染 AI 的「深挖建议」列表，让用户勾选要 Grill 的经历。
 * 建议的 section_title 会和当前画布的二级经历 title 进行匹配，得到 sectionId。
 */
export function GrillSuggestionPanel({
  suggestions,
  sections,
  isLoading,
  onStartGrill,
  onSkip,
}: GrillSuggestionPanelProps) {
  // 建议项 → sectionId 的匹配（取相似度最高的，找不到则 undefined）
  const matchedSuggestions = useMemo(() => {
    const activeLevel2 = sections.filter(s => !s.isArchived)
    return suggestions.map(sg => {
      let bestId: string | undefined = undefined
      let bestScore = 0
      for (const sec of activeLevel2) {
        const score = titleSimilarity(sg.section_title, sec.title)
        if (score > bestScore) {
          bestScore = score
          bestId = sec.id
        }
      }
      return { ...sg, _sectionId: bestId, _score: bestScore }
    })
  }, [suggestions, sections])

  // 默认全部勾选高优先级 + 能匹配上的建议
  const [checkedTitles, setCheckedTitles] = useState<Set<string>>(new Set())
  useEffect(() => {
    const initChecked = new Set<string>(
      matchedSuggestions
        .filter(s => s.priority === "high" && s._sectionId)
        .map(s => s.section_title)
    )
    setCheckedTitles(initChecked)
  }, [matchedSuggestions])

  const toggleCheck = (title: string) => {
    setCheckedTitles(prev => {
      const next = new Set(prev)
      if (next.has(title)) next.delete(title)
      else next.add(title)
      return next
    })
  }

  const handleStart = () => {
    // 收集勾选项 → 对应 sectionId（去重，剔除无匹配项）
    const ids = matchedSuggestions
      .filter(s => checkedTitles.has(s.section_title) && s._sectionId)
      .map(s => s._sectionId as string)
    const uniqueIds = Array.from(new Set(ids))
    onStartGrill(uniqueIds)
  }

  const checkedCount = matchedSuggestions.filter(
    s => checkedTitles.has(s.section_title) && s._sectionId
  ).length

  if (isLoading) {
    return (
      <div className="mt-3 flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50/70 p-3 text-xs text-orange-800">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        正在分析全量简历与 JD，挑出值得深挖的经历...
      </div>
    )
  }

  if (matchedSuggestions.length === 0) {
    return (
      <div className="mt-3 flex items-center justify-between rounded-lg border border-green-200 bg-green-50/70 p-3">
        <div className="flex items-center gap-2 text-xs text-green-800">
          <CheckCircle className="h-3.5 w-3.5" />
          AI 认为当前简历已经足够详实，没有明显薄弱段落需要深挖。
        </div>
        <Button size="sm" className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white" onClick={onSkip}>
          直接进入下一步 <ChevronRight className="ml-1 h-3 w-3" />
        </Button>
      </div>
    )
  }

  return (
    <div className="mt-3 rounded-lg border border-orange-200 bg-orange-50/50 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <Flame className="h-3.5 w-3.5 text-orange-600" />
        <span className="text-xs font-bold text-orange-800">AI 深挖建议（请勾选要 Grill 的经历）</span>
      </div>

      <div className="max-h-[260px] space-y-2 overflow-y-auto pr-1">
        {matchedSuggestions.map((sg, idx) => {
          const checked = checkedTitles.has(sg.section_title)
          const noMatch = !sg._sectionId
          return (
            <label
              key={idx}
              className={`flex cursor-pointer items-start gap-2 rounded-md border bg-white/80 p-2 transition-colors ${
                noMatch ? "cursor-not-allowed opacity-50" : "hover:bg-orange-50"
              } ${checked ? "border-orange-300" : "border-slate-200"}`}
            >
              <Checkbox
                checked={checked}
                disabled={noMatch}
                onCheckedChange={() => toggleCheck(sg.section_title)}
                className="mt-0.5"
              />
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs font-semibold text-slate-800 break-all">
                    {sg._sectionId
                      ? (sections.find(s => s.id === sg._sectionId)?.title || sg.section_title)
                      : sg.section_title}
                  </span>
                  <Badge
                    variant="outline"
                    className={`shrink-0 px-1 py-0 text-[9px] ${
                      sg.priority === "high"
                        ? "border-red-300 bg-red-50 text-red-600"
                        : "border-amber-300 bg-amber-50 text-amber-700"
                    }`}
                  >
                    {sg.priority === "high" ? "高优先" : "中优先"}
                  </Badge>
                  <Badge variant="outline" className="shrink-0 px-1 py-0 text-[9px] text-slate-600">
                    {sg.signal}
                  </Badge>
                  {noMatch && (
                    <span className="shrink-0 text-[9px] text-slate-400">(画布未找到)</span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-slate-600" style={{ overflowWrap: 'break-word', wordBreak: 'break-all' }}>{sg.direction}</p>
              </div>
            </label>
          )
        })}
      </div>

      <div className="mt-3 flex items-center justify-end gap-2">
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs border-orange-300 text-orange-700 hover:bg-orange-100"
          onClick={onSkip}
        >
          跳过深挖
        </Button>
        <Button
          size="sm"
          className="h-7 text-xs bg-orange-500 hover:bg-orange-600 text-white disabled:opacity-50"
          disabled={checkedCount === 0}
          onClick={handleStart}
        >
          <Flame className="mr-1 h-3 w-3" /> 开始深度拷问 ({checkedCount} 段)
        </Button>
      </div>
    </div>
  )
}

/** 简易标题相似度：基于字符包含关系打分，0~1。 */
function titleSimilarity(a: string, b: string): number {
  if (!a || !b) return 0
  const na = a.trim()
  const nb = b.trim()
  if (na === nb) return 1
  if (na.includes(nb) || nb.includes(na)) return 0.8
  // 取交集字符数比例
  const setA = new Set(na)
  const setB = new Set(nb)
  let common = 0
  setA.forEach(c => {
    if (setB.has(c)) common++
  })
  return common / Math.max(setA.size, setB.size)
}
