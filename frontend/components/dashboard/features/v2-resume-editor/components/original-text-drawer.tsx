"use client"

/**
 * 「对照原文」抽屉（自包含触发按钮 + Sheet）：原文底稿 vs 当前结构化内容对照。
 *
 * 数据来源：后端快照目录（上传解析时留存的 original.md / 原件）。
 * 按需拉取：只在抽屉首次打开时请求 original_markdown，进编辑器不增加任何请求。
 * 老简历（上传早于快照功能）无 _meta.snapshot_id，Trigger 自动隐藏。
 */

import React, { useEffect, useState } from "react"
import { FileText, Loader2 } from "lucide-react"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { API_BASE } from "@/lib/api"

interface SnapshotData {
  snapshot_id: string
  source_filename: string
  source_available: boolean
  original_markdown: string
  created_at: string
}

interface OriginalTextTriggerProps {
  snapshotId?: string
}

export function OriginalTextTrigger({ snapshotId }: OriginalTextTriggerProps) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<SnapshotData | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 切换简历时清空缓存，防止抽屉显示旧简历底稿而下载按钮指向新简历
  useEffect(() => {
    setData(null)
    setError(null)
  }, [snapshotId])

  // 按需加载：首次打开才拉取（原文可能很大，避免进编辑器就发请求）
  const handleOpenChange = async (next: boolean) => {
    setOpen(next)
    if (next && snapshotId && !data && !loading) {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`${API_BASE}/api/strategy/resume_snapshot/${encodeURIComponent(snapshotId)}`)
        const json = await res.json()
        if (res.ok && json.status === "success") {
          setData(json.data)
        } else {
          setError(json.detail || "快照读取失败")
        }
      } catch {
        setError("网络异常，无法读取原文快照")
      } finally {
        setLoading(false)
      }
    }
  }

  if (!snapshotId) return null // 老简历无快照，不显示入口

  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        className="h-7 px-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-md flex items-center gap-1"
        onClick={() => handleOpenChange(true)}
      >
        <FileText className="size-3.5" />
        <span className="hidden lg:inline">对照原文</span>
      </Button>

      <Sheet open={open} onOpenChange={handleOpenChange}>
        <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2 text-base">
              <FileText className="size-4" />
              对照原文
              {data?.source_filename && (
                <span className="text-xs font-normal text-muted-foreground truncate max-w-[200px]">{data.source_filename}</span>
              )}
            </SheetTitle>
          </SheetHeader>

          <div className="px-4 pb-6">
            {data?.source_available && snapshotId && (
              <Button variant="outline" size="sm" className="mb-3" asChild>
                <a href={`${API_BASE}/api/strategy/resume_snapshot/${encodeURIComponent(snapshotId)}/file`} target="_blank" rel="noreferrer">
                  下载原件
                </a>
              </Button>
            )}

            {loading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
                <Loader2 className="size-4 animate-spin" />
                正在读取原文快照…
              </div>
            )}

            {error && <div className="text-sm text-destructive py-4">{error}</div>}

            {data && (
              <div className="rounded-md border bg-secondary/20 p-4 text-[13px] leading-relaxed prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.original_markdown}</ReactMarkdown>
              </div>
            )}

            <p className="mt-3 text-[11px] text-muted-foreground">
              本抽屉为上传原件的解析中间稿；请对照旁边编辑区的结构化内容，发现切错位/丢内容直接在编辑区修改。
            </p>
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}
