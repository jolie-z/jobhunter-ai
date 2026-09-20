"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { FileText, Plus, Trash2, Copy } from "lucide-react"

interface ResumeItem {
  id: string
  name: string
  status?: string // 🌟 新增：接收状态字段
}

interface ResumeSidebarProps {
  resumes: ResumeItem[]
  activeId: string
  onSelect: (id: string) => void
  onRename: (id: string, name: string) => void
  onDuplicate?: (id: string) => void
  onDelete: (id: string) => void
  onCreate: () => void
}

export function ResumeSidebar({ resumes, activeId, onSelect, onRename, onDuplicate, onDelete, onCreate }: ResumeSidebarProps) {
  return (
    <aside className="flex w-50 shrink-0 flex-col border-r border-border bg-muted/40">
      <div className="flex items-center gap-1.5 px-3 py-3.5">
        <FileText className="h-4 w-4 shrink-0 text-primary" />
        <h2 className="truncate text-sm font-semibold tracking-tight text-foreground">我的简历</h2>
      </div>

      <nav className="flex-1 overflow-y-auto px-1.5 py-1">
        <ul className="flex flex-col gap-0.5">
          {resumes.map((r) => {
            const active = r.id === activeId
            const isActiveResume = r.status === '启用'
            return (
              <li key={r.id}>
                <div
                  onClick={() => onSelect(r.id)}
                  className={cn(
                    "group flex items-center gap-1 rounded-md py-1 pl-2 pr-1 text-xs transition-colors relative",
                    active
                      ? "bg-background font-medium text-foreground shadow-sm ring-1 ring-border"
                      : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
                  )}
                >
                  {/* 🌟 新增：生效状态小绿点，视觉上与飞书状态对齐 */}
                  {r.status === '启用' && (
                    <div className="absolute left-1 top-2.5 h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.5)]" />
                  )}
                  <span
                    className={cn(
                      "flex-1 truncate px-1 py-1 text-xs select-none cursor-pointer",
                      r.status === '启用' ? "pl-3.5" : "" // 留出小绿点的空间
                    )}
                  >
                    {r.name}
                  </span>
                  
                  <div className="flex items-center opacity-0 group-hover:opacity-100 transition-opacity">
                    {onDuplicate && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-5 w-5 shrink-0 text-muted-foreground hover:text-blue-500"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDuplicate(r.id)
                        }}
                        title="复制这份简历"
                      >
                        <Copy className="h-3 w-3" />
                        <span className="sr-only">复制{r.name}</span>
                      </Button>
                    )}
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-5 w-5 shrink-0 text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation()
                        onDelete(r.id)
                      }}
                      disabled={resumes.length <= 1 || isActiveResume}
                      title={isActiveResume ? "生效中的简历不能删除，请先将其它简历设为生效" : "删除简历"}
                    >
                      <Trash2 className="h-3 w-3" />
                      <span className="sr-only">删除{r.name}</span>
                    </Button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </nav>

      <div className="sticky bottom-0 border-t border-border bg-muted/40 p-2">
        <Button onClick={onCreate} className="w-full text-xs" size="sm">
          <Plus className="mr-1 h-3.5 w-3.5" />
          新建简历
        </Button>
      </div>
    </aside>
  )
}
