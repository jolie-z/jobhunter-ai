"use client"

import { useState } from "react"
import { History } from "lucide-react"
import { cn } from "@/lib/utils"

export interface HistoryItem {
  id: number
  keyword: string
  city: string
  salary: string
  jobs_added: number
  source: string
  used_at: string
}

interface ScrapeHistorySectionProps {
  history: HistoryItem[]
  onDeleteHistory: (id: number) => void
}

export function ScrapeHistorySection({ history, onDeleteHistory }: ScrapeHistorySectionProps) {
  const [showHistory, setShowHistory] = useState(false)

  return (
    <div className="border-t border-border/60 pt-2">
      <button
        type="button"
        onClick={() => setShowHistory((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground font-medium transition-colors"
      >
        <History className="h-3.5 w-3.5 text-violet-500" />
        <span>历史抓取与归档留痕 ({history.length})</span>
        <span className="text-[10px] text-muted-foreground font-normal">
          {showHistory ? "点击收起" : "展开查看曾经抓过的条件"}
        </span>
      </button>

      {showHistory && (
        <div className="mt-2 space-y-1.5 max-h-40 overflow-y-auto rounded-xl border border-border/60 bg-muted/20 p-2">
          {history.length === 0 ? (
            <p className="text-center py-2 text-[10px] text-muted-foreground">暂无历史记录</p>
          ) : (
            history.map((h) => (
              <div
                key={h.id}
                className="flex items-center justify-between gap-2 rounded-md bg-background px-2 py-1 text-[10px] border border-border/50"
              >
                <div className="flex items-center gap-2 truncate">
                  <span className="font-semibold text-foreground truncate">{h.keyword}</span>
                  <span className="text-muted-foreground">
                    {h.city || "广州"} · {h.salary || "不限"}
                  </span>
                  <span
                    className={cn(
                      "rounded px-1 text-[9px] font-medium",
                      h.source === "archive"
                        ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                        : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                    )}
                  >
                    {h.source === "archive" ? "手动归档" : `实抓+${h.jobs_added}`}
                  </span>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="font-mono text-[9px] text-muted-foreground">
                    {(h.used_at || "").replace("T", " ").slice(0, 16)}
                  </span>
                  <button
                    type="button"
                    onClick={() => onDeleteHistory(h.id)}
                    className="text-muted-foreground hover:text-rose-500 ml-1 p-0.5"
                    title="删除此条历史记录"
                  >
                    ×
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
