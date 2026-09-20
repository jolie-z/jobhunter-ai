"use client"

import type React from "react"
import { useState, useEffect } from "react"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { ArrowDown, ArrowUp, Check, Pencil, Trash2, X } from "lucide-react"

interface ModuleCardProps {
  id?: string
  title: string
  icon?: React.ReactNode
  onDelete?: () => void
  onMoveUp?: () => void
  onMoveDown?: () => void
  onTitleChange?: (newTitle: string) => void
  canMoveUp?: boolean
  canMoveDown?: boolean
  isFixed?: boolean
  headerTools?: React.ReactNode
  children: React.ReactNode
}

export function ModuleCard({
  id,
  title,
  icon,
  onDelete,
  onMoveUp,
  onMoveDown,
  onTitleChange,
  canMoveUp = true,
  canMoveDown = true,
  isFixed = false,
  headerTools,
  children,
}: ModuleCardProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title)

  useEffect(() => {
    if (!editing) {
      setDraft(title)
    }
  }, [title, editing])

  const handleSaveTitle = () => {
    if (onTitleChange) onTitleChange(draft)
    setEditing(false)
  }

  const handleCancelTitle = () => {
    setDraft(title)
    setEditing(false)
  }

  return (
    <Card id={id} data-section-id={id} className="overflow-hidden border border-slate-200/50 shadow-sm bg-white rounded-xl transition-all duration-300 hover:shadow-md hover:border-slate-300/60">
      <div className="flex items-center justify-between gap-3 px-4 pt-0 pb-0 group">
        <div className="flex min-w-0 items-center gap-2 mt-0">
          {editing ? (
            <div className="flex items-center gap-1.5">
              <Input
                value={draft || ""}
                onChange={(e) => setDraft(e.target.value)}
                className="h-8 w-48"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSaveTitle()
                  if (e.key === "Escape") handleCancelTitle()
                }}
              />
              <Button size="icon" variant="ghost" className="h-8 w-8 text-emerald-600 hover:text-emerald-700" onClick={handleSaveTitle}>
                <Check className="h-4 w-4" />
                <span className="sr-only">确认</span>
              </Button>
              <Button size="icon" variant="ghost" className="h-8 w-8 text-muted-foreground" onClick={handleCancelTitle}>
                <X className="h-4 w-4" />
                <span className="sr-only">取消</span>
              </Button>
            </div>
          ) : (
            <h2 
              onClick={() => {
                if (!isFixed || onTitleChange) setEditing(true);
              }}
              className="truncate text-base font-semibold text-foreground cursor-pointer hover:text-emerald-600 transition-colors group relative"
              title="点击编辑标题"
            >
              {title}
              {(!isFixed || onTitleChange) && <Pencil className="h-3 w-3 inline-block ml-1.5 opacity-0 group-hover:opacity-100 transition-opacity" />}
            </h2>
          )}
          {headerTools && (
            <div className="flex items-center ml-2 space-x-1 shrink-0">
              {headerTools}
            </div>
          )}
        </div>

        {!editing && !isFixed ? (
          <div className="flex shrink-0 items-center gap-0.5">
            <Button size="icon" variant="ghost" disabled={!canMoveUp} className="h-8 w-8 text-muted-foreground hover:text-foreground disabled:opacity-30" onClick={onMoveUp}>
              <ArrowUp className="h-4 w-4" />
            </Button>
            <Button size="icon" variant="ghost" disabled={!canMoveDown} className="h-8 w-8 text-muted-foreground hover:text-foreground disabled:opacity-30" onClick={onMoveDown}>
              <ArrowDown className="h-4 w-4" />
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button size="icon" variant="ghost" className="h-8 w-8 text-muted-foreground hover:text-destructive">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>确认删除该模块？</AlertDialogTitle>
                  <AlertDialogDescription>
                    删除后无法撤销，但如果你误删了系统内置的模块，可以在页面底部重新找回。对于自定义模块，删除后其中的所有内容将丢失。
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction onClick={onDelete}>
                    确认删除
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        ) : null}
      </div>
      <div className="px-4 pb-1 pt-0">{children}</div>
    </Card>
  )
}
