"use client"

import React from "react"
import { parseJobDescription } from "@/lib/utils/job-description"

/**
 * 岗位详情结构化渲染：章节标题 + 编号条目 + 段落。
 * 猎聘正文在采集端被压成一整行，这里在渲染层还原结构；其余平台已带换行，效果等价。
 */
export function JobDescriptionView({
  text,
  className = "",
}: {
  text?: string | null
  className?: string
}) {
  const blocks = parseJobDescription(text || "")

  if (blocks.length === 0) {
    return (
      <div className={`rounded-xl border border-border bg-muted/50 p-4 text-sm text-muted-foreground ${className}`}>
        暂无岗位详情
      </div>
    )
  }

  return (
    <div className={`rounded-xl border border-border bg-muted/50 p-4 ${className}`}>
      <div className="space-y-2">
        {blocks.map((block, index) => {
          if (block.kind === "heading") {
            return (
              <h4
                key={index}
                className="flex items-center gap-2 pt-2 text-[13px] font-semibold leading-5 text-foreground first:pt-0"
              >
                <span className="h-3.5 w-1 shrink-0 rounded-full bg-primary" />
                {block.text}
              </h4>
            )
          }

          if (block.kind === "item") {
            return (
              <div key={index} className="flex gap-2.5">
                <span className="mt-0.5 flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md bg-primary/10 px-1 text-[11px] font-semibold tabular-nums text-primary">
                  {block.marker}
                </span>
                <p className="min-w-0 flex-1 text-sm leading-6 text-foreground/90">{block.text}</p>
              </div>
            )
          }

          return (
            <p key={index} className="text-sm leading-7 text-foreground/90">
              {block.text}
            </p>
          )
        })}
      </div>
    </div>
  )
}
