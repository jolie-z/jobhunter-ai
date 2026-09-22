"use client"

// 简历库编辑工具岛：加粗 + 查找替换 + 撤销/重做
// 自「定制面板-简历编辑区」(v2-resume-editor) 迁移（2026-09-23 七项修复#5）：
// - 加粗为纯 DOM 操作（零耦合，textarea/input 通用）
// - 查找替换复用 SearchReplacePopover + resume-search-utils（数据层就是两区共用的 ResumeDataV2 store）
// - 撤销/重做复用 useResumeUndoRedo（resumeKey 用简历库的 record_id）
// 视图层唯一适配：锚点 id 命名（简历库模块卡为 module-anchor-{key}，编辑区为裸 key）

import React, { useEffect, useMemo, useState } from "react"
import { Bold, Redo2, Undo2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip"
import { toast } from "@/hooks/use-toast"
import { ToastAction } from "@/components/ui/toast"
import { useResumeV2Store } from "@/hooks/use-resume-v2-store"
import { SearchReplacePopover } from "@/components/dashboard/features/v2-resume-editor/components/search-replace-popover"
import {
  searchResumeMatches,
  replaceResumeText,
} from "@/components/dashboard/features/v2-resume-editor/utils/resume-search-utils"
import { useResumeUndoRedo } from "@/components/dashboard/features/v2-resume-editor/hooks/use-resume-undo-redo"
import { useEditorSearchHighlight } from "@/components/dashboard/features/v2-resume-editor/hooks/use-editor-search-highlight"

export function EditToolsCluster({ resumeKey }: { resumeKey?: string }) {
  const { resumeData, setResumeData } = useResumeV2Store()

  const [findText, setFindText] = useState("")
  const [replaceText, setReplaceText] = useState("")
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0)

  const { canUndo, canRedo, undo, redo, takeSnapshot } = useResumeUndoRedo({ resumeKey })

  // 动态检索全简历树的匹配项（数据层）
  const searchResult = useMemo(() => {
    return searchResumeMatches(resumeData, findText)
  }, [resumeData, findText])
  const matches = searchResult.matches

  // 全画布高亮与光标导航（视图层，依赖简历库画布容器的 data-resume-canvas="true"）
  const { scrollToCurrentMatch, matches: domMatches } = useEditorSearchHighlight({
    findText,
    currentMatchIndex,
  })

  // DOM 已扫描出匹配时以视图层为准，否则以数据层为准
  const effectiveTotalMatches = domMatches.length > 0 ? domMatches.length : searchResult.totalMatches
  const safeMatchIndex = effectiveTotalMatches > 0 ? Math.min(currentMatchIndex, effectiveTotalMatches - 1) : 0

  useEffect(() => {
    setCurrentMatchIndex(0)
  }, [findText])

  // 替换后匹配数变小时自动收敛游标
  useEffect(() => {
    if (effectiveTotalMatches === 0) {
      setCurrentMatchIndex(0)
    } else if (currentMatchIndex >= effectiveTotalMatches) {
      setCurrentMatchIndex(effectiveTotalMatches - 1)
    }
  }, [effectiveTotalMatches, currentMatchIndex])

  const scrollToMatch = (n: number) => {
    // 1. DOM 级字级精准定位
    const handled = scrollToCurrentMatch(n)
    // 2. 卡片级兜底：简历库锚点为 module-anchor-{key}（编辑区为裸 key），两套命名都试
    if (!handled && matches.length > 0 && n >= 0 && n < matches.length) {
      const match = matches[n]
      const safeId = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(match.sectionId) : match.sectionId
      const el =
        document.querySelector(`[data-section-id="${safeId}"]`) ||
        document.getElementById(`module-anchor-${match.sectionId}`) ||
        document.getElementById(match.sectionId)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
      }
    }
  }

  const handleReplace = (replaceAll: boolean) => {
    if (!findText) {
      toast({ title: "提示", description: "请输入要查找的内容" })
      return
    }
    if (!resumeData) return

    const result = replaceResumeText(resumeData, findText, replaceText, replaceAll, safeMatchIndex)
    if (result.replacedCount === 0) {
      toast({ title: "未找到匹配项", description: `未在简历中找到「${findText}」` })
      return
    }

    // 仅在真实替换即将写入时入栈，杜绝 0 命中产生空步
    takeSnapshot(resumeData)
    setResumeData(result.nextData)
    toast({
      title: replaceAll ? "✅ 全部替换成功" : "✅ 替换成功",
      description: `已完成 ${result.replacedCount} 处「${findText}」的替换（保存需点「保存并同步」）`,
      action: (
        <ToastAction altText="撤销本次替换" onClick={undo}>
          撤销
        </ToastAction>
      ),
    })
  }

  const handleBold = () => {
    const el = document.activeElement as HTMLTextAreaElement | HTMLInputElement
    if (el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT")) {
      const start = el.selectionStart
      const end = el.selectionEnd
      if (start !== null && end !== null && start !== end) {
        const val = el.value
        const selectedText = val.substring(start, end)
        const replacement = `**${selectedText}**`
        el.setRangeText(replacement, start, end, "select")
        el.dispatchEvent(new Event("input", { bubbles: true }))
      }
    }
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex items-center gap-0.5">
        {/* 撤销 (Undo) */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className={`h-8 w-7 rounded-lg ${
                canUndo
                  ? "text-muted-foreground hover:text-foreground hover:bg-background"
                  : "text-muted-foreground/30 opacity-40 cursor-not-allowed"
              }`}
              onClick={() => canUndo && undo()}
            >
              <Undo2 className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>撤销修改 (⌘Z / Ctrl+Z)</TooltipContent>
        </Tooltip>

        {/* 重做 (Redo) */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className={`h-8 w-7 rounded-lg ${
                canRedo
                  ? "text-muted-foreground hover:text-foreground hover:bg-background"
                  : "text-muted-foreground/30 opacity-40 cursor-not-allowed"
              }`}
              onClick={() => canRedo && redo()}
            >
              <Redo2 className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>重做修改 (⌘⇧Z / Ctrl+Y)</TooltipContent>
        </Tooltip>

        {/* 加粗 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-8 w-7 rounded-lg text-muted-foreground hover:text-foreground hover:bg-background"
              onClick={handleBold}
              onMouseDown={(e) => e.preventDefault()}
            >
              <Bold className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>加粗（选中文字后点击）</TooltipContent>
        </Tooltip>

        {/* 查找替换（自编辑区原样复用的受控组件） */}
        <SearchReplacePopover
          findText={findText}
          setFindText={setFindText}
          replaceText={replaceText}
          setReplaceText={setReplaceText}
          effectiveTotalMatches={effectiveTotalMatches}
          safeMatchIndex={safeMatchIndex}
          setCurrentMatchIndex={setCurrentMatchIndex}
          scrollToMatch={scrollToMatch}
          handleReplace={handleReplace}
        />
      </div>
    </TooltipProvider>
  )
}
