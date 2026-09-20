"use client"

import React, { useState } from "react"
import { Stethoscope, FileCode, ChevronDown, ChevronUp } from "lucide-react"

interface FailedDiagnosisReportProps {
  diagnosis: any
  formatTime: (timeStr?: string) => string
}

export const FailedDiagnosisReport = React.memo(function FailedDiagnosisReport({
  diagnosis,
  formatTime,
}: FailedDiagnosisReportProps) {
  const [showTicket, setShowTicket] = useState(false)

  if (!diagnosis) return null

  return (
    <div className="rounded-lg bg-violet-500/10 border border-violet-500/20 p-2.5 text-xs text-violet-900 dark:text-violet-200 space-y-1.5">
      <div className="font-semibold flex items-center justify-between gap-1">
        <span className="flex items-center gap-1.5 text-[11px]">
          <Stethoscope className="h-3.5 w-3.5 text-violet-600 dark:text-violet-400" />
          AI 诊断 · {diagnosis.category}
          <span className="text-[9px] font-normal text-muted-foreground">
            (置信度 {diagnosis.confidence})
          </span>
        </span>
        {diagnosis.diagnosed_at && (
          <span className="font-mono text-[9px] text-muted-foreground">
            {formatTime(diagnosis.diagnosed_at)}
          </span>
        )}
      </div>

      <p className="text-[11px] leading-relaxed">
        <span className="font-semibold text-violet-950 dark:text-violet-100">死因：</span>
        {diagnosis.root_cause}
      </p>

      {diagnosis.fix_hint && (
        <p className="text-[11px] leading-relaxed">
          <span className="font-semibold text-violet-950 dark:text-violet-100">建议：</span>
          {diagnosis.fix_hint}
        </p>
      )}

      {diagnosis.ticket_md && (
        <div className="pt-1">
          <button
            type="button"
            onClick={() => setShowTicket(!showTicket)}
            className="flex items-center gap-1 text-[10px] font-medium text-violet-700 dark:text-violet-300 hover:underline cursor-pointer"
          >
            <FileCode className="h-3 w-3" />
            {showTicket ? "收起修复工单" : "展开修复工单 (可复制给 Agent 执行)"}
            {showTicket ? <ChevronUp className="h-2.5 w-2.5" /> : <ChevronDown className="h-2.5 w-2.5" />}
          </button>
          {showTicket && (
            <pre className="mt-1.5 p-2 rounded bg-background/90 border border-violet-500/25 text-[10px] font-mono whitespace-pre-wrap max-h-48 overflow-y-auto leading-relaxed select-all">
              {diagnosis.ticket_md}
            </pre>
          )}
        </div>
      )}
    </div>
  )
})
