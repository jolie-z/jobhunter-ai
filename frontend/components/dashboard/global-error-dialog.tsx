"use client"

// 统一「意外错误」弹窗：详情 + 一键导出诊断包。
// 2026-10-28 起因：简历库保存报 `Extra data: line 1 column 5 (char 4)`，用户侧无法取证、
// 开发者拿不到日志（最终查明是填错数据表 ID，但纯靠截图猜）。此后意外错误（500/网络/解析
// 失败）一律走本弹窗，替代裸 alert；表单校验类轻提示仍走 toast，不配诊断按钮。
// 取证链路：详情区展示后端 detail（含响应 body 快照）→ 点【导出诊断日志】→ 桌面壳
// collectDiagnostics 打包 shell.log（含后端 logger.exception traceback）到桌面并打开文件夹。

import { useEffect, useState } from "react"
import { AlertTriangle, Copy, FileDown, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  showGlobalError,
  subscribeGlobalError,
  type GlobalErrorPayload,
} from "@/components/dashboard/global-error-bus"

// 导出/复制失败统一文案（IPC 桥异常或磁盘失败时的兜底引导）
const EXPORT_FAIL_HINT = "导出失败，请通过托盘菜单「导出诊断日志」重试"

export function GlobalErrorDialog() {
  const [payload, setPayload] = useState<GlobalErrorPayload | null>(null)
  const [exporting, setExporting] = useState(false)
  const [hint, setHint] = useState<{ text: string; ok: boolean } | null>(null)

  useEffect(() => subscribeGlobalError((p) => {
    setPayload(p)
    setHint(null)
  }), [])

  // 桌面壳 preload 注入诊断桥（web 开发模式无此桥 → 隐藏导出按钮，降级复制详情）
  const canExport = typeof window !== "undefined" && !!window.appConfig?.exportDiagnostics

  const handleExport = async () => {
    if (!window.appConfig?.exportDiagnostics || exporting) return
    setExporting(true)
    try {
      const zipPath = await window.appConfig.exportDiagnostics()
      setHint(zipPath
        ? { text: `诊断包已保存到桌面：${zipPath.split(/[\\/]/).pop()}`, ok: true }
        : { text: EXPORT_FAIL_HINT, ok: false })
    } catch {
      setHint({ text: EXPORT_FAIL_HINT, ok: false })
    } finally {
      setExporting(false)
    }
  }

  const handleCopy = async () => {
    if (!payload) return
    try {
      await navigator.clipboard.writeText(`${payload.title}\n${payload.detail}`)
      setHint({ text: "错误详情已复制", ok: true })
    } catch {
      setHint({ text: "复制失败，请手动截图错误详情", ok: false })
    }
  }

  return (
    <Dialog open={!!payload} onOpenChange={(o) => !o && setPayload(null)}>
      <DialogContent className="sm:max-w-lg border-slate-200 bg-white">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base font-bold text-slate-900">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-red-100">
              <AlertTriangle className="size-4 text-red-600" />
            </span>
            {payload?.title}
          </DialogTitle>
          <DialogDescription className="pt-2 text-[13px] leading-relaxed text-slate-600">
            操作未成功。若反复出现，请导出诊断日志发给开发者，便于定位问题。
          </DialogDescription>
        </DialogHeader>

        {payload && (
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-all rounded-xl bg-slate-50 px-3.5 py-2.5 font-mono text-[11px] leading-relaxed text-slate-700 ring-1 ring-inset ring-slate-200/70">
            {payload.detail}
          </pre>
        )}

        {hint && (
          <p className={`text-xs ${hint.ok ? "text-emerald-600" : "text-rose-600"}`} role="status">{hint.text}</p>
        )}

        <div className="flex gap-2 pt-1">
          {canExport && (
            <Button
              onClick={handleExport}
              disabled={exporting}
              className="flex-1 gap-1.5 bg-slate-900 text-white hover:bg-slate-800"
            >
              {exporting
                ? <Loader2 className="size-4 animate-spin" />
                : <FileDown className="size-4" />}
              {exporting ? "正在导出…" : "导出诊断日志"}
            </Button>
          )}
          <Button
            variant="outline"
            onClick={handleCopy}
            className="flex-1 gap-1.5 border-slate-200 text-slate-700 hover:bg-slate-50"
          >
            <Copy className="size-4" />
            复制详情
          </Button>
          <Button
            variant="outline"
            onClick={() => setPayload(null)}
            className="flex-1 border-slate-200 text-slate-700 hover:bg-slate-50"
          >
            关闭
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export { showGlobalError }
