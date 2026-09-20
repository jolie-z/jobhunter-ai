/**
 * 猎聘 Tab 分区共享原子组件（机械搬迁）
 */
"use client"

import { useContext, type ReactNode } from "react"
import { LiepinReportWarningsContext, LIEPIN_NOTICE_MAP } from "../constants"
import { ModuleReportNotice } from "../../agent-report-shared"
import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Lock } from "lucide-react"
import { cn } from "@/lib/utils"


export function SectionCard({ children, moduleKey }: { children: React.ReactNode; moduleKey?: string }) {
  const warnings = useContext(LiepinReportWarningsContext)
  const notice = moduleKey ? LIEPIN_NOTICE_MAP[moduleKey] : undefined
  return (
    <div className="bg-white border border-[#e8e8e8] rounded-lg p-5 mb-4">
      {notice && warnings && warnings.length > 0 && (
        <ModuleReportNotice warnings={warnings} matchKeywords={notice.keywords} title={notice.title} />
      )}
      {children}
    </div>
  )
}


export function DialogActions({ onCancel, onConfirm, disabled, saving }: { onCancel: () => void; onConfirm: () => void; disabled?: boolean; saving?: boolean }) {
  return (
    <div className="flex justify-end gap-3 mt-5">
      <Button
        variant="outline"
        onClick={onCancel}
        className="border-gray-300 text-gray-600"
      >
        取消
      </Button>
      <Button
        onClick={onConfirm}
        disabled={disabled || saving}
        className="bg-[#FF6B00] hover:bg-[#e55f00] text-white"
      >
        {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
        确定
      </Button>
    </div>
  )
}


export function ReadOnlyNote() {
  return (
    <span className="inline-flex items-center gap-0.5 text-[11px] text-gray-400">
      <Lock className="w-3 h-3" />
      仅可通过官网修改
    </span>
  )
}
