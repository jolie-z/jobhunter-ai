import React from "react"
import { Check, X, Trash2, RefreshCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { ResumeSection } from "@/types/resume"

interface ProjectTrashBinProps {
  archivedProjects: ResumeSection[]
  onRestore: (idsToRestore: string[]) => void
  onCancel: () => void
}

export function ProjectTrashBin({
  archivedProjects,
  onRestore,
  onCancel,
}: ProjectTrashBinProps) {
  
  const handleRestoreAll = () => {
    onRestore(archivedProjects.map(p => p.id))
  }

  const handleRestoreSingle = (id: string) => {
    onRestore([id])
  }

  return (
    <div className="mt-2 w-full border border-slate-200 bg-slate-50/50 rounded-lg p-3 shadow-sm text-sm">
      <div className="flex items-center justify-between mb-3 border-b border-slate-200/60 pb-2">
        <h4 className="font-semibold flex items-center text-slate-700">
          <Trash2 className="mr-1.5 h-4 w-4" /> 项目回收站
        </h4>
        <Button variant="ghost" size="icon" className="h-6 w-6 text-slate-400 hover:text-slate-700 hover:bg-slate-100/50" onClick={onCancel}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="space-y-3">
        <p className="text-xs text-slate-500 leading-relaxed mb-2">
          以下是之前被判定“不符合当前岗位要求”而被切除的项目。您可以随时将它们恢复至主画布。
        </p>
        <div className="max-h-[300px] overflow-y-auto space-y-2 pr-1 custom-scrollbar">
          {archivedProjects.length === 0 ? (
            <div className="py-4 text-center text-slate-400 text-xs">暂无被切除的项目</div>
          ) : (
            archivedProjects.map(p => (
              <div 
                key={p.id} 
                className="flex items-center justify-between p-2.5 rounded-md border bg-white border-slate-200"
              >
                <div className="flex flex-col min-w-0 pr-4">
                  <span className="font-semibold text-[13px] text-slate-600 truncate line-through">
                    {p.title || "未命名项目"}
                  </span>
                  <span className="text-[11px] text-slate-400 mt-0.5 line-clamp-1 break-all">
                    {p.content.replace(/\n/g, " ").slice(0, 100)}...
                  </span>
                </div>
                <Button 
                  size="sm" 
                  variant="outline"
                  className="h-7 text-xs text-emerald-600 border-emerald-200 hover:bg-emerald-50 hover:text-emerald-700 shrink-0"
                  onClick={() => handleRestoreSingle(p.id)}
                >
                  <RefreshCcw className="h-3 w-3 mr-1" />
                  恢复
                </Button>
              </div>
            ))
          )}
        </div>

        <div className="flex items-center justify-end gap-2 mt-4 pt-2 border-t border-slate-200/60">
          <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-500 hover:bg-slate-100" onClick={onCancel}>
            关闭
          </Button>
          {archivedProjects.length > 0 && (
            <Button 
              size="sm" 
              className="h-7 text-xs bg-slate-800 hover:bg-slate-900 text-white shadow-sm"
              onClick={handleRestoreAll}
            >
              一键恢复全部 ({archivedProjects.length})
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
