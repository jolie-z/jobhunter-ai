"use client"

import React, { useMemo } from "react"
import ReactMarkdown from "react-markdown"

interface EvaluationDimensionsCardProps {
  detailText: string
}

interface DimensionItem {
  title: string
  score: string
  description: string
}

function getScoreBadgeClass(score: string) {
  if (score.includes("5/5") || score.startsWith("5")) {
    return "bg-emerald-50 text-emerald-700 border-emerald-200/80 dark:bg-emerald-950/30 dark:text-emerald-300"
  }
  if (score.includes("4/5") || score.startsWith("4")) {
    return "bg-violet-50 text-violet-700 border-violet-200/80 dark:bg-violet-950/30 dark:text-violet-300"
  }
  if (score.includes("3/5") || score.startsWith("3")) {
    return "bg-amber-50 text-amber-700 border-amber-200/80 dark:bg-amber-950/30 dark:text-amber-300"
  }
  if (score.includes("1/5") || score.includes("2/5") || score.startsWith("1") || score.startsWith("2")) {
    return "bg-rose-50 text-rose-700 border-rose-200/80 dark:bg-rose-950/30 dark:text-rose-300"
  }
  return "bg-zinc-100 text-zinc-700 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-300"
}

export function EvaluationDimensionsCard({ detailText }: EvaluationDimensionsCardProps) {
  const { items, isStructured } = useMemo(() => {
    if (!detailText || !detailText.trim()) {
      return { items: [], isStructured: false }
    }

    const raw = detailText.trim()
    // 按段落分割（支持双换行，或紧跟的 **【 或 【）
    const blocks = raw
      .split(/\n\s*\n|(?<=\n)(?=\*\*【|【)/)
      .map((b) => b.trim())
      .filter(Boolean)

    const parsedItems: DimensionItem[] = []

    for (const b of blocks) {
      // 匹配 **【维度】** 分数 \n 描述 或 【维度】 分数 \n 描述
      const match = b.match(
        /^(?:\*\*)?【([^\n】\*\:]+?)】(?:\*\*)?\s*[:：]?\s*([0-9\/\.\s分]+)?\s*\n*([\s\S]*)$/
      )
      if (match) {
        const title = match[1].trim()
        const score = (match[2] || "").trim()
        const description = (match[3] || "").trim()
        parsedItems.push({ title, score, description })
      }
    }

    if (parsedItems.length > 0) {
      return { items: parsedItems, isStructured: true }
    }

    return { items: [], isStructured: false }
  }, [detailText])

  if (!detailText || !detailText.trim()) {
    return <p className="text-[11px] text-muted-foreground py-1">暂无诊断数据，请先执行 AI 评估</p>
  }

  // 若成功解析出结构化维度，采用人类阅读极度友好的微卡片排版
  if (isStructured && items.length > 0) {
    return (
      <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
        {items.map((item, index) => {
          const badgeClass = getScoreBadgeClass(item.score)
          return (
            <div
              key={index}
              className="rounded-lg border border-violet-100/90 dark:border-violet-900/30 bg-white dark:bg-zinc-900/60 p-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.03)] transition-all hover:border-violet-300 dark:hover:border-violet-800"
            >
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="size-1.5 rounded-full bg-violet-500 shrink-0" />
                  <span className="text-[11px] font-semibold text-zinc-800 dark:text-zinc-200">
                    {item.title}
                  </span>
                </div>
                {item.score && (
                  <span
                    className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-mono font-bold border ${badgeClass}`}
                  >
                    {item.score}
                  </span>
                )}
              </div>
              {item.description && (
                <div className="text-[11px] leading-relaxed text-zinc-600 dark:text-zinc-400 pl-3 border-l-2 border-violet-100 dark:border-violet-900/40">
                  <ReactMarkdown
                    components={{
                      p: ({ children }) => <span>{children}</span>,
                      strong: ({ children }) => (
                        <strong className="font-semibold text-zinc-800 dark:text-zinc-200">
                          {children}
                        </strong>
                      ),
                    }}
                  >
                    {item.description}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  // 兜底排版：使用 ReactMarkdown 进行标准美观渲染，杜绝暴露裸露的 ** 语法符号
  return (
    <div className="text-[11px] text-zinc-700 dark:text-zinc-300 leading-relaxed bg-violet-50/50 dark:bg-violet-950/20 border border-violet-100 dark:border-violet-900/40 rounded-md p-2.5 max-h-72 overflow-y-auto">
      <ReactMarkdown
        components={{
          p: ({ children }) => <p className="mb-1.5 last:mb-0">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-violet-900 dark:text-violet-300">
              {children}
            </strong>
          ),
          ul: ({ children }) => <ul className="list-disc pl-4 space-y-1 mb-1.5">{children}</ul>,
          li: ({ children }) => <li>{children}</li>,
        }}
      >
        {detailText}
      </ReactMarkdown>
    </div>
  )
}
