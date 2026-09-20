import React from "react"
import { Check, X, RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { ResumeSection } from "@/types/resume"

interface WorkRestoreBinProps {
  compressedWorks: ResumeSection[]
  onRestore: (idsToRestore: string[]) => void
  onCancel: () => void
}

export function WorkRestoreBin({ compressedWorks, onRestore, onCancel }: WorkRestoreBinProps) {
  return (
    <div className="mt-2 w-full border border-purple-200 bg-purple-50/50 rounded-lg p-3 shadow-sm text-sm">
      <div className="flex items-center justify-between mb-3 border-b border-purple-200/60 pb-2">
        <h4 className="font-semibold flex items-center text-purple-700">
          <RotateCcw className="mr-1.5 h-4 w-4" /> 工作经历还原站
        </h4>
        <Button variant="ghost" size="icon" className="h-6 w-6 text-purple-400 hover:text-purple-700 hover:bg-purple-100/50" onClick={onCancel}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <p className="text-xs text-purple-600/80 leading-relaxed mb-3">
        以下是已被折叠压缩的经历原稿，您可以随时无损还原。
      </p>

      <div className="max-h-[300px] overflow-y-auto space-y-2 pr-1 custom-scrollbar">
        {compressedWorks.map(w => (
          <div key={w.id} className="flex gap-3 items-start p-2.5 rounded-md border border-purple-100 bg-white shadow-sm">
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-semibold text-[13px] text-slate-800 truncate">
                  {w.title}
                </span>
                <Button 
                  size="sm" 
                  variant="outline"
                  className="h-6 text-[11px] text-purple-600 border-purple-200 hover:bg-purple-50"
                  onClick={() => onRestore([w.id])}
                >
                  恢复原稿
                </Button>
              </div>
              <div className="text-[11px] text-slate-500 line-clamp-3 leading-relaxed whitespace-pre-wrap">
                {w.originalContent}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex justify-end mt-4 pt-2 border-t border-purple-200/60">
        <Button 
          size="sm" 
          className="h-7 text-xs bg-purple-600 hover:bg-purple-700 text-white shadow-sm"
          onClick={() => onRestore(compressedWorks.map(w => w.id))}
        >
          <RotateCcw className="mr-1.5 h-3.5 w-3.5" /> 一键全部还原
        </Button>
      </div>
    </div>
  )
}
