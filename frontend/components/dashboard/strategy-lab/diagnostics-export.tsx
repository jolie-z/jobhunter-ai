"use client"

// 底层配置页「内测诊断通道」卡片：一键导出诊断日志包到桌面 + 打开 shell.log 所在文件夹。
// 复用桌面壳 collectDiagnostics 链路（shell.log + 环境检查报告 + Edge 运行日志 → zip 到
// 桌面），与统一错误弹窗（global-error-dialog.tsx）共享同一 IPC 与降级策略：反馈模式
// （loading 转圈 + emerald/rose 内联 hint）也与其对齐。
//
// ⚠️ 内测期诊断通道（阶段性策略）：系统整体稳定后整体移除——
// ① 本文件；② system-config.tsx 的挂载点与 import；③ preload.js 的 openLogFolder；
// ④ frontend/lib/api.ts 的 openLogFolder 类型行；⑤ desktop/main.js 的 shell:open-log-folder
// handler。「导出诊断日志」主链路（托盘/错误弹窗）与本次无关，移除本卡片不影响那两处。

import { useState, useSyncExternalStore } from "react"
import { FileDown, FolderOpen, Loader2, Stethoscope } from "lucide-react"

// 客户端挂载探测：服务端/首帧返回 false，hydration 后返回 true（避免 setState-in-effect）
const subscribeNoop = () => () => {}

// 失败兜底文案（IPC 桥异常或磁盘失败时，引导回已知可用的托盘入口 / 手动路径）
const EXPORT_FAIL_HINT = "导出失败，请通过托盘菜单「导出诊断日志」重试"
const OPEN_FAIL_HINT = "打开失败，可手动前往 %APPDATA%\\JobHunter 目录查看 shell.log"

export function DiagnosticsExportCard() {
  const [exporting, setExporting] = useState(false)
  const [opening, setOpening] = useState(false)
  const [hint, setHint] = useState<{ text: string; ok: boolean } | null>(null)
  // 服务端渲染与首帧统一按「无桌面桥」渲染，mount 后再探测，避免 Electron 下 hydration 不一致
  const mounted = useSyncExternalStore(subscribeNoop, () => true, () => false)

  // 桌面壳 preload 注入诊断桥；纯浏览器模式没有此桥 → 卡片保留但按钮置灰并提示
  const canExport = mounted && !!window.appConfig?.exportDiagnostics
  const showWebHint = mounted && !canExport

  const handleExport = async () => {
    if (!window.appConfig?.exportDiagnostics || exporting) return
    setExporting(true)
    setHint(null)
    try {
      const target = await window.appConfig.exportDiagnostics()
      setHint(target
        ? { text: `诊断包已保存到桌面：${target.split(/[\\/]/).pop()}`, ok: true }
        : { text: EXPORT_FAIL_HINT, ok: false })
    } catch {
      setHint({ text: EXPORT_FAIL_HINT, ok: false })
    } finally {
      setExporting(false)
    }
  }

  const handleOpenFolder = async () => {
    if (!window.appConfig?.openLogFolder || opening) return
    setOpening(true)
    setHint(null)
    try {
      const ok = await window.appConfig.openLogFolder()
      setHint(ok ? { text: "已在文件管理器中定位日志文件", ok: true } : { text: OPEN_FAIL_HINT, ok: false })
    } catch {
      setHint({ text: OPEN_FAIL_HINT, ok: false })
    } finally {
      setOpening(false)
    }
  }

  return (
    <div className="flex items-start justify-between gap-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs transition-all">
      <div className="flex items-start gap-3.5">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-xs">
          <Stethoscope className="size-5" />
        </div>
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-sm font-semibold text-slate-900">遇到异常？一键导出诊断日志</h2>
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-inset ring-blue-200/60">
              <span className="size-1.5 rounded-full bg-blue-500" />
              内测期功能
            </span>
            {showWebHint && (
              <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-[10px] font-medium text-slate-500 ring-1 ring-inset ring-slate-200/60">
                浏览器模式
              </span>
            )}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            导出完整日志包（系统信息 + 版本 + 运行日志）到电脑桌面，直接发给开发即可精准定位问题，无需截图。日志仅保存在本机，是否外发由你决定。
          </p>
          {showWebHint && (
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              当前是浏览器模式：导出诊断日志 / 打开日志文件夹需要在 JobHunter 桌面客户端中使用。
            </p>
          )}
          {hint && (
            <p className={`mt-2 text-xs ${hint.ok ? "text-emerald-600" : "text-rose-600"}`} role="status">{hint.text}</p>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={handleOpenFolder}
          disabled={!canExport || opening || exporting}
          title={canExport ? undefined : "该功能需要在 JobHunter 桌面客户端中使用"}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-xs transition-all hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100"
        >
          {opening ? <Loader2 className="size-3.5 animate-spin" /> : <FolderOpen className="size-3.5 text-slate-400" />}
          打开日志文件夹
        </button>
        <button
          type="button"
          onClick={handleExport}
          disabled={!canExport || exporting || opening}
          title={canExport ? undefined : "该功能需要在 JobHunter 桌面客户端中使用"}
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-xs transition-all hover:bg-slate-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100"
        >
          {exporting ? <Loader2 className="size-3.5 animate-spin" /> : <FileDown className="size-3.5" />}
          {exporting ? "正在导出…" : "导出诊断日志"}
        </button>
      </div>
    </div>
  )
}
