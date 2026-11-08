"use client"

/**
 * 平台抓取失败弹窗（右下角常驻）
 * =========================================================================
 * 任一平台（BOSS直聘/前程无忧/智联招聘/猎聘/小红书）抓取任务失败时弹出，
 * 展示失败原因与搜索条件。用户手动点击「知道了」关闭前常驻——绝不自动消失，
 * 确保离开座位回来也不会错过失败；同一轮多平台失败各自成卡纵向堆叠。
 *
 * 数据来源：SSE platform_failure 事件（后端 crawlers._run_and_track 统一发射，
 * 同时发飞书通知）；新任务 startPipeline 时清空历史弹窗。
 */

import { AlertTriangle, X } from "lucide-react"
import { usePipelineStore } from "@/store/pipeline-store"

export function PlatformFailureDialog() {
  const failures = usePipelineStore((s) => s.platformFailures)
  const dismiss = usePipelineStore((s) => s.dismissPlatformFailure)

  if (failures.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-[80] flex flex-col gap-3 max-w-sm w-[calc(100vw-2rem)] sm:w-96">
      {failures.map((f) => (
        <div
          key={f.id}
          role="alert"
          className="bg-card border border-rose-500/40 rounded-xl shadow-lg p-4 flex flex-col gap-2 animate-in slide-in-from-bottom-4 fade-in duration-300"
        >
          {/* 标题行 */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <AlertTriangle className="h-4.5 w-4.5 shrink-0 text-rose-500" />
              <span className="text-sm font-bold text-rose-700 dark:text-rose-300 truncate">
                {f.platform_name}抓取任务失败
              </span>
            </div>
            {/* 手动关闭：唯一关闭途径，无自动消失 */}
            <button
              onClick={() => dismiss(f.id)}
              aria-label="关闭失败通知"
              className="shrink-0 rounded-md p-1 text-muted-foreground/60 hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* 失败原因 */}
          <div className="rounded-lg bg-rose-500/10 border border-rose-500/20 px-3 py-2">
            <p className="text-xs leading-relaxed text-rose-700 dark:text-rose-300 break-words">
              <span className="font-semibold">失败原因：</span>
              {f.reason}
            </p>
          </div>

          {/* 搜索条件 + 后续动作 */}
          <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
            <span className="truncate">
              {f.keyword || "不限"} | {f.city || "不限"} | {f.salary || "不限"}
            </span>
            <span className="shrink-0 font-mono">{f.time}</span>
          </div>
          {f.cursor_note && (
            <p className="text-[11px] text-muted-foreground">{f.cursor_note}</p>
          )}
        </div>
      ))}
    </div>
  )
}
