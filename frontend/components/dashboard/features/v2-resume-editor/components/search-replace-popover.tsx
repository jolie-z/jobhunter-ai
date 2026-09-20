"use client"

import React from "react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Replace, Search, ChevronUp, ChevronDown } from "lucide-react"

interface SearchReplacePopoverProps {
  findText: string
  setFindText: (val: string) => void
  replaceText: string
  setReplaceText: (val: string) => void
  effectiveTotalMatches: number
  safeMatchIndex: number
  setCurrentMatchIndex: (val: number) => void
  scrollToMatch: (n: number) => void
  handleReplace: (replaceAll: boolean) => void
}

/**
 * 🌟 独立解耦的简历查找与替换 Popover 控件
 * 包含双向光标轮播计数器 (如 5/9)、Enter/Shift+Enter 连续查找按键响应
 */
export function SearchReplacePopover({
  findText,
  setFindText,
  replaceText,
  setReplaceText,
  effectiveTotalMatches,
  safeMatchIndex,
  setCurrentMatchIndex,
  scrollToMatch,
  handleReplace,
}: SearchReplacePopoverProps) {
  return (
    <Popover>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="size-7 text-slate-600 hover:text-slate-900 hover:bg-slate-100/80 rounded-md"
            >
              <Replace className="size-3.5" />
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>查找与替换</TooltipContent>
      </Tooltip>
      <PopoverContent className="w-80 p-4 shadow-xl rounded-xl border-slate-200" align="start">
        <div className="flex flex-col gap-3.5">
          <h4 className="text-sm font-bold text-slate-800">查找与替换</h4>
          <div className="flex flex-col gap-2.5">
            <div className="relative flex items-center">
              <Search className="absolute left-2.5 size-4 text-slate-400" />
              <Input
                placeholder="要查找的词..."
                value={findText}
                onChange={(e) => setFindText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    if (effectiveTotalMatches > 0) {
                      const n = e.shiftKey
                        ? safeMatchIndex > 0
                          ? safeMatchIndex - 1
                          : effectiveTotalMatches - 1
                        : safeMatchIndex < effectiveTotalMatches - 1
                        ? safeMatchIndex + 1
                        : 0
                      setCurrentMatchIndex(n)
                      scrollToMatch(n)
                    }
                  }
                }}
                className="h-8 pl-8 pr-20 text-xs focus-visible:ring-indigo-500"
              />
              {findText && (
                <div className="absolute right-1 flex items-center gap-0.5 text-[10px] text-slate-400">
                  <span className="mr-1">
                    {effectiveTotalMatches > 0 ? safeMatchIndex + 1 : 0}/{effectiveTotalMatches}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-6 p-0 hover:bg-slate-100"
                    onClick={() => {
                      if (effectiveTotalMatches > 0) {
                        const n =
                          safeMatchIndex > 0
                            ? safeMatchIndex - 1
                            : effectiveTotalMatches - 1
                        setCurrentMatchIndex(n)
                        scrollToMatch(n)
                      }
                    }}
                  >
                    <ChevronUp className="size-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-6 p-0 hover:bg-slate-100"
                    onClick={() => {
                      if (effectiveTotalMatches > 0) {
                        const n =
                          safeMatchIndex < effectiveTotalMatches - 1
                            ? safeMatchIndex + 1
                            : 0
                        setCurrentMatchIndex(n)
                        scrollToMatch(n)
                      }
                    }}
                  >
                    <ChevronDown className="size-3" />
                  </Button>
                </div>
              )}
            </div>
            <Input
              placeholder="替换为..."
              value={replaceText}
              onChange={(e) => setReplaceText(e.target.value)}
              className="h-8 text-xs focus-visible:ring-indigo-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              className="flex-1 h-8 text-xs font-medium"
              onClick={() => handleReplace(false)}
            >
              替换
            </Button>
            <Button
              size="sm"
              className="flex-1 h-8 text-xs bg-indigo-600 hover:bg-indigo-700 font-medium"
              onClick={() => handleReplace(true)}
            >
              全部替换
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
