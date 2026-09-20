"use client"

import React from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Trash2, BookOpen, FileText } from "lucide-react"
import type { SkillMeta } from "../skill-selector"

interface SkillDetailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  skillDetail: SkillMeta | null
  onDeleteSkill: (skillId: string) => Promise<void>
}

export function SkillDetailDialog({
  open,
  onOpenChange,
  skillDetail,
  onDeleteSkill,
}: SkillDetailDialogProps) {
  if (!skillDetail) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between pr-4">
            <span className="flex items-center gap-2">
              {skillDetail.name === "resume_rewrite" ? "官方标准剧本" : skillDetail.name}
              {skillDetail.is_package && (
                <span className="inline-flex items-center rounded-full border border-purple-200 bg-purple-50 px-2 py-0.5 text-[11px] font-semibold text-purple-700">
                  多文件知识库
                </span>
              )}
              {skillDetail.is_official ? (
                <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
                  官方
                </span>
              ) : (
                <span className="inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-700">
                  自定义
                </span>
              )}
            </span>
            {!skillDetail.is_official && (
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs text-red-500 hover:bg-red-50 hover:text-red-600"
                onClick={() => onDeleteSkill(skillDetail.id)}
              >
                <Trash2 className="size-3.5 mr-1" />
                删除
              </Button>
            )}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {skillDetail.description || "暂无描述"}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2 text-xs">
          <div className="grid grid-cols-2 gap-2 text-slate-600 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
            <div>版本: <code className="text-indigo-600 font-mono">v{skillDetail.version || "1.0.0"}</code></div>
            <div>ID: <code className="text-slate-800 font-mono">{skillDetail.id}</code></div>
            <div>主文件: <code className="text-slate-800 font-mono">{skillDetail.file}</code></div>
            <div>References: <span className="font-semibold text-purple-700">{skillDetail.references_count || 0} 个</span></div>
          </div>

          {/* 资料清单 */}
          {skillDetail.reference_names && skillDetail.reference_names.length > 0 && (
            <div className="space-y-1.5">
              <div className="font-semibold text-slate-700 flex items-center gap-1.5">
                <BookOpen className="size-3.5 text-purple-600" />
                附属参考资料库与证据链 (References):
              </div>
              <div className="max-h-36 overflow-y-auto rounded-md border border-slate-200 bg-white p-2 space-y-1">
                {skillDetail.reference_names.map((refName, idx) => (
                  <div key={idx} className="flex items-center gap-1.5 text-[11px] text-slate-600 font-mono truncate">
                    <FileText className="size-3 text-slate-400 shrink-0" />
                    <span>{refName}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
