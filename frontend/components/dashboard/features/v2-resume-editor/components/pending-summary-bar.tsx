"use client"

/**
 * 解析置信度汇总条：低置信模块计数 + 点击跳转（对照原文核实引导）。
 * v2-resume-editor 与 resume-builder（简历库）两套编辑器共用。
 */

import { AlertTriangle } from "lucide-react"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { getPendingModuleKeys } from "../utils/resume-confidence-utils"

export function PendingSummaryBar() {
  const confidence = useResumeV2Store((state) => state.resumeData?._meta?.confidence)
  const pendingKeys = getPendingModuleKeys(confidence)

  if (pendingKeys.length === 0) return null

  const jumpToFirst = () => {
    for (const key of pendingKeys) {
      const el =
        document.querySelector(`[data-section-id="${key}"]`) ||
        document.getElementById(key) ||
        document.getElementById(`module-anchor-${key}`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
        return
      }
    }
  }

  return (
    <button
      type="button"
      onClick={jumpToFirst}
      className="flex w-full items-center gap-2 rounded-lg border border-amber-300/80 bg-amber-50/90 px-3 py-2 text-left text-xs text-amber-900 transition-colors hover:bg-amber-100"
    >
      <AlertTriangle className="size-3.5 shrink-0 text-amber-600" />
      <span>
        {pendingKeys.length} 处内容待确认（AI 解析置信度低），建议点「对照原文」核实后手动修改；确认无误可点模块卡片上的角标消掉提示
      </span>
    </button>
  )
}
