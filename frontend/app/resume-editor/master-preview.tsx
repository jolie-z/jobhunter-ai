/**
 * 主简历预览（Q-M5-3 接页面：GET /api/agent-map/master 闲置端点接 UI）。
 * 动作栏「主简历预览」按钮 → 弹窗展示主简历来源/字数/模块清单与正文摘要。
 */
"use client"

import { API_BASE } from "@/lib/api"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { FileText, Loader2 } from "lucide-react"

interface MasterInfo {
  success: boolean
  source: string
  record_id?: string | null
  name?: string
  char_count: number
  message: string
  sections: string[]
}

export function MasterPreviewButton() {
  const [info, setInfo] = useState<MasterInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/agent-map/master?use_active=true`)
      const json = (await res.json()) as MasterInfo
      setInfo(json)
    } catch (e) {
      setInfo({
        success: false,
        source: "",
        char_count: 0,
        message: "加载失败: " + (e instanceof Error ? e.message : String(e)),
        sections: [],
        record_id: null,
        name: "",
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v)
        if (v && (!info || !info.success)) load()
      }}
    >
      <DialogTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs shrink-0 text-gray-600 hover:text-gray-900 border-gray-200"
          title="查看映射所使用的主简历来源与内容摘要"
        >
          {loading ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <FileText className="w-3 h-3 mr-1" />}
          主简历预览
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="text-sm font-semibold text-gray-900">主简历来源预览</DialogTitle>
        </DialogHeader>
        {!info ? (
          <div className="flex items-center justify-center py-8 text-sm text-gray-400">
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />加载中...
          </div>
        ) : !info.success ? (
          <div className="text-sm text-red-500 py-4">{info.message || "主简历加载失败"}</div>
        ) : (
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div className="p-2.5 rounded-lg bg-gray-50 border border-gray-100">
                <div className="text-gray-400 text-[11px]">来源</div>
                <div className="text-gray-900 font-medium mt-0.5">{info.source}</div>
              </div>
              <div className="p-2.5 rounded-lg bg-gray-50 border border-gray-100">
                <div className="text-gray-400 text-[11px]">字数</div>
                <div className="text-gray-900 font-medium mt-0.5">{info.char_count}</div>
              </div>
              <div className="p-2.5 rounded-lg bg-gray-50 border border-gray-100 col-span-2">
                <div className="text-gray-400 text-[11px]">简历名 / record_id</div>
                <div className="text-gray-900 font-medium mt-0.5 break-all">
                  {info.name || "—"}{info.record_id ? `（${info.record_id}）` : ""}
                </div>
              </div>
            </div>
            {info.sections.length > 0 && (
              <div>
                <div className="text-gray-400 text-[11px] mb-1">包含模块（{info.sections.length}）</div>
                <div className="flex flex-wrap gap-1">
                  {info.sections.map((s) => (
                    <span key={s} className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-100 text-[11px]">
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
